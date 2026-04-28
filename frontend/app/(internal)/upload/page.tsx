"use client";
import { useState, useCallback } from "react";
import {
  Upload, FileSpreadsheet, CheckCircle, Loader2,
  X, ChevronDown, Globe, Building2,
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

const VENDORS = [
  "Exo Travel", "Asia Trails", "Diethelm Travel",
  "Buffalo Tours", "Indochina Services", "Other",
];

const MARKETS = [
  { code: "US", label: "United States" },
  { code: "UK", label: "United Kingdom" },
  { code: "AU", label: "Australia" },
  { code: "JP", label: "Japan" },
];

const STEPS = [
  { key: "upload",     en: "Uploading to S3",        desc: "Secure upload to Bronze layer" },
  { key: "ingestion",  en: "Parsing Excel",           desc: "Extracting tour rows from sheets" },
  { key: "seo",        en: "SEO Intelligence",        desc: "DataForSEO keyword fetch + cache" },
  { key: "generation", en: "Content Generation",      desc: "LLM rewrite via LangGraph" },
  { key: "validation", en: "Brand Validation",        desc: "29 rules + quality score check" },
  { key: "export",     en: "Export to Catalog",       desc: "Promoting approved tours to gold layer" },
];

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/cis_api_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

interface FileEntry {
  file: File;
  status: "ready" | "uploading" | "done" | "error";
}

function Select({ label, value, onChange, options, icon: Icon }: {
  label: string; value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  icon: any;
}) {
  return (
    <div>
      <label style={{ fontSize: 11, color: "var(--text-muted)", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
        {label}
      </label>
      <div style={{ position: "relative" }}>
        <Icon size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--text-secondary)" }} />
        <select value={value} onChange={e => onChange(e.target.value)} style={{
          width: "100%", padding: "9px 32px 9px 34px",
          background: "var(--bg-primary)", border: "1px solid var(--border)",
          borderRadius: 8, color: "var(--text-primary)", fontSize: 13,
          appearance: "none", cursor: "pointer",
        }}>
          <option value="">Select {label}...</option>
          {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <ChevronDown size={14} style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-secondary)", pointerEvents: "none" }} />
      </div>
    </div>
  );
}

function StepRow({ step, index, activeStep, progress }: {
  step: typeof STEPS[0]; index: number; activeStep: number; progress: number;
}) {
  const done   = index < activeStep;
  const active = index === activeStep;
  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 32, height: 32, borderRadius: "50%",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--border)",
          color: "white", fontWeight: 700, fontSize: 12,
          boxShadow: active ? "0 0 0 4px rgba(219,150,40,0.2)" : "none",
          transition: "all 0.3s",
        }}>
          {done ? <CheckCircle size={16} /> : active ? <Loader2 size={16} /> : index + 1}
        </div>
        {index < STEPS.length - 1 && (
          <div style={{ width: 2, height: 36, marginTop: 4, background: done ? "#22c55e" : "var(--border)", transition: "background 0.3s" }} />
        )}
      </div>
      <div style={{ paddingTop: 6, flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--text-muted)" }}>
          {step.en}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{step.desc}</div>
        {active && (
          <div style={{ marginTop: 8 }}>
            <div style={{ height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${progress}%`, background: "linear-gradient(90deg, var(--brand-gold), #f59e0b)", borderRadius: 2, transition: "width 0.4s ease" }} />
            </div>
            <div style={{ fontSize: 11, color: "var(--brand-gold)", marginTop: 4 }}>{progress}% complete</div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function UploadPage() {
  const [dragOver, setDragOver]     = useState(false);
  const [files, setFiles]           = useState<FileEntry[]>([]);
  const [vendor, setVendor]         = useState("");
  const [market, setMarket]         = useState("");
  const [activeStep, setActiveStep] = useState(-1);
  const [stepProgress, setProgress] = useState(0);
  const [isRunning, setIsRunning]   = useState(false);
  const [allDone, setAllDone]       = useState(false);
  const [error, setError]           = useState("");
  const [executionArn, setExecArn]  = useState("");
  const [toursProcessed, setTours]  = useState<number | null>(null);

  const addFiles = useCallback(async (newFiles: File[]) => {
    const xlsx = newFiles.filter(f => f.name.match(/\.xlsx?$/i));
    setFiles(prev => [...prev, ...xlsx.map(f => ({ file: f, status: "ready" as const }))]);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    addFiles(Array.from(e.dataTransfer.files));
  }, [addFiles]);

  const canRun = files.length > 0 && vendor && market && !isRunning && !allDone;

  const runPipeline = async () => {
    if (!canRun) return;
    const token = getToken();
    if (!token) { setError("Not authenticated — please login again"); return; }

    setIsRunning(true); setAllDone(false); setError("");

    try {
      // Step 0: Upload file to S3
      setActiveStep(0); setProgress(10);
      const file = files[0].file;

      // Get presigned URL
      const urlRes = await fetch(`${API_URL}/v1/pipeline/upload-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ filename: file.name, content_type: file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
      });
      if (!urlRes.ok) throw new Error("Failed to get upload URL");
      const { upload_url, s3_key } = await urlRes.json();
      setProgress(40);

      // Upload to S3
      const uploadRes = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
        body: file,
      });
      if (!uploadRes.ok) throw new Error("S3 upload failed");
      setProgress(100);

      // Step 1-5: Poll Step Functions (Lambda triggered by S3)
      // Wait for SF to start (~5s)
      setActiveStep(1); setProgress(0);
      await new Promise(r => setTimeout(r, 5000));

      // Poll SF status
      const SF_ARN_PREFIX = `arn:aws:states:us-west-1:867490540162:execution:aa-cis-dev-pipeline:`;
      const execName = s3_key.split("/").pop()?.replace(".xlsx", "").replace(".xls", "") || "unknown";

      // Animate remaining steps while waiting for SF
      const stepDurations = [15000, 30000, 60000, 10000]; // ms per step
      for (let i = 1; i < STEPS.length; i++) {
        setActiveStep(i); setProgress(0);
        const duration = stepDurations[i - 1] || 15000;
        const interval = 500;
        const steps = duration / interval;
        for (let p = 0; p < steps; p++) {
          await new Promise(r => setTimeout(r, interval));
          setProgress(Math.min(95, Math.round((p / steps) * 100)));

          // Check SF status every 10s after step 2
          if (i >= 2 && p % 20 === 0 && executionArn) {
            try {
              const sfRes = await fetch(`${API_URL}/v1/pipeline/execution/${encodeURIComponent(executionArn)}`, {
                headers: { Authorization: `Bearer ${token}` },
              });
              if (sfRes.ok) {
                const sfData = await sfRes.json();
                if (sfData.status === "SUCCEEDED") {
                  setTours(sfData.tours_processed);
                  setProgress(100);
                  break;
                }
              }
            } catch {}
          }
        }
        setProgress(100);
      }

      setActiveStep(STEPS.length);
      setAllDone(true);
      setFiles(prev => prev.map(f => ({ ...f, status: "done" })));
    } catch (e: any) {
      setError(e.message || "Pipeline failed");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Upload Tour Content</h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
          Upload supplier Excel files → AI pipeline rewrites to Adventure Asia brand standards
        </p>
      </div>

      {error && (
        <div style={{ padding: "12px 16px", background: "rgba(239,68,68,0.1)", border: "1px solid #ef4444", borderRadius: 8, color: "#f87171", fontSize: 13, marginBottom: 16 }}>
          ⚠ {error}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* LEFT */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>Configuration</div>
            <Select label="Supplier / Vendor" value={vendor} onChange={setVendor} icon={Building2}
              options={VENDORS.map(v => ({ value: v, label: v }))} />
            <Select label="Target Market" value={market} onChange={setMarket} icon={Globe}
              options={MARKETS.map(m => ({ value: m.code, label: `${m.label} (${m.code})` }))} />
          </div>

          <div
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => document.getElementById("file-input")?.click()}
            style={{
              border: `2px dashed ${dragOver ? "var(--brand-gold)" : "var(--border)"}`,
              borderRadius: 12, padding: "32px 24px", textAlign: "center",
              background: dragOver ? "rgba(219,150,40,0.06)" : "var(--bg-card)",
              cursor: "pointer", transition: "all 0.2s",
            }}>
            <input id="file-input" type="file" style={{ display: "none" }}
              accept=".xlsx,.xls" multiple
              onChange={e => e.target.files && addFiles(Array.from(e.target.files))} />
            <FileSpreadsheet size={36} style={{ color: "var(--text-muted)", margin: "0 auto 12px" }} />
            <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: 14 }}>Drop Excel files here</div>
            <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 4 }}>.xlsx or .xls · Multiple files supported</div>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 16, padding: "8px 20px", background: "var(--brand-gold)", borderRadius: 8, color: "white", fontSize: 13, fontWeight: 600 }}>
              <Upload size={14} /> Browse Files
            </div>
          </div>

          {files.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {files.map((f, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, padding: "10px 14px" }}>
                  <FileSpreadsheet size={16} style={{ color: "#22c55e", flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{f.file.name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>{(f.file.size / 1024).toFixed(0)} KB</div>
                  </div>
                  {f.status === "done"
                    ? <CheckCircle size={15} style={{ color: "#22c55e" }} />
                    : !isRunning && (
                      <button onClick={e => { e.stopPropagation(); setFiles(prev => prev.filter((_, j) => j !== i)); }}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 2 }}>
                        <X size={14} />
                      </button>
                    )
                  }
                </div>
              ))}
            </div>
          )}

          <button onClick={runPipeline} disabled={!canRun}
            style={{
              padding: "12px 24px", borderRadius: 10, border: "none",
              fontWeight: 700, fontSize: 14, cursor: canRun ? "pointer" : "not-allowed",
              background: allDone ? "#22c55e" : canRun ? "var(--brand-gold)" : "var(--border)",
              color: canRun || allDone ? "white" : "var(--text-muted)",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              transition: "all 0.2s",
            }}>
            {isRunning
              ? <><Loader2 size={16} /> Processing...</>
              : allDone
              ? <><CheckCircle size={16} /> Pipeline Complete{toursProcessed ? ` — ${toursProcessed} Tours` : ""}</>
              : `Start Pipeline · ${files.length} File${files.length > 1 ? "s" : ""}`
            }
          </button>
        </div>

        {/* RIGHT — Pipeline progress */}
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, padding: 24 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1, marginBottom: 24 }}>
            Pipeline Progress
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {STEPS.map((step, i) => (
              <StepRow key={step.key} step={step} index={i} activeStep={activeStep} progress={stepProgress} />
            ))}
          </div>

          {allDone && (
            <div style={{ marginTop: 24, padding: 16, background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)", borderRadius: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#22c55e", fontWeight: 600, fontSize: 13 }}>
                <CheckCircle size={16} /> File uploaded — pipeline running in background
              </div>
              <div style={{ fontSize: 12, color: "#16a34a", marginTop: 6 }}>
                Tours will appear in Catalog when processing completes (~2-3 min)
              </div>
              <a href="/catalog" style={{ display: "inline-block", marginTop: 10, padding: "6px 14px", background: "var(--brand-gold)", borderRadius: 6, color: "white", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>
                Go to Catalog →
              </a>
            </div>
          )}

          {activeStep === -1 && (
            <div style={{ marginTop: 16, padding: 16, background: "var(--bg-primary)", borderRadius: 10 }}>
              <p style={{ fontSize: 12, color: "var(--text-muted)", margin: 0, lineHeight: 1.6 }}>
                Configure vendor and market, upload Excel files, then click
                <strong style={{ color: "var(--brand-gold)" }}> Start Pipeline</strong>.
                File will be uploaded to S3 → Lambda → Step Functions automatically.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
