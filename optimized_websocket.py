"""
Optimized WebSocket handler for ultra-low latency audio streaming.
Implements frame-based processing, VAD, and real-time streaming.
"""
import asyncio
import json
import base64
from typing import Optional, Dict, Any
from collections import deque
import time

from fastapi import WebSocket
from loguru import logger

from nova_sonic_streaming import NovaSonicStreamingSession
from audio_processor import AudioProcessor
from utils import ulaw_b64_to_pcm16_bytes, pcm16_bytes_to_ulaw_b64
from call_state import CallStateManager
from prompt_builder import prompt_builder


class OptimizedWebSocketHandler:
    """Handles real-time audio streaming between Twilio and Nova Sonic"""
    
    def __init__(self, websocket: WebSocket, call_id: str, call_manager: CallStateManager):
        self.websocket = websocket
        self.call_id = call_id
        self.call_manager = call_manager
        self.stream_sid: Optional[str] = None
        self.call_sid: Optional[str] = None
        
        # Audio processing components
        self.audio_processor = AudioProcessor()
        self.nova_session: Optional[NovaSonicStreamingSession] = None
        
        # Performance tracking
        self.metrics = {
            "start_time": time.time(),
            "audio_frames_received": 0,
            "audio_frames_sent": 0,
            "avg_processing_time": 0,
            "max_processing_time": 0,
        }
        
        # Audio buffering for smooth playback
        self.audio_queue = asyncio.Queue(maxsize=50)
        self.frame_buffer = deque(maxlen=3)  # Small buffer for jitter compensation
        
        # Control flags
        self.running = True
        self.audio_started = False
        self.tasks: list[asyncio.Task] = []

    async def handle(self):
        """Main handler for WebSocket connection"""
        try:
            # Start receiving messages from Twilio
            await self._process_twilio_messages()
            
        except Exception as e:
            logger.error(f"Error in WebSocket handler: {e}")
        finally:
            await self._cleanup()

    async def _process_twilio_messages(self):
        """Process incoming messages from Twilio"""
        async for message in self.websocket.iter_text():
            if not self.running:
                break
                
            try:
                data = json.loads(message)
                event_type = data.get("event")
                
                # Route events to appropriate handlers
                if event_type == "start":
                    await self._handle_start(data)
                elif event_type == "media":
                    await self._handle_media(data)
                elif event_type == "stop":
                    await self._handle_stop(data)
                elif event_type == "mark":
                    await self._handle_mark(data)
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {message[:100]}")
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    async def _handle_start(self, data: Dict[str, Any]):
        """Handle call start event with error handling"""
        try:
            start_data = data.get("start", {})
            self.stream_sid = start_data.get("streamSid")
            self.call_sid = start_data.get("callSid")
            
            logger.info(f"Call started - SID: {self.call_sid}, Stream: {self.stream_sid}")
            
            # Get call metadata
            call_data = self.call_manager.get_call(self.call_id)
            voice_id = call_data.get("voice_id", "mathew") if call_data else "mathew"
            
            # Build complete prompt using prompt builder
            # Get prospect info from call data if available
            prospect_info = call_data.get("prospect_info", {}) if call_data else {}
            scenario = call_data.get("scenario", "universal") if call_data else "universal"
            
            # Build the complete prompt
            system_prompt = prompt_builder.build_complete_prompt(
                prospect_info=prospect_info,
                scenario=scenario
            )
            logger.info(f"Built prompt for {prompt_builder.get_agent_name()} from {prompt_builder.get_company_name()}")
            
            # Initialize Nova Sonic session with streaming
            self.nova_session = NovaSonicStreamingSession(
                voice_id=voice_id,
                system_prompt=system_prompt,
                stream_sid=self.stream_sid,
            )
            
            # Start the Nova Sonic session with error handling
            try:
                await self.nova_session.start()
            except Exception as e:
                logger.error(f"Failed to start Nova Sonic session: {e}")
                # Send error message to Twilio
                await self._send_error_to_twilio("Service temporarily unavailable. Please try again later.")
                # Close the WebSocket
                await self.websocket.close(code=1011, reason="Nova Sonic initialization failed")
                return
            
            # Start background tasks for audio processing
            self.tasks = [
                asyncio.create_task(self._audio_sender()),
                asyncio.create_task(self._nova_receiver()),
                asyncio.create_task(self._metrics_logger()),
            ]
            
            # Mark audio as started
            self.audio_started = True
            logger.info("Audio streaming initialized and started")
            
        except Exception as e:
            logger.error(f"Critical error in _handle_start: {e}")
            await self._send_error_to_twilio("System error occurred. Call will be disconnected.")
            await self.websocket.close(code=1011, reason="Start handler failed")

    async def _handle_media(self, data: Dict[str, Any]):
        """Handle incoming audio media frames"""
        if not self.audio_started or not self.nova_session:
            return
            
        media_data = data.get("media", {})
        payload = media_data.get("payload")
        
        if not payload:
            return
            
        start_time = time.time()
        
        try:
            # Convert μ-law to PCM16
            pcm16_data = ulaw_b64_to_pcm16_bytes(payload)
            
            # Apply audio processing (VAD, noise reduction, etc.)
            processed_audio = self.audio_processor.process_incoming(pcm16_data)
            
            if processed_audio:
                # Send to Nova Sonic immediately (no buffering)
                await self.nova_session.send_audio(processed_audio)
                
            # Track metrics
            processing_time = time.time() - start_time
            self._update_metrics(processing_time)
            
        except Exception as e:
            logger.error(f"Error processing audio frame: {e}")

    async def _handle_stop(self, data: Dict[str, Any]):
        """Handle stop speaking event - triggers AI response"""
        if not self.nova_session:
            return
            
        logger.debug("User stopped speaking - triggering AI response")
        await self.nova_session.finish_user_turn()

    async def _handle_mark(self, data: Dict[str, Any]):
        """Handle mark events for synchronization"""
        mark_data = data.get("mark", {})
        mark_name = mark_data.get("name")
        logger.debug(f"Received mark: {mark_name}")

    async def _audio_sender(self):
        """Send audio frames to Twilio with optimal timing"""
        sequence = 0
        frame_duration = 0.02  # 20ms frames for 8kHz audio
        
        try:
            while self.running:
                try:
                    # Get audio from queue with timeout
                    audio_data = await asyncio.wait_for(
                        self.audio_queue.get(),
                        timeout=0.1
                    )
                    
                    # Send to Twilio
                    await self._send_audio_to_twilio(audio_data, sequence)
                    sequence += 1
                    
                    # Maintain consistent frame timing
                    await asyncio.sleep(frame_duration)
                    
                except asyncio.TimeoutError:
                    # No audio available, continue
                    continue
                    
        except asyncio.CancelledError:
            logger.info("Audio sender task cancelled")
        except Exception as e:
            logger.error(f"Error in audio sender: {e}")

    async def _nova_receiver(self):
        """Receive audio from Nova Sonic and queue for sending"""
        if not self.nova_session:
            return
            
        try:
            async for audio_chunk in self.nova_session.receive_audio():
                if not self.running:
                    break
                    
                # Apply output processing
                processed_audio = self.audio_processor.process_outgoing(audio_chunk)
                
                # Queue for sending to Twilio
                if processed_audio:
                    try:
                        self.audio_queue.put_nowait(processed_audio)
                    except asyncio.QueueFull:
                        # Drop oldest frame if queue is full
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.put_nowait(processed_audio)
                        except:
                            pass
                            
        except asyncio.CancelledError:
            logger.info("Nova receiver task cancelled")
        except Exception as e:
            logger.error(f"Error in Nova receiver: {e}")

    async def _send_audio_to_twilio(self, pcm16_data: bytes, sequence: int):
        """Send audio frame to Twilio"""
        if not self.stream_sid:
            return
            
        try:
            # Convert PCM16 to μ-law
            ulaw_data = pcm16_bytes_to_ulaw_b64(pcm16_data)
            
            # Create media message
            media_msg = {
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {
                    "payload": ulaw_data
                }
            }
            
            # Send to Twilio
            await self.websocket.send_text(json.dumps(media_msg))
            
            # Send mark for synchronization
            if sequence % 50 == 0:  # Every 50 frames (1 second)
                mark_msg = {
                    "event": "mark",
                    "streamSid": self.stream_sid,
                    "mark": {"name": f"audio-{sequence}"}
                }
                await self.websocket.send_text(json.dumps(mark_msg))
                
            self.metrics["audio_frames_sent"] += 1
            
        except Exception as e:
            logger.error(f"Error sending audio to Twilio: {e}")

    async def _metrics_logger(self):
        """Log performance metrics periodically"""
        try:
            while self.running:
                await asyncio.sleep(10)  # Log every 10 seconds
                
                runtime = time.time() - self.metrics["start_time"]
                logger.info(
                    f"Call {self.call_id} metrics - "
                    f"Runtime: {runtime:.1f}s, "
                    f"Frames in: {self.metrics['audio_frames_received']}, "
                    f"Frames out: {self.metrics['audio_frames_sent']}, "
                    f"Avg processing: {self.metrics['avg_processing_time']*1000:.1f}ms, "
                    f"Max processing: {self.metrics['max_processing_time']*1000:.1f}ms"
                )
                
        except asyncio.CancelledError:
            pass

    def _update_metrics(self, processing_time: float):
        """Update performance metrics"""
        self.metrics["audio_frames_received"] += 1
        
        # Update average processing time
        total_frames = self.metrics["audio_frames_received"]
        current_avg = self.metrics["avg_processing_time"]
        self.metrics["avg_processing_time"] = (
            (current_avg * (total_frames - 1) + processing_time) / total_frames
        )
        
        # Update max processing time
        if processing_time > self.metrics["max_processing_time"]:
            self.metrics["max_processing_time"] = processing_time
    
    async def _send_error_to_twilio(self, message: str):
        """Send error message as TTS to Twilio"""
        try:
            # Create a simple TTS message using Twilio's say verb
            error_twiml = {
                "event": "say",
                "streamSid": self.stream_sid,
                "say": {
                    "text": message,
                    "voice": "Polly.Matthew"
                }
            }
            await self.websocket.send_text(json.dumps(error_twiml))
            logger.info(f"Sent error message to caller: {message}")
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

    async def _cleanup(self):
        """Clean up resources"""
        logger.info(f"Cleaning up WebSocket handler for call {self.call_id}")
        
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
                
        # Wait for tasks to complete
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Close Nova Sonic session
        if self.nova_session:
            await self.nova_session.close()
        
        # Log final metrics
        runtime = time.time() - self.metrics["start_time"]
        logger.info(
            f"Call {self.call_id} completed - "
            f"Duration: {runtime:.1f}s, "
            f"Total frames: {self.metrics['audio_frames_received']}, "
            f"Avg latency: {self.metrics['avg_processing_time']*1000:.1f}ms"
        )


async def handle_twilio_websocket(
    websocket: WebSocket, 
    call_id: str, 
    call_manager: CallStateManager
):
    """Entry point for handling Twilio WebSocket connections"""
    handler = OptimizedWebSocketHandler(websocket, call_id, call_manager)
    await handler.handle()
