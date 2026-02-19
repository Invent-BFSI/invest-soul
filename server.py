# app.py
import os
import requests
from flask import Flask, jsonify, Response

app = Flask(__name__)

PORT = int(os.environ.get("PORT", 3000))
SPEECH_KEY = os.environ.get("SPEECH_KEY")
SPEECH_REGION = os.environ.get("SPEECH_REGION")

@app.get("/api/avatar/relay-token")
def relay_token():
    if not SPEECH_KEY or not SPEECH_REGION:
        return jsonify({"error": "Missing SPEECH_KEY or SPEECH_REGION environment variables"}), 500

    url = f"https://{SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1"
    try:
        r = requests.get(url, headers={"Ocp-Apim-Subscription-Key": SPEECH_KEY}, timeout=15)
        # Mirror status code and body on error
        if not r.ok:
            # Try to preserve error body (text) from upstream
            return Response(r.text, status=r.status_code, content_type=r.headers.get("Content-Type", "text/plain"))
        # Return JSON response on success
        return jsonify(r.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
