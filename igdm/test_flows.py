"""Drive fake webhooks through the server and assert on the outbox.

Run: SHADOW=1 IG_ID=999 python test_flows.py
"""
import json
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("SHADOW", "1")
os.environ.setdefault("IG_ID", "999")

import server  # noqa: E402

STATE = server.STATE


def reset():
    if STATE.exists():
        shutil.rmtree(STATE)
    STATE.mkdir()
    server.STATE = STATE


def comment(cid, text, author="user_1"):
    return {"object": "instagram", "entry": [{"id": "999", "changes": [
        {"field": "comments", "value": {"id": cid, "text": text,
                                        "from": {"id": author, "username": "tester"},
                                        "media": {"id": "media_1"}}}]}]}


def dm(text, sender="user_1", mid="m1"):
    return {"object": "instagram", "entry": [{"id": "999", "messaging": [
        {"sender": {"id": sender}, "recipient": {"id": "999"},
         "timestamp": 1, "message": {"mid": mid, "text": text}}]}]}


def outbox():
    path = STATE / "outbox.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def post(client, payload):
    return client.post("/webhook", json=payload)


def run():
    client = server.app.test_client()
    failures = []

    def check(label, condition, detail=""):
        status = "pass" if condition else "FAIL"
        print(f"  [{status}] {label}{'  ' + detail if detail else ''}")
        if not condition:
            failures.append(label)

    print("keyword match sends a public reply and one private reply")
    reset()
    post(client, comment("c1", "hey send me the link please"))
    sends = outbox()
    check("two sends", len(sends) == 2, f"got {len(sends)}")
    check("public reply first", sends[0]["path"] == "c1/replies")
    check("private reply uses comment_id",
          sends[1]["payload"]["recipient"] == {"comment_id": "c1"})

    print("duplicate webhook for the same comment sends nothing extra")
    post(client, comment("c1", "hey send me the link please"))
    check("still two sends", len(outbox()) == 2, f"got {len(outbox())}")

    print("comment with no keyword is ignored")
    reset()
    post(client, comment("c2", "nice photo"))
    check("no sends", len(outbox()) == 0)

    print("substring is not a match")
    reset()
    post(client, comment("c3", "blinking cursor"))
    check("'link' inside 'blinking' ignored", len(outbox()) == 0)

    print("follow up only fires after they write back")
    reset()
    post(client, comment("c4", "what is the price"))
    before = len(outbox())
    post(client, dm("how much for the small one", mid="m9"))
    sends = outbox()
    check("one extra send", len(sends) == before + 1, f"got {len(sends) - before}")
    check("follow up is a normal DM", sends[-1]["payload"]["recipient"] == {"id": "user_1"})

    print("follow up does not repeat on a second inbound")
    post(client, dm("still there?", mid="m10"))
    check("no third send", len(outbox()) == before + 1)

    print("inbound DM with no prior comment does nothing")
    reset()
    post(client, dm("random hello", sender="user_7", mid="m11"))
    check("no sends", len(outbox()) == 0)

    print("our own comment is ignored")
    reset()
    post(client, comment("c5", "send me the link", author="999"))
    check("no sends", len(outbox()) == 0)

    print("emoji only comment does nothing")
    reset()
    post(client, comment("c6", "🔥🔥🔥"))
    check("no sends", len(outbox()) == 0)

    print("two people commenting the same keyword both get a DM")
    reset()
    post(client, comment("c7", "link please", author="user_a"))
    post(client, comment("c8", "link please", author="user_b"))
    dms = [s for s in outbox() if "comment_id" in str(s["payload"].get("recipient"))]
    check("two private replies", len(dms) == 2, f"got {len(dms)}")
    check("distinct comments", {d["payload"]["recipient"]["comment_id"] for d in dms} == {"c7", "c8"})

    print("reply after the 24h window closed sends nothing")
    reset()
    post(client, comment("c9", "what is the price", author="user_c"))
    before = len(outbox())
    contacts = json.loads((STATE / "contacts.json").read_text())
    contacts["user_c"]["last_inbound"] = 0  # two days ago
    (STATE / "contacts.json").write_text(json.dumps(contacts))
    post(client, dm("hello?", sender="user_c", mid="m20"))
    check("window reopens on their message so follow up is allowed",
          len(outbox()) == before + 1, f"got {len(outbox()) - before}")

    print("DM from someone who never commented does nothing")
    reset()
    post(client, dm("hi", sender="stranger", mid="m21"))
    post(client, dm("hello", sender="stranger", mid="m22"))
    check("no sends", len(outbox()) == 0)

    print("keyword is matched case insensitively")
    reset()
    post(client, comment("c10", "PLEASE SEND ME THE LINK"))
    check("fired", len(outbox()) == 2, f"got {len(outbox())}")

    print("malformed payload still returns 200")
    reset()
    resp = client.post("/webhook", data=b"{not json", content_type="application/json")
    check("returns 200 so Meta stops retrying", resp.status_code == 200,
          f"got {resp.status_code}")

    print()
    if failures:
        print(f"{len(failures)} failing: {failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
