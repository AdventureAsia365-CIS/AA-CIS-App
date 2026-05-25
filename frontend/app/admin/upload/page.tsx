"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Upload, CheckCircle, XCircle, ArrowRight, Loader2,
  ChevronDown, ChevronUp, FileText,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Btn, TabBar, TH, TD, Badge, LoadingScreen,
} from "../_components/adminUi";

const TENANT_ID = "00000000-0000-0000-0000-000000000001";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DryRunTour {
  tour_id: string;
  src_name: string;
  country: string;
  duration: string | null;
  price_raw: string | null;
  group_size: string | null;
  period: string | null;
  pipeline_status: string;
  ingest_at: string;
  src_subtitle: string | null;
  src_summary: string | null;
  src_highlights: string | null;
  src_itineraries: string | null;
  provider: string | null;
  activities: string | null;
  inclusions: string | null;
  exclusions: string | null;
  sku: string | null;
  src_description: string | null;
  links: string | null;
  feature: string | null;
  best_time_to_go: string | null;
  missing_fields: string[];
  is_duplicate: boolean;
}

interface UploadHistoryRow {
  filename: string;
  s3_path: string | null;
  row_count: number | null;
  parsed_at: string | null;
  parse_errors: string | null;
  file_hash: string | null;
}

interface DryRunResult {
  status: string;
  batch_id: string;
  tour_count: number;
  duplicate_count: number;
  error_count: number;
  tours: DryRunTour[];
  upload_history: UploadHistoryRow[];
}

interface BrandRules {
  configured: boolean;
  system_prompt: string | null;
  style_guide: string | null;
  forbidden_words: string[];
  version: number;
  updated_at: string | null;
}

// ─── StepIndicator ────────────────────────────────────────────────────────────

function StepIndicator({ step }: { step: 1 | 2 | 3 }) {
  const STEPS = [
    { n: 1 as const, label: "Select File" },
    { n: 2 as const, label: "Upload to S3" },
    { n: 3 as const, label: "Data Quality Review" },
  ];
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 28 }}>
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
                color: active ? A.gold : "#fff", fontSize: 11, fontWeight: 700,
              }}>
                {done ? "✓" : s.n}
              </div>
              <span style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap",
                color: active ? "#fff" : done ? A.green : A.muted }}>
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
  );
}

// ─── TourRow (expandable) ─────────────────────────────────────────────────────

const DL_LABEL: React.CSSProperties = {
  fontSize: 10, fontWeight: 700, textTransform: "uppercase",
  letterSpacing: "0.12em", color: A.muted, marginBottom: 2,
};
const DL_VAL: React.CSSProperties = {
  fontSize: 12, color: A.body, lineHeight: 1.6, marginBottom: 10,
};

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div>
      <div style={DL_LABEL}>{label}</div>
      <div style={DL_VAL}>{value}</div>
    </div>
  );
}

function TourRow({ tour, idx, isExpanded, onToggle }: {
  tour: DryRunTour; idx: number; isExpanded: boolean; onToggle: () => void;
}) {
  const hasMissing  = tour.missing_fields.length > 0;
  const isDuplicate = tour.is_duplicate;

  let badgeColor: "green" | "amber" | "blue" | "red" = "green";
  let badgeLabel = "Ready";
  if (hasMissing && isDuplicate) { badgeColor = "red";   badgeLabel = "Skip"; }
  else if (hasMissing)           { badgeColor = "amber"; badgeLabel = "Incomplete"; }
  else if (isDuplicate)          { badgeColor = "blue";  badgeLabel = "Duplicate"; }

  const itinPreview = tour.src_itineraries
    ? (tour.src_itineraries.length > 200
        ? tour.src_itineraries.slice(0, 200) + "..."
        : tour.src_itineraries)
    : null;

  return (
    <>
      <tr
        style={{ cursor: "pointer", background: idx % 2 === 1 ? A.bg : "transparent" }}
        onClick={onToggle}
      >
        <td style={{ ...TD, textAlign: "center" as const, color: A.muted2 }}>{idx}</td>
        <td style={{ ...TD, fontWeight: 600, color: hasMissing ? A.red : A.ink }}>{tour.src_name || "—"}</td>
        <td style={TD}>{tour.country || "—"}</td>
        <td style={TD}>{tour.duration || "—"}</td>
        <td style={TD}>{tour.price_raw || "—"}</td>
        <td style={TD}>{tour.group_size || "—"}</td>
        <td style={TD}>{tour.period || "—"}</td>
        <td style={TD}>{tour.provider || "—"}</td>
        <td style={TD}>{tour.sku || "—"}</td>
        <td style={TD}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Badge color={badgeColor}>{badgeLabel}</Badge>
            {isExpanded
              ? <ChevronUp size={13} style={{ color: A.muted2 }} />
              : <ChevronDown size={13} style={{ color: A.muted2 }} />}
          </div>
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={10} style={{ padding: 0, background: A.bg }}>
            <div style={{ padding: "16px 20px 18px", borderBottom: `1px solid ${A.line}` }}>
              {/* 2-column grid */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                {/* Left column */}
                <div>
                  <DetailField label="Subtitle"        value={tour.src_subtitle} />
                  <DetailField label="Summary"         value={tour.src_summary} />
                  <DetailField label="Description"     value={tour.src_description} />
                  <DetailField label="Best Time to Go" value={tour.best_time_to_go} />
                  <DetailField label="Feature"         value={tour.feature} />
                </div>
                {/* Right column */}
                <div>
                  <DetailField label="Highlights"  value={tour.src_highlights} />
                  <DetailField label="Activities"  value={tour.activities} />
                  <DetailField label="Includes"    value={tour.inclusions} />
                  <DetailField label="Excludes"    value={tour.exclusions} />
                  <DetailField label="Itinerary"   value={itinPreview} />
                  <DetailField label="Links"       value={tour.links} />
                </div>
              </div>
              {/* Full-width alerts */}
              {hasMissing && (
                <div style={{ marginTop: 10, fontSize: 12, color: "#92400E",
                  background: "#FFFBEB", border: "1px solid #FDE68A",
                  borderRadius: 6, padding: "6px 12px" }}>
                  <strong>Missing fields:</strong> {tour.missing_fields.join(", ")}
                </div>
              )}
              {isDuplicate && (
                <div style={{ marginTop: 6, fontSize: 12, color: "#9A3412",
                  background: "#FFF7ED", border: "1px solid #FDBA74",
                  borderRadius: 6, padding: "6px 12px" }}>
                  <strong>Duplicate:</strong> Yes — tour name already exists in catalog
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Field helper ─────────────────────────────────────────────────────────────

function Field({
  label, value, onChange, placeholder = "", rows, style = {},
}: {
  label: string; value: string; onChange: (v: string) => void;
  placeholder?: string; rows?: number; style?: React.CSSProperties;
}) {
  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 12px", borderRadius: 7,
    border: `1px solid ${A.line}`, background: "#fff",
    fontSize: 13, color: A.ink, fontFamily: sans,
    resize: rows ? "vertical" : undefined,
    boxSizing: "border-box",
  };
  return (
    <div style={style}>
      <label style={{ fontSize: 12, fontWeight: 600, color: A.muted, display: "block", marginBottom: 5 }}>
        {label}
      </label>
      {rows ? (
        <textarea value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} rows={rows} style={inputStyle} />
      ) : (
        <input type="text" value={value} onChange={e => onChange(e.target.value)}
          placeholder={placeholder} style={inputStyle} />
      )}
    </div>
  );
}

function Divider({ label }: { label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "4px 0 14px" }}>
      <div style={{ flex: 1, height: 1, background: A.line }} />
      <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.16em", color: A.muted2 }}>{label}</span>
      <div style={{ flex: 1, height: 1, background: A.line }} />
    </div>
  );
}

// ─── Tab 1: Tour Content ──────────────────────────────────────────────────────

type Step = 1 | 2 | 3;
type S2Status = "idle" | "getting-url" | "uploading" | "done" | "error";

const S2_PHASES = [
  { id: "getting-url" as const, label: "Getting upload URL..." },
  { id: "uploading"   as const, label: "Uploading to S3..." },
  { id: "done"        as const, label: "Upload complete ✓" },
];
const S2_IDX: Record<S2Status, number> = {
  idle: -1, "getting-url": 0, uploading: 1, done: 2, error: -1,
};

interface UploadUrlResult { upload_url: string; s3_key: string; bucket: string; }

function TourContentTab() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep]           = useState<Step>(1);
  const [dragging, setDragging]   = useState(false);
  const [file, setFile]           = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [maxTours, setMaxTours]   = useState(50);

  const [s2Status, setS2Status] = useState<S2Status>("idle");
  const [s2Error, setS2Error]   = useState("");
  const [urlResult, setUrlResult] = useState<UploadUrlResult | null>(null);

  const [dryRunResult, setDryRunResult]   = useState<DryRunResult | null>(null);
  const [dryRunError, setDryRunError]     = useState("");
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [expandedRow, setExpandedRow]     = useState<string | null>(null);
  const toggleRow = (id: string) => setExpandedRow(prev => prev === id ? null : id);

  function selectFile(f: File) {
    if (!f.name.match(/\.xlsx$/i)) { setFileError("Only .xlsx files are supported"); return; }
    if (f.size > 50 * 1024 * 1024) { setFileError("File exceeds 50 MB limit"); return; }
    setFile(f); setFileError("");
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0]; if (f) selectFile(f);
  }, []);

  function reset() {
    setStep(1); setFile(null); setFileError("");
    setS2Status("idle"); setS2Error(""); setUrlResult(null);
    setDryRunResult(null); setDryRunError(""); setDryRunLoading(false);
  }

  async function doUpload() {
    if (!file) return;
    setStep(2); setS2Status("getting-url"); setS2Error("");
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
        method: "PUT", body: file,
        headers: { "Content-Type": file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
      });
      if (!putRes.ok) throw new Error(`S3 upload failed (${putRes.status})`);
      setS2Status("done");

      setTimeout(() => doIngestDryRun(urlData.s3_key), 600);
    } catch (err: unknown) {
      setS2Status("error");
      setS2Error(err instanceof Error ? err.message : "Upload failed");
    }
  }

  async function doIngestDryRun(s3Key: string) {
    setStep(3); setDryRunLoading(true); setDryRunError("");
    try {
      const res = await fetch("/api/admin/ingest-s3", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ s3_key: s3Key, tenant_id: TENANT_ID, max_tours: maxTours, dry_run: true }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Parse failed (${res.status})`);
      }
      setDryRunResult(await res.json());
    } catch (err: unknown) {
      setDryRunError(err instanceof Error ? err.message : "Parse failed");
    } finally {
      setDryRunLoading(false);
    }
  }

  const s2Idx = S2_IDX[s2Status];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <StepIndicator step={step} />

      {/* ── Step 1: Select File ── */}
      {step === 1 && (
        <div style={{ maxWidth: 560 }}>
          <Card>
            <SLabel>Source File</SLabel>
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragging ? A.gold : file ? "#22C55E" : A.line}`,
                borderRadius: 10, padding: "40px 24px", textAlign: "center",
                cursor: "pointer", transition: "all .15s", marginBottom: 16,
                background: dragging ? A.goldTint : file ? "#F0FDF4" : A.bg,
              }}
            >
              <input ref={fileInputRef} type="file" accept=".xlsx" style={{ display: "none" }}
                onChange={e => { const f = e.target.files?.[0]; if (f) selectFile(f); }} />
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
            <div style={{ marginBottom: 24 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: A.muted, display: "block", marginBottom: 6 }}>
                Max tours to process
              </label>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <input type="number" min={1} max={500} value={maxTours}
                  onChange={e => setMaxTours(Math.min(500, Math.max(1, Number(e.target.value))))}
                  style={{ width: 100, padding: "8px 12px", borderRadius: 7,
                    border: `1px solid ${A.line}`, background: "#fff",
                    fontSize: 14, color: A.ink, fontFamily: sans }} />
                <span style={{ fontSize: 12, color: A.muted2 }}>min 1 · max 500</span>
              </div>
            </div>
            <Btn variant="primary" disabled={!file} onClick={doUpload}
              style={{ background: file ? A.gold : A.muted, border: `1px solid ${file ? A.gold : A.muted}`,
                display: "flex", alignItems: "center", gap: 8 }}>
              Upload File <ArrowRight size={14} />
            </Btn>
          </Card>
        </div>
      )}

      {/* ── Step 2: Upload to S3 ── */}
      {step === 2 && (
        <div style={{ maxWidth: 480 }}>
          <Card>
            <SLabel>Upload to S3</SLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {S2_PHASES.map((phase, i) => {
                const isDone   = s2Status === "done" || i < s2Idx;
                const isActive = i === s2Idx && s2Status !== "done";
                return (
                  <div key={phase.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{
                      width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: isDone ? "#22C55E" : isActive ? A.gold : A.line2,
                    }}>
                      {isActive
                        ? <Loader2 size={12} style={{ color: "#fff", animation: "spin 1s linear infinite" }} />
                        : isDone
                          ? <CheckCircle size={12} style={{ color: "#fff" }} />
                          : <span style={{ color: A.muted2, fontSize: 11, fontWeight: 700 }}>{i + 1}</span>}
                    </div>
                    <span style={{ fontSize: 13, fontWeight: isActive ? 600 : 400,
                      color: isDone ? "#15803D" : isActive ? A.ink : A.muted2 }}>
                      {phase.label}
                    </span>
                  </div>
                );
              })}
            </div>
            {s2Status === "error" && (
              <div style={{ marginTop: 20 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                  color: A.red, fontSize: 13, marginBottom: 14 }}>
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

      {/* ── Step 3: Data Quality Review ── */}
      {step === 3 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {dryRunLoading ? (
            <LoadingScreen msg="Parsing tours from Excel…" />
          ) : dryRunError ? (
            <Card>
              <div style={{ display: "flex", alignItems: "center", gap: 8,
                color: A.red, fontSize: 14, marginBottom: 16 }}>
                <XCircle size={16} />{dryRunError}
              </div>
              <Btn variant="secondary" onClick={reset}>← Upload Another</Btn>
            </Card>
          ) : dryRunResult ? (
            <>
              {/* 4 summary cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
                {[
                  { label: "Tours Parsed",    value: dryRunResult.tour_count,      color: A.gold },
                  { label: "Errors",           value: dryRunResult.error_count,     color: dryRunResult.error_count > 0 ? A.red : A.muted2 },
                  { label: "Duplicates",       value: dryRunResult.duplicate_count, color: dryRunResult.duplicate_count > 0 ? "#F59E0B" : A.muted2 },
                  { label: "Ready to Process", value: Math.max(0, dryRunResult.tour_count - dryRunResult.error_count - dryRunResult.duplicate_count), color: "#22C55E" },
                ].map(c => (
                  <Card key={c.label}>
                    <SLabel>{c.label}</SLabel>
                    <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500,
                      color: c.color, letterSpacing: "-0.02em" }}>{c.value}</div>
                  </Card>
                ))}
              </div>

              {/* Tours table */}
              <Card style={{ padding: 0 }}>
                <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${A.line}` }}>
                  <SLabel>Parsed Tours — {file?.name}</SLabel>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr>
                        {["#", "Tour Name", "Country", "Duration", "Price", "Group Size", "Period", "Provider", "SKU", "Status"].map((h, i) => (
                          <th key={h} style={{ ...TH, textAlign: i === 0 ? "center" : "left" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {dryRunResult.tours.map((tour, i) => (
                        <TourRow
                          key={tour.tour_id}
                          tour={tour}
                          idx={i + 1}
                          isExpanded={expandedRow === tour.tour_id}
                          onToggle={() => toggleRow(tour.tour_id)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* Upload History */}
              {dryRunResult.upload_history.length > 0 && (
                <Card style={{ padding: 0 }}>
                  <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${A.line}` }}>
                    <SLabel>Upload History</SLabel>
                  </div>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr>
                          {["Filename", "Rows", "Parsed At", "Errors", "Hash"].map((h, i) => (
                            <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dryRunResult.upload_history.map((r, i) => (
                          <tr key={i} style={{ background: i % 2 === 1 ? A.bg : "transparent" }}>
                            <td style={{ ...TD, maxWidth: 260, overflow: "hidden",
                              textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.filename}</td>
                            <td style={{ ...TD, textAlign: "right" }}>{r.row_count ?? "—"}</td>
                            <td style={{ ...TD, textAlign: "right", color: A.muted }}>
                              {r.parsed_at ? String(r.parsed_at).slice(0, 16).replace("T", " ") : "—"}
                            </td>
                            <td style={{ ...TD, textAlign: "right", color: A.muted2 }}>
                              {r.parse_errors || "—"}
                            </td>
                            <td style={{ ...TD, textAlign: "right" }}>
                              <code style={{ fontFamily: mono, fontSize: 11, color: A.muted2 }}>
                                {r.file_hash ? r.file_hash.slice(0, 8) : "—"}
                              </code>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Card>
              )}

              {/* Action buttons */}
              <div style={{ display: "flex", gap: 12 }}>
                <Btn variant="secondary" onClick={reset}>← Upload Another</Btn>
                <Btn variant="primary" onClick={() => router.push("/admin/pipeline/s1")}
                  style={{ background: A.gold, border: `1px solid ${A.gold}`,
                    display: "flex", alignItems: "center", gap: 8 }}>
                  Proceed to S1 Rewrite <ArrowRight size={14} />
                </Btn>
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ─── Tab 2: Brand Identity ────────────────────────────────────────────────────

function BrandTab() {
  const [subTab, setSubTab]   = useState<"docx" | "manual">("docx");
  const docxRef               = useRef<HTMLInputElement>(null);
  const [docxFile, setDocxFile]         = useState<File | null>(null);
  const [docxDragging, setDocxDragging] = useState(false);
  const [docxLoading, setDocxLoading]   = useState(false);
  const [docxError, setDocxError]       = useState("");

  // Manual form fields
  const [brandName,       setBrandName]       = useState("");
  const [brandType,       setBrandType]       = useState("");
  const [coreIdea,        setCoreIdea]        = useState("");
  const [targetMarkets,   setTargetMarkets]   = useState("");
  const [customerSegment, setCustomerSegment] = useState("");
  const [customerMindset, setCustomerMindset] = useState("");
  const [toneOfVoice,     setToneOfVoice]     = useState("");
  const [writingStyle,    setWritingStyle]    = useState("");
  const [goodExamples,    setGoodExamples]    = useState("");
  const [shouldWrite,     setShouldWrite]     = useState("");
  const [shouldNotWrite,  setShouldNotWrite]  = useState("");

  const [saving,       setSaving]       = useState(false);
  const [saveError,    setSaveError]    = useState("");
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  const [brandRules, setBrandRules] = useState<BrandRules | null>(null);
  const [rulesLoading, setRulesLoading] = useState(true);

  useEffect(() => {
    setRulesLoading(true);
    fetch("/api/admin/brand-identity")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setBrandRules(d); })
      .catch(() => {})
      .finally(() => setRulesLoading(false));
  }, [savedVersion]);

  async function handleDocxParse() {
    if (!docxFile) return;
    setDocxLoading(true); setDocxError("");
    const fd = new FormData();
    fd.append("file", docxFile);
    try {
      const res = await fetch(`/api/admin/tenants/${TENANT_ID}/brand-brief`, {
        method: "POST", body: fd,
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(Array.isArray(e.detail) ? e.detail.join("; ") : (e.detail || `Failed (${res.status})`));
      }
      const data = await res.json();
      if (data.brand_name)       setBrandName(data.brand_name);
      if (data.brand_type)       setBrandType(data.brand_type);
      if (data.core_idea)        setCoreIdea(data.core_idea);
      if (data.target_markets)   setTargetMarkets(Array.isArray(data.target_markets) ? data.target_markets.join(", ") : String(data.target_markets));
      if (data.customer_segment) setCustomerSegment(data.customer_segment);
      if (data.customer_mindset) setCustomerMindset(data.customer_mindset);
      if (data.tone_of_voice)    setToneOfVoice(data.tone_of_voice);
      if (data.writing_style)    setWritingStyle(data.writing_style);
      if (data.good_examples)    setGoodExamples(data.good_examples);
      if (data.should_write)     setShouldWrite(data.should_write);
      if (data.forbidden_words)  setShouldNotWrite(Array.isArray(data.forbidden_words) ? data.forbidden_words.join("\n") : String(data.forbidden_words));
      setSubTab("manual");
    } catch (err: unknown) {
      setDocxError(err instanceof Error ? err.message : "Parse failed");
    } finally {
      setDocxLoading(false);
    }
  }

  async function handleSave() {
    setSaving(true); setSaveError(""); setSavedVersion(null);
    const systemPrompt = [
      brandName       ? `Brand: ${brandName}` : "",
      brandType       ? `Type: ${brandType}` : "",
      coreIdea        ? `Core Idea: ${coreIdea}` : "",
      targetMarkets   ? `Target Markets: ${targetMarkets}` : "",
      customerSegment ? `Customer Segment: ${customerSegment}` : "",
      customerMindset ? `Customer Mindset: ${customerMindset}` : "",
      toneOfVoice     ? `Tone: ${toneOfVoice}` : "",
    ].filter(Boolean).join("\n");
    const styleGuide = [
      writingStyle ? `Writing Style:\n${writingStyle}` : "",
      goodExamples ? `Good Examples:\n${goodExamples}` : "",
      shouldWrite  ? `Should Write:\n${shouldWrite}` : "",
    ].filter(Boolean).join("\n\n");
    const forbiddenWords = shouldNotWrite.split("\n").map(s => s.trim()).filter(Boolean);
    try {
      const res = await fetch("/api/admin/brand-identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          system_prompt:   systemPrompt || null,
          style_guide:     styleGuide || null,
          forbidden_words: forbiddenWords,
        }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Save failed (${res.status})`);
      }
      const data = await res.json();
      setSavedVersion(data.version);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const subTabs = [
    { key: "docx",   label: "Upload DOCX" },
    { key: "manual", label: "Manual Entry" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div><TabBar tabs={subTabs} active={subTab} onChange={v => setSubTab(v as "docx" | "manual")} /></div>

      {/* ── Sub-tab A: Upload DOCX ── */}
      {subTab === "docx" && (
        <div style={{ maxWidth: 520 }}>
          <Card>
            <SLabel>Brand Brief DOCX</SLabel>
            <div
              onDragOver={e => { e.preventDefault(); setDocxDragging(true); }}
              onDragLeave={() => setDocxDragging(false)}
              onDrop={e => {
                e.preventDefault(); setDocxDragging(false);
                const f = e.dataTransfer.files[0];
                if (f && f.name.endsWith(".docx")) setDocxFile(f);
              }}
              onClick={() => docxRef.current?.click()}
              style={{
                border: `2px dashed ${docxDragging ? A.gold : docxFile ? "#22C55E" : A.line}`,
                borderRadius: 10, padding: "36px 24px", textAlign: "center",
                cursor: "pointer", transition: "all .15s", marginBottom: 16,
                background: docxDragging ? A.goldTint : docxFile ? "#F0FDF4" : A.bg,
              }}
            >
              <input ref={docxRef} type="file" accept=".docx" style={{ display: "none" }}
                onChange={e => { const f = e.target.files?.[0]; if (f) setDocxFile(f); }} />
              {docxFile ? (
                <>
                  <FileText size={26} style={{ color: "#22C55E", marginBottom: 10 }} />
                  <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>{docxFile.name}</div>
                  <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
                    {(docxFile.size / 1024).toFixed(1)} KB · click to change
                  </div>
                </>
              ) : (
                <>
                  <FileText size={26} style={{ color: A.muted2, marginBottom: 10 }} />
                  <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>Drop brand brief DOCX here</div>
                  <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>Supported: .docx · max 5 MB</div>
                </>
              )}
            </div>
            {docxError && (
              <div style={{ display: "flex", alignItems: "center", gap: 8,
                color: A.red, fontSize: 13, marginBottom: 16 }}>
                <XCircle size={14} />{docxError}
              </div>
            )}
            <Btn variant="primary" disabled={!docxFile || docxLoading} onClick={handleDocxParse}
              style={{ background: docxFile && !docxLoading ? A.gold : A.muted,
                border: `1px solid ${docxFile && !docxLoading ? A.gold : A.muted}`,
                display: "flex", alignItems: "center", gap: 8 }}>
              {docxLoading
                ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Parsing…</>
                : <>Parse Brand Brief <ArrowRight size={14} /></>}
            </Btn>
          </Card>
        </div>
      )}

      {/* ── Sub-tab B: Manual Entry ── */}
      {subTab === "manual" && (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>

          {/* Form */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <Card>
              <SLabel>Brand Identity Form</SLabel>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
                <Field label="Brand Name" value={brandName} onChange={setBrandName} />
                <Field label="Brand Type" value={brandType} onChange={setBrandType}
                  placeholder="e.g. Luxury cultural travel brand" />
              </div>
              <Field label="Core Idea" value={coreIdea} onChange={setCoreIdea} rows={3}
                style={{ marginBottom: 16 }} />

              <Divider label="Target Market" />
              <Field label="Primary Markets" value={targetMarkets} onChange={setTargetMarkets}
                placeholder="US, UK, UAE" style={{ marginBottom: 12 }} />
              <Field label="Customer Segment" value={customerSegment} onChange={setCustomerSegment}
                rows={2} style={{ marginBottom: 12 }} />
              <Field label="Customer Mindset" value={customerMindset} onChange={setCustomerMindset}
                rows={2} style={{ marginBottom: 16 }} />

              <Divider label="Voice & Style" />
              <Field label="Tone of Voice" value={toneOfVoice} onChange={setToneOfVoice}
                placeholder="Elegant, Discreet, Cultured" style={{ marginBottom: 12 }} />
              <Field label="Writing Style" value={writingStyle} onChange={setWritingStyle}
                rows={3} style={{ marginBottom: 16 }} />

              <Divider label="Examples" />
              <Field label="Good Examples" value={goodExamples} onChange={setGoodExamples}
                rows={3} placeholder="One example per line" style={{ marginBottom: 12 }} />
              <Field label="Should Write" value={shouldWrite} onChange={setShouldWrite}
                rows={3} style={{ marginBottom: 12 }} />
              <Field label="Should NOT Write" value={shouldNotWrite} onChange={setShouldNotWrite}
                rows={3} placeholder="One phrase per line — becomes forbidden words list"
                style={{ marginBottom: 20 }} />

              {saveError && (
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                  color: A.red, fontSize: 13, marginBottom: 14 }}>
                  <XCircle size={14} />{saveError}
                </div>
              )}
              {savedVersion && (
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                  color: "#15803D", fontSize: 13, marginBottom: 14 }}>
                  <CheckCircle size={14} />Brand Identity saved. Version {savedVersion} active.
                </div>
              )}
              <Btn variant="primary" disabled={saving} onClick={handleSave}
                style={{ background: A.gold, border: `1px solid ${A.gold}`,
                  display: "flex", alignItems: "center", gap: 8 }}>
                {saving
                  ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Saving…</>
                  : <>Save Brand Identity <ArrowRight size={14} /></>}
              </Btn>
            </Card>
          </div>

          {/* Active brand rules sidebar */}
          <div style={{ width: 280, flexShrink: 0 }}>
            <Card>
              <SLabel>Active Brand Rules</SLabel>
              {rulesLoading ? (
                <div style={{ fontSize: 13, color: A.muted }}>Loading…</div>
              ) : brandRules?.configured ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <span style={{ fontSize: 11, color: A.muted }}>Version </span>
                    <strong style={{ color: A.gold, fontSize: 14 }}>{brandRules.version}</strong>
                    {brandRules.updated_at && (
                      <span style={{ fontSize: 11, color: A.muted2, marginLeft: 8 }}>
                        · {String(brandRules.updated_at).slice(0, 10)}
                      </span>
                    )}
                  </div>
                  {brandRules.system_prompt && (
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                        letterSpacing: "0.12em", color: A.muted, marginBottom: 4 }}>System Prompt</div>
                      <div style={{ fontSize: 12, color: A.body, lineHeight: 1.55,
                        background: A.bg, padding: "8px 10px", borderRadius: 6,
                        whiteSpace: "pre-wrap" }}>
                        {brandRules.system_prompt.slice(0, 200)}{brandRules.system_prompt.length > 200 ? "…" : ""}
                      </div>
                    </div>
                  )}
                  {brandRules.forbidden_words.length > 0 && (
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase",
                        letterSpacing: "0.12em", color: A.muted, marginBottom: 6 }}>
                        Forbidden Words ({brandRules.forbidden_words.length})
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {brandRules.forbidden_words.slice(0, 8).map((w, i) => (
                          <span key={i} style={{ fontSize: 11, padding: "2px 7px",
                            background: A.redSoft, color: A.red, borderRadius: 4 }}>{w}</span>
                        ))}
                        {brandRules.forbidden_words.length > 8 && (
                          <span style={{ fontSize: 11, color: A.muted2 }}>
                            +{brandRules.forbidden_words.length - 8} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ fontSize: 13, color: A.muted }}>No brand rules configured yet.</div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const PAGE_TABS = [
  { key: "tours", label: "Tour Content" },
  { key: "brand", label: "Brand Identity" },
];

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState("tours");

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
          <div style={{ marginBottom: 24 }}>
            <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink,
              margin: "0 0 6px", letterSpacing: "-0.01em" }}>Upload (S0)</h1>
            <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>
              Tour Content ingestion · Brand Identity management
            </p>
          </div>
          <div style={{ marginBottom: 28 }}>
            <TabBar tabs={PAGE_TABS} active={activeTab} onChange={setActiveTab} />
          </div>
          {activeTab === "tours" && <TourContentTab />}
          {activeTab === "brand" && <BrandTab />}
        </main>
      </div>
    </div>
  );
}
