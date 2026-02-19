# app.py
import os
import requests
from flask import Flask, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder="static")

SPEECH_KEY = os.environ.get("SPEECH_KEY")
SPEECH_REGION = os.environ.get("SPEECH_REGION")  # e.g., "westus2"

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.get("/api/config")
def get_config():
    if not SPEECH_REGION:
        return jsonify({"error": "SPEECH_REGION not configured"}), 500
    return jsonify({"region": SPEECH_REGION})

@app.get("/api/speech/token")
def issue_speech_token():
    """
    Exchange the subscription key for a short-lived Speech token.
    Tokens expire (~10 minutes); client should refresh periodically.
    """
    if not SPEECH_KEY or not SPEECH_REGION:
        return jsonify({"error": "Missing SPEECH_KEY or SPEECH_REGION"}), 500

    url = f"https://{SPEECH_REGION}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": "0",
    }
    try:
        r = requests.post(url, headers=headers, timeout=15)
        if not r.ok:
            return Response(
                r.text, status=r.status_code, content_type=r.headers.get("Content-Type", "text/plain")
            )
        # Return JSON for convenience { token: "...", region: "..." }
        return jsonify({"token": r.text, "region": SPEECH_REGION})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/avatar/relay-token")
def get_avatar_relay_token():
    """
    Fetch TURN/ICE relay details for WebRTC to Azure Avatar service.
    """
    if not SPEECH_KEY or not SPEECH_REGION:
        return jsonify({"error": "Missing SPEECH_KEY or SPEECH_REGION"}), 500

    url = f"https://{SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    headers = {"Ocp-Apim-Subscription-Key": SPEECH_KEY}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if not r.ok:
            return Response(
                r.text, status=r.status_code, content_type=r.headers.get("Content-Type", "text/plain")
            )
        return jsonify(r.json())  # { urls:[], username:'', credential:'', ttl:'...' }
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

# Local dev only; App Service uses Gunicorn to run `app:app`
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3000")), debug=True)
