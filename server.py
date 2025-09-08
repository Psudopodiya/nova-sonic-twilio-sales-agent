"""
Optimized FastAPI server with WebSocket streaming for low-latency AI voice calls.
Replaces Flask with FastAPI for better async support and performance.
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

from optimized_websocket import handle_twilio_websocket
from call_state import CallStateManager

# Load environment variables
load_dotenv(override=True)

# Configuration with validation
def validate_config():
    """Validate required configuration and credentials"""
    errors = []
    
    # Check Twilio credentials
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
    
    if not TWILIO_ACCOUNT_SID:
        errors.append("TWILIO_ACCOUNT_SID is missing")
    if not TWILIO_AUTH_TOKEN:
        errors.append("TWILIO_AUTH_TOKEN is missing")
    if not TWILIO_PHONE_NUMBER:
        errors.append("TWILIO_PHONE_NUMBER is missing")
    
    # Check AWS credentials
    AWS_REGION = os.getenv("AWS_REGION")
    AWS_ACCESS_KEY = os.getenv("aws_access_key_id")
    AWS_SECRET_KEY = os.getenv("aws_secret_access_key")
    
    if not AWS_REGION:
        errors.append("AWS_REGION is missing")
    if not AWS_ACCESS_KEY:
        errors.append("aws_access_key_id is missing")
    if not AWS_SECRET_KEY:
        errors.append("aws_secret_access_key is missing")
    
    # Check PUBLIC_HOST
    PUBLIC_HOST = os.getenv("PUBLIC_HOST")
    if not PUBLIC_HOST or PUBLIC_HOST == "your.domain.com":
        errors.append("PUBLIC_HOST not configured (set to your ngrok URL or domain)")
    
    if errors:
        logger.error("Configuration validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("\nPlease check your .env file and ensure all required variables are set")
        return False, errors
    
    return True, None

# Validate configuration before proceeding
config_valid, config_errors = validate_config()
if not config_valid:
    logger.error("\n⚠️  Cannot start server due to configuration errors")
    logger.error("Please fix the above issues and try again")
    import sys
    sys.exit(1)

# Load configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
USE_HTTPS = os.getenv("USE_HTTPS", "false").lower() == "true"
PORT = int(os.getenv("PORT", "7860"))

# Initialize services with error handling
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    # Test Twilio credentials by fetching account info
    account = twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
    logger.success(f"✓ Twilio connected: {account.friendly_name}")
except Exception as e:
    logger.error(f"Failed to connect to Twilio: {e}")
    logger.error("Please check your Twilio credentials")
    import sys
    sys.exit(1)

call_manager = CallStateManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles FastAPI startup and shutdown."""
    logger.info(f"Starting server on {PUBLIC_HOST}:{PORT}")
    yield
    logger.info("Shutting down server")


# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# Configure CORS for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "nova-sonic-optimized"}


@app.post("/make-call")
async def make_outbound_call(request: Request):
    """Initiate an outbound call with AI agent"""
    try:
        data = await request.json()
        to_number = data.get("to")
        from_number = data.get("from", TWILIO_PHONE_NUMBER)
        voice_id = data.get("voice_id", "mathew")
        
        # Extract prospect information if provided
        prospect_info = data.get("prospect_info", {})
        scenario = data.get("scenario", "universal")  # universal, aws_existing, migration
        
        if not to_number:
            return {"error": "Missing 'to' number"}, 400
            
        # Generate call ID
        call_id = str(uuid4())
        
        # Create call record with prospect info
        call_manager.create_call(call_id, {
            "to": to_number,
            "from": from_number,
            "voice_id": voice_id,
            "status": "initiating",
            "prospect_info": prospect_info,
            "scenario": scenario
        })
        
        # Build webhook URL
        protocol = "https" if USE_HTTPS else "http"
        webhook_url = f"{protocol}://{PUBLIC_HOST}/webhooks/voice/{call_id}"
        
        # Initiate Twilio call
        call = twilio_client.calls.create(
            to=to_number,
            from_=from_number,
            url=webhook_url,
            method="POST",
            record=True,
            status_callback=f"{protocol}://{PUBLIC_HOST}/webhooks/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        
        # Update call record with Twilio SID
        call_manager.update_call(call_id, {
            "twilio_sid": call.sid,
            "status": "initiated"
        })
        
        logger.info(f"Initiated outbound call {call_id} (Twilio SID: {call.sid})")
        
        return {
            "success": True,
            "call_id": call_id,
            "call_sid": call.sid,
            "to": to_number,
            "status": "initiated"
        }
        
    except Exception as e:
        logger.error(f"Error making call: {e}")
        return {"error": str(e)}, 500


@app.post("/webhooks/voice/{call_id}")
async def voice_webhook(request: Request, call_id: str):
    """Handle Twilio voice webhook - return TwiML to connect media stream"""
    try:
        # Build WebSocket URL
        protocol = "wss" if USE_HTTPS else "ws"
        ws_url = f"{protocol}://{PUBLIC_HOST}/media-stream/{call_id}"
        
        # Get call metadata
        call_data = call_manager.get_call(call_id)
        voice_id = call_data.get("voice_id", "mathew") if call_data else "mathew"
        
        # Create TwiML response with media stream
        response = VoiceResponse()
        
        # Add a brief pause to ensure call is established
        response.pause(length=1)
        
        # Connect to WebSocket with custom parameters
        connect = response.connect()
        stream = connect.stream(url=ws_url)
        
        # Add custom parameters for voice configuration
        stream.parameter(name="voice_id", value=voice_id)
        stream.parameter(name="call_id", value=call_id)
        
        # Convert to XML
        twiml = str(response)
        logger.info(f"Generated TwiML for call {call_id} with WebSocket: {ws_url}")
        
        return HTMLResponse(content=twiml, media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error in voice webhook: {e}")
        # Return error TwiML
        response = VoiceResponse()
        response.say("An error occurred. Please try again later.")
        response.hangup()
        return HTMLResponse(content=str(response), media_type="application/xml")


@app.post("/webhooks/status")
async def status_webhook(request: Request):
    """Handle Twilio status callbacks"""
    try:
        form = await request.form()
        call_sid = form.get("CallSid")
        call_status = form.get("CallStatus")
        
        logger.info(f"Call {call_sid} status: {call_status}")
        
        # Update call status in database if needed
        # This is useful for tracking and analytics
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error in status webhook: {e}")
        return {"error": str(e)}, 500


@app.websocket("/media-stream/{call_id}")
async def media_stream_endpoint(websocket: WebSocket, call_id: str):
    """
    WebSocket endpoint for Twilio Media Streams
    This is where the real-time audio processing happens
    """
    try:
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for call {call_id}")
        
        # Update call status
        call_manager.update_call(call_id, {"status": "connected"})
        
        # Handle the WebSocket connection with optimized processing
        await handle_twilio_websocket(websocket, call_id, call_manager)
        
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for call {call_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {e}")
    finally:
        # Update call status
        call_manager.update_call(call_id, {"status": "completed"})
        logger.info(f"WebSocket cleanup complete for call {call_id}")


@app.get("/calls/{call_id}")
async def get_call_status(call_id: str):
    """Get the status of a specific call"""
    call_data = call_manager.get_call(call_id)
    if not call_data:
        return {"error": "Call not found"}, 404
    return call_data


@app.get("/calls")
async def list_active_calls():
    """List all active calls"""
    return {"calls": call_manager.list_active_calls()}


async def main():
    """Run the FastAPI server"""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
