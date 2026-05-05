"use client";
import { useState, useCallback, useEffect } from "react";
import {
  Upload, FileSpreadsheet, CheckCircle, Loader2,
  X, History, SkipForward, Search,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

const SEO_MODES = [
  { value: "standard",   label: "Standard",   desc: "Balanced keyword density" },
  { value: "aggressive", label: "Aggressive",  desc: "Max keyword integration + PAA" },
  { value: "minimal",    label: "Minimal",     desc: "Light SEO — brand voice first" },
];

const STEPS = [
  { key: "upload",     label: "Uploading to S3",      desc: "Secure upload to Bronze layer" },
  { key: "ingestion",  label: "Parsing Excel",         desc: "Extracting tour rows from sheets" },
  { key: "seo",        label: "SEO Intelligence",      desc: "DataForSEO keyword fetch + cache" },
  { key: "generation", label: "Content Generation",    desc: "LLM rewrite via LangGraph" },
  { key: "validation", label: "Brand Validation",      desc: "29 rules + quality score check" },
  { key: "export",     label: "Export to Catalog",     desc: "Promoting approved tours to gold layer" },
];

function estimateTime(fileSizeKb: number): string {
  const estRows = Math.max(1, Math.round(fileSizeKb / 8));
  const secs = 30 + estRows * 4.5;
  if (secs < 60) return `~${Math.round(secs)}s`;
  return `~${Math.round(secs / 60)} min`;
}

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/cis_api_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

interface FileEntry {
  file: File;
  status: "ready" | "uploading" | "done" | "error" | "duplicate";
  activeStep: number;
  progress: number;
  estTime: string;
  errorMsg?: string;
}

interface SourceEntry {
  id: string;
  filename: string;
  file_hash: string | null;
  file_size_kb: number | null;
  row_count: number | null;
  parsed_at: string | null;
}

function StepRow({ step, index, activeStep, progress }: {
  step: typeof STEPS[0]; index: number; activeStep: number; progress: number;
}) {
  const done   = index < activeStep;
  const active = index === activeStep;
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          background: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--border)",
          color: "white", fontWeight: 700, fontSize: 10,
          boxShadow: active ? "0 0 0 3px rgba(219,150,40,0.2)" : "none",
          transition: "all 0.3s",
        }}>
          {done ? <CheckCircle size={13} /> : active ? <Loader2 size={13} /> : index + 1}
        </div>
        {index < STEPS.length - 1 && (
          <div style={{ width: 2, height: 24, marginTop: 3,
            background: done ? "#22c55e" : "var(--border)", transition: "background 0.3s" }} />
        )}
      </div>
      <div style={{ paddingTop: 3, flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 600,
          color: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--text-muted)" }}>
          {step.label}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{step.desc}</div>
        {active && (
          <div style={{ marginTop: 5 }}>
            <div style={{ height: 3, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${progress}%`,
                background: "linear-gradient(90deg, var(--brand-gold), #f59e0b)",
                borderRadius: 2, transition: "width 0.4s ease" }} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function UploadPage() {
  const [dragOver, setDragOver]         = useState(false);
  const [files, setFiles]               = useState<FileEntry[]>([]);
  const [seoMode, setSeoMode]           = useState("standard");
  const [isRunning, setIsRunning]       = useState(false);
  const [sources, setSources]           = useState<SourceEntry[]>([]);
  const [loadingSources, setLoadingSources] = useState(false);

  // Global pipeline progress (for step tracker — tracks first active file)
  const activeFile = files.find(f => f.status === "uploading") ?? files[files.length - 1];
  const globalStep = activeFile?.activeStep ?? -1;
  const globalProg = activeFile?.progress ?? 0;

  const fetchSources = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoadingSources(true);
    try {
      const res = await fetch(`${API_URL}/v1/pipeline/sources?limit=20`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const d = await res.json();
        setSources(d.sources || []);
      }
    } catch {}
    finally { setLoadingSources(false); }
  }, []);

  useEffect(() => { fetchSources(); }, [fetchSources]);

  const addFiles = useCallback((newFiles: File[]) => {
    const xlsx = newFiles.filter(f => f.name.match(/\.xlsx?$/i));
    const entries: FileEntry[] = xlsx.map(f => ({
      file: f,
      status: "ready",
      activeStep: -1,
      progress: 0,
      estTime: estimateTime(f.size / 1024),
    }));
    setFiles(prev => {
      // Deduplicate by name
      const existing = new Set(prev.map(e => e.file.name));
      return [...prev, ...entries.filter(e => !existing.has(e.file.name))];
    });
  }, []);

  const updateFile = (index: number, patch: Partial<FileEntry>) => {
    setFiles(prev => prev.map((f, i) => i === index ? { ...f, ...patch } : f));
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    addFiles(Array.from(e.dataTransfer.files));
  }, [addFiles]);

  const uploadSingleFile = async (entry: FileEntry, index: number, token: string) => {
    updateFile(index, { status: "uploading", activeStep: 0, progress: 10 });

    // Step 0: get presigned URL
    const urlRes = await fetch(`${API_URL}/v1/pipeline/upload-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        filename: entry.file.name,
        content_type: entry.file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        seo_mode: seoMode,
      }),
    });
    if (!urlRes.ok) throw new Error("Failed to get upload URL");
    const { upload_url } = await urlRes.json();
    updateFile(index, { progress: 50 });

    // Upload to S3
    const uploadRes = await fetch(upload_url, {
      method: "PUT",
      headers: { "Content-Type": entry.file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      body: entry.file,
    });
    if (!uploadRes.ok) throw new Error("S3 upload failed");
    updateFile(index, { activeStep: 0, progress: 100 });

    // Wait for Lambda ingestion (~4s)
    await new Promise(r => setTimeout(r, 4000));

    // Check dedup
    try {
      const srcRes = await fetch(`${API_URL}/v1/pipeline/sources?limit=1`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (srcRes.ok) {
        const srcData = await srcRes.json();
        const latest: SourceEntry | undefined = srcData.sources?.[0];
        if (latest && latest.filename === entry.file.name && latest.parsed_at) {
          const age = Date.now() - new Date(latest.parsed_at).getTime();
          if (age > 15000) {
            updateFile(index, { status: "duplicate", activeStep: STEPS.length });
            return;
          }
        }
      }
    } catch {}

    // Simulate remaining pipeline steps
    const stepDurations = [5000, 5000, 30000, 10000, 8000];
    for (let s = 1; s < STEPS.length; s++) {
      updateFile(index, { activeStep: s, progress: 0 });
      const duration = stepDurations[s - 1] || 10000;
      const tick = 400;
      const ticks = duration / tick;
      for (let p = 0; p <= ticks; p++) {
        await new Promise(r => setTimeout(r, tick));
        updateFile(index, { progress: Math.min(95, Math.round((p / ticks) * 100)) });
      }
      updateFile(index, { progress: 100 });
    }

    updateFile(index, { status: "done", activeStep: STEPS.length, progress: 100 });
  };

  const runPipeline = async () => {
    const readyFiles = files.filter(f => f.status === "ready");
    if (readyFiles.length === 0 || isRunning) return;
    const token = getToken();
    if (!token) return;

    setIsRunning(true);
    try {
      // Upload all files in parallel
      await Promise.all(
        files.map((entry, index) =>
          entry.status === "ready"
            ? uploadSingleFile(entry, index, token).catch(err => {
                updateFile(index, { status: "error", errorMsg: err.message });
              })
            : Promise.resolve()
        )
      );
      await fetchSources();
    } finally {
      setIsRunning(false);
    }
  };

  const readyCount    = files.filter(f => f.status === "ready").length;
  const doneCount     = files.filter(f => f.status === "done").length;
  const allDone       = files.length > 0 && files.every(f => ["done","error","duplicate"].includes(f.status));
  const canRun        = readyCount > 0 && !isRunning;

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
          Upload Tour Content
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
          Upload supplier Excel files {"\u2192"} AI pipeline rewrites to Adventure Asia brand standards
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* LEFT — dropzone + config + file list */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* SEO Mode */}
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)",
              textTransform: "uppercase", letterSpacing: 1, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
              <Search size={12} /> SEO Mode
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {SEO_MODES.map(m => (
                <button key={m.value} onClick={() => setSeoMode(m.value)}
                  style={{
                    flex: 1, padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                    border: `1px solid ${seoMode === m.value ? "var(--brand-gold)" : "var(--border)"}`,
                    background: seoMode === m.value ? "rgba(219,150,40,0.08)" : "var(--bg-primary)",
                    color: seoMode === m.value ? "var(--brand-gold)" : "var(--text-muted)",
                    fontSize: 12, fontWeight: seoMode === m.value ? 700 : 400,
                    textAlign: "left" as const, transition: "all 0.15s",
                  }}>
                  <div style={{ fontWeight: 600 }}>{m.label}</div>
                  <div style={{ fontSize: 10, marginTop: 2, opacity: 0.8 }}>{m.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Dropzone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("file-input")?.click()}
            style={{
              border: `2px dashed ${dragOver ? "var(--brand-gold)" : "var(--border)"}`,
              borderRadius: 12, padding: "28px 20px", textAlign: "center",
              background: dragOver ? "rgba(219,150,40,0.06)" : "var(--bg-card)",
              cursor: "pointer", transition: "all 0.2s",
            }}>
            <input id="file-input" type="file" style={{ display: "none" }}
              accept=".xlsx,.xls" multiple
              onChange={e => e.target.files && addFiles(Array.from(e.target.files))} />
            <FileSpreadsheet size={32} style={{ color: "var(--text-muted)", margin: "0 auto 10px" }} />
            <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: 14 }}>
              Drop Excel files here
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 4 }}>
              .xlsx or .xls {"\u00B7"} Multiple files supported
            </div>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 14,
              padding: "7px 18px", background: "var(--brand-gold)", borderRadius: 8,
              color: "white", fontSize: 13, fontWeight: 600 }}>
              <Upload size={13} /> Browse Files
            </div>
          </div>

          {/* File list */}
          {files.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {files.map((f, i) => {
                const kb = (f.file.size / 1024).toFixed(0);
                const statusColor = f.status === "done" ? "#22c55e"
                  : f.status === "error" ? "#ef4444"
                  : f.status === "duplicate" ? "#f59e0b"
                  : "var(--text-muted)";
                const statusLabel = f.status === "done" ? "Done"
                  : f.status === "error" ? (f.errorMsg || "Error")
                  : f.status === "duplicate" ? "Duplicate — skipped"
                  : f.status === "uploading" ? "Processing..."
                  : `Ready ${f.estTime}`;
                return (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 10,
                    background: "var(--bg-card)", border: "1px solid var(--border)",
                    borderRadius: 8, padding: "9px 12px" }}>
                    <FileSpreadsheet size={15} style={{ color: "#22c55e", flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, color: "var(--text-primary)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {f.file.name}
                      </div>
                      <div style={{ fontSize: 11, color: statusColor, marginTop: 1 }}>
                        {kb} KB {"\u00B7"} {statusLabel}
                      </div>
                    </div>
                    {f.status === "done" && <CheckCircle size={14} style={{ color: "#22c55e" }} />}
                    {f.status === "duplicate" && <SkipForward size={14} style={{ color: "#f59e0b" }} />}
                    {f.status === "uploading" && <Loader2 size={14} style={{ color: "var(--brand-gold)" }} />}
                    {f.status === "ready" && !isRunning && (
                      <button onClick={e => { e.stopPropagation(); setFiles(prev => prev.filter((_, j) => j !== i)); }}
                        style={{ background: "none", border: "none", cursor: "pointer",
                          color: "var(--text-muted)", padding: 2, display: "flex" }}>
                        <X size={13} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Run button */}
          <button onClick={runPipeline} disabled={!canRun}
            style={{
              padding: "11px 20px", borderRadius: 10, border: "none",
              fontWeight: 700, fontSize: 14, cursor: canRun ? "pointer" : "not-allowed",
              background: allDone ? "#22c55e" : canRun ? "var(--brand-gold)" : "var(--border)",
              color: canRun || allDone ? "white" : "var(--text-muted)",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              transition: "all 0.2s",
            }}>
            {isRunning
              ? <><Loader2 size={15} /> Processing {files.filter(f => f.status === "uploading").length} file(s)...</>
              : allDone
              ? <><CheckCircle size={15} /> Complete — {doneCount} file(s) processed</>
              : <>Start Pipeline {"\u00B7"} {readyCount} file{readyCount !== 1 ? "s" : ""} {"\u00B7"} SEO: {seoMode}</>
            }
          </button>
        </div>

        {/* RIGHT — Pipeline step tracker */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: 22 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)",
            textTransform: "uppercase", letterSpacing: 1, marginBottom: 20 }}>
            Pipeline Progress
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {STEPS.map((step, i) => (
              <StepRow key={step.key} step={step} index={i} activeStep={globalStep} progress={globalProg} />
            ))}
          </div>

          {allDone && doneCount > 0 && (
            <div style={{ marginTop: 20, padding: 14,
              background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8,
                color: "#22c55e", fontWeight: 600, fontSize: 13 }}>
                <CheckCircle size={15} /> Pipeline running in background
              </div>
              <div style={{ fontSize: 12, color: "#16a34a", marginTop: 5 }}>
                Tours will appear in Catalog when processing completes (~2-3 min)
              </div>
              <a href="/catalog" style={{ display: "inline-block", marginTop: 10,
                padding: "6px 14px", background: "var(--brand-gold)", borderRadius: 6,
                color: "white", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
                Go to Catalog {"\u2192"}
              </a>
            </div>
          )}

          {globalStep === -1 && (
            <div style={{ marginTop: 14, padding: 14, background: "var(--bg-primary)", borderRadius: 10 }}>
              <p style={{ fontSize: 12, color: "var(--text-muted)", margin: 0, lineHeight: 1.6 }}>
                Select SEO mode, upload Excel files, then click
                <strong style={{ color: "var(--brand-gold)" }}> Start Pipeline</strong>.
                Multiple files are processed in parallel.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Upload History */}
      <div style={{ marginTop: 32 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <History size={15} style={{ color: "var(--text-secondary)" }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)",
              textTransform: "uppercase", letterSpacing: 1 }}>Upload History</span>
          </div>
          <button onClick={fetchSources} disabled={loadingSources}
            style={{ fontSize: 12, color: "var(--brand-gold)", background: "none",
              border: "none", cursor: "pointer", opacity: loadingSources ? 0.5 : 1 }}>
            {loadingSources ? "Refreshing..." : "\u21BB Refresh"}
          </button>
        </div>

        {sources.length === 0 ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: 13,
            background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12 }}>
            No uploads yet
          </div>
        ) : (
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)",
            borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-primary)" }}>
                  {["Filename", "Rows", "Size", "Hash", "Uploaded"].map(h => (
                    <th key={h} style={{ padding: "9px 14px", textAlign: "left", fontSize: 11,
                      color: "var(--text-muted)", fontWeight: 600,
                      textTransform: "uppercase", letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sources.map((s, i) => (
                  <tr key={s.id}
                    style={{ borderBottom: i < sources.length - 1 ? "1px solid var(--border)" : "none" }}
                    onMouseEnter={e => (e.currentTarget.style.background = "var(--bg-primary)")}
                    onMouseLeave={e => (e.currentTarget.style.background = "transparent")}>
                    <td style={{ padding: "9px 14px", color: "var(--text-primary)", fontWeight: 500 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <FileSpreadsheet size={13} style={{ color: "#22c55e", flexShrink: 0 }} />
                        <span style={{ maxWidth: 200, overflow: "hidden",
                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.filename}</span>
                      </div>
                    </td>
                    <td style={{ padding: "9px 14px", color: "var(--text-secondary)" }}>
                      {s.row_count ?? "\u2014"}
                    </td>
                    <td style={{ padding: "9px 14px", color: "var(--text-secondary)" }}>
                      {s.file_size_kb ? `${s.file_size_kb} KB` : "\u2014"}
                    </td>
                    <td style={{ padding: "9px 14px" }}>
                      {s.file_hash
                        ? <span style={{ fontFamily: "monospace", fontSize: 11,
                            background: "var(--bg-primary)", padding: "2px 6px",
                            borderRadius: 4, color: "var(--text-muted)" }}>
                            {s.file_hash.slice(0, 12)}...
                          </span>
                        : <span style={{ color: "var(--text-muted)" }}>\u2014</span>}
                    </td>
                    <td style={{ padding: "9px 14px", color: "var(--text-muted)", fontSize: 12 }}>
                      {s.parsed_at ? new Date(s.parsed_at).toLocaleString("en-GB", {
                        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                      }) : "\u2014"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
