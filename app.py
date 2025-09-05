from flask import Flask, request, jsonify
from twilio.rest import Client
from utils import logger, get_env
from twilio_service import init_call, twiml_response_for_call
from dotenv import load_dotenv
import os

app = Flask(__name__)
twilio_client = Client(
    get_env("TWILIO_ACCOUNT_SID", required=True),
    get_env("TWILIO_AUTH_TOKEN", required=True),
)

load_dotenv()

PUBLIC_HOST = os.getenv('PUBLIC_HOST')
WEBSOCKET_URL = os.getenv('WEBSOCKET_URL')


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/make-call", methods=["POST"])
def make_call():
    data = request.get_json()
    phone = data["phone_number"]

    try:
        with open("system_prompt.txt", "r") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        logger.error("system_prompt.txt not found! Using default prompt.")
        system_prompt = "You are a helpful AI assistant."

    call_id = init_call(phone, system_prompt, 120)
    webhook_url = f"https://{PUBLIC_HOST}/webhook/call/{call_id}"

    call = twilio_client.calls.create(
        to=phone,
        from_=get_env("TWILIO_PHONE_NUMBER", required=True),
        url=webhook_url,
        method="POST",
    )

    return jsonify({"call_sid": call.sid, "call_id": call_id})


@app.route("/webhook/call/<call_id>", methods=["POST"])
def call_webhook(call_id):
    websocket_url = f"wss://{WEBSOCKET_URL}/stream/{call_id}"
    return twiml_response_for_call(call_id, websocket_url)


if __name__ == "__main__":
    logger.info(f"Using PUBLIC_HOST={PUBLIC_HOST}")
    logger.info(f"Using WEBSOCKET_URL={WEBSOCKET_URL}")
    app.run(host="0.0.0.0", port=3000)
