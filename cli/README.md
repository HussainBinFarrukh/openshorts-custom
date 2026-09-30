# ClipLinQ CLI

Clip long videos into vertical 9:16 shorts from the terminal. Zero
dependencies; talks to the same API the dashboard, the MCP server and the
webhooks use.

Self-hosted only — no account, no key server-side. Point it at your own
instance and bring your own API keys the same way the dashboard does:

```bash
pip install cliplinq        # or: uvx cliplinq / pipx run cliplinq

export CLIPLINQ_API_URL=http://localhost:8000
export GEMINI_API_KEY=...           # required for `process`
export UPLOAD_POST_API_KEY=...      # required for `publish`

cliplinq process "https://youtube.com/watch?v=..." --wait
cliplinq clips <job_id>
cliplinq publish <job_id> 0 --platforms tiktok,youtube
```

For pipelines, prefer the webhook to `--wait`: pass `--webhook` and
`--webhook-secret` and ClipLinQ POSTs once (HMAC-signed,
`X-ClipLinQ-Signature: sha256=<hex>`) when the job ends, with clip titles
and download links.

MIT licensed, no meter, no watermark, no cap. Agent-native version of the
same surface: the built-in MCP server at `/mcp` (see the main README).
