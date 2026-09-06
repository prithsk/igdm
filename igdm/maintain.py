"""Everything this thing needs done on a schedule. One cron entry.

    0 4 * * *  cd /path/to/igdm && python maintain.py >> state/maintain.log 2>&1

Exits non-zero when something needs a human. Point a monitor at that.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
STATE = HERE / "state"
TOKEN_FILE = STATE / "token.json"
SEEN_TTL = 8 * 24 * 3600  # private replies die at 7 days, keep one day of slack
REFRESH_AFTER = 30 * 24 * 3600  # refresh at the halfway mark, not the deadline
problems = []


def say(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M')}  {msg}")


def prune_seen():
    """Drop handled comment IDs old enough that they can never fire again."""
    path = STATE / "seen.json"
    if not path.exists():
        say("seen.json missing, nothing to prune")
        return
    seen = json.loads(path.read_text())
    cutoff = time.time() - SEEN_TTL
    kept = {k: v for k, v in seen.items() if v > cutoff}
    dropped = len(seen) - len(kept)
    tmp = STATE / "seen.json.tmp"
    tmp.write_text(json.dumps(kept, indent=2))
    tmp.replace(path)
    say(f"seen.json: kept {len(kept)}, dropped {dropped}")


def prune_contacts():
    """Forget contacts whose window closed and whose follow up already went."""
    path = STATE / "contacts.json"
    if not path.exists():
        return
    contacts = json.loads(path.read_text())
    cutoff = time.time() - 30 * 24 * 3600
    kept = {
        k: v for k, v in contacts.items()
        if v.get("last_inbound", 0) > cutoff or not v.get("followed_up")
    }
    tmp = STATE / "contacts.json.tmp"
    tmp.write_text(json.dumps(kept, indent=2))
    tmp.replace(path)
    say(f"contacts.json: kept {len(kept)}, dropped {len(contacts) - len(kept)}")


def token_age():
    if not TOKEN_FILE.exists():
        return None
    return time.time() - json.loads(TOKEN_FILE.read_text()).get("refreshed_at", 0)


def refresh_token():
    """Long lived tokens last 60 days. Miss the window and OAuth starts over."""
    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if TOKEN_FILE.exists():
        token = json.loads(TOKEN_FILE.read_text()).get("access_token", token)
    if not token:
        problems.append("no token anywhere, set IG_ACCESS_TOKEN")
        return

    age = token_age()
    if age is not None and age < REFRESH_AFTER:
        days = int((REFRESH_AFTER - age) / 86400)
        say(f"token still fresh, next refresh in {days} days")
        return

    resp = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=15,
    )
    if resp.status_code != 200:
        problems.append(f"token refresh failed {resp.status_code}: {resp.text[:200]}")
        return
    body = resp.json()
    TOKEN_FILE.write_text(json.dumps({
        "access_token": body["access_token"],
        "refreshed_at": time.time(),
        "expires_in": body.get("expires_in"),
    }, indent=2))
    say(f"token refreshed, valid for {int(body.get('expires_in', 0) / 86400)} days")


def check_failures():
    path = STATE / "failures.jsonl"
    if not path.exists():
        say("no failures")
        return
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    recent = [json.loads(l) for l in lines if json.loads(l).get("ts", 0) > time.time() - 86400]
    if recent:
        problems.append(f"{len(recent)} failed sends in the last day")
        for r in recent[:3]:
            say(f"  failure: {json.dumps(r.get('response'))[:160]}")
    else:
        say(f"no failures today ({len(lines)} historic)")


def check_traffic():
    """Silence is the failure mode nobody notices. Webhooks stop, nothing errors."""
    path = STATE / "inbound.jsonl"
    if not path.exists():
        problems.append("no inbound.jsonl, webhook may never have fired")
        return
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    if not lines:
        problems.append("inbound.jsonl is empty")
        return
    last = json.loads(lines[-1]).get("ts", 0)
    hours = (time.time() - last) / 3600
    if hours > 72:
        problems.append(f"no webhook traffic for {int(hours)} hours, check the subscription")
    else:
        say(f"last webhook {hours:.1f} hours ago")


if __name__ == "__main__":
    STATE.mkdir(exist_ok=True)
    prune_seen()
    prune_contacts()
    check_failures()
    check_traffic()
    if os.environ.get("SHADOW", "1") == "0":
        refresh_token()
    else:
        say("shadow mode, skipping token refresh")

    if problems:
        say("NEEDS ATTENTION")
        for p in problems:
            say(f"  {p}")
        sys.exit(1)
    say("all clear")
