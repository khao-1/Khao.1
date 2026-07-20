"""Event-driven entry point — replaces cron for anything customer-facing.
Wire your WhatsApp Business API provider (360dialog/Twilio) webhook here.
Cron remains only for: Monday payouts, daily Monitor sweep, Sunday audit pack.

Run: pip install flask && python webhook.py
"""
from flask import Flask, request, jsonify
import state_store, agents

app = Flask(__name__)
state_store.init()

@app.post("/wa")            # WhatsApp inbound message -> immediate agent run
def wa_inbound():
    body = request.get_json(force=True)
    msg = body.get("text", "")
    out = agents.run_support(msg)
    # provider send-API call goes here with out["reply"]
    return jsonify(out)

@app.post("/monitor")       # hit by daily cron
def monitor():
    return jsonify(agents.run_monitor())

if __name__ == "__main__":
    app.run(port=8080)
