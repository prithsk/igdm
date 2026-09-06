# Instagram comment-to-DM

A small replacement for the one ManyChat feature you actually need. Someone
comments a keyword on your post, they get a DM.

It does comment-to-DM and nothing else. No broadcasts, no story replies, no
web builder. That narrow scope is deliberate.

**Read this before you set `SHADOW=0`.** The default ships with placeholder
example.com links and untested flows. Verify against a reference system first
using the steps below. Turning off shadow mode sends real messages to real
followers, and a bad flow burns your one private reply per comment.

## Run it

```
pip install flask requests
SHADOW=1 python server.py
```

Shadow mode is the default. Nothing gets sent. Every intended call lands in
`state/outbox.jsonl` so you can compare it against what ManyChat did.

Tests:

```
SHADOW=1 IG_ID=999 python test_flows.py
```

## Verify before you go live

1. Keep ManyChat's free tier running on the account. It is your reference.
2. Point this server's `/webhook` at the same Instagram webhook subscription.
3. Comment on your own post from a second account, using each keyword.
4. ManyChat sends the real DM. This logs what it would have sent.
5. Diff `state/outbox.jsonl` against the DM that actually arrived.

Cases worth forcing on purpose: the same keyword twice on one post, a keyword
inside a longer word, an emoji-only comment, a comment then a reply two days
later, and two people commenting within the same second.

When the outbox matches ManyChat on every case for a week, flip `SHADOW=0`
and turn the ManyChat flow off.

## Environment

| Variable | What it is |
| --- | --- |
| `IG_ID` | Your Instagram professional account ID |
| `IG_ACCESS_TOKEN` | Instagram user access token |
| `IG_APP_SECRET` | App secret, used to verify webhook signatures |
| `IG_VERIFY_TOKEN` | Any string, must match what you enter in the App dashboard |
| `SHADOW` | `1` logs only, `0` actually sends |

You need an Instagram professional account, a Meta app with the Instagram
Business login product, and Advanced Access for messaging permissions before
this works on anyone's comments but your own.

## Rules baked into the code

- One private reply per comment, ever. Enforced by `state/seen.json`.
- A private reply does not open the 24-hour window. `after_reply` waits for
  them to write back first.
- Free-form DMs only inside 24 hours of their last inbound message.
- No HUMAN_AGENT tag anywhere. Meta reserves it for a real person and
  suspends accounts that automate under it.
- The webhook always returns 200 so Meta never retries a message you already
  handled.

## What it does not do yet

- No media, buttons, or quick replies in the DM. Text only.
- Retries are manual. Failed sends land in `state/failures.jsonl`.
- State is JSON files, so run one process. Two will race.
- No web UI. Edit `flows.md` and restart.

## Maintenance

- `state/seen.json` grows forever. Prune entries older than 8 days on a cron.
- `state/failures.jsonl` should stay empty. If it is not, something changed.
- Meta bumps the Graph version roughly twice a year. `API` at the top of
  `server.py` is the one line to change.

## Scripts

| Command | What it does |
| --- | --- |
| `python server.py` | The webhook receiver |
| `python test_flows.py` | 17 checks against fake webhooks, no network |
| `python report.py` | Prints what the engine would have sent, for shadow comparison |
| `python maintain.py` | Cron job. Refreshes the token, prunes state, exits 1 if something needs you |

Cron:

```
0 4 * * * cd /path/to/igdm && python maintain.py >> state/maintain.log 2>&1
```

`maintain.py` exits non-zero when it finds trouble, so any monitor that
watches exit codes will page you. It checks for failed sends and for silence,
which is the failure nobody notices. A webhook subscription that quietly
unsubscribes produces no errors at all, just no messages.

The token matters most. Long-lived tokens last 60 days, and one that goes
60 days without a refresh expires for good and cannot be refreshed. This
refreshes at day 30 to leave room for a broken cron.
