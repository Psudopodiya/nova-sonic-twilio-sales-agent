# websocket_service.py
import os
import json
import asyncio
import websockets

from utils import (
    logger,
    get_int_env,
    ulaw_b64_to_pcm16_bytes,
    pcm16_bytes_to_ulaw_b64,
)
from bedrock_service import SonicSession
from twilio_service import call_metadata
from twilio.rest import Client as TwilioClient

MAX_SECS = get_int_env("MAX_CONVO_SECS", 50)  # Increased for realistic convo length
twilio_client = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))


async def handle_websocket(websocket, path):
    """
    Bridges Twilio Media Streams <-> Bedrock Nova Sonic.
    - Twilio sends base64 μ-law @ 8kHz frames in "media.payload"
    - Nova Sonic expects base64 PCM16 @ 8kHz via BiDi events
    - We convert both ways.
    - We enforce a hard cap of MAX_SECS seconds.
    """

    stream_sid = None
    call_id = path.split("/")[-1]
    logger.info(f"WebSocket connected for call {call_id}")

    try:
        with open("system_prompt.txt", "r") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        logger.error("system_prompt.txt not found! Using default prompt.")
        system_prompt = "You are a helpful AI assistant."

    meta = call_metadata.get(call_id, {})
    voice_id = meta.get("voice_id", "tiffany")

    logger.info(
        f"Call metadata: system_prompt='{system_prompt[:50]}...', voice_id={voice_id}")

    session = SonicSession(voice_id=voice_id)
    # --- MODIFICATION START: Task Management ---
    # Initialize receive_task to None. It will be created and cancelled dynamically.
    receive_task = None
    # --- MODIFICATION END ---
    cap_task = None
    call_sid = None
    audio_input_started = False

    async def enforce_time_cap():
        logger.info(f"Starting time cap enforcement: {MAX_SECS} seconds")
        await asyncio.sleep(MAX_SECS)
        logger.info("Time cap reached, closing WebSocket")
        if call_sid:
            try:
                logger.info(f"Hanging up call {call_sid}")
                twilio_client.calls(call_sid).update(status="completed")
            except Exception as e:
                logger.error(f"Failed to hang up call: {e}")
        await websocket.close(code=1000, reason="max_duration_reached")

    async def relay_model_audio():
        """Relay model audio back to Twilio (PCM16 -> μ-law b64)"""
        logger.info("Starting model audio relay task.")
        seq = 0
        try:
            async for pcm16 in session.recv_loop():
                if not pcm16:
                    continue

                # This check ensures that if the task is cancelled, it stops promptly.
                await asyncio.sleep(0)

                logger.debug(f"Converting {len(pcm16)} bytes PCM16 to μ-law for Twilio")
                payload = pcm16_bytes_to_ulaw_b64(pcm16)
                seq += 1

                media_msg = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": payload}
                }
                await websocket.send(json.dumps(media_msg))

                mark_msg = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": f"chunk-{seq}"}
                }
                await websocket.send(json.dumps(mark_msg))
                logger.debug(f"Sent {len(payload)} bytes of μ-law audio to Twilio")

        except asyncio.CancelledError:
            logger.info("Model audio relay task was cancelled due to interruption.")
        except Exception as e:
            logger.error(f"Error in model audio relay: {e}")
        finally:
            logger.info("Model audio relay task ended.")

    try:
        logger.info("Starting WebSocket message loop")
        async for raw in websocket:
            try:
                data = json.loads(raw)
                event_type = data.get("event")

                if event_type == "start":
                    start_data = data.get("start", {})
                    call_sid = start_data.get("callSid")
                    stream_sid = start_data.get("streamSid")
                    logger.info(f"Call started with SID: {call_sid}, streamID: {stream_sid}")

                    combined = system_prompt.strip()
                    logger.info("Starting Nova Sonic session...")
                    await session.start(system_text=combined)

                    # --- MODIFICATION: Trigger initial AI greeting ---
                    # This is the correct way to make the AI speak first for an outbound call.
                    await session.trigger_initial_response()
                    logger.info("Triggered AI's initial greeting for outbound call.")

                    audio_input_started = True

                    # --- MODIFICATION: Create the first relay task ---
                    if not receive_task or receive_task.done():
                        receive_task = asyncio.create_task(relay_model_audio())

                    cap_task = asyncio.create_task(enforce_time_cap())
                    logger.info("Background tasks started")
                    continue

                elif event_type == "media" and audio_input_started:
                    # --- MODIFICATION START: Interruption Handling ---
                    # If the AI is speaking (receive_task is active) and we get user audio, it's an interruption.
                    if receive_task and not receive_task.done():
                        logger.warning("Interruption detected! User started speaking during AI playback.")

                        # 1. Send a 'clear' message to Twilio to stop playback immediately.
                        clear_msg = {
                            "event": "clear",
                            "streamSid": stream_sid
                        }
                        await websocket.send(json.dumps(clear_msg))
                        logger.info("Sent 'clear' message to Twilio.")

                        # 2. Cancel the current audio relay task to stop sending more audio.
                        receive_task.cancel()
                        try:
                            await receive_task
                        except asyncio.CancelledError:
                            pass  # This is expected
                        receive_task = None
                    # --- MODIFICATION END ---

                    media_data = data.get("media", {})
                    b64 = media_data.get("payload")
                    if b64:
                        try:
                            pcm16 = ulaw_b64_to_pcm16_bytes(b64)
                            await session.send_audio_pcm16(pcm16)
                        except Exception as e:
                            logger.error(f"Error processing audio frame: {e}")
                    continue

                elif event_type == "stop" and audio_input_started:
                    logger.info("Received 'stop' event, finishing user turn.")
                    await session.finish_user_turn()

                    # --- MODIFICATION START: Prepare for AI's response ---
                    # The user has stopped talking, so we now expect the AI to respond.
                    # We create a new relay task to handle this upcoming response.
                    if not receive_task or receive_task.done():
                        logger.info("User turn finished. Creating new task to listen for AI response.")
                        receive_task = asyncio.create_task(relay_model_audio())
                    # --- MODIFICATION END ---
                    continue

                else:
                    logger.debug(f"Ignoring event: {event_type} (audio_input_started={audio_input_started})")

            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON from Twilio: {e}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")

    except websockets.exceptions.ConnectionClosed:
        logger.info(f"WebSocket closed for {call_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {e}")
    finally:
        logger.info("Cleaning up WebSocket connection")
        if receive_task and not receive_task.done():
            receive_task.cancel()
        if cap_task and not cap_task.done():
            cap_task.cancel()

        # Await all cancelled tasks to ensure clean shutdown
        await asyncio.gather(
            receive_task or asyncio.sleep(0),
            cap_task or asyncio.sleep(0),
            return_exceptions=True
        )

        await session.close()
        logger.info(f"WebSocket cleanup complete for {call_id}")