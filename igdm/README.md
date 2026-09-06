# igdm

Self-hosted Instagram comment-to-DM. Someone comments a keyword on your post,
they get a direct message.

This replaces the one ManyChat feature most people actually pay for. It does
comment-to-DM and nothing else. No broadcasts, no story replies, no drag-and-
drop builder. The narrow scope is the point.

## Why

ManyChat prices by contact count. If comment-to-DM is all you run, you are
paying for a platform to deliver one webhook and make one API call. This is
that webhook and that API call, in about 250 lines, on a box you already have.

What self-hosting does not save you: Meta still gates messaging permissions
behind App Review, and the platform rules still apply the same way.

## Quick start

```bash
pip install -r requirements.txt
SHADOW=1 IG_ID=999 python test_flows.py
```

That runs 17 checks against fake webhooks. No network, no Meta account, no
credentials. If it passes, the engine works and everything left is setup.

To run the server:

```bash
cp .env.example .env    # fill it in
SHADOW=1 python server.py
```

## Shadow mode

Shadow mode is the default and it sends nothing. Every message the engine
decides to send gets written to `state/outbox.jsonl` instead.

This exists because passing tests only proves the code does what I told it to
do. It does not prove the code matches a system people already trust. So run
ManyChat's free tier on the same account, point both at the same webhook, and
compare:

```bash
python report.py
```

Every row shows a comment and the DM this engine would have sent. Check each
one against the DM that ManyChat actually delivered. When they match for a
week, including the ugly cases, set `SHADOW=0` and switch ManyChat off.

Cases worth forcing on purpose: the same keyword twice on one post, a keyword
buried inside a longer word, an emoji-only comment, a reply two days later,
and two people commenting in the same second.

## Flows

Flows live in `flows.md`. Edit the file, restart the server.

```markdown
## lead-magnet

keywords: link, guide, send me
public: Just sent it over, check your DMs
dm: Here is the guide you asked for. https://example.com/guide
after_reply: Want the checklist that goes with it?
```

`dm` is the private reply, and you get exactly one per comment. `after_reply`
only fires if they write back, for reasons explained below.

## Platform rules baked in

These are Meta's, not mine, and getting them wrong gets accounts limited.

- One private reply per comment, ever, within 7 days of that comment.
- A private reply does not open the 24-hour messaging window. The window
  opens only when the person messages you. `after_reply` waits for that.
- Free-form DMs work only inside 24 hours of their last inbound message.
- No `HUMAN_AGENT` tag anywhere. Meta reserves it for a real person replying
  and takes action against accounts that automate under it.
- The webhook always returns 200, so Meta never retries something already
  handled. Duplicate deliveries are deduped on comment ID.

## Setup

You need an Instagram professional account, a Meta app with the Instagram
product added, and Advanced Access for the messaging permissions. Until that
review clears you can only message people who comment on your own posts.

Start the review early. It takes longer than building this did.

| Variable | What it is |
| --- | --- |
| `IG_ID` | Instagram professional account ID |
| `IG_ACCESS_TOKEN` | Long-lived Instagram user access token |
| `IG_APP_SECRET` | Verifies webhook signatures |
| `IG_VERIFY_TOKEN` | Any string, must match the App dashboard |
| `SHADOW` | `1` logs only, `0` actually sends |

## Maintenance

One cron entry covers it:

```
0 4 * * * cd /path/to/igdm && python maintain.py >> state/maintain.log 2>&1
```

`maintain.py` refreshes the access token, prunes old state, and exits non-zero
when something needs you. Point any exit-code monitor at it.

The token is the thing that will bite you. Long-lived tokens last 60 days, and
one that goes 60 days without a refresh expires permanently and cannot be
refreshed. This refreshes at day 30 to leave slack for a broken cron.

It also alerts on silence, which is the failure nobody notices. A webhook
subscription that quietly drops produces no errors at all, just no messages.

## Files

| File | Purpose |
| --- | --- |
| `server.py` | Webhook receiver and flow engine |
| `flows.md` | Your keywords and messages |
| `test_flows.py` | 17 offline checks |
| `report.py` | Shadow-mode comparison output |
| `maintain.py` | Cron job |

State lives in JSON files under `state/`, which is gitignored because it holds
access tokens and real user data. Run one process. Two will race.

## Not done yet

- Text only. No media, buttons, or quick replies.
- Retries are manual. Failed sends land in `state/failures.jsonl`.
- Keyword matching is literal and whole-word. Real people type "linkkk".
- `after_reply` fires once per contact, ever.
- No web UI.
