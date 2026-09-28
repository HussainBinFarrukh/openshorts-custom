# Automation pipeline (fork addition)

This fork adds a self-hosted pipeline that runs OpenShorts on a schedule and
carries each clip through commentary, review, publishing and measurement:

```
watchlist → intake → OpenShorts job → clips (draft)
          → shortlist → watch sheet → your reaction recording → align → compose
          → QA → pending_review → approve (you) → paced schedule → YouTube upload
          → metrics at 24 h / 72 h / 7 d
```

Everything lives in `pipeline/` (MIT, same as the core app) and the
`Pipeline` dashboard tab. It never touches `cloud/`, which is under a separate
commercial license and is not used or required here.

## Rules (carried over from clip-engine's AGENTS.md)

1. **Sources are yours to vouch for.** A watchlist entry records who granted
   permission and when. Nothing is ingested from a channel that is not on the
   watchlist. Downloading from YouTube runs against YouTube's Terms of Service;
   that risk is the operator's, and the app never presents it as sanctioned.
2. **Your commentary is required.** A clip cannot reach `pending_review`
   without an aligned reaction segment containing at least
   `PIPELINE_MIN_COMMENTARY_SECONDS` (default 5) of speech.
3. **A person approves every publish.** Only `approved` clips are scheduled.
   The approval records who approved and when. There is no auto-approve path.
4. **Pacing beats API ceilings.** Default: at most 3 publishes per day, at
   least 3 hours apart, inside a daily window. The YouTube Data API allows
   about 6 uploads per day per Google Cloud project (10,000 units, ~1,600 per
   upload); the scheduler tracks units and refuses to exceed them.
5. **Private until verified.** Uploads from an unverified Google Cloud OAuth
   app are locked private by YouTube, so the default privacy is `private` until
   `PIPELINE_YT_APP_VERIFIED=1`.

## Clip states

| State | Meaning | Next |
|---|---|---|
| `draft` | Rendered by OpenShorts, not yet chosen | `shortlisted`, `rejected` |
| `shortlisted` | Chosen for commentary; goes on the next watch sheet | `awaiting_reaction` |
| `awaiting_reaction` | On a watch sheet you have not recorded against yet | `composing` (reaction uploaded) |
| `composing` | Reaction aligned; stacked/PiP render running | `qa_failed`, `pending_review` |
| `qa_failed` | A QA check failed (see `qa_report`) | re-align / recompose |
| `pending_review` | Ready for you | `approved`, `rejected`, `shortlisted` (send back) |
| `approved` | You approved it | `scheduled` |
| `scheduled` | Has a publish slot | `published`, `publish_failed` |
| `published` | Live on YouTube (`youtube_video_id` set) | metrics pulls |
| `rejected` | Dropped | — |

## Commentary flow

1. Shortlist clips in the Pipeline tab.
2. **Build watch sheet**: one MP4 with, per clip, a 1 kHz tone (0.6 s), an ID
   card showing the clip number (1.5 s), then the clip. Clips are separated by
   `PIPELINE_REACTION_TAIL_SECONDS` (default 12) of black so you have room to
   add a closing comment after each one.
3. Play the sheet full-screen and record yourself (webcam + mic) reacting,
   starting the recording before pressing play. Your speakers must be audible to
   the mic so the tones land in the recording, or use headphones and play the
   sheet's audio through a loopback.
4. Upload the recording. The aligner finds each tone by cross-correlation and
   cuts one reaction segment per clip: the clip's duration plus the tail.
   Offsets can be nudged per clip if a tone was missed.
5. Compose: while the clip plays, your camera sits on top (stacked, 40% of the
   height) or in a corner (picture-in-picture) with the clip's own audio. Then
   the closing comment plays full-frame with your voice, trimmed to 0.6 s after
   you stop talking. The result is loudness-normalised to −14 LUFS.

   Recording through speakers means your mic also hears the clip, so your voice
   is left out of the clip portion to avoid an echo. If you record on
   headphones with the sheet's audio looped into the recording (so the tones
   are still captured), set `PIPELINE_REACTION_AUDIO_DURING_CLIP=1`: your voice
   is then mixed in during the clip too, with the clip ducked under it by
   sidechain compression.

## QA checks

Duration within the Shorts limit (≤ 180 s), vertical frame, integrated
loudness within ±2 LU of target, no black stretch over 2 s, no silence over
3 s, and commentary speech at or over the minimum. Speech is measured in the
closing comment, where the sheet is silent, so the clip's own dialogue
bleeding into your mic cannot count as your commentary. Each failure is stored
with its measurement; a clip that fails any check cannot be approved.

If a tone was missed, that clip's reaction is placed at the position the other
tones predict and flagged in review; nudge it with the sync offset if needed.

## YouTube setup (one time)

1. Google Cloud console → new project → enable **YouTube Data API v3** and
   **YouTube Analytics API**.
2. OAuth consent screen (External, add yourself as a test user), then an OAuth
   client of type **Web application** with redirect URI
   `http://localhost:8000/api/pipeline/youtube/callback`.
3. Put `PIPELINE_YT_CLIENT_ID`, `PIPELINE_YT_CLIENT_SECRET` and
   `PIPELINE_YT_API_KEY` (an API key from the same project, used for cheap
   channel listing) in `.env`.
4. Pipeline tab → **Connect YouTube**.

Submit the app for verification and a quota increase when you are ready to
publish publicly; until then keep `PIPELINE_YT_APP_VERIFIED=0`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PIPELINE_ENABLED` | `1` | Start the pipeline loops (self-host only) |
| `PIPELINE_DATA_DIR` | `pipeline_data` | SQLite DB, durable clips, sheets, reactions, renders |
| `PIPELINE_TIMEZONE` | `America/New_York` | Timezone for the publish window and daily caps |
| `PIPELINE_INTAKE_EVERY_MINUTES` | `60` | Watchlist check interval |
| `PIPELINE_INTAKE_DAILY_LIMIT` | `2` | New source videos submitted per 24 h |
| `PIPELINE_MAX_VIDEO_AGE_DAYS` | `3` | Only uploads newer than this are picked |
| `PIPELINE_MAX_SOURCE_MINUTES` | `45` | Clip only the first N minutes of long sources |
| `PIPELINE_PUBLISH_MAX_PER_DAY` | `3` | Publishes per local day |
| `PIPELINE_PUBLISH_MIN_GAP_MINUTES` | `180` | Minimum spacing between publishes |
| `PIPELINE_PUBLISH_WINDOW` | `09:00-21:00` | Local publish window |
| `PIPELINE_YT_DAILY_QUOTA` | `10000` | Data API units per day for the project |
| `PIPELINE_YT_APP_VERIFIED` | `0` | `1` allows public/unlisted uploads |
| `PIPELINE_DEFAULT_PRIVACY` | `public` | Used only once verified |
| `PIPELINE_MIN_COMMENTARY_SECONDS` | `5` | QA minimum speech in the reaction |
| `PIPELINE_REACTION_TAIL_SECONDS` | `12` | Room after each clip for a closing comment |
| `PIPELINE_REACTION_AUDIO_DURING_CLIP` | `0` | `1` if you record on headphones with loopback |
| `PIPELINE_ADMIN_TOKEN` | *(empty)* | Require this token on `/api/pipeline/*` if the port is reachable by others |

## What this does not do (yet)

- TikTok / Instagram publishing (their APIs need an audit or app review first).
- Learning loop: metrics are stored and joined to clips, but the scoring prompt
  is not yet revised from them.
- Face-tracking of the reaction video: the reaction is scaled and cropped to
  its panel, not tracked.
- Authentication: self-host OpenShorts has none. Keep the backend on
  localhost, or set `PIPELINE_ADMIN_TOKEN` before exposing it.

## Attribution

The intake guard rails (only uploads published after the watch was added,
maximum age, per-day cap, skip Shorts) follow the same reasoning as
OpenShorts' own `cloud/autopilot.py`; no code is copied from `cloud/`. The
review → schedule → publish → measure loop follows the design of
clip-engine (github.com/HussainBinFarrukh/clip-engine) and the approval-gated
publishing pattern of AgentTube (github.com/darkzOGx/youtube-automation-agent,
MIT); it is reimplemented here in Python.
