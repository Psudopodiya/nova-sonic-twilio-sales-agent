# Conversational Voice AI (AWS Bedrock + Twilio)

Outbound, real-time voice agent that **calls users**, streams audio via **Twilio Media Streams**, and talks using **Amazon Bedrock – Nova Sonic** (with **barge-in/interruptions handled** for natural flow).

---

## Features
- **Outbound calling** via a simple REST `/make-call`.
- **Bidirectional audio** (Twilio ⇆ Backend ⇆ Bedrock).
- **Nova Sonic** low-latency speech + **true barge-in** (interrupt mid-utterance).

---

## Architecture
```
Client request → Flask (app.py) → Twilio Outbound Call
                                  ↕ WebSocket (Media Streams)
                              WebSocket Server (websocket_server.py)
                                  ↕
                             AWS Bedrock (Nova Sonic)
```

---

## Prerequisites
- Python **3.8+**
- **AWS** account with access to `amazon.nova-sonic-v1:0`
- **Twilio** account + voice-enabled phone number
- **ngrok** (for public URLs during local dev)

---

## Quickstart

### 1) Install
```bash
git clone <repo-url>
cd <repo>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Start ngrok
```bash
ngrok start --all --config ngrok.yml
```
Copy the two public URLs ngrok shows:
- HTTPS for **Flask** (port 3000)
- HTTPS for **WebSocket** (port 8080)

### 3) Configure `.env`
> Use **hosts only** (no `https://` / `wss://`).

```env
# Public hosts from ngrok (NO scheme)
PUBLIC_HOST=your-flask-subdomain.ngrok-free.app
WEBSOCKET_URL=your-ws-subdomain.ngrok-free.app

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1XXXXXXXXXX   # your Twilio voice number

# AWS
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=xxxxxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_SESSION_TOKEN=optional-if-using-temporary-creds

# Bedrock
MODEL_ID=amazon.nova-sonic-v1:0
```

### 4) Run the servers
```bash
# Terminal A
python websocket_server.py   # listens on :8080, handles Twilio media stream

# Terminal B
python app.py                # Flask on :3000, exposes /make-call and TwiML
```

### 5) Make a call
```bash
curl -X POST "http://localhost:3000/make-call"   -H "Content-Type: application/json"   -d '{ "phone_number": "+11234567890" }'
```
Answer the call to talk to **Alex (ConsultAdd)**.

---

## Notes
- **Barge-in enabled**: if the callee speaks while the agent talks, playback flushes and the agent listens.
- Use **E.164** phone format (`+<country><number>`).
- Twilio trial accounts can call **verified** numbers only.
