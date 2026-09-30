# ClipLinQ as an Agent Skill

`SKILL.md` plus `reference.md` are an
[Agent Skill](https://github.com/agentskills/agentskills): an open standard
adopted by 26+ agent products, so this one folder installs in Claude Code,
OpenClaw, Hermes, Codex, Gemini CLI, Cursor and VS Code without changes.

It teaches an agent to turn a long video into vertical 9:16 clips through the
ClipLinQ API: which options actually produce good clips, which responses look
like errors but are not, and when to stop and ask the user.

## Setup

ClipLinQ is self-hosted, MIT-licensed and free — no account, no API key
server-side. Run it with Docker (see the main README), then point the agent
at your instance's base URL (`http://localhost:8000` by default). You'll need
your own Google Gemini key for the pipeline itself, and your own
[Upload-Post](https://www.upload-post.com/) account for the publishing steps.

If the host speaks MCP, add the server too so the agent gets typed tools instead
of raw HTTP:

```bash
claude mcp add --transport http cliplinq http://localhost:8000/mcp
```

The skill works either way: with MCP it calls the tools, without it it calls the
REST API documented in `reference.md`.

## Install

**Claude Code.** Copy the folder into `~/.claude/skills/` for every project, or
a project's `.claude/skills/` for one:

```bash
cp -r skills/openshorts ~/.claude/skills/
```

**OpenClaw.** Copy it into your OpenClaw `skills/` directory, or install from
git with `openclaw add <owner>/<repo>`.

**Hermes.** Skills live in `~/.hermes/skills/`; installing from the marketplace
runs a security scan first.

**Anything else.** Drop the folder wherever that agent reads skills from.

## Related

- `cli/` is the same API as a zero-dependency CLI: `uvx cliplinq process <url> --wait`.
- `examples/n8n/` has the same pipeline as importable n8n workflows.
- `/docs` on your own running instance documents the full REST API.
