import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  FileText,
  UploadCloud,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Languages,
  Layers,
  ShieldCheck,
  BookOpen,
  Download,
  X,
  Loader2,
  Link2,
  ZoomIn,
  ZoomOut,
  Settings2,
  AlertCircle,
  Check,
  RotateCcw,
  Search,
} from "lucide-react";
import "./index.css";

type Model = { id: string; name: string; provider: string };
type Block = {
  id: string;
  text: string;
  translation: string;
  status: string;
  bbox: number[];
  reason?: string;
};
type Page = {
  page: number;
  width: number;
  height: number;
  orig_img: string;
  trans_img: string;
  blocks: Block[];
};
type Result = {
  pages: Page[];
  translated_pdf?: string;
  bilingual_pdf?: string;
  native_file?: string;
  report: string;
  warnings: string[];
};
type Task = {
  task_id: string;
  filename: string;
  stage: string;
  percent: number;
  message: string;
  result?: Result;
  created_at: number;
};
const stages = ["解析文档", "理解版面", "AI 翻译", "重建排版"];
async function api(path: string, init?: RequestInit) {
  const response = await fetch(path, init);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}
function SamplePaper({ chinese = false }: { chinese?: boolean }) {
  return (
    <article className="sample-paper">
      <div className="paper-journal">
        DOCUMENT INTELLIGENCE · READING SAMPLE
      </div>
      <h2>
        {chinese
          ? "跨越语言，保持知识的原貌"
          : "Beyond language.\nWithin the original."}
      </h2>
      <div className="paper-authors">TranslatorHelper Research · 2026</div>
      <div className="paper-rule" />
      <h4>{chinese ? "摘要" : "Abstract"}</h4>
      <p>
        {chinese
          ? "好的翻译，让思想自由流动，也让文档保留原有的样子。我们将文档理解与版面重建结合，让阅读无需在语言与格式之间妥协。"
          : "Good translation makes ideas travel, while keeping the document familiar. By bringing document understanding and layout reconstruction together, we make knowledge more accessible."}
      </p>
      <div className="paper-columns">
        <section>
          <h4>{chinese ? "1  文档结构" : "1  Document structure"}</h4>
          <p>
            {chinese
              ? "标题、段落与注释都有自己的位置。通过分析页面上的文字坐标，译文可以回到原本属于它的地方。"
              : "Headings, paragraphs and annotations each have a place. By analyzing the coordinates of text on a page, translations return to where they belong."}
          </p>
          <div className="paper-chart">
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </div>
          <small>
            {chinese
              ? "图 1. 结构化文档示意"
              : "Figure 1. Structured document illustration"}
          </small>
        </section>
        <section>
          <h4>{chinese ? "2  保留上下文" : "2  Preserving context"}</h4>
          <p>
            {chinese
              ? "插图与公式承载着文字之外的信息。原始视觉元素得到保留，读者可以在左右两栏中同步理解完整内容。"
              : "Figures and equations carry meaning beyond words. Original visual elements are preserved, helping readers follow the complete context in parallel."}
          </p>
          <div className="paper-equation">
            Attention(Q, K, V)
            <br />= softmax(QKᵀ / √dₖ)V
          </div>
          <p>
            {chinese
              ? "让每一页，都与原文相对应。"
              : "Every page stays connected to its source."}
          </p>
        </section>
      </div>
      <footer>
        TRANSLATORHELPER <span>01</span>
      </footer>
    </article>
  );
}
export default function App() {
  const [models, setModels] = useState<Model[]>([]),
    [model, setModel] = useState("qwen3.7-flash");
  const [custom, setCustom] = useState(""),
    [mode, setMode] = useState("academic");
  const [file, setFile] = useState<File | null>(null),
    [task, setTask] = useState<Task | null>(null),
    [history, setHistory] = useState<Task[]>([]);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [drag, setDrag] = useState(false),
    [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(100),
    [sync, setSync] = useState(true),
    [textView, setTextView] = useState(false),
    [query, setQuery] = useState("");
  const [tab, setTab] = useState("workspace"),
    [settings, setSettings] = useState(false),
    [glossary, setGlossary] = useState("");
  const [config, setConfig] = useState({
    has_default_key: false,
    authorized: true,
    ocr_available: false,
    office_preview_available: false,
  });
  const [access, setAccess] = useState(""),
    [connected, setConnected] = useState(""),
    [testing, setTesting] = useState(false),
    [downloading, setDownloading] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null),
    left = useRef<HTMLDivElement>(null),
    right = useRef<HTMLDivElement>(null),
    scrollLock = useRef(false);
  const result = task?.result,
    current = result?.pages[page];
  const refresh = () =>
    api("/api/tasks")
      .then(setHistory)
      .catch(() => {});
  useEffect(() => {
    api("/api/config")
      .then((c) => {
        setModels(c.models);
        setModel(c.default_model);
        setConfig(c);
        if (!c.authorized) setSettings(true);
        refresh();
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!task || ["completed", "failed", "cancelled"].includes(task.stage))
      return;
    const controller = new AbortController();
    const timer = setInterval(
      () =>
        api(`/api/tasks/${task.task_id}`, { signal: controller.signal })
          .then((t) => {
            setTask(t);
            if (["completed", "failed", "cancelled"].includes(t.stage)) {
              setBusy(false);
              refresh();
            }
          })
          .catch((e) => {
            if (e.name !== "AbortError") {
              setError(e.message);
              setBusy(false);
            }
          }),
      1500,
    );
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [task?.task_id, task?.stage]);

  // 稳健文件下载：通过 fetch 获取 Blob，捕获后端详细错误提示，并命名为包含原文件名的友好名称
  const handleDownload = async (url: string, label: string) => {
    try {
      setDownloading(label);
      setError("");
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `下载失败 (HTTP ${res.status})`);
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      const stem = task?.filename ? task.filename.replace(/\.[^/.]+$/, "") : "文档";
      const ext = url.split(".").pop()?.split("?")[0] || "pdf";
      let suffix = "翻译";
      if (label.includes("对照")) suffix = "双栏对照(左原件·右中文)";
      else if (label.includes("无痕") || label.includes("中文")) suffix = "中文无痕";
      else if (label.includes("原格式")) suffix = "原格式译文";
      else if (label.includes("质量报告")) suffix = "质量报告";
      a.download = `${stem}_${suffix}.${ext}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
    } catch (e: any) {
      setError(e.message || "下载失败，请刷新页面或重试");
    } finally {
      setDownloading(null);
    }
  };

  function choose(f?: File) {
    if (!f) return;
    if (!/\.(pdf|png|jpe?g|docx|pptx|xlsx)$/i.test(f.name)) {
      setError("请上传 PDF、PNG、JPG、DOCX、PPTX 或 XLSX 文件");
      return;
    }
    if (f.size > 50 * 1024 * 1024) {
      setError("文件不能超过 50 MB");
      return;
    }
    setFile(f);
    setError("");
  }
  async function translate() {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setPage(0);
    try {
      const form = new FormData();
      form.append("file", file);
      const upload = await api("/api/files", { method: "POST", body: form });
      const t = await api("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_id: upload.file_id,
          model: model === "custom" ? custom : model,
          mode,
          glossary,
        }),
      });
      setTask(t);
      setTab("workspace");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  function synchronize(source: HTMLDivElement, target: HTMLDivElement | null) {
    if (!sync || !target || scrollLock.current) return;
    scrollLock.current = true;
    target.scrollTop =
      (source.scrollTop /
        Math.max(1, source.scrollHeight - source.clientHeight)) *
      (target.scrollHeight - target.clientHeight);
    target.scrollLeft =
      (source.scrollLeft /
        Math.max(1, source.scrollWidth - source.clientWidth)) *
      (target.scrollWidth - target.clientWidth);
    requestAnimationFrame(() => {
      scrollLock.current = false;
    });
  }
  const shownBlocks =
    current?.blocks.filter(
      (b) =>
        !query ||
        `${b.text} ${b.translation}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    ) || [];
  return (
    <div className="app">
      <header className="topbar">
        <a href="/" className="brand">
          <span className="brand-icon">
            <Languages size={21} />
          </span>
          译页<span className="brand-en">TranslatorHelper</span>
          <sup>2.0</sup>
        </a>
        <nav>
          <button
            className={tab === "workspace" ? "active" : ""}
            onClick={() => setTab("workspace")}
          >
            翻译工作台
          </button>
          <button
            className={tab === "history" ? "active" : ""}
            onClick={() => {
              setTab("history");
              refresh();
            }}
          >
            我的文档
          </button>
        </nav>
        <button className="settings-link" onClick={() => setSettings(true)}>
          <Settings2 size={16} /> 模型设置
        </button>
        <span className="avatar">译</span>
      </header>
      <main>
        <div className="intro">
          <div>
            <div className="eyebrow">
              <span /> DOCUMENT TRANSLATION, REIMAGINED
            </div>
            <h1>
              读懂世界，<em>原貌呈现。</em>
            </h1>
            <p>让语言改变，让排版留下。你的 AI 文档翻译工作台。</p>
          </div>
          <div className="intro-note">
            <Layers size={20} />
            <span>
              文字在原位，理解更进一步
              <br />
              <small>原始版面 · 中英对照 · 多模型支持</small>
            </span>
          </div>
        </div>
        {error && (
          <div className="alert" role="alert">
            <AlertCircle size={17} />
            {error}
            <button aria-label="关闭错误" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {tab === "history" ? (
          <section className="history panel">
            <div className="section-title">
              <h2>我的文档</h2>
              <span>当前浏览器的翻译记录</span>
            </div>
            {history.length === 0 ? (
              <div className="empty-history">
                <BookOpen size={38} />
                <h3>你的下一次阅读，从这里开始</h3>
                <p>上传第一份文档后，翻译记录会显示在这里。</p>
                <button className="primary" onClick={() => setTab("workspace")}>
                  翻译文档 <ArrowRight size={16} />
                </button>
              </div>
            ) : (
              history.map((t) => (
                <button
                  className="history-row"
                  key={t.task_id}
                  onClick={() => {
                    setTask(t);
                    setPage(0);
                    setBusy(
                      !["completed", "failed", "cancelled"].includes(t.stage),
                    );
                    setTab("workspace");
                  }}
                >
                  <FileText size={23} />
                  <span>
                    <strong>{t.filename}</strong>
                    <small>
                      {new Date(t.created_at * 1000).toLocaleString("zh-CN")}
                    </small>
                  </span>
                  <span className={`status ${t.stage}`}>
                    {t.stage === "completed"
                      ? "翻译完成"
                      : t.stage === "failed"
                        ? "处理失败"
                        : t.stage === "cancelled"
                          ? "已取消"
                          : `${t.percent}%`}
                  </span>
                  <ArrowUpRight size={18} />
                </button>
              ))
            )}
          </section>
        ) : (
          <div className="workspace">
            <aside className="sidebar">
              <section className="panel upload-panel">
                <div className="section-title">
                  <h2>开始新的翻译</h2>
                  <span className="step-tag">01 — 03</span>
                </div>
                <label className="field-label">
                  01 <span>上传文档</span>
                </label>
                <button
                  className={`dropzone ${drag ? "drag" : ""} ${file ? "selected" : ""}`}
                  disabled={busy}
                  onClick={() => input.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    if (!busy) choose(e.dataTransfer.files[0]);
                  }}
                >
                  <span className="upload-icon">
                    {file ? <FileText size={27} /> : <UploadCloud size={27} />}
                  </span>
                  <strong>{file ? file.name : "将文档拖放到这里"}</strong>
                  <span>
                    {file ? (
                      `${(file.size / 1024 / 1024).toFixed(2)} MB · 点击重新选择`
                    ) : (
                      <>
                        或 <b>点击选择文件</b>
                      </>
                    )}
                  </span>
                  <small>
                    PDF · Word · PPT · Excel · 图片
                    <br />
                    单个文件最大 50 MB
                  </small>
                </button>
                <input
                  ref={input}
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.docx,.pptx,.xlsx"
                  hidden
                  onChange={(e) => choose(e.target.files?.[0])}
                />
                <label className="field-label">
                  02 <span>翻译语言</span>
                </label>
                <div className="language-pair">
                  <span>
                    英语 <small>EN</small>
                  </span>
                  <ArrowRight size={16} />
                  <span>
                    简体中文 <small>ZH</small>
                  </span>
                </div>
                <label className="field-label" htmlFor="model">
                  03 <span>选择翻译模型</span>
                </label>
                <div className="select-wrap">
                  <span className="model-symbol">✳</span>
                  <select
                    id="model"
                    value={model}
                    disabled={busy}
                    onChange={(e) => {
                      setModel(e.target.value);
                      setConnected("");
                    }}
                  >
                    {Array.from(new Set(models.map((m) => m.provider))).map(
                      (provider) => (
                        <optgroup key={provider} label={provider}>
                          {models
                            .filter((m) => m.provider === provider)
                            .map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.name}
                              </option>
                            ))}
                        </optgroup>
                      ),
                    )}
                    <option value="custom">自定义模型 ID</option>
                  </select>
                  <ChevronDown size={14} />
                </div>
                {model === "custom" && (
                  <input
                    className="text-input"
                    aria-label="自定义模型 ID"
                    placeholder="输入服务商提供的模型 ID"
                    value={custom}
                    onChange={(e) => setCustom(e.target.value)}
                  />
                )}
                <div className="mode-selector">
                  {[
                    ["academic", "学术论文"],
                    ["courseware", "课件演示"],
                    ["general", "通用文档"],
                  ].map(([id, label]) => (
                    <button
                      key={id}
                      disabled={busy}
                      className={mode === id ? "chosen" : ""}
                      onClick={() => setMode(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <button
                  className="glossary-link"
                  onClick={() => setSettings(true)}
                >
                  <BookOpen size={14} /> 术语表与高级设置{" "}
                  <ArrowUpRight size={13} />
                </button>
                <button
                  className="primary translate-button"
                  onClick={translate}
                  disabled={
                    !file || busy || (model === "custom" && !custom.trim())
                  }
                >
                  {busy ? (
                    <>
                      <Loader2 className="spin" size={17} /> 正在处理文档
                    </>
                  ) : (
                    <>
                      开始翻译 <ArrowRight size={17} />
                    </>
                  )}
                </button>
                <p className="privacy">
                  <ShieldCheck size={13} /> 密钥仅在服务端使用
                </p>
              </section>
              <div className="note-card">
                <span className="note-icon">
                  <Layers size={17} />
                </span>
                <h3>原格式，才有完整语境。</h3>
                <p>
                  保留图表、公式与章节结构。复杂区域会标记待检查，让每一处翻译都有据可查。
                </p>
                <div>
                  <span>版面感知</span>
                  <span>公式保护</span>
                  <span>原位重排</span>
                </div>
              </div>
            </aside>
            <section className="reader panel">
              <div className="reader-heading">
                <div>
                  <span className="live-dot" />
                  <h2>{task ? task.filename : "双栏对照阅读"}</h2>
                  <span className="badge">
                    {task
                      ? task.stage === "completed"
                        ? "已完成"
                        : task.stage === "failed"
                          ? "失败"
                          : task.stage === "cancelled"
                            ? "已取消"
                            : "处理中"
                      : "排版示意"}
                  </span>
                </div>
                <button
                  className="icon-button"
                  aria-label="新文档"
                  title="新文档"
                  disabled={busy}
                  onClick={() => {
                    setTask(null);
                    setFile(null);
                    setPage(0);
                    setBusy(false);
                  }}
                >
                  <RotateCcw size={15} />
                </button>
              </div>
              {task && task.stage !== "completed" && (
                <div
                  className={`progress-box ${task.stage === "failed" ? "failed" : ""}`}
                  role="status"
                >
                  <div>
                    <strong>{task.message}</strong>
                    <span>{task.percent}%</span>
                  </div>
                  <div className="progress-track">
                    <i style={{ width: `${task.percent}%` }} />
                  </div>
                  <div className="stages">
                    {stages.map((s, i) => (
                      <span
                        key={s}
                        className={task.percent >= i * 25 ? "done" : ""}
                      >
                        {task.percent >= (i + 1) * 25 ? (
                          <Check size={12} />
                        ) : (
                          <span>{i + 1}</span>
                        )}
                        {s}
                      </span>
                    ))}
                  </div>
                  {!["failed", "cancelled"].includes(task.stage) && (
                    <button
                      className="text-button"
                      onClick={() =>
                        api(`/api/tasks/${task.task_id}/cancel`, {
                          method: "POST",
                        })
                          .then((t) => {
                            setTask(t);
                            setBusy(false);
                            refresh();
                          })
                          .catch((e) => setError(e.message))
                      }
                    >
                      取消任务
                    </button>
                  )}
                </div>
              )}
              <div className="reader-toolbar">
                <div className="view-toggle">
                  <button
                    className={!textView ? "chosen" : ""}
                    onClick={() => setTextView(false)}
                  >
                    <Layers size={14} />
                    版面对照
                  </button>
                  <button
                    className={textView ? "chosen" : ""}
                    onClick={() => setTextView(true)}
                  >
                    <FileText size={14} />
                    文本精读
                  </button>
                </div>
                <div className="reader-tools">
                  <button
                    className={sync ? "sync on" : "sync"}
                    onClick={() => setSync(!sync)}
                  >
                    <Link2 size={14} />
                    <span>同步滚动</span>
                  </button>
                  <span className="tool-divider" />
                  <button
                    aria-label="缩小"
                    disabled={zoom <= 60}
                    onClick={() => setZoom((z) => z - 10)}
                  >
                    <ZoomOut size={15} />
                  </button>
                  <span className="zoom-label">{zoom}%</span>
                  <button
                    aria-label="放大"
                    disabled={zoom >= 200}
                    onClick={() => setZoom((z) => z + 10)}
                  >
                    <ZoomIn size={15} />
                  </button>
                </div>
              </div>
              {textView && current && (
                <div className="search-bar">
                  <Search size={14} />
                  <input
                    aria-label="搜索当前页"
                    placeholder="搜索当前页原文或译文…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
              )}
              <div className="column-labels">
                <span>
                  <i />
                  英文原文 <small>ORIGINAL</small>
                </span>
                <span>
                  <i />
                  中文译文 <small>TRANSLATION</small>
                  {!result && <b>示例 · 非翻译结果</b>}
                </span>
              </div>
              {result && !result.pages.length ? (
                <div className="empty-preview">
                  <FileText size={38} />
                  <h3>原格式译文已生成</h3>
                  <p>
                    此环境暂不能生成 Office
                    页面预览，请下载下方原格式译文和质量报告。
                  </p>
                </div>
              ) : (
                <div className="reader-columns">
                  {[false, true].map((translated, i) => (
                    <div
                      key={i}
                      className="page-scroll"
                      ref={translated ? right : left}
                      onScroll={(e) =>
                        synchronize(
                          e.currentTarget,
                          translated ? left.current : right.current,
                        )
                      }
                    >
                      {textView && current ? (
                        <div
                          className="text-page"
                          style={{ fontSize: `${zoom}%` }}
                        >
                          {shownBlocks.map((b) => (
                            <div
                              className={`text-block ${b.status}`}
                              key={b.id}
                            >
                              <small>
                                {b.id}
                                {translated && b.reason ? ` · ${b.reason}` : ""}
                              </small>
                              <p>
                                {translated ? b.translation || b.text : b.text}
                              </p>
                            </div>
                          ))}
                          {!shownBlocks.length && <p>当前页没有匹配的文字。</p>}
                        </div>
                      ) : (
                        <div
                          className="page-scale"
                          style={{ width: `${zoom}%` }}
                        >
                          {current ? (
                            <img
                              className="document-page"
                              src={
                                translated
                                  ? current.trans_img
                                  : current.orig_img
                              }
                              alt={`${translated ? "译文" : "原文"}第 ${page + 1} 页`}
                            />
                          ) : (
                            <SamplePaper chinese={translated} />
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
              <div className="reader-bottom">
                <span>
                  <ShieldCheck size={14} />
                  {current
                    ? `${current.blocks.filter((b) => b.status === "translated").length} 个区域已替换 · ${current.blocks.filter((b) => b.status === "review").length} 个待检查`
                    : "上传文档，即可开始逐页对照阅读"}
                </span>
                <div>
                  <button
                    aria-label="上一页"
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span>
                    {page + 1} <small>/ {result?.pages.length || 1}</small>
                  </span>
                  <button
                    aria-label="下一页"
                    disabled={!result || page >= result.pages.length - 1}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
              {result && (
                <div className="exports">
                  {[
                    [result.bilingual_pdf, "双栏对照 PDF (左原件·右中文)", true],
                    [result.translated_pdf, "中文无痕 PDF", false],
                    [result.native_file, "原格式译文", false],
                    [result.report, "质量报告", false],
                  ]
                    .filter(([url]) => url)
                    .map(([url, label, highlight]) => (
                      <button
                        key={label as string}
                        type="button"
                        className={`download-btn ${highlight ? "highlight" : ""}`}
                        disabled={downloading === (label as string)}
                        onClick={() =>
                          handleDownload(url as string, label as string)
                        }
                      >
                        {downloading === (label as string) ? (
                          <Loader2 size={14} className="spin" />
                        ) : (
                          <Download size={14} />
                        )}
                        {downloading === (label as string)
                          ? "下载中..."
                          : (label as string)}
                      </button>
                    ))}
                  {result.warnings.length > 0 && (
                    <details>
                      <summary>
                        <AlertCircle size={14} />
                        {result.warnings.length} 条质量提示
                      </summary>
                      {result.warnings.map((w, i) => (
                        <p key={i}>{w}</p>
                      ))}
                    </details>
                  )}
                </div>
              )}
            </section>
          </div>
        )}
        <footer className="app-footer">
          <span>
            译页 <span> / </span> 让知识，不止于一种语言。
          </span>
          <span>
            PDF · DOCX · PPTX · XLSX · PNG · JPG{" "}
            <span className="footer-dot">●</span> 格式感知翻译
          </span>
        </footer>
      </main>
      {settings && (
        <div className="modal-backdrop" onClick={() => setSettings(false)}>
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-label="模型与翻译设置"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="section-title">
              <h2>模型与翻译设置</h2>
              <button aria-label="关闭设置" onClick={() => setSettings(false)}>
                <X size={19} />
              </button>
            </div>
            <p>
              所有模型通过统一的千炼兼容接口调用。实际可用性以你的服务商权限为准。
            </p>
            <div className="service-state">
              <span
                className={config.has_default_key ? "live-dot" : "off-dot"}
              />
              {config.has_default_key
                ? "服务端已配置 API 密钥"
                : "服务端尚未配置 DASHSCOPE_API_KEY"}
            </div>
            {!config.authorized && (
              <>
                <label>平台访问口令</label>
                <input
                  type="password"
                  className="text-input"
                  value={access}
                  onChange={(e) => setAccess(e.target.value)}
                  placeholder="输入部署时设置的 APP_ACCESS_TOKEN"
                />
                <button
                  className="primary"
                  onClick={async () => {
                    try {
                      await api("/api/session", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ token: access }),
                      });
                      setConfig({ ...config, authorized: true });
                      setAccess("");
                      setConnected("已解锁");
                      refresh();
                    } catch (e) {
                      setConnected((e as Error).message);
                    }
                  }}
                >
                  解锁平台
                </button>
              </>
            )}
            <button
              className="secondary"
              disabled={testing || !config.authorized}
              onClick={async () => {
                setTesting(true);
                try {
                  const r = await api("/api/models/test", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      model: model === "custom" ? custom : model,
                    }),
                  });
                  setConnected(r.message);
                } catch (e) {
                  setConnected((e as Error).message);
                } finally {
                  setTesting(false);
                }
              }}
            >
              {testing ? (
                <Loader2 className="spin" size={15} />
              ) : (
                <Link2 size={15} />
              )}
              测试当前模型连接
            </button>
            {connected && <p role="status">{connected}</p>}
            <label htmlFor="glossary">
              术语表 <small>每行一个：英文 = 中文</small>
            </label>
            <textarea
              id="glossary"
              placeholder={
                "attention = 注意力\nlarge language model = 大语言模型"
              }
              rows={5}
              maxLength={8000}
              value={glossary}
              onChange={(e) => setGlossary(e.target.value)}
            />
            <div className="capabilities">
              <span>
                本地 OCR：{config.ocr_available ? "可用" : "未安装 Tesseract"}
              </span>
              <span>
                Office 预览：
                {config.office_preview_available
                  ? "可用"
                  : "需安装 LibreOffice"}
              </span>
            </div>
            <button className="primary" onClick={() => setSettings(false)}>
              完成设置 <Check size={16} />
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
