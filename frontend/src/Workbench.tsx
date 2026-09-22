import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Health = { version: string };
type JobStatus = "QUEUED" | "PLANNING" | "AWAITING_APPROVAL" | "EXECUTING" | "RENDERING" | "PASSED" | "FAILED" | "BLOCKED";
type Finding = { scene_id: string; action_id: string; description: string };
type Job = {
  id: string; status: JobStatus; message: string; spec_id: string | null;
  run_status: string | null; safety_findings: Finding[]; preview_revision: number;
};
type Event = {
  sequence: number; kind: string; status: string | null; message: string | null;
  scene_id: string | null; action_id: string | null; assertion_id: string | null;
};
type Scene = { id: string; title: string; goal: string; actions: { id: string; type: string }[]; assertions: { id: string; type: string }[] };
type DemoSpec = { id: string; title: string; goal: string; source_url: string; scenes: Scene[] };
type AssertionResult = { assertion_id: string; status: string; reason?: string;
  evidence?: { kind: string; expected: unknown; observed: unknown } | null };
type Report = { verification_status: string; scene_results: { scene_id: string; status: string; reason?: string; assertion_results: AssertionResult[] }[]; artifact_warnings: string[] };
type Manifest = { artifacts: { kind: string; path: string }[] };
type Tab = "scenes" | "verification" | "spec";

const api = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const terminal = new Set<JobStatus>(["PASSED", "FAILED", "BLOCKED"]);
const stages = ["规划", "执行与验证", "渲染", "交付"];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${api}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function eventText(item: Event): string {
  if (item.message) return item.message;
  const label: Record<string, string> = {
    ACTION_STARTED: "开始操作", ACTION_FINISHED: "操作完成", ASSERTION_EVALUATED: "断言已检查",
    SCENE_EVALUATED: "场景已验证", PREVIEW_UPDATED: "画面已更新", RUN_TRANSITION: "运行状态变化",
  };
  const subject = [item.scene_id, item.action_id ?? item.assertion_id].filter(Boolean).join(" / ");
  return `${label[item.kind] ?? item.kind}${subject ? ` · ${subject}` : ""}`;
}

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);
  const [url, setUrl] = useState("");
  const [goal, setGoal] = useState("");
  const [audience, setAudience] = useState("");
  const [language, setLanguage] = useState("zh");
  const [duration, setDuration] = useState("60");
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem("proofdemo-job-id"));
  const [job, setJob] = useState<Job | null>(null);
  const [spec, setSpec] = useState<DemoSpec | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [tab, setTab] = useState<Tab>("scenes");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshing = useRef(false);
  const fetched = useRef({ spec: "", report: "", manifest: "" });

  useEffect(() => {
    let mounted = true;
    const check = () => {
      request<Health>("/health").then((value) => {
        if (mounted) { setHealth(value); setOnline(true); }
      }).catch(() => { if (mounted) setOnline(false); });
    };
    check();
    const interval = window.setInterval(check, 5000);
    return () => { mounted = false; window.clearInterval(interval); };
  }, []);

  const refresh = useCallback(async (id: string) => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      const current = await request<Job>(`/jobs/${id}`);
      setJob(current);
      if (current.spec_id && fetched.current.spec !== id) {
        setSpec(await request<DemoSpec>(`/jobs/${id}/spec`));
        fetched.current.spec = id;
      }
      if (current.run_status && fetched.current.report !== id) {
        setReport(await request<Report>(`/jobs/${id}/report`));
        fetched.current.report = id;
      }
      if (current.status === "PASSED" && fetched.current.manifest !== id) {
        setManifest(await request<Manifest>(`/jobs/${id}/manifest`));
        fetched.current.manifest = id;
      }
    } catch (caught) {
      if (caught instanceof Error && caught.message === "Job not found") {
        localStorage.removeItem("proofdemo-job-id");
        setJobId(null);
      } else setError(caught instanceof Error ? caught.message : "无法读取任务状态");
    } finally { refreshing.current = false; }
  }, []);

  useEffect(() => {
    if (!jobId) return;
    void refresh(jobId);
    request<Event[]>(`/jobs/${jobId}/event-log`).then((history) => {
      setEvents((previous) => {
        const merged = new Map([...history, ...previous].map((item) => [item.sequence, item]));
        return [...merged.values()].sort((a, b) => a.sequence - b.sequence).slice(-100);
      });
    }).catch(() => undefined);
    if (job && terminal.has(job.status)) return;
    const source = new EventSource(`${api}/jobs/${jobId}/events`);
    source.onmessage = (message: MessageEvent<string>) => {
      const item = JSON.parse(message.data) as Event;
      setEvents((previous) => previous.some((saved) => saved.sequence === item.sequence)
        ? previous : [...previous, item].slice(-100));
      if (["JOB_STATUS", "PREVIEW_UPDATED", "SCENE_EVALUATED"].includes(item.kind)) {
        void refresh(jobId);
      }
    };
    const poll = window.setInterval(() => { void refresh(jobId); }, 2500);
    return () => { source.close(); window.clearInterval(poll); };
  }, [jobId, job?.status, refresh]);

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true); setError(null);
    try {
      const created = await request<Job>("/jobs", {
        method: "POST", headers: { "Content-Type": "application/json", "X-ProofDemo-Client": "studio" },
        body: JSON.stringify({ source_url: url, goal, audience: audience.trim() || null,
          language, approximate_duration_seconds: Number(duration) }),
      });
      setSpec(null); setReport(null); setManifest(null); setEvents([]);
      fetched.current = { spec: "", report: "", manifest: "" };
      localStorage.setItem("proofdemo-job-id", created.id);
      setJob(created); setJobId(created.id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建任务失败");
    } finally { setSending(false); }
  }

  async function approve() {
    if (!job) return;
    setSending(true); setError(null);
    try { setJob(await request<Job>(`/jobs/${job.id}/approve`, {
      method: "POST", headers: { "X-ProofDemo-Client": "studio" },
    })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "批准失败"); }
    finally { setSending(false); }
  }

  const active = job && !terminal.has(job.status);
  const phase = !job ? -1 : job.status === "PASSED" ? 3 : job.status === "RENDERING" ? 2
    : job.status === "EXECUTING" ? 1 : job.status === "QUEUED" ? -1 : 0;
  const videoReady = job?.status === "PASSED" && report?.verification_status === "PASSED"
    && manifest?.artifacts.some((item) => item.kind === "FINAL_VIDEO");

  return <main className="app-shell">
    <nav className="topbar" aria-label="ProofDemo">
      <a className="brand" href="/"><span className="brand-mark">P</span>ProofDemo <small>STUDIO</small></a>
      <span className={`api-badge ${online ? "api-online" : "api-offline"}`}>
        <i />{online ? `引擎在线 · ${health?.version}` : "引擎离线"}</span>
    </nav>
    <header className="page-heading">
      <div><p className="eyebrow">VERIFIED PRODUCT DEMOS</p>
        <h1>从一个想法，到有证据的演示。</h1>
        <p>输入产品地址和目标。ProofDemo 规划场景、操作浏览器、验证结果，并交付视频。</p></div>
      <span className="mode-pill">LOCAL STUDIO · STAGE 11</span>
    </header>
    <div className="workspace">
      <aside className="panel control-panel">
        <div className="panel-title"><span>01</span><h2>创建演示</h2></div>
        <form onSubmit={(event) => { void generate(event); }}>
          <label htmlFor="url">产品 URL</label>
          <input id="url" type="url" required placeholder="https://your-product.example"
            value={url} onChange={(event) => setUrl(event.target.value)} />
          <label htmlFor="goal">你想演示什么？</label>
          <textarea id="goal" required rows={5} maxLength={2000}
            placeholder="例如：展示如何创建一个任务并把它标记为已完成"
            value={goal} onChange={(event) => setGoal(event.target.value)} />
          <label htmlFor="audience">目标受众 <small>可选</small></label>
          <input id="audience" maxLength={200} placeholder="例如：第一次使用的团队成员"
            value={audience} onChange={(event) => setAudience(event.target.value)} />
          <div className="form-row"><div><label htmlFor="language">语言</label>
            <select id="language" value={language} onChange={(event) => setLanguage(event.target.value)}>
              <option value="zh">中文</option><option value="en">English</option></select></div>
            <div><label htmlFor="duration">目标时长</label>
              <select id="duration" value={duration} onChange={(event) => setDuration(event.target.value)}>
                <option value="30">30 秒</option><option value="60">60 秒</option>
                <option value="90">90 秒</option><option value="120">120 秒</option></select></div></div>
          <button className="primary-button" type="submit" disabled={sending || Boolean(active) || !online}>
            {sending ? "正在提交…" : active ? "演示进行中" : "生成演示 ↗"}</button>
        </form>
        <p className="fine-print">仅用于你获授权访问的站点。模型规划需要配置后端模型。未验证的结果不会生成成功视频。</p>
      </aside>
      <div className="results-column">
        <section className="panel progress-panel">
          <div className="panel-title"><span>02</span><h2>运行进度</h2>
            {job && <strong className={`job-state state-${job.status.toLowerCase()}`}>{job.status}</strong>}</div>
          <div className="phase-track">{stages.map((name, index) => <div key={name}
            className={`phase ${index <= phase ? "phase-active" : ""}`}>
            <span>{String(index + 1).padStart(2, "0")}</span><strong>{name}</strong></div>)}</div>
          <p className="current-message">{job?.message ?? "等待创建任务。先描述你想讲述的产品故事。"}</p>
          {error && <p className="error-message" role="alert">{error}</p>}
          {job?.status === "AWAITING_APPROVAL" && <div className="approval-box">
            <h3>执行前需要你的批准</h3><p>请先检查 DemoSpec 和以下具名风险。这次批准不会用于以后的运行。</p>
            <ul>{job.safety_findings.map((item) => <li key={`${item.scene_id}/${item.action_id}`}>
              {item.scene_id} / {item.action_id}：{item.description}</li>)}</ul>
            <button type="button" onClick={() => { void approve(); }} disabled={sending}>我已审核，批准这一次执行</button>
          </div>}
        </section>
        <section className="panel live-panel">
          <div className="panel-title"><span>03</span><h2>实时浏览器</h2><small>{job?.status === "EXECUTING" ? "LIVE" : "PREVIEW"}</small></div>
          <div className="live-layout"><div className="browser-frame">
            <div className="browser-chrome"><i /><i /><i /><span>{spec?.source_url ?? "等待浏览器启动"}</span></div>
            {job && job.preview_revision > 0
              ? <img alt="浏览器执行实时预览" src={`${api}/jobs/${job.id}/preview?v=${job.preview_revision}`} />
              : <div className="preview-placeholder"><span>◎</span><strong>浏览器画面将在这里出现</strong>
                <small>每完成一个操作，都会更新一次预览</small></div>}
          </div><div className="event-feed"><h3>执行事件</h3>
            {events.length ? [...events].reverse().slice(0, 12).map((item) => <div className="event-item" key={item.sequence}>
              <span>{String(item.sequence).padStart(2, "0")}</span><strong>{eventText(item)}</strong>
              <em>{item.status}</em></div>) : <p>等待规划和操作事件…</p>}</div></div>
        </section>
        <section className="panel details-panel">
          <div className="panel-title"><span>04</span><h2>计划与证据</h2></div>
          <div className="tabs" role="tablist" aria-label="演示详情">{(["scenes", "verification", "spec"] as Tab[])
            .map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item}
              onClick={() => setTab(item)}>{item === "scenes" ? "场景" : item === "verification" ? "验证" : "DemoSpec"}</button>)}</div>
          {tab === "scenes" && <div className="scene-list">{spec?.scenes.map((scene, index) =>
            <article className="scene-card" key={scene.id}><small>SCENE {String(index + 1).padStart(2, "0")}</small>
              <h3>{scene.title}</h3><p>{scene.goal}</p><span>{scene.actions.length} 个操作 · {scene.assertions.length} 项断言</span>
            </article>) ?? <p className="empty-copy">规划完成后，场景会显示在这里。</p>}</div>}
          {tab === "verification" && <div className="verification-list">{report ? <>
            <p>验证状态：<strong>{report.verification_status}</strong></p>
            {report.scene_results.map((scene) => <article className="verification-card" key={scene.scene_id}>
              <h3>{scene.scene_id} <span>{scene.status}</span></h3>{scene.reason && <p>{scene.reason}</p>}
              {scene.assertion_results.map((item) => <div key={item.assertion_id}>
                <span>{item.assertion_id}</span><strong>{item.status}</strong>
                {item.evidence && <small>预期 {JSON.stringify(item.evidence.expected)} · 观察 {JSON.stringify(item.evidence.observed)}</small>}
                {item.reason && <small>{item.reason}</small>}</div>)}
            </article>)}{report.artifact_warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
          </> : <p className="empty-copy">执行结束后，这里会展示逐场景的验证结果。</p>}</div>}
          {tab === "spec" && (spec ? <pre className="spec-json">{JSON.stringify(spec, null, 2)}</pre>
            : <p className="empty-copy">尚无 DemoSpec。</p>)}
        </section>
        {videoReady && job && <section className="panel delivery-panel">
          <div className="panel-title"><span>05</span><h2>演示视频</h2><small>✓ 已验证</small></div>
          <video controls playsInline src={`${api}/jobs/${job.id}/video`} />
          <a href={`${api}/jobs/${job.id}/video`} download={`proofdemo-${job.id}.mp4`}>下载 MP4 ↗</a>
        </section>}
      </div>
    </div>
    <footer><span>PROOFDEMO · EVIDENCE BEFORE POLISH</span><span>本地工作台 · 未启用云端账号</span></footer>
  </main>;
}
