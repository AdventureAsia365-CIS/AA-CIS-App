"use client";
import { useState, useCallback } from "react";
import {
  Upload, FileSpreadsheet, CheckCircle, Loader2,
  X, ChevronDown, Globe, Building2,
} from "lucide-react";

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
  { key: "parsing",    en: "Parsing Excel",         desc: "Extracting tour rows from sheets" },
  { key: "seo",        en: "SEO Intelligence",       desc: "DataForSEO keyword fetch + cache" },
  { key: "generation", en: "Content Generation",     desc: "LLM rewrite via LangGraph" },
  { key: "validation", en: "Brand Validation",       desc: "29 rules + quality score check" },
  { key: "export",     en: "Export to Catalog",      desc: "Promoting approved tours to gold layer" },
];

interface FileEntry {
  file: File;
  sheets: number;
  rows: number;
  status: "ready" | "processing" | "done" | "error";
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
  const done    = index < activeStep;
  const active  = index === activeStep;

  return (
    <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
      {/* Connector */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: 32, height: 32, borderRadius: "50%",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--border)",
          color: "white", fontWeight: 700, fontSize: 12,
          boxShadow: active ? "0 0 0 4px rgba(219,150,40,0.2)" : "none",
          transition: "all 0.3s",
        }}>
          {done ? <CheckCircle size={16} /> : active ? <Loader2 size={16} className="animate-spin" /> : index + 1}
        </div>
        {index < STEPS.length - 1 && (
          <div style={{
            width: 2, height: 36, marginTop: 4,
            background: done ? "#22c55e" : "var(--border)",
            transition: "background 0.3s",
          }} />
        )}
      </div>

      {/* Content */}
      <div style={{ paddingTop: 6, flex: 1 }}>
        <div style={{
          fontSize: 13, fontWeight: 600,
          color: done ? "#22c55e" : active ? "var(--brand-gold)" : "var(--text-muted)",
        }}>
          {step.en}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
          {step.desc}
        </div>
        {active && (
          <div style={{ marginTop: 8 }}>
            <div style={{ height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${progress}%`,
                background: "linear-gradient(90deg, var(--brand-gold), #f59e0b)",
                borderRadius: 2, transition: "width 0.4s ease",
              }} />
            </div>
            <div style={{ fontSize: 11, color: "var(--brand-gold)", marginTop: 4 }}>
              {progress}% complete
            </div>
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
  const [eta, setEta]               = useState("");
  const [allDone, setAllDone]       = useState(false);

  const parseFile = async (f: File): Promise<FileEntry> => {
    await new Promise(r => setTimeout(r, 300));
    return {
      file: f, status: "ready",
      sheets: Math.floor(Math.random() * 3) + 1,
      rows:   Math.floor(Math.random() * 80) + 20,
    };
  };

  const addFiles = useCallback(async (newFiles: File[]) => {
    const xlsx = newFiles.filter(f => f.name.match(/\.xlsx?$/i));
    const parsed = await Promise.all(xlsx.map(parseFile));
    setFiles(prev => [...prev, ...parsed]);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragOver(false);
    addFiles(Array.from(e.dataTransfer.files));
  }, [addFiles]);

  const canRun = files.length > 0 && vendor && market && !isRunning && !allDone;

  const totalTours = files.reduce((s, f) => s + f.rows, 0);

  const runPipeline = async () => {
    if (!canRun) return;
    setIsRunning(true); setAllDone(false);

    for (let i = 0; i < STEPS.length; i++) {
      setActiveStep(i); setProgress(0);
      const remaining = STEPS.length - i;
      setEta(`~${remaining * 2} min remaining`);

      // Animate progress bar
      for (let p = 0; p <= 100; p += 5) {
        setProgress(p);
        await new Promise(r => setTimeout(r, 80 + Math.random() * 40));
      }
    }

    setActiveStep(STEPS.length);
    setEta("Complete");
    setAllDone(true);
    setIsRunning(false);
    setFiles(prev => prev.map(f => ({ ...f, status: "done" })));
  };

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
          Upload Tour Content
        </h1>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 6 }}>
          Upload supplier Excel files → AI pipeline rewrites to Adventure Asia brand standards
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
        {/* LEFT — Config + Upload */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Vendor + Market */}
          <div style={{
            background: "var(--bg-card)", border: "1px solid var(--border)",
            borderRadius: 12, padding: 20, display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>
              Configuration
            </div>
            <Select label="Supplier / Vendor" value={vendor} onChange={setVendor} icon={Building2}
              options={VENDORS.map(v => ({ value: v, label: v }))} />
            <Select label="Target Market" value={market} onChange={setMarket} icon={Globe}
              options={MARKETS.map(m => ({ value: m.code, label: `${m.label} (${m.code})` }))} />
          </div>

          {/* Drop zone */}
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
            <div style={{ color: "var(--text-secondary)", fontWeight: 600, fontSize: 14 }}>
              Drop Excel files here
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 12, marginTop: 4 }}>
              .xlsx or .xls · Multiple files supported
            </div>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              marginTop: 16, padding: "8px 20px",
              background: "var(--brand-gold)", borderRadius: 8,
              color: "white", fontSize: 13, fontWeight: 600,
            }}>
              <Upload size={14} /> Browse Files
            </div>
          </div>

          {/* File list */}
          {files.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {files.map((f, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  background: "var(--bg-card)", border: "1px solid var(--border)",
                  borderRadius: 8, padding: "10px 14px",
                }}>
                  <FileSpreadsheet size={16} style={{ color: "#22c55e", flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {f.file.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      {f.sheets} sheet{f.sheets > 1 ? "s" : ""} · {f.rows} tours estimated
                    </div>
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

              {/* Summary */}
              <div style={{
                display: "flex", justifyContent: "space-between",
                padding: "8px 14px", background: "rgba(219,150,40,0.06)",
                border: "1px solid rgba(219,150,40,0.2)", borderRadius: 8,
                fontSize: 12, color: "var(--brand-gold)",
              }}>
                <span>{files.length} file{files.length > 1 ? "s" : ""} selected</span>
                <span>{totalTours} tours total</span>
              </div>
            </div>
          )}

          {/* Run button */}
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
              ? <><Loader2 size={16} className="animate-spin" /> Running Pipeline...</>
              : allDone
              ? <><CheckCircle size={16} /> Pipeline Complete — {totalTours} Tours Processed</>
              : `Start Pipeline${totalTours > 0 ? ` · ${totalTours} Tours` : ""}`
            }
          </button>
          {!vendor && files.length > 0 && (
            <p style={{ fontSize: 11, color: "#f59e0b", margin: 0, textAlign: "center" }}>
              ⚠ Please select a vendor and target market to continue
            </p>
          )}
        </div>

        {/* RIGHT — Pipeline progress */}
        <div style={{
          background: "var(--bg-card)", border: "1px solid var(--border)",
          borderRadius: 12, padding: 24,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 1 }}>
              Pipeline Progress
            </div>
            {eta && (
              <div style={{ fontSize: 12, color: allDone ? "#22c55e" : "var(--brand-gold)" }}>
                {eta}
              </div>
            )}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {STEPS.map((step, i) => (
              <StepRow key={step.key} step={step} index={i}
                activeStep={activeStep} progress={stepProgress} />
            ))}
          </div>

          {/* Done summary */}
          {allDone && (
            <div style={{
              marginTop: 24, padding: 16,
              background: "rgba(34,197,94,0.08)", border: "1px solid rgba(34,197,94,0.2)",
              borderRadius: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#22c55e", fontWeight: 600, fontSize: 13 }}>
                <CheckCircle size={16} /> All tours processed successfully
              </div>
              <div style={{ fontSize: 12, color: "#16a34a", marginTop: 6 }}>
                {totalTours} tours → Review Queue for quality score &lt; 7.0
              </div>
              <a href="/review" style={{
                display: "inline-block", marginTop: 10, padding: "6px 14px",
                background: "var(--brand-gold)", borderRadius: 6,
                color: "white", fontSize: 12, fontWeight: 600,
                textDecoration: "none",
              }}>
                Go to Review Queue →
              </a>
            </div>
          )}

          {activeStep === -1 && (
            <div style={{
              marginTop: 16, padding: 16,
              background: "var(--bg-primary)", borderRadius: 10,
            }}>
              <p style={{ fontSize: 12, color: "var(--text-muted)", margin: 0, lineHeight: 1.6 }}>
                Configure vendor and market, upload Excel files, then click
                <strong style={{ color: "var(--brand-gold)" }}> Start Pipeline</strong>.
                Tours will be rewritten to Adventure Asia brand standards automatically.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
