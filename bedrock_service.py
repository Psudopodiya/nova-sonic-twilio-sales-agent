# bedrock_service.py
import asyncio
import base64
import json
import os
import uuid
from utils import logger, get_env
import time

try:
    from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient
    from aws_sdk_bedrock_runtime.config import Config, SigV4AuthScheme, HTTPAuthSchemeResolver
    from aws_sdk_bedrock_runtime.models import (
        InvokeModelWithBidirectionalStreamOperationInput,
        InvokeModelWithBidirectionalStreamInputChunk,
        BidirectionalInputPayloadPart,
    )
    from smithy_aws_core.credentials_resolvers import StaticCredentialsResolver
    from smithy_aws_core.identity import AWSCredentialsIdentity
    from smithy_core.aio.eventstream import DuplexEventStream
except ModuleNotFoundError as e:
    logger.error(f"Missing AWS Nova Sonic dependencies: {e}")
    logger.error("Install with: pip install pipecat-ai[aws-nova-sonic]")
    raise

SILENCE_MS = int(os.getenv("TURN_SILENCE_MS", "700"))
silence_task = None
silence_deadline = 0.0
MODEL_ID = "amazon.nova-sonic-v1:0"
REGION = get_env("AWS_REGION", required=True)


def _mk_client():
    """Create AWS Bedrock Runtime client for Nova Sonic"""
    cfg = Config(
        endpoint_uri=f"https://bedrock-runtime.{REGION}.amazonaws.com",
        region=REGION,
        aws_credentials_identity_resolver=StaticCredentialsResolver(
            credentials=AWSCredentialsIdentity(
                access_key_id=get_env("aws_access_key_id", required=True),
                secret_access_key=get_env("aws_secret_access_key", required=True),
                session_token=get_env("aws_session_token")
            )
        ),
        http_auth_scheme_resolver=HTTPAuthSchemeResolver(),
        http_auth_schemes={"aws.auth#sigv4": SigV4AuthScheme()},
    )
    return BedrockRuntimeClient(config=cfg)


class SonicSession:
    """
    AWS Nova Sonic bidirectional streaming session following the correct API structure.
    """

    def __init__(self, voice_id: str = "mathew"):
        self.voice_id = voice_id
        self.client = _mk_client()
        self.stream = None
        self.active = False
        self.prompt_name = str(uuid.uuid4())
        self.current_audio_content_name = None
        self.session_started = False

    async def initiate_ai_greeting(self):
        """
        Satisfies the API rule that a prompt must contain an audio block
        by sending an empty audio turn, then ends the prompt to trigger
        the AI's initial response.
        """
        if not self.session_started:
            logger.error("Cannot initiate greeting: session not started")
            return

        try:
            # 1. Define and start an empty audio content block from the user
            empty_audio_content_name = str(uuid.uuid4())
            await self._send_event({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": empty_audio_content_name,
                        "type": "AUDIO",
                        "interactive": True,
                        "role": "USER",
                        "audioInputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 8000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "audioType": "SPEECH",
                            "encoding": "base64"
                        }
                    }
                }
            })

            # 2. Immediately end that audio block since it's empty
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": empty_audio_content_name,
                        "type": "AUDIO"
                    }
                }
            })

            # 3. Now, end the entire prompt. The API is satisfied and will respond.
            await self._send_event({
                "event": {
                    "promptEnd": {
                        "promptName": self.prompt_name
                    }
                }
            })
            logger.info("Empty audio turn sent. Triggering AI's initial response.")

        except Exception as e:
            logger.error(f"Failed to trigger initial AI greeting: {e}")

    async def _send_empty_user_turn(self):
        """Sends an empty text input from the USER role to kickstart the AI's response."""
        try:
            user_content_name = str(uuid.uuid4())
            # 1. Start a content block for a user's turn
            await self._send_event({
                "event": {
                    "contentStart": {
                        "promptName": self.prompt_name,
                        "contentName": user_content_name,
                        "type": "TEXT",
                        "interactive": True,
                        "role": "USER",
                        "textInputConfiguration": {"mediaType": "text/plain"}
                    }
                }
            })

            # --------------------------------------------------------------- #
            # ADD THIS BLOCK: Send a textInput event with an empty string     #
            # --------------------------------------------------------------- #
            await self._send_event({
                "event": {
                    "textInput": {
                        "promptName": self.prompt_name,
                        "contentName": user_content_name,
                        "content": ""  # This empty string is the fix
                    }
                }
            })
            # --------------------------------------------------------------- #

            # 2. Immediately end the content block.
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": user_content_name,
                        "type": "TEXT"
                    }
                }
            })
            logger.debug("Sent an empty user turn to kickstart the AI.")

        except Exception as e:
            logger.error(f"Failed to send empty user turn: {e}")

    async def trigger_initial_response(self):
        """
        Triggers the model's initial response by sending an empty user turn
        and then ending the prompt.
        """
        if not self.session_started:
            logger.error("Cannot trigger initial response: session not started")
            return

        try:
            # First, send the empty "nudge" to the API
            await self._send_empty_user_turn()

            # Now, end the prompt to trigger the model's response
            await self._send_event({
                "event": {
                    "promptEnd": {
                        "promptName": self.prompt_name
                    }
                }
            })
            logger.info("Initial prompt ended to trigger model's first response")

        except Exception as e:
            logger.error(f"Failed to trigger initial response: {e}")

    async def start(self, system_text: str = ""):
        """Start the bidirectional stream and initialize session"""
        try:
            # Open the bidirectional stream
            self.stream = await self.client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID)
            )
            self.active = True

            # 1. Send session start event
            await self._send_event({
                "event": {
                    "sessionStart": {
                        "inferenceConfiguration": {
                            "maxTokens": 512,
                            "topP": 0.9,
                            "temperature": 0.7
                        }
                    }
                }
            })

            # 2. Send prompt start event
            await self._send_event({
                "event": {
                    "promptStart": {
                        "promptName": self.prompt_name,
                        "textOutputConfiguration": {
                            "mediaType": "text/plain"
                        },
                        "audioOutputConfiguration": {
                            "mediaType": "audio/lpcm",
                            "sampleRateHertz": 8000,
                            "sampleSizeBits": 16,
                            "channelCount": 1,
                            "voiceId": self.voice_id,
                            "encoding": "base64",
                            "audioType": "SPEECH"
                        }
                    }
                }
            })

            # 3. Send system message if provided
            if not system_text:
                system_text = "You are a helpful AI assistant."

            await self._send_system_message(system_text)
            self.session_started = True
            logger.info("Nova Sonic session started successfully with system message")

        except Exception as e:
            logger.error(f"Failed to start Nova Sonic session: {e}")
            self.active = False
            raise

    async def _send_system_message(self, system_text: str):
        """Send system message using the correct 3-part pattern"""
        system_content_name = str(uuid.uuid4())

        # contentStart for system message
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": system_content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        })

        # textInput with actual content
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName": self.prompt_name,
                    "contentName": system_content_name,
                    "content": system_text
                }
            }
        })

        # contentEnd to close the system message
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": system_content_name,
                    "type": "TEXT"
                }
            }
        })

    async def start_audio_input(self):
        """Start a new audio input content block"""
        if not self.session_started:
            logger.error("Cannot start audio input: session not started")
            return

        self.current_audio_content_name = str(uuid.uuid4())

        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": self.current_audio_content_name,
                    "type": "AUDIO",
                    "interactive": True,
                    "role": "USER",
                    "audioInputConfiguration": {
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 8000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }
                }
            }
        })
        logger.info("Audio input started")

    async def send_audio_pcm16(self, pcm16: bytes):
        """Send PCM16 audio data to Nova Sonic"""
        if not self.active or not pcm16 or not self.current_audio_content_name:
            if not self.active:
                logger.debug("Cannot send audio: session not active")
            elif not self.current_audio_content_name:
                logger.debug("Cannot send audio: no active audio content")
            return

        try:
            b64 = base64.b64encode(pcm16).decode("ascii")
            logger.debug(f"Sending {len(pcm16)} bytes of PCM16 audio to Nova Sonic")
            await self._send_event({
                "event": {
                    "audioInput": {
                        "promptName": self.prompt_name,
                        "contentName": self.current_audio_content_name,
                        "content": b64
                    }
                }
            })
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")

    async def finish_user_turn(self):
        """Signal end of user audio input to trigger model response"""
        if not self.active or not self.current_audio_content_name:
            return

        try:
            # Close the current audio content
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.current_audio_content_name,
                        "type": "AUDIO"
                    }
                }
            })

            # End the prompt to trigger model response
            await self._send_event({
                "event": {
                    "promptEnd": {
                        "promptName": self.prompt_name
                    }
                }
            })

            # Clear current audio content since it's closed
            self.current_audio_content_name = None
            logger.info("User turn finished, waiting for model response")

        except Exception as e:
            logger.error(f"Failed to finish user turn: {e}")

    async def recv_loop(self):
        """Yield raw PCM16 bytes from model audioOutput events"""
        if not self.active or not self.stream:
            logger.warning("recv_loop called but session not active or no stream")
            return

        logger.info("Starting Nova Sonic recv_loop")
        try:
            while self.active:
                try:
                    # Wait for output from the stream
                    output = await self.stream.await_output()
                    result = await output[1].receive()

                    if not result.value or not result.value.bytes_:
                        continue

                    try:
                        response_data = result.value.bytes_.decode("utf-8")
                        json_data = json.loads(response_data)

                        if "event" in json_data:
                            event = json_data["event"]
                            event_type = list(event.keys())[0] if event else "unknown"
                            logger.debug(f"Received Nova Sonic event: {event_type}")

                            # Handle audio output
                            if "audioOutput" in event:
                                audio_content = event["audioOutput"]["content"]
                                pcm16_data = base64.b64decode(audio_content)
                                logger.debug(f"Yielding {len(pcm16_data)} bytes of PCM16 audio")
                                yield pcm16_data

                            # Handle completion end - start new prompt for next turn
                            elif "completionEnd" in event:
                                logger.info("Model response completed, starting new prompt")
                                # Generate new prompt name for next turn
                                self.prompt_name = str(uuid.uuid4())

                                # Start new prompt for continued conversation
                                await self._send_event({
                                    "event": {
                                        "promptStart": {
                                            "promptName": self.prompt_name,
                                            "textOutputConfiguration": {
                                                "mediaType": "text/plain"
                                            },
                                            "audioOutputConfiguration": {
                                                "mediaType": "audio/lpcm",
                                                "sampleRateHertz": 8000,
                                                "sampleSizeBits": 16,
                                                "channelCount": 1,
                                                "voiceId": self.voice_id,
                                                "encoding": "base64",
                                                "audioType": "SPEECH"
                                            }
                                        }
                                    }
                                })

                                # Start audio input for next turn
                                await self.start_audio_input()
                                continue

                            # Handle other events
                            elif "textOutput" in event:
                                text = event["textOutput"]["content"]
                                logger.info(f"Model text output: {text}")

                            elif "inputTranscript" in event:
                                transcript = event["inputTranscript"]["content"]
                                logger.info(f"User transcript: {transcript}")

                    except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
                        # Skip malformed events or keep-alives
                        logger.debug(f"Skipping malformed event: {e}")
                        continue

                except asyncio.CancelledError:
                    logger.info("recv_loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in recv_loop iteration: {e}")
                    # Don't break on individual errors, continue listening
                    continue

        except asyncio.CancelledError:
            logger.info("recv_loop cancelled")
        except Exception as e:
            logger.error(f"Error in recv_loop: {e}")
        finally:
            logger.info("recv_loop ended")

    async def close(self):
        """Close the Nova Sonic session"""
        if not self.active:
            logger.debug("Session already closed")
            return

        logger.info("Closing Nova Sonic session")
        self.active = False  # Set this first to stop loops

        try:
            # Give a small delay for any pending operations
            await asyncio.sleep(0.1)

            # Close any open audio content
            if self.current_audio_content_name:
                await self._send_event({
                    "event": {
                        "contentEnd": {
                            "promptName": self.prompt_name,
                            "contentName": self.current_audio_content_name,
                            "type": "AUDIO"
                        }
                    }
                })

                await self._send_event({
                    "event": {
                        "promptEnd": {
                            "promptName": self.prompt_name
                        }
                    }
                })

            # End session
            await self._send_event({
                "event": {
                    "sessionEnd": {}
                }
            })
            logger.info("Nova Sonic session ended")
        except Exception as e:
            logger.error(f"Error closing session: {e}")
        finally:
            if self.stream:
                try:
                    await self.stream.input_stream.close()
                    logger.debug("Stream input closed")
                except Exception as e:
                    logger.debug(f"Error closing stream input: {e}")
                self.stream = None

    async def _send_event(self, obj: dict):
        """Send an event to Nova Sonic via the bidirectional stream"""
        if not self.stream or not self.active:
            return

        try:
            data = json.dumps(obj).encode("utf-8")
            chunk = InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=data)
            )
            await self.stream.input_stream.send(chunk)
        except Exception as e:
            logger.error(f"Failed to send event: {e}")
            raise
