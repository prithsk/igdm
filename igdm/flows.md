# Flows

Each `## block` is one trigger. Edit this file and restart the server.
Keywords match case-insensitively as whole words anywhere in the comment.

- `keywords` — comma separated. Any one match fires the block.
- `public` — optional reply posted under their comment. Leave blank to skip.
- `dm` — the private reply. This is your one shot per comment.
- `after_reply` — sent only if they write back, which opens the 24h window.

## lead-magnet

keywords: link, guide, send me, want it
public: Just sent it over, check your DMs
dm: Hey! Here is the guide you asked for. https://example.com/guide
after_reply: Glad it landed. Want me to send the checklist that goes with it?

## pricing

keywords: price, pricing, how much, cost
public: Replied in your DMs
dm: Thanks for asking. Full pricing is here. https://example.com/pricing
after_reply: Happy to walk you through which tier fits. What are you working on?
