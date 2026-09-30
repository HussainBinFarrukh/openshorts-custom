import React from 'react';
import { Sparkles, Zap, Globe, FileVideo, Subtitles, Youtube, Instagram, Shield, Github, ArrowRight, Check, ChevronDown, Monitor, Cpu, Languages, Type, Upload, Scissors, Link2, Bot } from 'lucide-react';
import './landing.css';

const REPO_URL = 'https://github.com/HussainBinFarrukh/openshorts-custom';

// 64 deterministic tick heights: gaussian envelope × sine wave (no randomness)
const METER_TICKS = Array.from({ length: 64 }, (_, i) => {
  const t = i / 63;
  const envelope = Math.exp(-((t - 0.5) ** 2) / (2 * 0.18 * 0.18));
  const wave = 0.55 + 0.45 * Math.sin(i * 1.7);
  return Math.round((4 + 24 * envelope * wave) * 10) / 10;
});

const APPARATUS_CALLOUTS = ['RATIO · 9:16', 'CLIPS · 3–15', 'DUB · 30+ LANGS', 'SUBS · WORD-LEVEL'];

const SectionHeader = ({ eyebrow, title, children }) => (
  <div className="mb-12">
    <p className="eyebrow mb-3">{eyebrow}</p>
    <h2 className="font-display text-3xl md:text-4xl lowercase text-ink tracking-tight mb-4">{title}</h2>
    {children && <p className="text-muted max-w-2xl leading-relaxed">{children}</p>}
  </div>
);

const FeatureCard = ({ icon, title, description }) => {
  const Icon = icon;
  return (
    <div className="card card-hover p-6">
      <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center mb-4">
        <Icon size={18} className="text-brass" />
      </div>
      <h3 className="font-display text-xl lowercase text-ink mb-2">{title}</h3>
      <p className="text-muted text-sm leading-relaxed">{description}</p>
    </div>
  );
};

const StepCard = ({ number, title, description }) => (
  <div className="flex gap-5">
    <span className="font-mono text-micro text-brass uppercase pt-1.5 flex-shrink-0">
      {String(number).padStart(2, '0')}
    </span>
    <div>
      <h3 className="text-ink font-medium mb-1">{title}</h3>
      <p className="text-muted text-sm leading-relaxed">{description}</p>
    </div>
  </div>
);

const FAQItem = ({ question, answer, isOpen, onClick }) => (
  <div>
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-1 py-5 text-left"
    >
      <span className="text-ink font-medium pr-4">{question}</span>
      <ChevronDown size={18} className={`text-muted flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
    </button>
    {isOpen && (
      <div className="px-1 pb-6">
        <p className="faq-answer text-muted text-sm leading-relaxed">{answer}</p>
      </div>
    )}
  </div>
);

export default function Landing({ onLaunchApp }) {
  const [openFaq, setOpenFaq] = React.useState(null);
  const [heroUrl, setHeroUrl] = React.useState('');

  // Hand the pasted link to the app: MediaInput picks it up on mount, so the
  // user lands with their own video ready instead of an empty form.
  const handleHeroSubmit = (e) => {
    e.preventDefault();
    const url = heroUrl.trim();
    if (url) {
      try { localStorage.setItem('os_pending_url', url); } catch { /* ignore */ }
    }
    onLaunchApp();
  };

  const features = [
    {
      icon: Sparkles,
      title: "AI Viral Moment Detection",
      description: "Google Gemini scores your transcript and scenes to find the 3-15 most engaging moments. Automatic AI clipping, no manual scrubbing."
    },
    {
      icon: Scissors,
      title: "Smart 9:16 Vertical Cropping",
      description: "Dual-mode AI reframing with MediaPipe face tracking and YOLOv8 fallback."
    },
    {
      icon: Subtitles,
      title: "Automatic Subtitle Generation",
      description: "faster-whisper subtitles with word-level timestamps, styled and burned into your clips."
    },
    {
      icon: Languages,
      title: "AI Voice Dubbing in 30+ Languages",
      description: "ElevenLabs AI dubbing translates your audio while preserving the speaker's voice."
    },
    {
      icon: Type,
      title: "Hook Text Overlays",
      description: "AI-generated hook titles that capture viewers in the first 3 seconds."
    },
    {
      icon: Zap,
      title: "AI Video Effects",
      description: "Gemini-generated FFmpeg filters: color grading, transitions, visual enhancements."
    },
    {
      icon: Upload,
      title: "Local Video Upload",
      description: "Upload podcasts, webinars, livestreams, and vlogs at full resolution."
    },
    {
      icon: Shield,
      title: "100% Self-Hosted & Private",
      description: "Run it with Docker on your own machine — videos never leave your infrastructure."
    },
    {
      icon: Monitor,
      title: "AI YouTube Studio",
      description: "AI thumbnail generator, 10 viral title suggestions, and auto descriptions with chapters."
    },
    {
      icon: Globe,
      title: "Direct Social Publishing",
      description: "Post to TikTok, Instagram Reels, and YouTube Shorts from the dashboard."
    },
    {
      icon: Bot,
      title: "MCP Server & API for AI Agents",
      description: "Connect Claude, ChatGPT or n8n to the same pipeline over MCP — no dashboard needed."
    },
    {
      icon: Sparkles,
      title: "AI UGC Video Generator",
      description: "AI writes the script and generates a lip-synced avatar video from a product description."
    },
    {
      icon: FileVideo,
      title: "AI Actors & Lip-Sync",
      description: "Pick an AI actor or upload a photo for a lip-synced talking head video."
    }
  ];

  const steps = [
    { title: "Upload a Long-Form Video", description: "Drop any video file you own — podcasts, webinars, livestreams, interviews." },
    { title: "AI Detects the Best Viral Moments", description: "Google Gemini finds 3-15 high-potential clips of 15-60 seconds." },
    { title: "Smart Cropping to Vertical 9:16", description: "AI reframes to vertical with face tracking — subjects stay centered." },
    { title: "Add Subtitles, Hooks & Effects", description: "Auto subtitles, hook overlays, AI effects — optionally dub into 30+ languages." },
    { title: "Download or Post to Social Media", description: "Export your clips or post directly to TikTok, Instagram Reels, and YouTube Shorts." }
  ];

  const faqs = [
    {
      question: "What is ClipLinQ and how does it work?",
      answer: "ClipLinQ is a self-hosted AI clip generator that transforms your long-form videos — podcasts, webinars, livestreams, vlogs, interviews — into viral-ready short clips in 9:16 vertical format. It uses a multi-step AI pipeline: faster-whisper for transcription with word-level timestamps, scene-boundary detection, and Google Gemini for identifying the most engaging viral moments."
    },
    {
      question: "Is ClipLinQ really free?",
      answer: "Yes. It's self-hosted and open source: you run it with Docker on your own machine and bring your own API keys, with no watermarks, no usage limits and no subscription. What it costs you is hardware and the time to keep it running. On a typical CPU an 8-minute video takes about 5 to 8 minutes to process; on an NVIDIA GPU it's closer to a minute. You need a Google Gemini key (the free tier is generous), plus ElevenLabs for dubbing and fal.ai for AI Shorts if you want those features."
    },
    {
      question: "How do I turn a long-form video into TikTok or Reels clips?",
      answer: "Upload your long-form video, enter your Gemini API key, and click Process. The AI transcribes it with faster-whisper, detects the best viral moments using Google Gemini, and crops them to 9:16 vertical format with MediaPipe face tracking."
    },
    {
      question: "Can it generate YouTube thumbnails and titles?",
      answer: "Yes. The YouTube Studio includes an AI thumbnail generator, a title generator, and a description generator — all powered by Gemini. Upload your video and the AI suggests 10 viral title options with an interactive refinement chat, then generates thumbnail designs with optional face/background composition."
    },
    {
      question: "What is the AI UGC Video Generator?",
      answer: "AI Shorts generates marketing videos with AI actors for any product or business. You describe your product or paste a website URL — the AI writes a script, generates a realistic AI actor with lip-synced voiceover, adds b-roll visuals, subtitles, and hook text overlays."
    },
    {
      question: "How does the smart vertical cropping work?",
      answer: "Two intelligent cropping modes convert 16:9 horizontal video to 9:16 vertical. TRACK mode uses MediaPipe face detection with YOLOv8 as fallback to follow a single subject with stabilized camera movement. GENERAL mode handles group shots and landscapes with a blurred background layout. Two-person conversations get a SPLIT layout, both speakers stacked."
    },
    {
      question: "Can I automate it from Claude, ChatGPT or n8n?",
      answer: "Yes. It exposes an MCP server plus a REST API with completion webhooks, so an AI agent can run the whole flow: submit a video URL, wait for processing, list the clips and publish them to TikTok, Instagram or YouTube."
    },
    {
      question: "What are the system requirements?",
      answer: "Any system with Docker installed. The recommended setup is 8GB+ RAM and a modern multi-core CPU. GPU acceleration (NVIDIA CUDA) is optional but speeds up processing significantly. Docker Compose handles all dependencies automatically. Works on Linux, macOS, and Windows (via WSL2/Docker Desktop)."
    }
  ];

  return (
    <div className="min-h-screen bg-paper text-ink2 overflow-x-clip">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 bg-paper border-b border-rule">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <a href="/" className="flex items-center gap-2.5 font-display text-xl lowercase text-ink tracking-tight">
            <span>cliplinq</span>
          </a>
          <div className="hidden md:flex items-center gap-7 text-sm lowercase text-muted">
            <a href="#features" className="hover:text-ink transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-ink transition-colors">How It Works</a>
            <a href="#faq" className="hover:text-ink transition-colors">FAQ</a>
          </div>
          <div className="flex items-center gap-3">
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex items-center gap-2 text-sm lowercase text-muted hover:text-ink transition-colors"
            >
              <Github size={16} />
              <span>GitHub</span>
            </a>
            <button onClick={onLaunchApp} className="btn-primary px-5 py-2 whitespace-nowrap">
              Launch App
            </button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="hero-blueprint relative overflow-clip border-b border-rule pt-32 pb-20 px-6">
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_auto] gap-14 items-center">
          <div className="min-w-0">
            <p className="eyebrow mb-6">00 · AI Clip Generator · Self-Hosted</p>

            <h1 className="hero-h1 mb-6">
              the open source ai <em>clip generator</em>, built to clip what people actually watch.
            </h1>

            <p className="hero-description text-muted max-w-2xl mb-8 leading-relaxed lowercase">
              turn long videos into viral 9:16 shorts, or generate ugc marketing videos with ai actors.
              run it on your own machine, bring your own keys. also a clipping tool for ai agents —
              claude, chatgpt and n8n can drive it over mcp.
            </p>

            <form onSubmit={handleHeroSubmit} className="mb-5">
              <div className="hero-input-row flex flex-col sm:flex-row items-stretch gap-3">
                <div className="relative flex-1 min-w-0">
                  <Link2 size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
                  <input
                    type="url"
                    value={heroUrl}
                    onChange={(e) => setHeroUrl(e.target.value)}
                    placeholder="paste a video link"
                    className="input-field pl-11"
                    aria-label="Video link"
                  />
                </div>
                <button type="submit" className="btn-primary whitespace-nowrap">
                  get started
                  <ArrowRight size={16} />
                </button>
              </div>
            </form>

            <p className="text-sm text-muted lowercase">
              free and open source, self-hosted with docker.{' '}
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="text-ink2 underline hover:text-ink transition-colors"
              >
                view on github →
              </a>
            </p>
          </div>

          <figure className="apparatus" aria-label="example vertical clip generated by cliplinq">
            <div className="apparatus-shell">
              <span className="apparatus-glow" aria-hidden="true" />
              <div className="apparatus-chamber">
                <video
                  src="/demo/clip-vertical.mp4"
                  autoPlay
                  muted
                  loop
                  playsInline
                  preload="metadata"
                  className="w-full h-full object-cover"
                />
                <span className="apparatus-stencil">9:16</span>
              </div>
            </div>
            <ul className="apparatus-callouts" aria-hidden="true">
              {APPARATUS_CALLOUTS.map((c) => (
                <li key={c}><span className="apparatus-leader" />{c}</li>
              ))}
            </ul>
          </figure>
        </div>
      </section>

      {/* Meter strip */}
      <section className="border-b border-rule" aria-hidden="true">
        <div className="max-w-6xl mx-auto px-6 meter-strip">
          <span className="readout whitespace-nowrap">Signal · 9:16</span>
          <div className="meter-ticks">
            {METER_TICKS.map((h, i) => (
              <span key={i} className="meter-tick" style={{ height: `${h}px` }} />
            ))}
          </div>
          <span className="readout whitespace-nowrap hidden sm:inline">Clips · 3–15 / video</span>
        </div>
      </section>

      {/* Stats */}
      <section className="border-b border-rule">
        <div className="max-w-6xl mx-auto px-6 py-12 grid grid-cols-3 divide-x divide-rule text-center">
          <div className="px-4">
            <div className="font-display text-4xl md:text-5xl text-ink tabular-nums">3–15</div>
            <div className="eyebrow mt-2">Clips per Video</div>
          </div>
          <div className="px-4">
            <div className="font-display text-4xl md:text-5xl text-ink tabular-nums">30+</div>
            <div className="eyebrow mt-2">Dubbing Languages</div>
          </div>
          <div className="px-4">
            <div className="font-display text-4xl md:text-5xl text-ink tabular-nums">100%</div>
            <div className="eyebrow mt-2">Open Source</div>
          </div>
        </div>
      </section>

      {/* Smart crop demo */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <SectionHeader eyebrow="01 · Smart Crop" title="one video in. the moment, reframed.">
            Real output: AI face tracking reframes 16:9 to vertical 9:16 — no manual positioning.
          </SectionHeader>
          <div className="flex flex-col md:flex-row items-center gap-8 md:gap-10">
            <figure className="crop-frame crop-frame-16-9 w-full max-w-xl min-w-0" aria-label="original 16:9 source video">
              <video src="/demo/clip-source.mp4" autoPlay muted loop playsInline preload="metadata" />
            </figure>
            <div className="crop-leader" aria-hidden="true">
              <span className="readout whitespace-nowrap">AI Tracking → 9:16</span>
              <span className="crop-leader-line" />
            </div>
            <figure className="crop-frame crop-frame-9-16 w-[180px] md:w-[210px] flex-none" aria-label="vertical 9:16 clip generated by cliplinq">
              <video src="/demo/clip-vertical.mp4" autoPlay muted loop playsInline preload="metadata" />
            </figure>
          </div>
        </div>
      </section>

      {/* 3 Tools in 1 */}
      <section className="py-20 px-6 border-t border-rule">
        <div className="max-w-6xl mx-auto">
          <SectionHeader eyebrow="02 · Tools" title="3 Tools in 1 Platform">
            Bring your own API keys — everything below runs on your own machine.
          </SectionHeader>
          <div className="grid md:grid-cols-3 gap-5">
            <div className="card p-8">
              <p className="eyebrow mb-4">01 · Clips</p>
              <Scissors size={20} className="text-brass mb-4" />
              <h3 className="font-display text-2xl lowercase text-ink mb-2">Clip Generator</h3>
              <p className="text-muted text-sm leading-relaxed mb-4">Turn long-form videos into viral-ready 9:16 shorts.</p>
              <ul className="space-y-1.5">
                {['AI viral moment detection', 'Smart face-tracking crop', 'Auto subtitles + AI dubbing in 30+ languages'].map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs text-muted"><Check size={12} className="text-ok shrink-0" />{f}</li>
                ))}
              </ul>
            </div>
            <div className="card p-8">
              <p className="eyebrow mb-4">02 · AI Shorts</p>
              <Sparkles size={20} className="text-brass mb-4" />
              <h3 className="font-display text-2xl lowercase text-ink mb-2">AI Shorts</h3>
              <p className="text-muted text-sm leading-relaxed mb-4">UGC marketing videos with AI actors for any business.</p>
              <ul className="space-y-1.5">
                {['AI actor generation + lip-sync', 'B-roll + TikTok-style subtitles', 'Pay-per-use via fal.ai + ElevenLabs'].map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs text-muted"><Check size={12} className="text-ok shrink-0" />{f}</li>
                ))}
              </ul>
            </div>
            <div className="card p-8">
              <p className="eyebrow mb-4">03 · Studio</p>
              <Monitor size={20} className="text-brass mb-4" />
              <h3 className="font-display text-2xl lowercase text-ink mb-2">YouTube Studio</h3>
              <p className="text-muted text-sm leading-relaxed mb-4">AI YouTube toolkit: thumbnails, titles, descriptions.</p>
              <ul className="space-y-1.5">
                {['AI thumbnail generator (with face upload)', '10 viral title suggestions + chat', 'Direct publish to YouTube'].map((f, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs text-muted"><Check size={12} className="text-ok shrink-0" />{f}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="py-20 px-6 border-t border-rule">
        <div className="max-w-6xl mx-auto">
          <SectionHeader eyebrow="03 · Features" title="AI Clip Generator + UGC Video Creator">
            A self-hosted AI video clipper for TikTok, Reels & Shorts.
          </SectionHeader>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map((feature, i) => (
              <FeatureCard key={i} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* API Keys */}
      <section className="py-20 px-6 border-t border-rule">
        <div className="max-w-5xl mx-auto">
          <SectionHeader eyebrow="04 · API Keys" title="Every API has a free tier">
            Bring your own keys (all with generous free tiers):
          </SectionHeader>
          <div className="grid md:grid-cols-3 gap-5">
            <div className="card p-6 relative">
              <span className="badge-brass absolute top-4 right-4">Required</span>
              <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center mb-4">
                <Cpu size={18} className="text-brass" />
              </div>
              <h3 className="font-display text-xl lowercase text-ink mb-1">Google Gemini API</h3>
              <div className="mb-3"><span className="badge-ok">Generous free tier</span></div>
              <p className="text-muted text-sm leading-relaxed">Powers all AI features: viral moment detection, title generation, video effects, thumbnail creation, and description writing.</p>
            </div>
            <div className="card p-6 relative">
              <span className="readout absolute top-4 right-4 border border-rule rounded-full px-2.5 py-1">Optional</span>
              <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center mb-4">
                <Languages size={18} className="text-brass" />
              </div>
              <h3 className="font-display text-xl lowercase text-ink mb-1">ElevenLabs API</h3>
              <div className="mb-3"><span className="badge-ok">Free tier included</span></div>
              <p className="text-muted text-sm leading-relaxed">Enables AI voice dubbing and translation in 30+ languages, preserving the original speaker's voice.</p>
            </div>
            <div className="card p-6 relative">
              <span className="readout absolute top-4 right-4 border border-rule rounded-full px-2.5 py-1">Optional</span>
              <div className="w-10 h-10 rounded-input bg-paper3 flex items-center justify-center mb-4">
                <Globe size={18} className="text-brass" />
              </div>
              <h3 className="font-display text-xl lowercase text-ink mb-1">Upload-Post API</h3>
              <div className="mb-3"><span className="badge-ok">Free tier included</span></div>
              <p className="text-muted text-sm leading-relaxed">Enables direct publishing to YouTube, TikTok, and Instagram Reels from the dashboard.</p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="py-20 px-6 border-t border-rule">
        <div className="max-w-4xl mx-auto">
          <SectionHeader eyebrow="05 · Pipeline" title="How It Works">
            From long-form video to viral-ready clips in 5 automated steps.
          </SectionHeader>
          <div className="space-y-8">
            {steps.map((step, i) => (
              <StepCard key={i} number={i + 1} {...step} />
            ))}
          </div>
        </div>
      </section>

      {/* Tech Stack */}
      <section className="py-20 px-6 border-t border-rule">
        <div className="max-w-5xl mx-auto">
          <SectionHeader eyebrow="06 · Stack" title="Built with Proven Technology">
            Industry-leading AI models and open source tools in one pipeline.
          </SectionHeader>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { name: "Google Gemini", desc: "AI Analysis" },
              { name: "faster-whisper", desc: "Transcription" },
              { name: "YOLOv8", desc: "Object Detection" },
              { name: "MediaPipe", desc: "Face Tracking" },
              { name: "FFmpeg", desc: "Video Processing" },
              { name: "ElevenLabs", desc: "Voice & TTS" },
              { name: "fal.ai", desc: "AI Video Gen" },
              { name: "React + Vite", desc: "Dashboard" },
              { name: "Docker", desc: "Deployment" }
            ].map((tech, i) => (
              <div key={i} className="border border-rule rounded-input bg-paper2 px-4 py-3 text-center">
                <div className="readout text-ink2">{tech.name}</div>
                <div className="text-xs text-muted mt-1">{tech.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Use Cases */}
      <section className="py-20 px-6 border-t border-rule">
        <div className="max-w-5xl mx-auto">
          <SectionHeader eyebrow="07 · Use Cases" title="Who Uses ClipLinQ?">
            Creators, marketers, and agencies scaling short-form video production.
          </SectionHeader>
          <div className="grid md:grid-cols-3 gap-5">
            {[
              {
                title: "Content Creators",
                description: "Repurpose long-form videos into TikTok and Reels clips automatically.",
                icon: Youtube
              },
              {
                title: "Social Media Managers",
                description: "Batch-process videos and publish for multiple clients from one dashboard.",
                icon: Instagram
              },
              {
                title: "Podcasters & Educators",
                description: "Extract the most engaging moments from episodes and lessons.",
                icon: FileVideo
              }
            ].map((useCase, i) => (
              <div key={i} className="card p-6">
                <useCase.icon size={18} className="text-brass mb-4" />
                <h3 className="font-display text-xl lowercase text-ink mb-2">{useCase.title}</h3>
                <p className="text-muted text-sm leading-relaxed">{useCase.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-20 px-6 border-t border-rule">
        <div className="max-w-3xl mx-auto">
          <SectionHeader eyebrow="08 · FAQ" title="Frequently Asked Questions">
            Everything you need to know, from setup to features.
          </SectionHeader>
          <div className="divide-y divide-rule border-y border-rule">
            {faqs.map((faq, i) => (
              <FAQItem
                key={i}
                question={faq.question}
                answer={faq.answer}
                isOpen={openFaq === i}
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
              />
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 px-6 border-t border-rule">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="font-display text-4xl md:text-5xl lowercase text-ink tracking-tight mb-5">start creating viral videos today.</h2>
          <p className="text-muted mb-10 max-w-xl mx-auto leading-relaxed lowercase">free, open source, self-hosted with docker.</p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <button onClick={onLaunchApp} className="btn-primary whitespace-nowrap">
              launch cliplinq
              <ArrowRight size={16} />
            </button>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-ghost whitespace-nowrap"
            >
              <Github size={16} />
              Star on GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-rule py-16 px-6">
        <div className="max-w-6xl mx-auto">
          <p className="font-display text-3xl md:text-5xl lowercase text-ink tracking-tight mb-10">clip it before it scrolls past.</p>
          <div className="border-t border-rule pt-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted">ClipLinQ — Open Source Clip Generator & AI UGC Video Creator</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm lowercase text-muted">
              <a href={REPO_URL} target="_blank" rel="noopener noreferrer" className="hover:text-ink transition-colors">GitHub</a>
              <a href="#features" className="hover:text-ink transition-colors">Features</a>
              <a href="#faq" className="hover:text-ink transition-colors">FAQ</a>
              <a href="#legal" className="hover:text-ink transition-colors whitespace-nowrap">Legal</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
