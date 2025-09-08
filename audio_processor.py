"""
Real-time audio processor with VAD, noise reduction, and frame optimization.
Implements Silero VAD for ultra-low latency voice activity detection.
"""
import asyncio
import numpy as np
from typing import Optional, Tuple
from collections import deque
import time

from loguru import logger


# Audio constants
SAMPLE_RATE = 8000  # 8kHz for Twilio
FRAME_DURATION_MS = 20  # 20ms frames
SAMPLES_PER_FRAME = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
BYTES_PER_SAMPLE = 2  # 16-bit PCM
FRAME_SIZE_BYTES = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE

# VAD constants
VAD_THRESHOLD = 0.5  # Silero VAD threshold
VAD_MIN_SPEECH_MS = 250  # Minimum speech duration to trigger
VAD_MIN_SILENCE_MS = 700  # Minimum silence to end speech
SPEECH_FRAMES_THRESHOLD = int(VAD_MIN_SPEECH_MS / FRAME_DURATION_MS)
SILENCE_FRAMES_THRESHOLD = int(VAD_MIN_SILENCE_MS / FRAME_DURATION_MS)


class SimpleVAD:
    """Simple VAD using WebRTC or energy-based detection for Python 3.12 compatibility"""
    
    def __init__(self):
        self.vad = None
        self._initialized = False
        self._init_vad()
    
    def _init_vad(self):
        """Initialize VAD - try WebRTC first, fallback to energy-based"""
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(2)  # Aggressiveness level 0-3
            self._initialized = True
            logger.info("WebRTC VAD initialized successfully")
        except ImportError:
            logger.warning("WebRTC VAD not available - using energy-based detection")
            self._initialized = False
    
    def is_speech(self, audio_bytes: bytes) -> float:
        """
        Detect if audio contains speech.
        Returns confidence score between 0 and 1.
        """
        if self._initialized and self.vad:
            try:
                # WebRTC VAD expects 10, 20, or 30ms frames at 8kHz
                # Our frame size is 20ms which is perfect
                is_speech = self.vad.is_speech(audio_bytes, SAMPLE_RATE)
                return 1.0 if is_speech else 0.0
            except Exception as e:
                logger.error(f"WebRTC VAD error: {e}")
                return self._energy_based_vad(audio_bytes)
        else:
            # Fallback to energy-based detection
            return self._energy_based_vad(audio_bytes)
    
    def _energy_based_vad(self, audio_bytes: bytes) -> float:
        """Simple energy-based VAD as fallback"""
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        energy = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2))
        
        # Normalize to 0-1 range
        silence_threshold = 500  # Empirical threshold for 16-bit audio
        speech_threshold = 2000
        
        if energy < silence_threshold:
            return 0.0
        elif energy > speech_threshold:
            return 1.0
        else:
            return (energy - silence_threshold) / (speech_threshold - silence_threshold)


class AudioProcessor:
    """
    Real-time audio processor for ultra-low latency processing.
    Handles VAD, noise reduction, and audio optimization.
    """
    
    def __init__(self):
        # VAD components
        self.vad = SimpleVAD()
        self.speech_frames = 0
        self.silence_frames = 0
        self.is_speaking = False
        
        # Audio buffers
        self.input_buffer = bytearray()
        self.output_buffer = bytearray()
        
        # Noise reduction
        self.noise_profile = None
        self.noise_gate_threshold = 0.02
        
        # Performance tracking
        self.metrics = {
            "frames_processed": 0,
            "speech_frames": 0,
            "silence_frames": 0,
            "avg_vad_time": 0,
        }
    
    def process_incoming(self, audio_data: bytes) -> Optional[bytes]:
        """
        Process incoming audio from user with minimal latency.
        Returns processed audio or None if should be dropped.
        """
        start_time = time.time()
        
        # Ensure we have complete frames
        self.input_buffer.extend(audio_data)
        
        if len(self.input_buffer) < FRAME_SIZE_BYTES:
            return None
        
        # Process one frame at a time
        frame = bytes(self.input_buffer[:FRAME_SIZE_BYTES])
        self.input_buffer = self.input_buffer[FRAME_SIZE_BYTES:]
        
        # Run VAD
        speech_prob = self.vad.is_speech(frame)
        
        # Update speech state
        if speech_prob > VAD_THRESHOLD:
            self.speech_frames += 1
            self.silence_frames = 0
            
            if self.speech_frames >= SPEECH_FRAMES_THRESHOLD:
                if not self.is_speaking:
                    logger.debug("Speech started")
                    self.is_speaking = True
        else:
            self.silence_frames += 1
            self.speech_frames = 0
            
            if self.silence_frames >= SILENCE_FRAMES_THRESHOLD:
                if self.is_speaking:
                    logger.debug("Speech ended")
                    self.is_speaking = False
        
        # Apply noise reduction if speaking
        if self.is_speaking:
            processed_frame = self._reduce_noise(frame)
        else:
            # Don't send silence to reduce bandwidth
            processed_frame = None
        
        # Update metrics
        vad_time = time.time() - start_time
        self._update_vad_metrics(vad_time)
        
        return processed_frame
    
    def process_outgoing(self, audio_data: bytes) -> bytes:
        """
        Process outgoing audio from AI with minimal latency.
        Mainly ensures consistent frame sizes.
        """
        # Add to output buffer
        self.output_buffer.extend(audio_data)
        
        # Return complete frames
        if len(self.output_buffer) >= FRAME_SIZE_BYTES:
            frame = bytes(self.output_buffer[:FRAME_SIZE_BYTES])
            self.output_buffer = self.output_buffer[FRAME_SIZE_BYTES:]
            return frame
        
        return b''  # Not enough data yet
    
    def _reduce_noise(self, audio_frame: bytes) -> bytes:
        """Apply simple noise reduction"""
        # Convert to numpy array
        audio_int16 = np.frombuffer(audio_frame, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        
        # Apply noise gate
        mask = np.abs(audio_float) > self.noise_gate_threshold
        audio_float = audio_float * mask
        
        # Convert back to int16
        audio_int16 = (audio_float * 32768).astype(np.int16)
        
        return audio_int16.tobytes()
    
    def _update_vad_metrics(self, vad_time: float):
        """Update VAD performance metrics"""
        self.metrics["frames_processed"] += 1
        
        if self.is_speaking:
            self.metrics["speech_frames"] += 1
        else:
            self.metrics["silence_frames"] += 1
        
        # Update average VAD time
        total = self.metrics["frames_processed"]
        current_avg = self.metrics["avg_vad_time"]
        self.metrics["avg_vad_time"] = (current_avg * (total - 1) + vad_time) / total
    
    def get_metrics(self) -> dict:
        """Get processing metrics"""
        return {
            **self.metrics,
            "avg_vad_time_ms": self.metrics["avg_vad_time"] * 1000,
            "is_speaking": self.is_speaking,
        }


class InterruptionHandler:
    """Handles user interruptions for natural conversation flow"""
    
    def __init__(self, min_words: int = 3):
        self.min_words = min_words
        self.current_transcript = ""
        self.word_count = 0
        self.interruption_detected = False
    
    def process_transcript(self, transcript: str) -> bool:
        """
        Process user transcript to detect valid interruptions.
        Returns True if interruption should be triggered.
        """
        # Update transcript
        self.current_transcript = transcript
        
        # Count words
        words = transcript.strip().split()
        self.word_count = len(words)
        
        # Check if enough words for valid interruption
        if self.word_count >= self.min_words:
            if not self.interruption_detected:
                logger.info(f"Interruption detected: '{transcript}'")
                self.interruption_detected = True
            return True
        
        return False
    
    def reset(self):
        """Reset interruption state"""
        self.current_transcript = ""
        self.word_count = 0
        self.interruption_detected = False
