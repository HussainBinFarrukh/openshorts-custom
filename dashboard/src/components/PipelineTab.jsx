import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Workflow, Inbox, Mic, ClipboardCheck, CalendarClock, Radio, BarChart3, Settings2,
  Loader2, RefreshCw, CheckCircle2, XCircle, Undo2, Upload, Download, Youtube, Play, AlertTriangle,
} from 'lucide-react';
import { apiFetch, ApiError } from '../lib/api';
import { getApiUrl } from '../config';

// Self-hosted automation pipeline (pipeline/, docs/PIPELINE.md):
// watchlist -> OpenShorts clips -> your reaction -> QA -> your approval -> paced YouTube publish -> metrics.

const TOKEN_KEY = 'pipeline_token';
const REVIEWER_KEY = 'pipeline_reviewer';

const readLocal = (k) => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
const writeLocal = (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

async function pipe(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = readLocal(TOKEN_KEY);
  if (token) headers.set('X-Pipeline-Token', token);
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    options = { ...options, body: JSON.stringify(options.json) };
  }
  const res = await apiFetch(`/api/pipeline${path}`, { ...options, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* not JSON */ }
  if (!res.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : `Request failed (${res.status})`;
    throw new ApiError(res.status, detail, text);
  }
  return data;
}

const mediaUrl = (kind, id) => {
  const token = readLocal(TOKEN_KEY);
  return getApiUrl(`/api/pipeline/media/${kind}/${id}${token ? `?token=${encodeURIComponent(token)}` : ''}`);
};

const fmt = (iso) => (iso
  ? new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
  : '—');
const secs = (n) => (n == null ? '—' : `${Number(n).toFixed(1)}s`);

const TABS = [
  { id: 'inbox', label: 'inbox', icon: Inbox, statuses: ['draft'] },
  { id: 'commentary', label: 'commentary', icon: Mic, statuses: ['shortlisted', 'awaiting_reaction', 'composing'] },
  { id: 'review', label: 'review', icon: ClipboardCheck, statuses: ['pending_review', 'qa_failed'] },
  { id: 'schedule', label: 'schedule', icon: CalendarClock, statuses: ['approved', 'scheduled', 'publish_failed', 'published'] },
  { id: 'sources', label: 'sources', icon: Radio },
  { id: 'performance', label: 'performance', icon: BarChart3 },
  { id: 'setup', label: 'setup', icon: Settings2 },
];

const STATUS_BADGE = {
  draft: 'readout', shortlisted: 'badge-brass', awaiting_reaction: 'badge-warn', composing: 'badge-brass',
  qa_failed: 'badge-danger', pending_review: 'badge-brass', approved: 'badge-ok', scheduled: 'badge-ok',
  publish_failed: 'badge-danger', published: 'badge-ok', rejected: 'readout',
};

function Badge({ status }) {
  return <span className={STATUS_BADGE[status] || 'readout'}>{(status || '').replace('_', ' ')}</span>;
}

function Notice({ kind = 'info', children, onClose }) {
  if (!children) return null;
  const cls = kind === 'error'
    ? 'border-[color:var(--color-danger)] text-ink2'
    : 'border-brass/40 bg-brass/5 text-ink2';
  return (
    <div className={`mb-4 rounded-card border px-4 py-3 text-sm flex items-start gap-2 ${cls}`} role="status">
      {kind === 'error' && <AlertTriangle size={15} className="mt-0.5 shrink-0" />}
      <span className="flex-1">{children}</span>
      {onClose && <button onClick={onClose} className="text-muted hover:text-ink" aria-label="dismiss">×</button>}
    </div>
  );
}

function ClipVideo({ clip, kind }) {
  const id = clip.id;
  // "#t=0.1" makes browsers paint the first frame instead of a blank tile.
  const src = `${mediaUrl(kind || (clip.composed_path ? 'composed' : 'raw'), id)}#t=0.1`;
  return (
    <video src={src} controls preload="metadata" playsInline
      className="w-full max-w-[220px] aspect-[9/16] rounded-card bg-black object-contain" />
  );
}

// --------------------------------------------------------------------------- //
export default function PipelineTab() {
  const [tab, setTab] = useState('review');
  const [overview, setOverview] = useState(null);
  const [clips, setClips] = useState([]);
  const [notice, setNotice] = useState(null);
  const [loading, setLoading] = useState(false);

  const say = (text, kind = 'info') => setNotice(text ? { text, kind } : null);
  const fail = (e) => say(e?.detail || e?.message || 'Something went wrong.', 'error');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, cl] = await Promise.all([pipe('/overview'), pipe('/clips')]);
      setOverview(ov);
      setClips(cl.clips || []);
    } catch (e) {
      fail(e);
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  // Compose runs in the background after an upload; poll while anything is in flight.
  const busy = clips.some((c) => c.status === 'composing' || c.status === 'awaiting_reaction');
  useEffect(() => {
    if (!busy) return undefined;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [busy, load]);

  const act = useCallback(async (clipId, action, extra = {}) => {
    try {
      await pipe(`/clips/${clipId}/action`, { method: 'POST', json: { action, ...extra } });
      await load();
      return true;
    } catch (e) { fail(e); return false; }
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps

  const counts = overview?.counts || {};
  const byTab = useMemo(() => {
    const out = {};
    for (const t of TABS) if (t.statuses) out[t.id] = clips.filter((c) => t.statuses.includes(c.status));
    return out;
  }, [clips]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="font-display lowercase text-3xl text-ink mb-2 flex items-center gap-3">
            <Workflow size={26} className="text-brass" /> pipeline
          </h1>
          <p className="text-muted text-sm max-w-2xl">
            New uploads on your permissioned channels are clipped automatically. You add your reaction,
            approve what goes out, and approved clips publish on a paced schedule.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {overview && (
            <span className="readout">
              quota {overview.quota.used}/{overview.quota.limit} · {overview.quota.uploads_left_today} uploads left today
            </span>
          )}
          <button onClick={load} className="btn-quiet inline-flex items-center gap-2" disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> refresh
          </button>
        </div>
      </div>

      {overview && !overview.youtube.connected && tab !== 'setup' && (
        <Notice>
          YouTube is not connected yet, so nothing can publish.{' '}
          <button className="underline" onClick={() => setTab('setup')}>Open setup</button>
        </Notice>
      )}
      {overview?.loops?.last_error && <Notice kind="error">Last background error: {overview.loops.last_error}</Notice>}
      <Notice kind={notice?.kind} onClose={() => setNotice(null)}>{notice?.text}</Notice>

      <div className="flex flex-wrap gap-2 mb-6" role="tablist">
        {TABS.map((t) => {
          const n = t.statuses ? t.statuses.reduce((a, s) => a + (counts[s] || 0), 0) : null;
          const on = tab === t.id;
          return (
            <button key={t.id} role="tab" aria-selected={on} onClick={() => setTab(t.id)}
              className={`px-4 py-2 rounded-full text-sm lowercase border inline-flex items-center gap-2 transition-colors ${on ? 'border-brass bg-brass/10 text-ink' : 'border-rule2 text-muted hover:text-ink2'}`}>
              <t.icon size={14} /> {t.label}{n ? <span className="readout">{n}</span> : null}
            </button>
          );
        })}
      </div>

      {tab === 'inbox' && <InboxView clips={byTab.inbox} act={act} />}
      {tab === 'commentary' && <CommentaryView clips={byTab.commentary} reload={load} say={say} fail={fail} act={act} />}
      {tab === 'review' && <ReviewView clips={byTab.review} act={act} reload={load} say={say} fail={fail} />}
      {tab === 'schedule' && <ScheduleView clips={byTab.schedule} act={act} reload={load} say={say} fail={fail} />}
      {tab === 'sources' && <SourcesView say={say} fail={fail} />}
      {tab === 'performance' && <PerformanceView fail={fail} />}
      {tab === 'setup' && <SetupView overview={overview} reload={load} say={say} fail={fail} />}
    </div>
  );
}

// --------------------------------------------------------------------------- //
function Empty({ children }) {
  return <div className="card p-8 text-center text-muted text-sm">{children}</div>;
}

function InboxView({ clips, act }) {
  if (!clips.length) return <Empty>No new clips. They land here when a watched channel posts, or when you add a video under sources.</Empty>;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {clips.map((c) => (
        <div key={c.id} className="card p-4 flex flex-col gap-3">
          <ClipVideo clip={c} kind="raw" />
          <p className="text-ink text-sm line-clamp-2">{c.title || 'untitled'}</p>
          <p className="readout">{secs(c.duration_s)} · hook: {c.hook_text || '—'}</p>
          <div className="flex gap-2 mt-auto">
            <button className="btn-primary flex-1" onClick={() => act(c.id, 'shortlist')}>react to this</button>
            <button className="btn-quiet" onClick={() => act(c.id, 'reject')} aria-label="drop">drop</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- //
function CommentaryView({ clips, reload, say, fail, act }) {
  const [sheets, setSheets] = useState([]);
  const [picked, setPicked] = useState({});
  const [building, setBuilding] = useState(false);
  const [uploading, setUploading] = useState(null);
  const fileRefs = useRef({});

  const loadSheets = useCallback(async () => {
    try { setSheets((await pipe('/sheets')).sheets || []); } catch (e) { fail(e); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadSheets(); }, [loadSheets]);

  const shortlisted = clips.filter((c) => c.status === 'shortlisted');
  const waiting = clips.filter((c) => c.status !== 'shortlisted');
  const chosen = shortlisted.filter((c) => picked[c.id] ?? true).map((c) => c.id);

  const build = async () => {
    setBuilding(true);
    try {
      await pipe('/sheets', { method: 'POST', json: { clip_ids: chosen } });
      say('Watch sheet ready. Download it, play it full-screen through your speakers, and record your reaction.');
      await Promise.all([reload(), loadSheets()]);
    } catch (e) { fail(e); } finally { setBuilding(false); }
  };

  const upload = async (sheetId, file) => {
    if (!file) return;
    setUploading(sheetId);
    try {
      const body = new FormData();
      body.append('file', file);
      const headers = {};
      const token = readLocal(TOKEN_KEY);
      if (token) headers['X-Pipeline-Token'] = token;
      const res = await apiFetch(`/api/pipeline/sheets/${sheetId}/reaction`, { method: 'POST', body, headers });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new ApiError(res.status, data.detail || 'Upload failed', '');
      const missed = (data.segments || []).filter((s) => !s.tone_detected).length;
      say(missed
        ? `Aligned, but ${missed} tone(s) were not heard; those clips use the estimated position. Check them in review.`
        : 'Aligned. Composing now; clips move to review when QA passes.');
      await Promise.all([reload(), loadSheets()]);
    } catch (e) { fail(e); } finally { setUploading(null); }
  };

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-1">1 · build a watch sheet</h3>
        <p className="text-muted text-sm mb-4">
          Each clip gets a beep and a numbered card, then the clip, then a few seconds of black for your closing comment.
          That closing comment is the part QA measures, so say something after every clip.
        </p>
        {!shortlisted.length ? <p className="text-muted text-sm">Shortlist clips from the inbox first.</p> : (
          <>
            <ul className="space-y-2 mb-4">
              {shortlisted.map((c) => (
                <li key={c.id} className="flex items-center gap-3 text-sm">
                  <input type="checkbox" checked={picked[c.id] ?? true}
                    onChange={(e) => setPicked((p) => ({ ...p, [c.id]: e.target.checked }))} />
                  <span className="text-ink2 flex-1 truncate">{c.title || 'untitled'}</span>
                  <span className="readout">{secs(c.duration_s)}</span>
                  <button className="btn-quiet" onClick={() => act(c.id, 'unshortlist')}>remove</button>
                </li>
              ))}
            </ul>
            <button className="btn-primary inline-flex items-center gap-2" disabled={!chosen.length || building} onClick={build}>
              {building ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} build sheet ({chosen.length})
            </button>
          </>
        )}
      </div>

      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-1">2 · record and upload</h3>
        <p className="text-muted text-sm mb-4">
          Start your camera recording first, then play the sheet. The mic must hear the beeps; that is how each reaction is matched to its clip.
        </p>
        {!sheets.length ? <p className="text-muted text-sm">No sheets yet.</p> : (
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {sheets.map((s) => (
              <li key={s.id} className="py-3 flex flex-wrap items-center gap-3 text-sm">
                <span className="text-ink2 flex-1">{(s.manifest || []).length} clips · {fmt(s.created_at)}</span>
                <Badge status={s.status === 'recorded' ? 'approved' : 'awaiting_reaction'} />
                <a className="btn-quiet inline-flex items-center gap-1" href={mediaUrl('sheet', s.id)} download>
                  <Download size={14} /> sheet
                </a>
                <input type="file" accept="video/*" className="hidden" ref={(el) => { fileRefs.current[s.id] = el; }}
                  onChange={(e) => upload(s.id, e.target.files?.[0])} />
                <button className="btn-primary inline-flex items-center gap-2" disabled={uploading === s.id}
                  onClick={() => fileRefs.current[s.id]?.click()}>
                  {uploading === s.id ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} upload reaction
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {waiting.length > 0 && (
        <div className="card p-6">
          <h3 className="font-display lowercase text-lg text-ink mb-3">in progress</h3>
          <ul className="space-y-2 text-sm">
            {waiting.map((c) => (
              <li key={c.id} className="flex items-center gap-3">
                <span className="text-ink2 flex-1 truncate">{c.title}</span><Badge status={c.status} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
function ReviewView({ clips, act, reload, say, fail }) {
  if (!clips.length) return <Empty>Nothing to review. Composed clips that pass QA show up here.</Empty>;
  return (
    <div className="space-y-4">
      {clips.map((c) => <ReviewCard key={c.id} clip={c} act={act} reload={reload} say={say} fail={fail} />)}
    </div>
  );
}

function ReviewCard({ clip, act, reload, say, fail }) {
  const [title, setTitle] = useState(clip.title || '');
  const [description, setDescription] = useState(clip.description || '');
  const [tags, setTags] = useState((clip.tags || []).join(', '));
  const [layout, setLayout] = useState(clip.layout || 'stacked');
  const [reviewer, setReviewer] = useState(readLocal(REVIEWER_KEY));
  const [segment, setSegment] = useState(null);
  const [offset, setOffset] = useState(0);
  const [saving, setSaving] = useState(false);
  const checks = clip.qa_report?.checks || [];

  useEffect(() => {
    pipe(`/clips/${clip.id}`).then((d) => { setSegment(d.segment); setOffset(d.segment?.manual_offset_ms || 0); }).catch(() => {});
  }, [clip.id, clip.updated_at]);

  const dirty = title !== (clip.title || '') || description !== (clip.description || '')
    || tags !== (clip.tags || []).join(', ') || layout !== (clip.layout || 'stacked');

  const save = async () => {
    setSaving(true);
    try {
      await pipe(`/clips/${clip.id}`, {
        method: 'PATCH',
        json: { title, description, tags: tags.split(',').map((t) => t.trim()).filter(Boolean), layout },
      });
      if (layout !== (clip.layout || 'stacked')) await act(clip.id, 'recompose');
      else await reload();
      return true;
    } catch (e) { fail(e); return false; } finally { setSaving(false); }
  };

  const approve = async () => {
    if (!reviewer.trim()) { say('Enter your name so the approval is recorded.', 'error'); return; }
    writeLocal(REVIEWER_KEY, reviewer.trim());
    if (dirty && !(await save())) return;
    if (await act(clip.id, 'approve', { reviewer: reviewer.trim() })) say('Approved and scheduled.');
  };

  const nudge = async () => {
    if (!segment) return;
    setSaving(true);
    try {
      await pipe(`/segments/${segment.id}/offset`, { method: 'POST', json: { manual_offset_ms: Number(offset) || 0 } });
      say('Re-aligned and recomposed.');
      await reload();
    } catch (e) { fail(e); } finally { setSaving(false); }
  };

  return (
    <div className="card p-5 flex flex-col md:flex-row gap-5">
      <ClipVideo clip={clip} kind={clip.composed_path ? 'composed' : 'raw'} />
      <div className="flex-1 min-w-0 space-y-3">
        <div className="flex items-center gap-2"><Badge status={clip.status} />
          {segment && !segment.tone_detected && <span className="badge-warn">tone not heard: check sync</span>}
        </div>
        <label className="block">
          <span className="readout">title ({title.length}/100)</span>
          <input className="input-field w-full mt-1" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="block">
          <span className="readout">description</span>
          <textarea className="input-field w-full mt-1 min-h-[80px]" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="readout">tags (comma separated)</span>
            <input className="input-field w-full mt-1" value={tags} onChange={(e) => setTags(e.target.value)} />
          </label>
          <label className="block">
            <span className="readout">layout</span>
            <select className="input-field w-full mt-1" value={layout} onChange={(e) => setLayout(e.target.value)}>
              <option value="stacked">stacked (you on top)</option>
              <option value="pip">picture in picture</option>
            </select>
          </label>
        </div>

        {checks.length > 0 && (
          <ul className="grid sm:grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {checks.map((ch) => (
              <li key={ch.check} className="flex items-center gap-2">
                {ch.passed ? <CheckCircle2 size={13} className="text-[color:var(--color-ok)]" /> : <XCircle size={13} className="text-[color:var(--color-danger)]" />}
                <span className="text-ink2">{ch.check}</span>
                <span className="readout truncate">{Array.isArray(ch.value) ? `${ch.value.length} found` : String(ch.value ?? '—')} · {ch.limit}</span>
              </li>
            ))}
          </ul>
        )}

        {segment && (
          <div className="flex flex-wrap items-end gap-2">
            <label className="block">
              <span className="readout">sync nudge (ms, + = later)</span>
              <input type="number" step="50" className="input-field w-32 mt-1" value={offset} onChange={(e) => setOffset(e.target.value)} />
            </label>
            <button className="btn-quiet" disabled={saving} onClick={nudge}>re-align</button>
            <span className="readout">your closing comment: {secs(segment.speech_seconds)}</span>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-2 pt-2">
          <label className="block">
            <span className="readout">approved by</span>
            <input className="input-field w-40 mt-1" value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="your name" />
          </label>
          <button className="btn-primary inline-flex items-center gap-2" disabled={saving || clip.status !== 'pending_review'} onClick={approve}>
            <CheckCircle2 size={14} /> approve &amp; schedule
          </button>
          {dirty && <button className="btn-ghost" disabled={saving} onClick={save}>save edits</button>}
          <button className="btn-quiet inline-flex items-center gap-1" onClick={() => act(clip.id, 'send_back')}><Undo2 size={14} /> new reaction</button>
          {clip.status === 'qa_failed' && <button className="btn-quiet" onClick={() => act(clip.id, 'recompose')}>recompose</button>}
          <button className="btn-quiet" onClick={() => act(clip.id, 'reject')}>reject</button>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function ScheduleView({ clips, act, reload, say, fail }) {
  const [running, setRunning] = useState(false);
  const scheduled = clips.filter((c) => c.status === 'scheduled').sort((a, b) => (a.scheduled_for || '').localeCompare(b.scheduled_for || ''));
  const failed = clips.filter((c) => c.status === 'publish_failed' || c.status === 'approved');
  const published = clips.filter((c) => c.status === 'published').sort((a, b) => (b.published_at || '').localeCompare(a.published_at || ''));

  const runNow = async () => {
    setRunning(true);
    try {
      const r = await pipe('/publish/run', { method: 'POST' });
      say(`Published ${r.published}, failed ${r.failed}${r.waiting_quota ? `, ${r.waiting_quota} waiting for quota` : ''}.`);
      await reload();
    } catch (e) { fail(e); } finally { setRunning(false); }
  };

  const Row = ({ c, children }) => (
    <li className="py-3 flex flex-wrap items-center gap-3 text-sm">
      <span className="text-ink2 flex-1 min-w-0 truncate">{c.title}</span>{children}
    </li>
  );

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display lowercase text-lg text-ink">upcoming</h3>
          <button className="btn-quiet inline-flex items-center gap-2" onClick={runNow} disabled={running}>
            {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} publish due now
          </button>
        </div>
        {!scheduled.length ? <p className="text-muted text-sm">Nothing scheduled.</p> : (
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {scheduled.map((c) => (
              <Row key={c.id} c={c}>
                <span className="readout">{fmt(c.scheduled_for)}</span>
                {c.publish_error && <span className="badge-warn truncate max-w-xs">{c.publish_error}</span>}
                <button className="btn-quiet" onClick={() => act(c.id, 'unschedule')}>unschedule</button>
              </Row>
            ))}
          </ul>
        )}
      </div>
      {failed.length > 0 && (
        <div className="card p-6">
          <h3 className="font-display lowercase text-lg text-ink mb-3">needs attention</h3>
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {failed.map((c) => (
              <Row key={c.id} c={c}>
                <Badge status={c.status} />
                {c.publish_error && <span className="readout truncate max-w-xs">{c.publish_error}</span>}
                <button className="btn-quiet" onClick={() => act(c.id, 'reschedule')}>schedule again</button>
              </Row>
            ))}
          </ul>
        </div>
      )}
      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-3">published</h3>
        {!published.length ? <p className="text-muted text-sm">Nothing published yet.</p> : (
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {published.map((c) => (
              <Row key={c.id} c={c}>
                <span className="readout">{fmt(c.published_at)}</span>
                <a className="btn-quiet inline-flex items-center gap-1" target="_blank" rel="noopener noreferrer"
                  href={`https://youtube.com/shorts/${c.youtube_video_id}`}><Youtube size={14} /> open</a>
              </Row>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function SourcesView({ say, fail }) {
  const [watches, setWatches] = useState([]);
  const [sources, setSources] = useState([]);
  const [channel, setChannel] = useState('');
  const [permission, setPermission] = useState('');
  const [grantedAt, setGrantedAt] = useState('');
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [w, s] = await Promise.all([pipe('/watchlist'), pipe('/sources?limit=50')]);
      setWatches(w.watches || []);
      setSources(s.sources || []);
    } catch (e) { fail(e); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);

  const run = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) say(ok); await load(); } catch (e) { fail(e); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-1">watchlist</h3>
        <p className="text-muted text-sm mb-4">
          Only channels listed here are read. New long-form uploads (not Shorts, not the back catalogue) are clipped automatically,
          within the daily limit. Record who gave you permission.
        </p>
        <div className="grid md:grid-cols-[1fr_1.4fr_auto_auto] gap-2 mb-4">
          <input className="input-field" placeholder="@handle or channel URL" value={channel} onChange={(e) => setChannel(e.target.value)} />
          <input className="input-field" placeholder="permission: who, how (e.g. email from producer)" value={permission} onChange={(e) => setPermission(e.target.value)} />
          <input className="input-field" type="date" value={grantedAt} onChange={(e) => setGrantedAt(e.target.value)} aria-label="permission date" />
          <button className="btn-primary" disabled={busy || !channel.trim() || !permission.trim()}
            onClick={() => run(async () => {
              await pipe('/watchlist', { method: 'POST', json: { channel, permission_note: permission, permission_granted_at: grantedAt || null } });
              setChannel(''); setPermission(''); setGrantedAt('');
            }, 'Channel added.')}>add</button>
        </div>
        {!watches.length ? <p className="text-muted text-sm">No channels yet.</p> : (
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {watches.map((w) => (
              <li key={w.id} className="py-3 flex flex-wrap items-center gap-3 text-sm">
                <span className="text-ink flex-1 min-w-0 truncate">{w.title}</span>
                <span className="readout truncate max-w-xs" title={w.permission_note}>{w.permission_note}</span>
                <span className="readout">checked {fmt(w.last_checked_at)}</span>
                {w.last_error && <span className="badge-danger truncate max-w-xs" title={w.last_error}>{w.last_error}</span>}
                <button className="btn-quiet" onClick={() => run(() => pipe(`/watchlist/${w.id}`, { method: 'PATCH', json: { active: !w.active } }))}>
                  {w.active ? 'pause' : 'resume'}
                </button>
                <button className="btn-quiet" onClick={() => { if (window.confirm(`Remove ${w.title}?`)) run(() => pipe(`/watchlist/${w.id}`, { method: 'DELETE' })); }}>remove</button>
              </li>
            ))}
          </ul>
        )}
        <button className="btn-quiet mt-3 inline-flex items-center gap-2" disabled={busy}
          onClick={() => run(async () => {
            const r = await pipe('/intake/run', { method: 'POST' });
            say(`Checked ${r.checked} channel(s): ${r.submitted} submitted, ${r.skipped} skipped, ${r.errors} errors.`);
          })}><RefreshCw size={14} /> check now</button>
      </div>

      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-1">one video</h3>
        <p className="text-muted text-sm mb-4">Clip a single video you have permission to use.</p>
        <div className="flex gap-2">
          <input className="input-field flex-1" placeholder="https://www.youtube.com/watch?v=..." value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn-primary" disabled={busy || !url.trim()}
            onClick={() => run(async () => { await pipe('/sources', { method: 'POST', json: { url } }); setUrl(''); }, 'Submitted. Clips arrive in the inbox when OpenShorts finishes.')}>clip it</button>
        </div>
      </div>

      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-3">recent sources</h3>
        {!sources.length ? <p className="text-muted text-sm">None yet.</p> : (
          <ul className="divide-y divide-[color:var(--color-rule)]">
            {sources.map((s) => (
              <li key={s.id} className="py-2 flex flex-wrap items-center gap-3 text-sm">
                <a className="text-ink2 hover:text-ink flex-1 min-w-0 truncate" href={s.url} target="_blank" rel="noopener noreferrer">{s.title || s.url}</a>
                <span className={s.status === 'failed' ? 'badge-danger' : s.status === 'completed' ? 'badge-ok' : 'readout'}>
                  {s.status}{s.skip_reason ? `: ${s.skip_reason.replace('_', ' ')}` : ''}
                </span>
                <span className="readout">{fmt(s.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function PerformanceView({ fail }) {
  const [rows, setRows] = useState(null);
  useEffect(() => { pipe('/performance').then((d) => setRows(d.rows || [])).catch(fail); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (rows === null) return <div className="flex justify-center py-10"><Loader2 className="animate-spin text-brass" /></div>;
  if (!rows.length) return <Empty>Metrics appear 24 hours after a clip is published, then again at 72 hours and 7 days.</Empty>;
  return (
    <div className="card p-0 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left readout">
            {['clip', 'channel', 'layout', 'length', 'comment', 'at', 'views', 'avg view', 'likes', 'subs'].map((h) => (
              <th key={h} className="px-4 py-3 font-normal">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-[color:var(--color-rule)]">
              <td className="px-4 py-2 text-ink2 max-w-[260px] truncate">{r.title}</td>
              <td className="px-4 py-2 text-muted">{r.channel_title || '—'}</td>
              <td className="px-4 py-2 text-muted">{r.layout}</td>
              <td className="px-4 py-2 tabular-nums">{secs(r.duration_s)}</td>
              <td className="px-4 py-2 tabular-nums">{secs(r.speech_seconds)}</td>
              <td className="px-4 py-2 readout">{r.checkpoint || 'pending'}</td>
              <td className="px-4 py-2 tabular-nums">{r.views ?? '—'}</td>
              <td className="px-4 py-2 tabular-nums">{r.avg_view_pct != null ? `${Number(r.avg_view_pct).toFixed(0)}%` : '—'}</td>
              <td className="px-4 py-2 tabular-nums">{r.likes ?? '—'}</td>
              <td className="px-4 py-2 tabular-nums">{r.subscribers_gained ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function SetupView({ overview, reload, say, fail }) {
  const [token, setToken] = useState(readLocal(TOKEN_KEY));
  const yt = overview?.youtube;
  const s = overview?.settings;

  const connect = async () => {
    try {
      const { url } = await pipe('/youtube/connect');
      window.open(url, '_blank', 'noopener');
      say('Finish the Google consent screen in the new tab, then press refresh here.');
    } catch (e) { fail(e); }
  };

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-3 flex items-center gap-2"><Youtube size={18} className="text-brass" /> youtube</h3>
        {!yt ? <Loader2 className="animate-spin text-brass" /> : (
          <>
            <p className="text-sm text-ink2 mb-1">
              {yt.connected ? `Connected: ${yt.channel_title || yt.channel_id}` : 'Not connected.'}
            </p>
            <p className="readout mb-4">
              uploads go out as <b>{yt.upload_privacy}</b>
              {!yt.app_verified && ' until your Google Cloud app is verified (PIPELINE_YT_APP_VERIFIED=1)'}
            </p>
            {!yt.configured && <Notice kind="error">Set PIPELINE_YT_CLIENT_ID and PIPELINE_YT_CLIENT_SECRET in .env (see docs/PIPELINE.md).</Notice>}
            {!yt.api_key_set && <Notice kind="error">Set PIPELINE_YT_API_KEY in .env so the watchlist can read channels.</Notice>}
            <div className="flex gap-2">
              <button className="btn-primary" disabled={!yt.configured} onClick={connect}>{yt.connected ? 'reconnect' : 'connect youtube'}</button>
              {yt.connected && (
                <button className="btn-quiet" onClick={async () => { try { await pipe('/youtube/disconnect', { method: 'POST' }); await reload(); } catch (e) { fail(e); } }}>disconnect</button>
              )}
            </div>
          </>
        )}
      </div>

      {s && (
        <div className="card p-6">
          <h3 className="font-display lowercase text-lg text-ink mb-3">pacing and rules</h3>
          <dl className="grid sm:grid-cols-2 gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted">publishes per day</dt><dd className="text-ink2">{s.publish_max_per_day}</dd>
            <dt className="text-muted">minimum gap</dt><dd className="text-ink2">{s.publish_min_gap_minutes} min</dd>
            <dt className="text-muted">publish window</dt><dd className="text-ink2">{s.publish_window.join('–')} ({s.timezone})</dd>
            <dt className="text-muted">new sources per day</dt><dd className="text-ink2">{s.intake_daily_limit}</dd>
            <dt className="text-muted">closing comment needed</dt><dd className="text-ink2">{s.min_commentary_seconds}s of speech</dd>
            <dt className="text-muted">room after each clip</dt><dd className="text-ink2">{s.reaction_tail_seconds}s</dd>
          </dl>
          <p className="readout mt-4">change these in .env (PIPELINE_*), then restart the backend</p>
        </div>
      )}

      <div className="card p-6">
        <h3 className="font-display lowercase text-lg text-ink mb-1">access token</h3>
        <p className="text-muted text-sm mb-3">Only needed if you set PIPELINE_ADMIN_TOKEN on the server.</p>
        <div className="flex gap-2">
          <input className="input-field flex-1" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          <button className="btn-ghost" onClick={() => { writeLocal(TOKEN_KEY, token); reload(); say('Saved.'); }}>save</button>
        </div>
      </div>
    </div>
  );
}
