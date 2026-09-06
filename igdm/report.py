"""Print what the engine would have sent, so you can compare it to ManyChat.

    python report.py

Run this after each shadow test. Every row is a comment you made from your
test account. Check the DM column against the DM that actually arrived.
"""
import json
import sys
from pathlib import Path

STATE = Path(__file__).parent / "state"


def rows(name):
    path = STATE / name
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def comments():
    out = []
    for rec in rows("inbound.jsonl"):
        for entry in rec.get("body", {}).get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") == "comments":
                    v = change.get("value") or {}
                    out.append({
                        "ts": rec.get("ts"),
                        "id": v.get("id"),
                        "text": v.get("text", ""),
                        "from": (v.get("from") or {}).get("username", "?"),
                    })
    return out


def sends_by_comment():
    index = {}
    for rec in rows("outbox.jsonl"):
        payload = rec.get("payload", {})
        recip = payload.get("recipient") or {}
        cid = recip.get("comment_id")
        if cid:
            index.setdefault(cid, {})["dm"] = payload["message"]["text"]
        elif rec.get("path", "").endswith("/replies"):
            index.setdefault(rec["path"].split("/")[0], {})["public"] = payload.get("message")
    return index


def main():
    seen = comments()
    if not seen:
        print("No comment webhooks recorded yet. Comment on your post from a")
        print("second account with the server running, then try again.")
        return 1

    index = sends_by_comment()
    skipped = {r.get("comment_id"): r.get("reason") for r in rows("skipped.jsonl")}

    dupes = {}
    unique = []
    for c in seen:
        dupes[c["id"]] = dupes.get(c["id"], 0) + 1
        if dupes[c["id"]] == 1:
            unique.append(c)

    print(f"{len(seen)} webhooks, {len(unique)} distinct comments\n")
    for c in unique:
        cid = c["id"]
        result = index.get(cid, {})
        repeat = f"  (webhook arrived {dupes[cid]}x)" if dupes[cid] > 1 else ""
        print(f"@{c['from']}: {c['text']!r}{repeat}")
        if result.get("public"):
            print(f"   public  {result['public']}")
        if result.get("dm"):
            print(f"   DM      {result['dm']}")
        if not result:
            print(f"   nothing ({skipped.get(cid, 'no matching flow')})")
        print()

    repeats = {k: v for k, v in dupes.items() if v > 1}
    if repeats:
        print(f"Meta sent duplicate webhooks for {len(repeats)} comment(s), deduped above.")
        print("Confirm each still shows exactly one DM above.\n")

    print("Compare every DM line against what ManyChat actually delivered.")
    print("Any difference is a bug in this engine, not in ManyChat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
