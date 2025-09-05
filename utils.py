import os
import logging
import audioop
import base64
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("voice-agent")


def get_env(name, default=None, required=False):
    """Helper for fetching env vars with error logging"""
    value = os.getenv(name, default)
    if required and not value:
        logger.error(f"Missing required environment variable: {name}")
        raise RuntimeError(f"{name} not set")
    return value


def get_int_env(name, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


# --- Audio conversions ---
def ulaw_b64_to_pcm16_bytes(b64_payload: str) -> bytes:
    """Twilio media payload (base64 μ-law @8k) -> raw PCM16 mono @8k"""
    try:
        ulaw = base64.b64decode(b64_payload)
        pcm16 = audioop.ulaw2lin(ulaw, 2)  # 2 bytes/sample
        logger.debug(f"Converted {len(ulaw)} μ-law bytes to {len(pcm16)} PCM16 bytes")
        return pcm16
    except Exception as e:
        logger.error(f"Error converting μ-law to PCM16: {e}")
        return b""


def pcm16_bytes_to_ulaw_b64(pcm16: bytes) -> str:
    """raw PCM16 mono @8k -> base64 μ-law @8k for Twilio media"""
    try:
        ulaw = audioop.lin2ulaw(pcm16, 2)
        b64 = base64.b64encode(ulaw).decode("ascii")
        logger.debug(f"Converted {len(pcm16)} PCM16 bytes to {len(b64)} base64 μ-law chars")
        return b64
    except Exception as e:
        logger.error(f"Error converting PCM16 to μ-law: {e}")
        return ""