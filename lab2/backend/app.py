import socket
from datetime import datetime, timezone

from flask import Flask, jsonify

app = Flask(__name__)
app.json.ensure_ascii = False


@app.get("/api/info")
def info():
    return jsonify(
        message="Привет от backend-сервиса на Flask!",
        container=socket.gethostname(),
        time=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/api/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
