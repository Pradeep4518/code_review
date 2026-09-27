import React, { useEffect, useState, useCallback } from "react";
import {
  Brain,
  Database,
  ScrollText,
  ShieldAlert,
  Zap,
  GitPullRequest,
  Sparkles,
  CheckCircle2,
  XCircle,
  Loader2,
  BookOpen,
  Tag,
  Clock,
  GraduationCap,
  Code2,
  AlertTriangle,
  ArrowLeftRight,
  Wifi,
  WifiOff,
} from "lucide-react";

const API_BASE = "/api";

const PRESETS = {
  raw_sql: {
    label: "Raw SQL Vulnerability",
    icon: Database,
    title: "Add get user by id endpoint",
    diff: `@app.get("/users/{user_id}")
def get_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return db.execute(query)`,
  },
  async_console: {
    label: "Async Error + Console Logging",
    icon: ScrollText,
    title: "Fetch order status from payment provider",
    diff: `@app.post("/orders/{order_id}/sync")
async def sync_order(order_id):
    print(f"syncing order {order_id}")
    resp = await payment_client.get_status(order_id)
    console.log("payment response:", resp.token)
    data = resp.json()
    return {"status": data["status"]}`,
  },
  clean: {
    label: "Clean PR",
    icon: CheckCircle2,
    title: "Add order status endpoint via repository layer",
    diff: `@app.get("/orders/{order_id}/status")
async def get_order_status(order_id: str):
    try:
        status = await order_repository.get_status(order_id)
        return {"order_id": order_id, "status": status}
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found")`,
  },
};

const CATEGORY_COLORS = {
  database: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  logging: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  architecture: "bg-purple-500/15 text-purple-300 border-purple-500/30",
  security: "bg-red-500/15 text-red-300 border-red-500/30",
  api: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
  testing: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  performance: "bg-pink-500/15 text-pink-300 border-pink-500/30",
  other: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

function catColor(cat) {
  return CATEGORY_COLORS[cat] || CATEGORY_COLORS.other;
}

async function api(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? JSON.stringify(body.detail) : `HTTP ${res.status}`);
  }
  return res.json();
}

function Badge({ children, tone = "slate" }) {
  const tones = {
    slate: "bg-slate-500/15 text-slate-300 border-slate-500/30",
    green: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    amber: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    red: "bg-red-500/15 text-red-300 border-red-500/30",
    blue: "bg-blue-500/15 text-blue-300 border-blue-500/30",
    purple: "bg-purple-500/15 text-purple-300 border-purple-500/30",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium ${tones[tone]}`}>
      {children}
    </span>
  );
}

function Header({ health }) {
  const hindsightOn = health?.memory_mode === "HINDSIGHT CONNECTED";
  const groqOn = health?.groq_configured;

  return (
    <header className="border-b border-border bg-panel/60 backdrop-blur px-6 py-4">
      <div className="max-w-[1600px] mx-auto flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent-blue to-accent-purple flex items-center justify-center shadow-glow">
            <Brain size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white leading-none">RepoMind</h1>
            <p className="text-xs text-slate-400 mt-0.5">The Self-Evolving Code Review Agent</p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Badge tone={hindsightOn ? "purple" : "amber"}>
            {hindsightOn ? <Wifi size={13} /> : <WifiOff size={13} />}
            {health?.memory_mode || "…"}
          </Badge>
          <Badge tone={groqOn ? "green" : "amber"}>
            <Zap size={13} />
            {health?.groq_status || "…"}
          </Badge>
          <Badge tone="blue">
            <BookOpen size={13} />
            {health?.memory_count ?? 0} memories
          </Badge>
        </div>
      </div>
    </header>
  );
}

function PresetButton({ preset, active, onClick }) {
  const Icon = preset.icon;
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs font-medium transition-colors ${
        active
          ? "bg-accent-blue/15 border-accent-blue/40 text-accent-blue"
          : "bg-panel2 border-border text-slate-300 hover:border-slate-600"
      }`}
    >
      <Icon size={14} />
      {preset.label}
    </button>
  );
}

function TeachCard({ onTaught }) {
  const [rule, setRule] = useState("");
  const [category, setCategory] = useState("architecture");
  const [status, setStatus] = useState(null); // null | "loading" | "success" | "error"
  const [errorMsg, setErrorMsg] = useState("");

  const categories = ["architecture", "database", "security", "logging", "testing", "api", "performance", "other"];

  const submit = async () => {
    if (rule.trim().length < 3) return;
    setStatus("loading");
    setErrorMsg("");
    try {
      await api("/teach", { method: "POST", body: JSON.stringify({ rule, category }) });
      setStatus("success");
      setRule("");
      onTaught?.();
      setTimeout(() => setStatus(null), 2500);
    } catch (e) {
      setStatus("error");
      setErrorMsg(String(e.message || e));
    }
  };

  return (
    <div className="rounded-xl border border-accent-purple/30 bg-gradient-to-br from-panel2 to-panel p-4 shadow-glow">
      <div className="flex items-center gap-2 mb-1.5">
        <GraduationCap size={17} className="text-accent-purple" />
        <h3 className="text-sm font-semibold text-white">Teach Hindsight</h3>
      </div>
      <p className="text-xs text-slate-400 mb-3 leading-relaxed">
        Teach RepoMind a new engineering convention. It will remember this rule and use it in future reviews.
      </p>

      <textarea
        value={rule}
        onChange={(e) => setRule(e.target.value)}
        placeholder='e.g. "All FastAPI route handlers must remain thin. Database access must never happen directly inside API routes."'
        rows={3}
        className="w-full bg-base border border-border rounded-lg px-3 py-2 text-xs text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-accent-purple/50 resize-none"
      />

      <div className="flex items-center gap-2 mt-2.5 flex-wrap">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="bg-base border border-border rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-accent-purple/50"
        >
          {categories.map((c) => (
            <option key={c} value={c}>
              {c[0].toUpperCase() + c.slice(1)}
            </option>
          ))}
        </select>

        <button
          onClick={submit}
          disabled={status === "loading" || rule.trim().length < 3}
          className="ml-auto flex items-center gap-1.5 bg-gradient-to-r from-accent-purple to-accent-blue text-white text-xs font-semibold px-3.5 py-1.5 rounded-lg disabled:opacity-40 hover:opacity-90 transition-opacity"
        >
          {status === "loading" ? <Loader2 size={14} className="animate-spin" /> : <GraduationCap size={14} />}
          Teach Hindsight
        </button>
      </div>

      {status === "success" && (
        <div className="mt-2.5 flex items-center gap-1.5 text-xs text-emerald-400 animate-fade-in">
          <CheckCircle2 size={14} /> Memory retained
        </div>
      )}
      {status === "error" && (
        <div className="mt-2.5 flex items-center gap-1.5 text-xs text-red-400 animate-fade-in">
          <XCircle size={14} /> Failed: {errorMsg}
        </div>
      )}
    </div>
  );
}

function MemoryPill({ mem }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] font-medium uppercase tracking-wide ${catColor(
        mem.category
      )}`}
      title={mem.content}
    >
      <Tag size={10} />
      {mem.category}
    </span>
  );
}

function ReviewText({ text }) {
  // Render "Memory used:" lines with a distinct highlighted style.
  const lines = text.split("\n");
  return (
    <div className="space-y-1.5 text-[13px] leading-relaxed">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("Memory used:")) {
          return (
            <div
              key={i}
              className="ml-4 flex items-start gap-1.5 bg-accent-purple/10 border border-accent-purple/25 rounded-md px-2.5 py-1.5 text-accent-purple/90"
            >
              <Brain size={13} className="mt-0.5 shrink-0" />
              <span className="italic">{trimmed.replace("Memory used:", "").trim()}</span>
            </div>
          );
        }
        if (trimmed.startsWith("###")) {
          return (
            <div key={i} className="text-slate-500 text-[11px] uppercase tracking-wider font-semibold mb-1">
              {trimmed.replace(/^#+/, "").trim()}
            </div>
          );
        }
        if (trimmed.startsWith("-")) {
          return (
            <div key={i} className="flex items-start gap-2 text-slate-200">
              <span className="text-accent-blue mt-1">•</span>
              <span dangerouslySetInnerHTML={{ __html: mdBold(trimmed.slice(1).trim()) }} />
            </div>
          );
        }
        if (!trimmed) return null;
        return (
          <p key={i} className="text-slate-200" dangerouslySetInnerHTML={{ __html: mdBold(trimmed) }} />
        );
      })}
    </div>
  );
}

function mdBold(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="bg-black/30 px-1 py-0.5 rounded text-[12px] font-mono">$1</code>');
}

function ReviewPanel({ title, badge, badgeTone, icon: Icon, result, loading, placeholder }) {
  return (
    <div className="rounded-xl border border-border bg-panel flex flex-col min-h-[280px]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <Icon size={16} className={badgeTone === "purple" ? "text-accent-purple" : "text-slate-400"} />
          <h3 className="text-sm font-semibold text-white">{title}</h3>
        </div>
        <Badge tone={badgeTone}>{badge}</Badge>
      </div>

      <div className="p-4 flex-1 overflow-auto">
        {loading && (
          <div className="flex items-center gap-2 text-slate-400 text-xs">
            <Loader2 size={14} className="animate-spin" /> Reviewing…
          </div>
        )}

        {!loading && !result && (
          <p className="text-xs text-slate-600 italic">{placeholder}</p>
        )}

        {!loading && result && (
          <div className="space-y-3 animate-fade-in">
            <ReviewText text={result.review} />

            {result.memories?.length > 0 && (
              <div className="pt-3 mt-3 border-t border-border/60">
                <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider font-semibold text-accent-purple mb-2">
                  <Sparkles size={12} /> Memories Recalled ({result.memory_count})
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {result.memories.map((m) => (
                    <MemoryPill key={m.id} mem={m} />
                  ))}
                </div>
              </div>
            )}

            <div className="flex items-center gap-3 pt-2 text-[11px] text-slate-500">
              <span className="flex items-center gap-1">
                <Clock size={11} /> {result.groq_latency_ms}ms
              </span>
              <span>
                {result.llm_provider === "groq" ? `Groq · ${result.llm_model}` : "Local fallback engine"}
              </span>
              {result.memory_enabled && (
                <span>Memory: {result.memory_provider}</span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [prTitle, setPrTitle] = useState(PRESETS.raw_sql.title);
  const [codeDiff, setCodeDiff] = useState(PRESETS.raw_sql.diff);
  const [activePreset, setActivePreset] = useState("raw_sql");

  const [statelessResult, setStatelessResult] = useState(null);
  const [memoryResult, setMemoryResult] = useState(null);
  const [loadingStateless, setLoadingStateless] = useState(false);
  const [loadingMemory, setLoadingMemory] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [banner, setBanner] = useState(null);

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api("/health");
      setHealth(h);
    } catch {
      setHealth({ memory_mode: "DEMO MEMORY MODE", groq_status: "GROQ FALLBACK (local engine)", memory_count: 0 });
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const id = setInterval(refreshHealth, 8000);
    return () => clearInterval(id);
  }, [refreshHealth]);

  const applyPreset = (key) => {
    setActivePreset(key);
    setPrTitle(PRESETS[key].title);
    setCodeDiff(PRESETS[key].diff);
    setStatelessResult(null);
    setMemoryResult(null);
  };

  const runStateless = async () => {
    setLoadingStateless(true);
    try {
      const r = await api("/review", {
        method: "POST",
        body: JSON.stringify({ code_diff: codeDiff, pr_title: prTitle, bypass_memory: true }),
      });
      setStatelessResult(r);
    } catch (e) {
      setBanner({ tone: "red", text: `Review failed: ${e.message}` });
    } finally {
      setLoadingStateless(false);
    }
  };

  const runMemory = async () => {
    setLoadingMemory(true);
    try {
      const r = await api("/review", {
        method: "POST",
        body: JSON.stringify({ code_diff: codeDiff, pr_title: prTitle, bypass_memory: false }),
      });
      setMemoryResult(r);
      refreshHealth();
    } catch (e) {
      setBanner({ tone: "red", text: `Review failed: ${e.message}` });
    } finally {
      setLoadingMemory(false);
    }
  };

  const runCompare = async () => {
    await Promise.all([runStateless(), runMemory()]);
  };

  const runSeed = async () => {
    setSeeding(true);
    try {
      const r = await api("/seed", { method: "POST" });
      setBanner({ tone: "green", text: `Seeded ${r.seeded_count} team memories into ${r.provider}.` });
      refreshHealth();
    } catch (e) {
      setBanner({ tone: "red", text: `Seed failed: ${e.message}` });
    } finally {
      setSeeding(false);
      setTimeout(() => setBanner(null), 4000);
    }
  };

  return (
    <div className="min-h-screen bg-base text-slate-100 font-sans">
      <Header health={health} />

      {banner && (
        <div className={`max-w-[1600px] mx-auto mt-3 px-6`}>
          <div
            className={`rounded-lg border px-3.5 py-2 text-xs flex items-center gap-2 ${
              banner.tone === "green"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                : "bg-red-500/10 border-red-500/30 text-red-300"
            }`}
          >
            {banner.tone === "green" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            {banner.text}
          </div>
        </div>
      )}

      <main className="max-w-[1600px] mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6">
        {/* LEFT SIDE */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-panel p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <GitPullRequest size={16} className="text-accent-blue" />
                <h2 className="text-sm font-semibold text-white">Pull Request Review</h2>
              </div>
              <button
                onClick={runSeed}
                disabled={seeding}
                className="text-[11px] text-slate-400 hover:text-slate-200 flex items-center gap-1 disabled:opacity-40"
                title="Seed starter team memories into Hindsight"
              >
                {seeding ? <Loader2 size={12} className="animate-spin" /> : <BookOpen size={12} />}
                Seed memories
              </button>
            </div>

            <label className="block text-[11px] text-slate-400 mb-1">PR Title</label>
            <input
              value={prTitle}
              onChange={(e) => setPrTitle(e.target.value)}
              className="w-full bg-base border border-border rounded-lg px-3 py-2 text-xs text-slate-200 mb-3 focus:outline-none focus:border-accent-blue/50"
            />

            <label className="block text-[11px] text-slate-400 mb-1 flex items-center gap-1">
              <Code2 size={12} /> Code Diff
            </label>
            <textarea
              value={codeDiff}
              onChange={(e) => setCodeDiff(e.target.value)}
              rows={10}
              className="w-full bg-black/40 border border-border rounded-lg px-3 py-2.5 text-[12px] font-mono text-slate-200 mb-3 focus:outline-none focus:border-accent-blue/50 code-scroll"
              spellCheck={false}
            />

            <div className="flex flex-wrap gap-2 mb-4">
              {Object.entries(PRESETS).map(([key, preset]) => (
                <PresetButton key={key} preset={preset} active={activePreset === key} onClick={() => applyPreset(key)} />
              ))}
            </div>

            <div className="grid grid-cols-1 gap-2">
              <button
                onClick={runStateless}
                disabled={loadingStateless}
                className="flex items-center justify-center gap-2 bg-panel2 border border-border hover:border-slate-500 text-slate-200 text-xs font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-40"
              >
                {loadingStateless ? <Loader2 size={14} className="animate-spin" /> : <ShieldAlert size={14} />}
                Review Without Memory
              </button>
              <button
                onClick={runMemory}
                disabled={loadingMemory}
                className="flex items-center justify-center gap-2 bg-gradient-to-r from-accent-purple to-accent-blue text-white text-xs font-semibold py-2.5 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-40"
              >
                {loadingMemory ? <Loader2 size={14} className="animate-spin" /> : <Brain size={14} />}
                Review With Hindsight
              </button>
              <button
                onClick={runCompare}
                disabled={loadingStateless || loadingMemory}
                className="flex items-center justify-center gap-2 bg-panel2 border border-accent-blue/30 text-accent-blue text-xs font-semibold py-2.5 rounded-lg hover:border-accent-blue/60 transition-colors disabled:opacity-40"
              >
                <ArrowLeftRight size={14} />
                Compare Reviews
              </button>
            </div>
          </div>

          <TeachCard onTaught={refreshHealth} />
        </div>

        {/* RIGHT SIDE */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start">
          <ReviewPanel
            title="Stateless / Generic Review"
            badge="NO MEMORY"
            badgeTone="slate"
            icon={ShieldAlert}
            result={statelessResult}
            loading={loadingStateless}
            placeholder="Run “Review Without Memory” to see a generic, stateless AI review with no knowledge of this team's conventions."
          />
          <ReviewPanel
            title="Hindsight Memory-Augmented Review"
            badge="MEMORY ENABLED"
            badgeTone="purple"
            icon={Brain}
            result={memoryResult}
            loading={loadingMemory}
            placeholder="Run “Review With Hindsight” to see the same PR reviewed with recalled team-specific engineering knowledge."
          />
        </div>
      </main>

      <footer className="max-w-[1600px] mx-auto px-6 pb-8 pt-2 text-center text-[11px] text-slate-600">
        RepoMind doesn't just review code. It remembers how your team builds software.
      </footer>
    </div>
  );
}
