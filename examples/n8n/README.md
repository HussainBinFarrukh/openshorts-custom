# ClipLinQ + n8n

Two importable workflows, from a one-shot clipper to a full channel autopilot.
Both run against your own self-hosted ClipLinQ instance (free, MIT, no
account, no API key server-side — see the main README to get one running).
You'll need your own Gemini key for the pipeline, and your own
[Upload-Post](https://www.upload-post.com/) account for the posting steps.

| Workflow | What it does | Credentials |
|---|---|---|
| `openshorts-clip-and-notify.json` | A video URL goes in through a form, clips come back on a signed webhook. No polling. | Gemini key (X-Gemini-Key header) |
| `openshorts-content-machine.json` | Your YouTube channel on autopilot: daily clipping, approval buttons in Telegram, drip-scheduled posting, weekly analytics digest. | Gemini key + Upload-Post key + Telegram bot |

## Shared setup

1. In n8n: **Workflows → Import from file** → pick the workflow.
2. Create a **Header Auth** credential for your Gemini key:
   - Name: `X-Gemini-Key`
   - Value: your Google Gemini API key
3. Point the HTTP request nodes at your instance's base URL
   (`http://localhost:8000` by default).
4. Open the **Clips ready (webhook)** node, copy its production URL, and paste
   it as `webhook_url` inside the **Start ClipLinQ job** node body.
5. Optional: change `webhook_secret`. ClipLinQ signs the webhook body with
   HMAC-SHA256 and sends it as `X-ClipLinQ-Signature: sha256=<hex>`; verify
   it in a Code node with:

   ```javascript
   const crypto = require('crypto');
   const expected = 'sha256=' + crypto
     .createHmac('sha256', 'change-me')
     .update(JSON.stringify($json.body))
     .digest('hex');
   ```

## The Content Machine

`openshorts-content-machine.json` runs your channel in four acts:

1. **Watch** — once a day it reads your channel's RSS feed
   (`https://www.youtube.com/feeds/videos.xml?channel_id=UC...`) and clips
   **one** video: the newest upload if there is one, otherwise the next
   unprocessed video from your back catalog. If ClipLinQ rejects the job
   (missing key, too many concurrent jobs) the machine pauses and tells you
   on Telegram instead of failing silently.
2. **Approve from your phone** — every finished clip lands in Telegram with
   ✅ Publish / ❌ Skip buttons. Clips over Telegram's ~20 MB URL limit fall
   back to a link message with the same buttons.
3. **Drip-publish** — each approved clip takes the next free daily slot and is
   scheduled through `POST /api/social/post` via your own Upload-Post account
   (TikTok, Instagram, YouTube). Approve five clips today, fill five
   days of content. The slot comes from the queue the server actually holds
   (`GET /api/social/scheduled`), so two clips approved seconds apart cannot
   book the same one.
4. **Sunday digest** — the machine reads the analytics of what it published
   (`GET /api/social/analytics/*`) and reports total impressions, per-platform
   split, and your best post of the week.

Machine-specific setup, all inside sticky notes on the canvas:

- Put your channel id in the **Channel RSS feed** node.
- Create a Telegram bot with [@BotFather](https://t.me/BotFather), add the
  `Telegram bot` credential, and replace `YOUR_TELEGRAM_CHAT_ID` in the
  notification nodes (message your bot, then check
  `api.telegram.org/bot<token>/getUpdates` for your chat id).
- Configure your Upload-Post API key (`X-Upload-Post-Key`) — the posting step
  uses it directly; no extra social credentials in n8n.

Note: the machine remembers which videos it already processed in n8n workflow
static data, which only persists for **production** executions — test runs in
the editor won't advance it. Scheduling deliberately does *not* use that
mechanism (see act 3).

## Webhook payload

```json
{
  "event": "job.completed",
  "job_id": "…",
  "status": "completed",
  "clips": [
    { "index": 0, "title": "…", "video_url": "…" }
  ]
}
```

Failed jobs fire the same webhook with `"event": "job.failed"` and an `error`
field, so the flow never hangs waiting.

## Publishing and analytics API

Direct posting: `POST /api/social/post` (accepts `scheduled_date`, ISO-8601).
Publishing queue: `GET /api/social/scheduled`, and
`DELETE /api/social/scheduled/{job_id}` to cancel one before it goes out.
Analytics of what you published: `GET /api/social/analytics` (profile totals),
`GET /api/social/analytics/posts` (per-post metrics),
`GET /api/social/analytics/impressions` (windowed totals, `period=last_week`).
Full API reference: `/docs` on your own running instance.
Agent-native version of the same pipeline: the built-in MCP server at `/mcp`.
