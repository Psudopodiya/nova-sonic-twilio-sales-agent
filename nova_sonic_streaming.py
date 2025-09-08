"""
Optimized Nova Sonic streaming session for ultra-low latency.
Implements true streaming without buffering for real-time conversations.
"""
import asyncio
import base64
import json
import uuid
from typing import AsyncGenerator, Optional
from enum import Enum
import time

from loguru import logger

from utils import get_env

# Import AWS Nova Sonic dependencies
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
except ImportError as e:
    logger.error(f"Missing AWS Nova Sonic dependencies: {e}")
    raise


# Configuration
MODEL_ID = "amazon.nova-sonic-v1:0"
REGION = get_env("AWS_REGION", required=True)
FRAME_SIZE = 320  # 20ms of 8kHz PCM16 audio (160 samples * 2 bytes)
MAX_CONCURRENT_SENDS = 3  # Limit concurrent send operations


class StreamingState(Enum):
    """States for the streaming session"""
    IDLE = "idle"
    STARTING = "starting"
    READY = "ready"
    STREAMING = "streaming"
    CLOSING = "closing"
    CLOSED = "closed"


class NovaSonicStreamingSession:
    """
    Optimized Nova Sonic session for real-time streaming.
    Key optimizations:
    - Zero buffering on audio input
    - Immediate frame-by-frame processing
    - Concurrent send/receive operations
    - Minimal state management overhead
    """
    
    def __init__(self, voice_id: str, system_prompt: str, stream_sid: str):
        self.voice_id = voice_id
        self.system_prompt = system_prompt
        self.stream_sid = stream_sid
        
        # AWS client
        self.client = self._create_client()
        self.stream = None
        
        # Session state
        self.state = StreamingState.IDLE
        self.prompt_name = str(uuid.uuid4())
        self.current_audio_content_name: Optional[str] = None
        
        # Performance tracking
        self.send_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SENDS)
        self.metrics = {
            "audio_chunks_sent": 0,
            "audio_chunks_received": 0,
            "start_time": time.time(),
        }
        
        # Control flags
        self.receiving = False
        self.user_speaking = False

    def _create_client(self) -> BedrockRuntimeClient:
        """Create optimized AWS Bedrock Runtime client with error handling"""
        try:
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
            client = BedrockRuntimeClient(config=cfg)
            logger.success("✓ AWS Bedrock client initialized")
            return client
        except Exception as e:
            logger.error(f"Failed to create AWS Bedrock client: {e}")
            logger.error("Please check your AWS credentials and ensure you have access to Bedrock")
            raise

    async def start(self):
        """Start the bidirectional streaming session with comprehensive error handling"""
        if self.state != StreamingState.IDLE:
            logger.warning(f"Cannot start session in state {self.state}")
            return
            
        self.state = StreamingState.STARTING
        logger.info("Starting Nova Sonic streaming session")
        
        try:
            # Open bidirectional stream
            self.stream = await self.client.invoke_model_with_bidirectional_stream(
                InvokeModelWithBidirectionalStreamOperationInput(model_id=MODEL_ID)
            )
            
            # Send session configuration
            await self._initialize_session()
            
            # Mark as ready
            self.state = StreamingState.READY
            self.receiving = True
            
            logger.info("Nova Sonic session ready for streaming")
            
        except Exception as e:
            error_msg = str(e)
            self.state = StreamingState.IDLE
            
            # Provide specific error messages for common issues
            if "AccessDeniedException" in error_msg:
                logger.error("AWS Access Denied: You don't have permission to use Bedrock Nova Sonic")
                logger.error("Please ensure your AWS account has access to the Nova Sonic model")
            elif "ResourceNotFoundException" in error_msg:
                logger.error("Nova Sonic model not found in your region")
                logger.error(f"Please ensure Nova Sonic is available in {REGION} region")
            elif "InvalidCredentials" in error_msg or "SignatureDoesNotMatch" in error_msg:
                logger.error("Invalid AWS credentials")
                logger.error("Please check your aws_access_key_id and aws_secret_access_key")
            elif "ExpiredToken" in error_msg:
                logger.error("AWS session token has expired")
                logger.error("Please refresh your AWS credentials")
            else:
                logger.error(f"Failed to start Nova Sonic session: {e}")
            
            raise

    async def _initialize_session(self):
        """Initialize session with minimal setup for lowest latency"""
        # Session start with optimized parameters
        await self._send_event({
            "event": {
                "sessionStart": {
                    "inferenceConfiguration": {
                        "maxTokens": 256,  # Reduced for faster responses
                        "topP": 0.9,
                        "temperature": 0.7
                    }
                }
            }
        })
        
        # Prompt start
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
        
        # System prompt
        await self._send_system_prompt()
        
        # Start audio input immediately
        await self._start_audio_content()
        
        # For outbound calls, trigger the AI to speak first
        await self._trigger_initial_greeting()

    async def _send_system_prompt(self):
        """Send system prompt efficiently"""
        content_name = str(uuid.uuid4())
        
        # Start content
        await self._send_event({
            "event": {
                "contentStart": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "type": "TEXT",
                    "interactive": False,
                    "role": "SYSTEM",
                    "textInputConfiguration": {"mediaType": "text/plain"}
                }
            }
        })
        
        # Send text
        await self._send_event({
            "event": {
                "textInput": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "content": self.system_prompt
                }
            }
        })
        
        # End content
        await self._send_event({
            "event": {
                "contentEnd": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "type": "TEXT"
                }
            }
        })

    async def _start_audio_content(self):
        """Start audio content for user input"""
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
        
        self.user_speaking = True

    async def send_audio(self, pcm16_data: bytes):
        """Send audio with minimal latency - no buffering"""
        if not self.current_audio_content_name or self.state != StreamingState.READY:
            return
            
        # Use semaphore to limit concurrent sends
        async with self.send_semaphore:
            try:
                # Direct conversion and send - no buffering
                b64_audio = base64.b64encode(pcm16_data).decode("ascii")
                
                await self._send_event({
                    "event": {
                        "audioInput": {
                            "promptName": self.prompt_name,
                            "contentName": self.current_audio_content_name,
                            "content": b64_audio
                        }
                    }
                })
                
                self.metrics["audio_chunks_sent"] += 1
                
            except Exception as e:
                logger.error(f"Error sending audio: {e}")

    async def finish_user_turn(self):
        """Finish user turn to trigger AI response"""
        if not self.user_speaking or not self.current_audio_content_name:
            return
            
        logger.debug("Finishing user turn")
        self.user_speaking = False
        
        try:
            # End audio content
            await self._send_event({
                "event": {
                    "contentEnd": {
                        "promptName": self.prompt_name,
                        "contentName": self.current_audio_content_name,
                        "type": "AUDIO"
                    }
                }
            })
            
            # End prompt to trigger response
            await self._send_event({
                "event": {
                    "promptEnd": {
                        "promptName": self.prompt_name
                    }
                }
            })
            
            # Clear current audio content
            self.current_audio_content_name = None
            
        except Exception as e:
            logger.error(f"Error finishing user turn: {e}")

    async def receive_audio(self) -> AsyncGenerator[bytes, None]:
        """Receive audio from Nova Sonic with minimal buffering"""
        if not self.stream or not self.receiving:
            return
            
        logger.info("Starting audio reception from Nova Sonic")
        
        try:
            while self.receiving:
                try:
                    # Get output from stream
                    output = await self.stream.await_output()
                    result = await output[1].receive()
                    
                    if not result.value or not result.value.bytes_:
                        continue
                        
                    # Parse response
                    response_data = result.value.bytes_.decode("utf-8")
                    json_data = json.loads(response_data)
                    
                    if "event" not in json_data:
                        continue
                        
                    event = json_data["event"]
                    
                    # Handle audio output immediately
                    if "audioOutput" in event:
                        audio_b64 = event["audioOutput"]["content"]
                        audio_pcm16 = base64.b64decode(audio_b64)
                        
                        self.metrics["audio_chunks_received"] += 1
                        yield audio_pcm16
                    
                    # Handle completion - prepare for next turn
                    elif "completionEnd" in event:
                        logger.debug("AI response completed, preparing for next turn")
                        
                        # Start new prompt for continued conversation
                        self.prompt_name = str(uuid.uuid4())
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
                        
                        # Immediately start audio input for next turn
                        await self._start_audio_content()
                    
                    # Log text output if present
                    elif "textOutput" in event:
                        text = event["textOutput"]["content"]
                        logger.info(f"AI: {text}")
                    
                    # Log user transcript if present
                    elif "inputTranscript" in event:
                        transcript = event["inputTranscript"]["content"]
                        logger.info(f"User: {transcript}")
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Error in receive loop: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Fatal error in receive_audio: {e}")
        finally:
            logger.info("Audio reception ended")

    async def close(self):
        """Close the streaming session"""
        if self.state == StreamingState.CLOSED:
            return
            
        logger.info("Closing Nova Sonic session")
        self.state = StreamingState.CLOSING
        self.receiving = False
        
        try:
            # Close any open content
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
            
            # Log metrics
            runtime = time.time() - self.metrics["start_time"]
            logger.info(
                f"Nova Sonic session closed - "
                f"Duration: {runtime:.1f}s, "
                f"Audio sent: {self.metrics['audio_chunks_sent']}, "
                f"Audio received: {self.metrics['audio_chunks_received']}"
            )
            
        except Exception as e:
            logger.error(f"Error closing session: {e}")
        finally:
            self.state = StreamingState.CLOSED
            if self.stream:
                try:
                    await self.stream.input_stream.close()
                except:
                    pass
                self.stream = None

    async def _send_event(self, obj: dict):
        """Send event to Nova Sonic with error handling"""
        if not self.stream or self.state == StreamingState.CLOSED:
            return
            
        try:
            data = json.dumps(obj).encode("utf-8")
            chunk = InvokeModelWithBidirectionalStreamInputChunk(
                value=BidirectionalInputPayloadPart(bytes_=data)
            )
            await self.stream.input_stream.send(chunk)
        except Exception as e:
            logger.error(f"Failed to send event: {e}")
            if self.state != StreamingState.CLOSING:
                raise
