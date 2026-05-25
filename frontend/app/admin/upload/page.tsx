"use client";

import React, { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Upload, CheckCircle, XCircle, ArrowRight, Loader2 } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, sans, Card, SLabel, Btn } from "../_components/adminUi";

const TENANT_ID = "00000000-0000-0000-0000-000000000001";

type Step = 1 | 2 | 3;
type S2Status = "idle" | "getting-url" | "uploading" | "done" | "error";
type S3Status = "idle" | "starting" | "done" | "error";

interface UploadUrlResult { upload_url: string; s3_key: string; bucket: string; }
interface IngestResult { batch_id: string; status: string; message?: string; }

const S2_PHASES = [
  { id: "getting-url" as const, label: "Getting upload URL..." },
  { id: "uploading"   as const, label: "Uploading to S3..." },
  { id: "done"        as const, label: "Upload complete ✓" },
];
const S2_IDX: Record<S2Status, number> = {
  idle: -1, "getting-url": 0, uploading: 1, done: 2, error: -1,
};

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep]         = useState<Step>(1);
  const [dragging, setDragging] = useState(false);
  const [file, setFile]         = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [maxTours, setMaxTours] = useState(50);

  const [s2Status, setS2Status] = useState<S2Status>("idle");
  const [s2Error, setS2Error]   = useState("");
  const [urlResult, setUrlResult] = useState<UploadUrlResult | null>(null);

  const [s3Status, setS3Status] = useState<S3Status>("idle");
  const [s3Error, setS3Error]   = useState("");
  const [ingestResult, setIngestResult] = useState<IngestResult | null>(null);

  // ── File selection ────────────────────────────────────────────────────────────
  function selectFile(f: File) {
    if (!f.name.match(/\.xlsx$/i)) { setFileError("Only .xlsx files are supported"); return; }
    if (f.size > 50 * 1024 * 1024) { setFileError("File exceeds 50 MB limit"); return; }
    setFile(f);
    setFileError("");
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) selectFile(f);
  }, []);

  function reset() {
    setStep(1); setFile(null); setFileError("");
    setS2Status("idle"); setS2Error(""); setUrlResult(null);
    setS3Status("idle"); setS3Error(""); setIngestResult(null);
  }

  // ── Step 2: Upload to S3 ──────────────────────────────────────────────────────
  async function doUpload() {
    if (!file) return;
    setStep(2);
    setS2Status("getting-url");
    setS2Error("");

    try {
      const urlRes = await fetch("/api/admin/upload-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, tenant_id: TENANT_ID }),
      });
      if (!urlRes.ok) {
        const e = await urlRes.json().catch(() => ({}));
        throw new Error(e.detail || `Failed to get upload URL (${urlRes.status})`);
      }
      const urlData: UploadUrlResult = await urlRes.json();
      setUrlResult(urlData);

      setS2Status("uploading");
      const putRes = await fetch(urlData.upload_url, {
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      });
      if (!putRes.ok) throw new Error(`S3 upload failed (${putRes.status})`);

      setS2Status("done");
      setTimeout(() => setStep(3), 800);
    } catch (err: unknown) {
      setS2Status("error");
      setS2Error(err instanceof Error ? err.message : "Upload failed");
    }
  }

  // ── Step 3: Trigger pipeline ──────────────────────────────────────────────────
  async function doIngest() {
    if (!urlResult) return;
    setS3Status("starting");
    setS3Error("");

    try {
      const res = await fetch("/api/admin/ingest-s3", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ s3_key: urlResult.s3_key, tenant_id: TENANT_ID, max_tours: maxTours }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Pipeline start failed (${res.status})`);
      }
      const data: IngestResult = await res.json();
      setIngestResult(data);
      setS3Status("done");
    } catch (err: unknown) {
      setS3Status("error");
      setS3Error(err instanceof Error ? err.message : "Pipeline start failed");
    }
  }

  // ── Step indicator ────────────────────────────────────────────────────────────
  const STEPS = [
    { n: 1 as Step, label: "Select File" },
    { n: 2 as Step, label: "Upload to S3" },
    { n: 3 as Step, label: "Ingest Pipeline" },
  ];

  const s2CurrentIdx = S2_IDX[s2Status];

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>

        <header style={{
          height: 56, background: "#fff", borderBottom: `1px solid ${A.line}`,
          display: "flex", alignItems: "center", padding: "0 32px", gap: 8,
          position: "sticky", top: 0, zIndex: 10,
        }}>
          <span style={{ fontSize: 12, color: A.muted2 }}>Admin /</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: A.body }}>Upload (S0)</span>
        </header>

        <main style={{ flex: 1, padding: "28px 36px 56px", overflowY: "auto" }}>

          <div style={{ marginBottom: 28 }}>
            <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em" }}>
              Upload Tours
            </h1>
            <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>S0 — Upload Excel to S3 · Ingest pipeline · aa_internal tenant</p>
          </div>

          {/* Step indicator */}
          <div style={{ display: "flex", alignItems: "center", marginBottom: 32 }}>
            {STEPS.map((s, i) => {
              const done   = s.n < step;
              const active = s.n === step;
              return (
                <React.Fragment key={s.n}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "7px 16px", borderRadius: 20,
                    background: active ? A.gold : done ? A.greenSoft : A.line2,
                  }}>
                    <div style={{
                      width: 20, height: 20, borderRadius: "50%", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: active ? "#fff" : done ? A.green : A.muted2,
                      color: active ? A.gold : "#fff",
                      fontSize: 11, fontWeight: 700,
                    }}>
                      {done ? "✓" : s.n}
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600, color: active ? "#fff" : done ? A.green : A.muted, whiteSpace: "nowrap" }}>
                      {s.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div style={{ width: 32, height: 1, background: A.line }} />
                  )}
                </React.Fragment>
              );
            })}
          </div>

          {/* ── Step 1: Select File ── */}
          {step === 1 && (
            <div style={{ maxWidth: 560 }}>
              <Card>
                <SLabel>Source File</SLabel>

                {/* Dropzone */}
                <div
                  onDragOver={e => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    border: `2px dashed ${dragging ? A.gold : file ? "#22C55E" : A.line}`,
                    borderRadius: 10, padding: "40px 24px",
                    textAlign: "center", cursor: "pointer",
                    background: dragging ? A.goldTint : file ? "#F0FDF4" : A.bg,
                    transition: "all .15s", marginBottom: 16,
                  }}
                >
                  <input
                    ref={fileInputRef} type="file" accept=".xlsx"
                    style={{ display: "none" }}
                    onChange={e => { const f = e.target.files?.[0]; if (f) selectFile(f); }}
                  />
                  {file ? (
                    <>
                      <CheckCircle size={28} style={{ color: "#22C55E", marginBottom: 10 }} />
                      <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>{file.name}</div>
                      <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
                        {(file.size / 1024).toFixed(1)} KB · click to change
                      </div>
                    </>
                  ) : (
                    <>
                      <Upload size={28} style={{ color: A.muted2, marginBottom: 10 }} />
                      <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>Drop Excel file here or click to browse</div>
                      <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>Supported: .xlsx · max 50 MB</div>
                    </>
                  )}
                </div>

                {fileError && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, color: A.red, fontSize: 13, marginBottom: 16 }}>
                    <XCircle size={14} />{fileError}
                  </div>
                )}

                {/* Max tours */}
                <div style={{ marginBottom: 24 }}>
                  <label style={{ fontSize: 12, fontWeight: 600, color: A.muted, display: "block", marginBottom: 6 }}>
                    Max tours to process
                  </label>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <input
                      type="number" min={1} max={500} value={maxTours}
                      onChange={e => setMaxTours(Math.min(500, Math.max(1, Number(e.target.value))))}
                      style={{
                        width: 100, padding: "8px 12px", borderRadius: 7,
                        border: `1px solid ${A.line}`, background: "#fff",
                        fontSize: 14, color: A.ink, fontFamily: sans,
                      }}
                    />
                    <span style={{ fontSize: 12, color: A.muted2 }}>min 1 · max 500</span>
                  </div>
                </div>

                <Btn
                  variant="primary"
                  disabled={!file}
                  onClick={doUpload}
                  style={{ background: file ? A.gold : A.muted, border: `1px solid ${file ? A.gold : A.muted}`, display: "flex", alignItems: "center", gap: 8 }}
                >
                  Upload File <ArrowRight size={14} />
                </Btn>
              </Card>
            </div>
          )}

          {/* ── Step 2: Upload to S3 ── */}
          {step === 2 && (
            <div style={{ maxWidth: 560 }}>
              <Card>
                <SLabel>Upload to S3</SLabel>

                <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: s2Status === "error" ? 20 : 0 }}>
                  {S2_PHASES.map((phase, i) => {
                    const isDone   = s2Status === "done" || (i < s2CurrentIdx);
                    const isActive = i === s2CurrentIdx && s2Status !== "done";
                    const isPending = !isDone && !isActive;
                    return (
                      <div key={phase.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{
                          width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          background: isDone ? "#22C55E" : isActive ? A.gold : A.line2,
                        }}>
                          {isActive ? (
                            <Loader2 size={12} style={{ color: "#fff", animation: "spin 1s linear infinite" }} />
                          ) : isDone ? (
                            <CheckCircle size={12} style={{ color: "#fff" }} />
                          ) : (
                            <span style={{ color: A.muted2, fontSize: 11, fontWeight: 700 }}>{i + 1}</span>
                          )}
                        </div>
                        <span style={{
                          fontSize: 13, fontWeight: isActive ? 600 : 400,
                          color: isDone ? "#15803D" : isActive ? A.ink : A.muted2,
                        }}>
                          {phase.label}
                        </span>
                      </div>
                    );
                  })}
                </div>

                {s2Status === "error" && (
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, color: A.red, fontSize: 13, marginBottom: 14 }}>
                      <XCircle size={14} />{s2Error}
                    </div>
                    <Btn variant="secondary" onClick={() => { setStep(1); setS2Status("idle"); setS2Error(""); }}>
                      ← Try Again
                    </Btn>
                  </div>
                )}
              </Card>
            </div>
          )}

          {/* ── Step 3: Trigger Pipeline ── */}
          {step === 3 && urlResult && (
            <div style={{ maxWidth: 560 }}>

              {/* Success state */}
              {s3Status === "done" && ingestResult ? (
                <Card style={{ border: `1px solid #22C55E`, background: "#F0FDF4" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
                    <CheckCircle size={22} style={{ color: "#22C55E" }} />
                    <span style={{ fontSize: 16, fontWeight: 600, color: "#15803D" }}>Pipeline started</span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13, marginBottom: 24 }}>
                    <div>
                      <span style={{ color: A.muted }}>Batch ID: </span>
                      <code style={{ fontFamily: "monospace", fontWeight: 600, color: A.ink }}>{ingestResult.batch_id}</code>
                    </div>
                    <div>
                      <span style={{ color: A.muted }}>Status: </span>
                      <strong style={{ color: "#15803D" }}>{ingestResult.status}</strong>
                    </div>
                    {ingestResult.message && (
                      <div><span style={{ color: A.muted }}>Message: </span>{ingestResult.message}</div>
                    )}
                    <div><span style={{ color: A.muted }}>File: </span>{file?.name}</div>
                    <div>
                      <span style={{ color: A.muted }}>S3 key: </span>
                      <code style={{ fontFamily: "monospace", fontSize: 11, color: A.muted2 }}>{urlResult.s3_key}</code>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 10 }}>
                    <Btn variant="secondary" onClick={reset}>Upload Another</Btn>
                    <Btn
                      variant="primary"
                      onClick={() => router.push("/admin/dashboard")}
                      style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 8 }}
                    >
                      → View in Dashboard
                    </Btn>
                  </div>
                </Card>
              ) : (
                /* Ready to trigger state */
                <Card>
                  <SLabel>Trigger Pipeline</SLabel>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: 13, color: A.body, marginBottom: 24 }}>
                    <div><span style={{ color: A.muted }}>File: </span><strong>{file?.name}</strong></div>
                    <div>
                      <span style={{ color: A.muted }}>S3 key: </span>
                      <code style={{ fontFamily: "monospace", fontSize: 11, color: A.muted2 }}>{urlResult.s3_key}</code>
                    </div>
                    <div><span style={{ color: A.muted }}>Tenant: </span>aa_internal</div>
                    <div><span style={{ color: A.muted }}>Max tours: </span>{maxTours}</div>
                  </div>

                  {s3Status === "error" && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, color: A.red, fontSize: 13, marginBottom: 16 }}>
                      <XCircle size={14} />{s3Error}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 10 }}>
                    <Btn
                      variant="primary"
                      disabled={s3Status === "starting"}
                      onClick={doIngest}
                      style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 8 }}
                    >
                      {s3Status === "starting" ? (
                        <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Starting pipeline...</>
                      ) : (
                        <>Start Pipeline <ArrowRight size={14} /></>
                      )}
                    </Btn>
                    {s3Status === "error" && (
                      <Btn variant="secondary" onClick={doIngest}>Retry</Btn>
                    )}
                  </div>
                </Card>
              )}
            </div>
          )}

        </main>
      </div>
    </div>
  );
}
