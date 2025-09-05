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

MAX_SECS = get_int_env("MAX_CONVO_SECS", 10)
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
    # system_prompt = meta.get("system_prompt", "")
    voice_id = meta.get("voice_id", "tiffany")

    logger.info(
        f"Call metadata: system_prompt='{system_prompt}...'', voice_id={voice_id}")

    session = SonicSession(voice_id=voice_id)
    receive_task = None
    cap_task = None
    call_sid = None
    audio_input_started = False

    async def enforce_time_cap():
        logger.info(f"Starting time cap enforcement: {MAX_SECS} seconds")
        await asyncio.sleep(MAX_SECS)
        logger.info("Time cap reached, closing WebSocket")
        # Primary: closing WS ends <Connect> since TwiML has no further verbs.
        await websocket.close(code=1000, reason="max_duration_reached")
        # Failsafe: explicit hangup if call SID is known
        if call_sid:
            try:
                logger.info(f"Hanging up call {call_sid}")
                twilio_client.calls(call_sid).update(status="completed")
            except Exception as e:
                logger.error(f"Failed to hang up call: {e}")

    async def relay_model_audio():
        """Relay model audio back to Twilio (PCM16 -> μ-law b64)"""
        logger.info("Starting model audio relay")
        seq = 0
        try:
            async for pcm16 in session.recv_loop():
                if not pcm16:
                    continue

                logger.debug(f"Converting {len(pcm16)} bytes PCM16 to μ-law for Twilio")
                payload = pcm16_bytes_to_ulaw_b64(pcm16)  # must be raw μ-law/8000, no headers
                seq += 1

                # >>> REQUIRED: include streamSid <<<
                media_msg = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": payload
                    }
                }
                await websocket.send(json.dumps(media_msg))

                # Optional but recommended: send a mark so you know when Twilio finishes playing this chunk
                mark_msg = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": f"chunk-{seq}"}
                }
                await websocket.send(json.dumps(mark_msg))
                logger.debug(f"Sent {len(payload)} bytes of μ-law audio to Twilio")

        except asyncio.CancelledError:
            logger.info("Model audio relay cancelled")
        except Exception as e:
            logger.error(f"Error in model audio relay: {e}")
        finally:
            logger.info("Model audio relay ended")

    try:
        logger.info("Starting WebSocket message loop")
        async for raw in websocket:
            try:
                data = json.loads(raw)
                event_type = data.get("event")
                logger.debug(f"Received Twilio event: {event_type}")

                # The first message from Twilio should be the "start" event
                if event_type == "start":
                    start_data = data.get("start", {})
                    call_sid = start_data.get("callSid")
                    stream_sid = start_data.get("streamSid")
                    logger.info(f"Call started with SID: {call_sid}, streamID: {stream_sid}")

                    # Start Nova Sonic session with combined prompts
                    # combined = f"{system_prompt}\n\n{industry_prompt}".strip()
                    combined = system_prompt.strip()
                    logger.info(f"Starting Nova Sonic with combined prompt:")
                    logger.info(combined)

                    await session.start(system_text=combined)

                    # # This block Works
                    await session.start_audio_input()
                    audio_input_started = True
                    logger.info("Audio input started, ready to process caller audio")

                    # TEST 1.
                    # await session.trigger_initial_response()
                    # logger.info("Triggered AI's initial greeting for outbound call.")
                    # audio_input_started = True

                    # # TEST 2.
                    # await session.initiate_ai_greeting()
                    # logger.info("Triggered AI's initial greeting for outbound call.")
                    # audio_input_started = True

                    # Start background tasks
                    receive_task = asyncio.create_task(relay_model_audio())
                    cap_task = asyncio.create_task(enforce_time_cap())
                    logger.info("Background tasks started")
                    continue

                # Caller audio frames - only process if audio input is started
                elif event_type == "media" and audio_input_started:
                    media_data = data.get("media", {})
                    b64 = media_data.get("payload")
                    if b64:
                        try:
                            pcm16 = ulaw_b64_to_pcm16_bytes(b64)
                            logger.debug(f"Received {len(b64)} bytes μ-law, converted to {len(pcm16)} bytes PCM16")
                            await session.send_audio_pcm16(pcm16)
                        except Exception as e:
                            logger.error(f"Error processing audio frame: {e}")
                    continue

                # Caller paused or stop-of-turn; let the model respond
                elif event_type == "stop" and audio_input_started:
                    logger.info(f"Received {event_type} event, finishing user turn")
                    await session.finish_user_turn()
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

        # Cancel tasks first
        if receive_task and not receive_task.done():
            logger.info("Cancelling receive task")
            receive_task.cancel()
            try:
                await receive_task
            except asyncio.CancelledError:
                logger.info("Receive task cancelled successfully")

        if cap_task and not cap_task.done():
            logger.info("Cancelling cap task")
            cap_task.cancel()
            try:
                await cap_task
            except asyncio.CancelledError:
                logger.info("Cap task cancelled successfully")

        # Close session last
        try:
            await session.close()
        except Exception as e:
            logger.error(f"Error closing Nova Sonic session: {e}")

        logger.info(f"WebSocket cleanup complete for {call_id}")
