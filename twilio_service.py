# twilio_service.py
import uuid
from flask import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from utils import logger

call_metadata = {}
active_streams = {}


def init_call(phone_number, system_prompt, timeout):
    """Create a new call record"""
    call_id = str(uuid.uuid4())
    call_metadata[call_id] = {
        "phone_number": phone_number,
        "status": "initiated",
        "system_prompt": system_prompt,
        # "industry_prompt": industry_prompt,
        "call_timeout": timeout,
        "conversation_turns": 0,
    }
    logger.info(f"Created call metadata for {phone_number}, id={call_id}")
    return call_id


def twiml_response_for_call(call_id, websocket_url):
    """Generate TwiML to connect Twilio to our WebSocket"""
    logger.info(f"Generating TwiML for call {call_id}, WS={websocket_url}")

    # Create VoiceResponse
    response = VoiceResponse()

    # Create Connect verb
    connect = Connect()

    # Create Stream - just pass the URL directly
    connect.stream(url=websocket_url)

    # Add Connect to the response
    response.append(connect)

    # Convert to XML string for debugging
    twiml_xml = str(response)
    logger.info(f"Generated TwiML XML: {twiml_xml}")

    # Return as Flask Response with correct content type
    return Response(twiml_xml, mimetype="text/xml")