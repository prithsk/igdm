"""Instagram comment-to-DM. Boring on purpose.

Run:  SHADOW=1 python server.py
Shadow mode writes every intended send to state/outbox.jsonl and calls nothing.
"""
import hashlib
import hmac
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from flask import Flask, request

API = "https://graph.instagram.com/v23.0"
STATE = Path(__file__).parent / "state"
STATE.mkdir(exist_ok=True)

APP_SECRET = os.environ.get("IG_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("IG_VERIFY_TOKEN", "changeme")
IG_ID = os.environ.get("IG_ID", "")
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
SHADOW = os.environ.get("SHADOW", "1") == "1"

app = Flask(__name__)


# ---------- flows ----------

def load_flows(path=None):
    """Parse flows.md into a list of blocks."""
    path = path or Path(__file__).parent / "flows.md"
    flows, current = [], None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            current = {"name": line[3:].strip()}
            flows.append(current)
        elif current is not None and ":" in line and not line.startswith("-"):
            key, _, val = line.partition(":")
            key = key.strip().lower()
            if key in ("keywords", "public", "dm", "after_reply"):
                current[key] = val.strip()
    for f in flows:
        raw = f.get("keywords", "")
        f["keywords"] = [k.strip().lower() for k in raw.split(",") if k.strip()]
    return [f for f in flows if f["keywords"] and f.get("dm")]


FLOWS = load_flows()


def match_flow(text, flows=None):
    """Return the first flow whose keyword appears as a whole word."""
    flows = FLOWS if flows is None else flows
    low = (text or "").lower()
    for flow in flows:
        for kw in flow["keywords"]:
            if re.search(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", low):
                return flow
    return None


# ---------- state ----------

def read_json(name, default):
    path = STATE / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(name, data):
    tmp = STATE / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(STATE / name)


def log(name, record):
    record["ts"] = time.time()
    with open(STATE / name, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def claim(key):
    """Mark a comment or message as handled. Returns False if already done."""
    seen = read_json("seen.json", {})
    if key in seen:
        return False
    seen[key] = time.time()
    write_json("seen.json", seen)
    return True


def note_inbound(igsid, flow_name=None):
    contacts = read_json("contacts.json", {})
    entry = contacts.setdefault(igsid, {})
    entry["last_inbound"] = time.time()
    if flow_name:
        entry["pending_flow"] = flow_name
    contacts[igsid] = entry
    write_json("contacts.json", contacts)
    return entry


def window_open(igsid):
    contacts = read_json("contacts.json", {})
    last = contacts.get(igsid, {}).get("last_inbound")
    return bool(last) and (time.time() - last) < 24 * 3600


# ---------- sending ----------

def call(path, payload):
    if SHADOW:
        log("outbox.jsonl", {"path": path, "payload": payload, "shadow": True})
        print("[shadow]", path, json.dumps(payload)[:120])
        return {"shadow": True}
    resp = requests.post(
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=payload,
        timeout=10,
    )
    body = resp.json() if resp.content else {}
    log("outbox.jsonl", {"path": path, "payload": payload, "status": resp.status_code, "response": body})
    if resp.status_code >= 400:
        log("failures.jsonl", {"path": path, "payload": payload, "response": body})
    return body


def private_reply(comment_id, text):
    """One message per comment, within 7 days. Does not open the 24h window."""
    return call(f"{IG_ID}/messages", {"recipient": {"comment_id": comment_id}, "message": {"text": text}})


def public_reply(comment_id, text):
    return call(f"{comment_id}/replies", {"message": text})


def direct_message(igsid, text):
    return call(f"{IG_ID}/messages", {"recipient": {"id": igsid}, "message": {"text": text}})


# ---------- handlers ----------

def handle_comment(value):
    comment_id = value.get("id")
    author = (value.get("from") or {}).get("id")
    text = value.get("text", "")
    if not comment_id or author == IG_ID:
        return
    flow = match_flow(text)
    if not flow:
        log("skipped.jsonl", {"comment_id": comment_id, "text": text, "reason": "no keyword"})
        return
    if not claim(f"comment:{comment_id}"):
        log("skipped.jsonl", {"comment_id": comment_id, "reason": "duplicate webhook"})
        return
    if flow.get("public"):
        public_reply(comment_id, flow["public"])
    private_reply(comment_id, flow["dm"])
    if author:
        contacts = read_json("contacts.json", {})
        contacts.setdefault(author, {})["pending_flow"] = flow["name"]
        write_json("contacts.json", contacts)


def handle_message(event):
    sender = (event.get("sender") or {}).get("id")
    message = event.get("message") or {}
    mid = message.get("mid")
    if not sender or sender == IG_ID or message.get("is_echo"):
        return
    if mid and not claim(f"mid:{mid}"):
        return
    entry = note_inbound(sender)
    pending = entry.get("pending_flow")
    if not pending or entry.get("followed_up"):
        return
    flow = next((f for f in FLOWS if f["name"] == pending), None)
    if not flow or not flow.get("after_reply"):
        return
    if not window_open(sender):
        return
    direct_message(sender, flow["after_reply"])
    contacts = read_json("contacts.json", {})
    contacts[sender]["followed_up"] = True
    write_json("contacts.json", contacts)


def process(body):
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") == "comments":
                handle_comment(change.get("value") or {})
        for event in entry.get("messaging", []):
            handle_message(event)


# ---------- routes ----------

@app.get("/webhook")
def verify():
    args = request.args
    if args.get("hub.mode") == "subscribe" and args.get("hub.verify_token") == VERIFY_TOKEN:
        return args.get("hub.challenge", ""), 200
    return "forbidden", 403


@app.post("/webhook")
def receive():
    raw = request.get_data()
    if APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return "bad signature", 403
    try:
        body = json.loads(raw or b"{}")
        log("inbound.jsonl", {"body": body})
        process(body)
    except Exception as err:
        log("errors.jsonl", {"error": repr(err), "raw": raw.decode("utf-8", "replace")})
    return "ok", 200


@app.get("/health")
def health():
    return {"flows": [f["name"] for f in FLOWS], "shadow": SHADOW}, 200


if __name__ == "__main__":
    print(f"flows loaded: {[f['name'] for f in FLOWS]}  shadow={SHADOW}", file=sys.stderr)
    app.run(port=int(os.environ.get("PORT", 8000)))
