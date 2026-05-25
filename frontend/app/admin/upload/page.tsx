"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  Upload, CheckCircle, XCircle, ArrowRight, Loader2,
  ChevronDown, ChevronUp, FileText, Copy, RefreshCw,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Btn, TabBar, TH, TD, Badge, LoadingScreen,
} from "../_components/adminUi";

const TENANT_ID = "00000000-0000-0000-0000-000000000001";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function stripUuidPrefix(filename: string): string {
  return filename.replace(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_/i, "");
}

function relativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return "—";
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return "Just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} minutes ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
  const d = new Date(isoStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface TourPreview {
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
}

interface BlockedTour {
  src_name: string;
  country: string | null;
  reason: "duplicate_tour" | "missing_fields";
  missing_fields?: string[];
  message: string;
}

interface DryRunResponse {
  status: "parsed" | "blocked";
  reason?: string;
  dry_run: boolean;
  batch_id?: string | null;
  ready_count?: number;
  blocked_count?: number;
  tours?: TourPreview[];
  blocked_tours?: BlockedTour[];
  message?: string;
}

interface BrandRules {
  configured: boolean;
  system_prompt: string | null;
  style_guide: string | null;
  forbidden_words: string[];
  version: number;
  updated_at: string | null;
}

interface FileState {
  id: string;
  file: File;
  status: "pending" | "uploading" | "parsing" | "parsed" | "blocked-file" | "committing" | "done" | "error";
  s3Key?: string;
  parseResult?: DryRunResponse;
  parseError?: string;
  commitResult?: { status: string; batch_id?: string; tour_count?: number };
  commitError?: string;
  expanded: boolean;
}

interface UploadHistoryItem {
  id: string;
  filename: string;
  file_size_kb: number | null;
  row_count: number | null;
  parsed_at: string | null;
  parse_error_count: number;
  batch_id: string | null;
}

interface TourReadyItem {
  tour_id: string;
  src_name: string;
  country: string | null;
  ingest_at: string | null;
  source_id: string | null;
  batch_id: string | null;
  filename: string | null;
}

// ─── StepIndicator ────────────────────────────────────────────────────────────

function StepIndicator({ step }: { step: 1 | 2 | 3 | 4 }) {
  const STEPS = [
    { n: 1 as const, label: "Select Files" },
    { n: 2 as const, label: "Upload to S3" },
    { n: 3 as const, label: "Parse & Review" },
    { n: 4 as const, label: "Commit" },
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
              padding: "7px 14px", borderRadius: 20,
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
              <div style={{ width: 20, height: 1, background: A.line }} />
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
  tour: TourPreview; idx: number; isExpanded: boolean; onToggle: () => void;
}) {
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
        <td style={{ ...TD, fontWeight: 600, color: A.ink }}>{tour.src_name || "—"}</td>
        <td style={TD}>{tour.country || "—"}</td>
        <td style={TD}>{tour.duration || "—"}</td>
        <td style={TD}>{tour.price_raw || "—"}</td>
        <td style={TD}>{tour.group_size || "—"}</td>
        <td style={TD}>{tour.period || "—"}</td>
        <td style={TD}>{tour.provider || "—"}</td>
        <td style={TD}>{tour.sku || "—"}</td>
        <td style={TD}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Badge color="green">Ready</Badge>
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
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 32px" }}>
                <div>
                  <DetailField label="Subtitle"        value={tour.src_subtitle} />
                  <DetailField label="Summary"         value={tour.src_summary} />
                  <DetailField label="Description"     value={tour.src_description} />
                  <DetailField label="Best Time to Go" value={tour.best_time_to_go} />
                  <DetailField label="Feature"         value={tour.feature} />
                </div>
                <div>
                  <DetailField label="Highlights"  value={tour.src_highlights} />
                  <DetailField label="Activities"  value={tour.activities} />
                  <DetailField label="Includes"    value={tour.inclusions} />
                  <DetailField label="Excludes"    value={tour.exclusions} />
                  <DetailField label="Itinerary"   value={itinPreview} />
                  <DetailField label="Links"       value={tour.links} />
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Brand tab helpers ────────────────────────────────────────────────────────

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

// ─── Toast ────────────────────────────────────────────────────────────────────

function Toast({ msg, type }: { msg: string; type: "success" | "error" }) {
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 999,
      background: type === "success" ? "#15803D" : "#DC2626",
      color: "#fff", padding: "12px 20px", borderRadius: 8,
      fontSize: 13, fontWeight: 500, boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
      display: "flex", alignItems: "center", gap: 8,
    }}>
      {type === "success" ? <CheckCircle size={14} /> : <XCircle size={14} />}
      {msg}
    </div>
  );
}

// ─── Section: Tours Ready for Rewrite ─────────────────────────────────────────

function ToursReadySection({ tours, loading, onRefresh }: {
  tours: TourReadyItem[]; loading: boolean; onRefresh: () => void;
}) {
  return (
    <Card style={{ padding: 0, marginTop: 32 }}>
      <div style={{
        padding: "14px 20px", borderBottom: `1px solid ${A.line}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: serif, fontSize: 16, fontWeight: 500, color: A.ink }}>
            Tours Ready for Rewrite
          </span>
          {!loading && (
            <span style={{
              fontSize: 12, background: A.goldTint, color: A.gold,
              padding: "2px 10px", borderRadius: 10, fontWeight: 700,
            }}>{tours.length}</span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button onClick={onRefresh} title="Refresh"
            style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, padding: 4 }}>
            <RefreshCw size={14} />
          </button>
          <a href="/admin/s1-rewrite" style={{
            fontSize: 12, fontWeight: 600, color: A.gold,
            textDecoration: "none", display: "flex", alignItems: "center", gap: 4,
          }}>
            Go to S1 Rewrite <ArrowRight size={12} />
          </a>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite", marginRight: 8 }} />
          Loading…
        </div>
      ) : tours.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No tours ready. Upload an Excel file above to get started.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Tour Name", "Country", "Source File", "Ingested At", "Action"].map(h => (
                  <th key={h} style={{ ...TH, textAlign: "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tours.map((t, i) => (
                <tr key={t.tour_id} style={{ background: i % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={{ ...TD, fontWeight: 600, color: A.ink }}>{t.src_name || "—"}</td>
                  <td style={TD}>{t.country || "—"}</td>
                  <td style={{ ...TD, color: A.muted, fontSize: 12 }}>
                    {t.filename ? stripUuidPrefix(t.filename) : "—"}
                  </td>
                  <td style={{ ...TD, color: A.muted, fontSize: 12 }}>{relativeTime(t.ingest_at)}</td>
                  <td style={TD}>
                    <a href={`/admin/s1-rewrite?tour_id=${t.tour_id}`} style={{
                      fontSize: 12, fontWeight: 600, color: A.gold,
                      textDecoration: "none", display: "flex", alignItems: "center", gap: 4,
                    }}>
                      Rewrite <ArrowRight size={11} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ─── Section: Upload History ───────────────────────────────────────────────────

function UploadHistorySection({ history, loading, onRefresh }: {
  history: UploadHistoryItem[]; loading: boolean; onRefresh: () => void;
}) {
  const [copied, setCopied] = useState<string | null>(null);

  function copyBatchId(id: string) {
    navigator.clipboard.writeText(id).catch(() => {});
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <Card style={{ padding: 0, marginTop: 20 }}>
      <div style={{
        padding: "14px 20px", borderBottom: `1px solid ${A.line}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontFamily: serif, fontSize: 16, fontWeight: 500, color: A.ink }}>
          Upload History (last 20)
        </span>
        <button onClick={onRefresh} title="Refresh"
          style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, padding: 4 }}>
          <RefreshCw size={14} />
        </button>
      </div>

      {loading ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite", marginRight: 8 }} />
          Loading…
        </div>
      ) : history.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No uploads yet.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["File Name", "File Size", "Tours Parsed", "Parse Errors", "Uploaded At", "Batch ID"].map((h, i) => (
                  <th key={h} style={{ ...TH, textAlign: i > 0 ? "right" : "left" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={h.id} style={{ background: i % 2 === 1 ? A.bg : "transparent" }}>
                  <td style={{ ...TD, maxWidth: 240, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
                    {stripUuidPrefix(h.filename)}
                  </td>
                  <td style={{ ...TD, textAlign: "right", color: A.muted }}>
                    {h.file_size_kb ? `${h.file_size_kb.toFixed(0)} KB` : "—"}
                  </td>
                  <td style={{ ...TD, textAlign: "right" }}>{h.row_count ?? "—"}</td>
                  <td style={{ ...TD, textAlign: "right" }}>
                    {h.parse_error_count > 0
                      ? <Badge color="red">{h.parse_error_count} errors</Badge>
                      : <span style={{ color: A.muted2, fontSize: 12 }}>0</span>}
                  </td>
                  <td style={{ ...TD, textAlign: "right", color: A.muted, fontSize: 12 }}>
                    {relativeTime(h.parsed_at)}
                  </td>
                  <td style={{ ...TD, textAlign: "right" }}>
                    {h.batch_id ? (
                      <button
                        onClick={() => copyBatchId(h.batch_id!)}
                        title="Copy batch ID"
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 4,
                          fontFamily: mono, fontSize: 11, color: copied === h.batch_id ? A.green : A.muted2,
                          background: "none", border: "none", cursor: "pointer", padding: 0,
                        }}
                      >
                        {h.batch_id.slice(0, 8)}…
                        <Copy size={10} />
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ─── Tab 1: Tour Content ──────────────────────────────────────────────────────

type Step = 1 | 2 | 3 | 4;

function TourContentTab() {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [step, setStep]         = useState<Step>(1);
  const [dragging, setDragging] = useState(false);
  const [fileStates, setFileStates] = useState<FileState[]>([]);
  const [fileError, setFileError]   = useState("");
  const [maxTours, setMaxTours]     = useState(50);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const [uploadHistory, setUploadHistory] = useState<UploadHistoryItem[]>([]);
  const [toursReady, setToursReady]       = useState<TourReadyItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [toursLoading, setToursLoading]     = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  useEffect(() => {
    setHistoryLoading(true);
    setToursLoading(true);
    fetch("/api/admin/upload-history")
      .then(r => r.ok ? r.json() : { sources: [] })
      .then(d => setUploadHistory(d.sources || []))
      .catch(() => setUploadHistory([]))
      .finally(() => setHistoryLoading(false));

    fetch("/api/admin/tours-ready")
      .then(r => r.ok ? r.json() : { tours: [] })
      .then(d => setToursReady(d.tours || []))
      .catch(() => setToursReady([]))
      .finally(() => setToursLoading(false));
  }, [refreshKey]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  }

  function updateFile(id: string, update: Partial<FileState>) {
    setFileStates(prev => prev.map(f => f.id === id ? { ...f, ...update } : f));
  }

  function addFiles(newFiles: File[]) {
    const valid = newFiles.filter(f => {
      if (!f.name.match(/\.xlsx$/i)) return false;
      if (f.size > 50 * 1024 * 1024) return false;
      return true;
    });
    if (valid.length === 0) {
      setFileError("Only .xlsx files up to 50 MB are supported");
      return;
    }
    setFileError("");
    setFileStates(prev => [
      ...prev,
      ...valid.map(f => ({
        id: `${f.name}-${Date.now()}-${Math.random()}`,
        file: f,
        status: "pending" as const,
        expanded: false,
      })),
    ]);
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    addFiles(Array.from(e.dataTransfer.files));
  }, []);

  function removeFile(id: string) {
    setFileStates(prev => prev.filter(f => f.id !== id));
  }

  function reset() {
    setStep(1); setFileStates([]); setFileError("");
    setExpandedRow(null);
  }

  async function doUploadAndParse() {
    if (fileStates.length === 0) return;
    setStep(2);

    await Promise.all(fileStates.map(async (fs) => {
      try {
        updateFile(fs.id, { status: "uploading" });

        const urlRes = await fetch("/api/admin/upload-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: fs.file.name, tenant_id: TENANT_ID }),
        });
        if (!urlRes.ok) {
          const e = await urlRes.json().catch(() => ({}));
          throw new Error(e.detail || `Failed to get upload URL (${urlRes.status})`);
        }
        const urlData: { upload_url: string; s3_key: string } = await urlRes.json();

        const putRes = await fetch(urlData.upload_url, {
          method: "PUT", body: fs.file,
          headers: { "Content-Type": fs.file.type || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
        });
        if (!putRes.ok) throw new Error(`S3 upload failed (${putRes.status})`);

        updateFile(fs.id, { status: "parsing", s3Key: urlData.s3_key });

        const parseRes = await fetch("/api/admin/ingest-s3", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ s3_key: urlData.s3_key, tenant_id: TENANT_ID, max_tours: maxTours, dry_run: true }),
        });
        if (!parseRes.ok) {
          const e = await parseRes.json().catch(() => ({}));
          throw new Error(e.detail || `Parse failed (${parseRes.status})`);
        }
        const parseData: DryRunResponse = await parseRes.json();

        updateFile(fs.id, {
          status: parseData.status === "blocked" ? "blocked-file" : "parsed",
          parseResult: parseData,
        });
      } catch (err) {
        updateFile(fs.id, {
          status: "error",
          parseError: err instanceof Error ? err.message : "Upload failed",
        });
      }
    }));

    setStep(3);
  }

  async function doCommit() {
    const toCommit = fileStates.filter(f => f.status === "parsed" && (f.parseResult?.ready_count ?? 0) > 0);
    if (toCommit.length === 0) return;

    // Atomically pre-set all statuses before rendering step 4
    setFileStates(prev => prev.map(f => {
      if (f.status === "parsed" && (f.parseResult?.ready_count ?? 0) === 0) {
        return { ...f, status: "done" as const, commitResult: { status: "skipped", tour_count: 0 } };
      }
      if (f.status === "parsed" && (f.parseResult?.ready_count ?? 0) > 0) {
        return { ...f, status: "committing" as const };
      }
      return f;
    }));
    setStep(4);

    await Promise.all(toCommit.map(async (fs) => {
      try {
        const res = await fetch("/api/admin/ingest-s3", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ s3_key: fs.s3Key, tenant_id: TENANT_ID, max_tours: maxTours, dry_run: false }),
        });
        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          throw new Error(e.detail || `Commit failed (${res.status})`);
        }
        const data = await res.json();
        updateFile(fs.id, { status: "done", commitResult: data });
      } catch (err) {
        updateFile(fs.id, {
          status: "error",
          commitError: err instanceof Error ? err.message : "Commit failed",
        });
      }
    }));

    setRefreshKey(k => k + 1);
    showToast(`Tours saved to database successfully`, "success");
  }

  const totalReady   = fileStates.reduce((n, f) => n + (f.parseResult?.ready_count ?? 0), 0);
  const totalBlocked = fileStates.reduce((n, f) => n + (f.parseResult?.blocked_count ?? 0), 0);
  const allUploading = fileStates.some(f => f.status === "uploading" || f.status === "parsing");
  const allDone      = fileStates.length > 0 && fileStates.every(f => ["done", "error", "blocked-file"].includes(f.status));

  const fileStatusColor: Record<FileState["status"], string> = {
    pending: A.muted2, uploading: A.gold, parsing: A.gold,
    parsed: A.green, "blocked-file": A.red, committing: A.gold, done: A.green, error: A.red,
  };
  const fileStatusLabel: Record<FileState["status"], string> = {
    pending: "Pending", uploading: "Uploading…", parsing: "Parsing…",
    parsed: "Ready", "blocked-file": "Blocked", committing: "Saving…", done: "Saved", error: "Error",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <StepIndicator step={step} />

      {/* ── Step 1: Select Files ── */}
      {step === 1 && (
        <div style={{ maxWidth: 620 }}>
          <Card>
            <SLabel>Source Files</SLabel>
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragging ? A.gold : A.line}`,
                borderRadius: 10, padding: "32px 24px", textAlign: "center",
                cursor: "pointer", transition: "all .15s", marginBottom: 16,
                background: dragging ? A.goldTint : A.bg,
              }}
            >
              <input ref={fileInputRef} type="file" accept=".xlsx" multiple style={{ display: "none" }}
                onChange={e => { if (e.target.files) addFiles(Array.from(e.target.files)); }} />
              <Upload size={26} style={{ color: A.muted2, marginBottom: 10 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>
                Drop Excel files here or click to browse
              </div>
              <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>
                Supported: .xlsx · max 50 MB per file · multiple files allowed
              </div>
            </div>

            {fileError && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: A.red, fontSize: 13, marginBottom: 12 }}>
                <XCircle size={14} />{fileError}
              </div>
            )}

            {/* File list */}
            {fileStates.length > 0 && (
              <div style={{ marginBottom: 16, display: "flex", flexDirection: "column", gap: 8 }}>
                {fileStates.map(fs => (
                  <div key={fs.id} style={{
                    display: "flex", alignItems: "center", gap: 10,
                    background: A.bg, borderRadius: 8, padding: "8px 12px",
                    border: `1px solid ${A.line}`,
                  }}>
                    <FileText size={14} style={{ color: A.muted2, flexShrink: 0 }} />
                    <span style={{ fontSize: 13, color: A.ink, flex: 1, minWidth: 0,
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {fs.file.name}
                    </span>
                    <span style={{ fontSize: 11, color: A.muted2, flexShrink: 0 }}>
                      {(fs.file.size / 1024).toFixed(0)} KB
                    </span>
                    <button onClick={() => removeFile(fs.id)}
                      style={{ background: "none", border: "none", cursor: "pointer",
                        color: A.muted2, padding: 0, display: "flex" }}>
                      <XCircle size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
              <div>
                <label style={{ fontSize: 12, fontWeight: 600, color: A.muted, display: "block", marginBottom: 5 }}>
                  Max tours per file
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="number" min={1} max={500} value={maxTours}
                    onChange={e => setMaxTours(Math.min(500, Math.max(1, Number(e.target.value))))}
                    style={{ width: 90, padding: "7px 10px", borderRadius: 7,
                      border: `1px solid ${A.line}`, background: "#fff",
                      fontSize: 13, color: A.ink, fontFamily: sans }} />
                  <span style={{ fontSize: 11, color: A.muted2 }}>min 1 · max 500</span>
                </div>
              </div>
            </div>

            <Btn variant="primary" disabled={fileStates.length === 0} onClick={doUploadAndParse}
              style={{
                background: fileStates.length > 0 ? A.gold : A.muted,
                border: `1px solid ${fileStates.length > 0 ? A.gold : A.muted}`,
                display: "flex", alignItems: "center", gap: 8,
              }}>
              Upload Files <ArrowRight size={14} />
            </Btn>
          </Card>
        </div>
      )}

      {/* ── Step 2: Uploading ── */}
      {step === 2 && (
        <div style={{ maxWidth: 560 }}>
          <Card>
            <SLabel>Upload to S3</SLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {fileStates.map(fs => (
                <div key={fs.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{
                    width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: fs.status === "done" || fs.status === "parsed" ? A.green
                      : fs.status === "error" ? A.red : A.gold,
                  }}>
                    {fs.status === "uploading" || fs.status === "parsing"
                      ? <Loader2 size={12} style={{ color: "#fff", animation: "spin 1s linear infinite" }} />
                      : fs.status === "error"
                        ? <XCircle size={12} style={{ color: "#fff" }} />
                        : <CheckCircle size={12} style={{ color: "#fff" }} />}
                  </div>
                  <span style={{ fontSize: 13, flex: 1, minWidth: 0,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    color: fs.status === "error" ? A.red : A.body }}>
                    {fs.file.name}
                  </span>
                  <span style={{ fontSize: 12, fontWeight: 500, color: fileStatusColor[fs.status], flexShrink: 0 }}>
                    {fileStatusLabel[fs.status]}
                  </span>
                </div>
              ))}
            </div>
            {allUploading && (
              <div style={{ marginTop: 16, color: A.muted, fontSize: 12 }}>
                Uploading and parsing files in parallel…
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ── Step 3: Parse & Review ── */}
      {step === 3 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14 }}>
            {[
              { label: "Tours Ready",   value: totalReady,   color: A.green },
              { label: "Tours Blocked", value: totalBlocked, color: totalBlocked > 0 ? A.red : A.muted2 },
              { label: "Files",         value: fileStates.length, color: A.gold },
            ].map(c => (
              <Card key={c.label}>
                <SLabel>{c.label}</SLabel>
                <div style={{ fontFamily: serif, fontSize: 28, fontWeight: 500,
                  color: c.color, letterSpacing: "-0.02em" }}>{c.value}</div>
              </Card>
            ))}
          </div>

          {/* Per-file results */}
          {fileStates.map(fs => (
            <Card key={fs.id} style={{ padding: 0,
              border: fs.status === "error" || fs.status === "blocked-file"
                ? `1px solid ${A.red}` : undefined }}>
              <div
                style={{
                  padding: "14px 20px", borderBottom: `1px solid ${A.line}`,
                  display: "flex", alignItems: "center", gap: 10,
                  cursor: "pointer",
                }}
                onClick={() => updateFile(fs.id, { expanded: !fs.expanded })}
              >
                {fs.status === "error" || fs.status === "blocked-file"
                  ? <XCircle size={14} style={{ color: A.red }} />
                  : <CheckCircle size={14} style={{ color: A.green }} />}
                <span style={{ flex: 1, fontWeight: 600, fontSize: 14, color: A.ink }}>
                  {fs.file.name}
                </span>
                {fs.status === "parsed" && (
                  <>
                    <Badge color="green">{fs.parseResult?.ready_count ?? 0} ready</Badge>
                    {(fs.parseResult?.blocked_count ?? 0) > 0 && (
                      <Badge color="red">{fs.parseResult?.blocked_count} blocked</Badge>
                    )}
                  </>
                )}
                {fs.status === "blocked-file" && (
                  <Badge color="red">File blocked</Badge>
                )}
                {fs.status === "error" && (
                  <Badge color="red">Error</Badge>
                )}
                {fs.expanded ? <ChevronUp size={14} style={{ color: A.muted2 }} /> : <ChevronDown size={14} style={{ color: A.muted2 }} />}
              </div>

              {fs.expanded && (
                <div style={{ padding: "0" }}>
                  {/* Error state */}
                  {(fs.status === "error" || fs.status === "blocked-file") && (
                    <div style={{ padding: "16px 20px", color: A.red, fontSize: 13 }}>
                      {fs.parseError || fs.parseResult?.message || "Upload failed"}
                    </div>
                  )}

                  {/* Ready tours table */}
                  {fs.status === "parsed" && (fs.parseResult?.ready_count ?? 0) > 0 && (
                    <div style={{ overflowX: "auto" }}>
                      <div style={{ padding: "10px 20px 4px", fontSize: 11, fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: "0.12em", color: A.muted }}>
                        Ready Tours
                      </div>
                      <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                          <tr>
                            {["#", "Tour Name", "Country", "Duration", "Price", "Group Size", "Period", "Provider", "SKU", "Status"].map((h, i) => (
                              <th key={h} style={{ ...TH, textAlign: i === 0 ? "center" : "left" }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(fs.parseResult?.tours ?? []).map((tour, i) => (
                            <TourRow
                              key={tour.tour_id}
                              tour={tour}
                              idx={i + 1}
                              isExpanded={expandedRow === tour.tour_id}
                              onToggle={() => setExpandedRow(prev => prev === tour.tour_id ? null : tour.tour_id)}
                            />
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Blocked tours table */}
                  {fs.status === "parsed" && (fs.parseResult?.blocked_count ?? 0) > 0 && (
                    <div style={{ overflowX: "auto" }}>
                      <div style={{ padding: "10px 20px 4px", fontSize: 11, fontWeight: 700,
                        textTransform: "uppercase", letterSpacing: "0.12em", color: A.red }}>
                        Blocked Tours
                      </div>
                      <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                          <tr>
                            {["Tour Name", "Country", "Reason", "Details"].map(h => (
                              <th key={h} style={{ ...TH, textAlign: "left" }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {(fs.parseResult?.blocked_tours ?? []).map((t, i) => (
                            <tr key={i} style={{ background: i % 2 === 1 ? A.bg : "transparent" }}>
                              <td style={{ ...TD, fontWeight: 600 }}>{t.src_name}</td>
                              <td style={TD}>{t.country || "—"}</td>
                              <td style={TD}>
                                <Badge color={t.reason === "duplicate_tour" ? "blue" : "amber"}>
                                  {t.reason === "duplicate_tour" ? "Duplicate" : "Missing Fields"}
                                </Badge>
                              </td>
                              <td style={{ ...TD, fontSize: 12, color: A.muted }}>
                                {t.reason === "missing_fields"
                                  ? (t.missing_fields ?? []).join(", ")
                                  : "Already in catalog"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </Card>
          ))}

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 12 }}>
            <Btn variant="secondary" onClick={reset}>← Upload Another</Btn>
            <Btn
              variant="primary"
              disabled={totalReady === 0}
              onClick={doCommit}
              style={{
                background: totalReady > 0 ? A.gold : A.muted,
                border: `1px solid ${totalReady > 0 ? A.gold : A.muted}`,
                display: "flex", alignItems: "center", gap: 8,
                opacity: totalReady === 0 ? 0.5 : 1,
                cursor: totalReady === 0 ? "not-allowed" : "pointer",
              }}
            >
              Confirm & Save to DB ({totalReady} tours) <ArrowRight size={14} />
            </Btn>
          </div>
        </div>
      )}

      {/* ── Step 4: Commit ── */}
      {step === 4 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <Card>
            <SLabel>Saving to Database</SLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {fileStates.filter(f => f.status !== "blocked-file").map(fs => (
                <div key={fs.id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{
                    width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
                    display: "flex", alignItems: "center", justifyContent: "center",
                    background: fs.status === "done" ? A.green
                      : fs.status === "error" ? A.red : A.gold,
                  }}>
                    {fs.status === "committing"
                      ? <Loader2 size={12} style={{ color: "#fff", animation: "spin 1s linear infinite" }} />
                      : fs.status === "error"
                        ? <XCircle size={12} style={{ color: "#fff" }} />
                        : <CheckCircle size={12} style={{ color: "#fff" }} />}
                  </div>
                  <span style={{ fontSize: 13, flex: 1, color: A.body }}>{fs.file.name}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: fileStatusColor[fs.status] }}>
                    {fs.status === "done"
                      ? `${fs.commitResult?.tour_count ?? 0} tours saved`
                      : fileStatusLabel[fs.status]}
                  </span>
                  {fs.commitError && (
                    <span style={{ fontSize: 11, color: A.red }}>{fs.commitError}</span>
                  )}
                </div>
              ))}
            </div>

            {allDone && (
              <div style={{ marginTop: 20 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                  color: "#15803D", fontSize: 14, fontWeight: 600, marginBottom: 16 }}>
                  <CheckCircle size={16} />
                  Done! Tours are ready for rewrite in S1.
                </div>
                <div style={{ display: "flex", gap: 12 }}>
                  <Btn variant="secondary" onClick={reset}>Upload More Files</Btn>
                  <a href="/admin/s1-rewrite" style={{
                    display: "inline-flex", alignItems: "center", gap: 8,
                    padding: "9px 18px", borderRadius: 8,
                    background: A.gold, border: `1px solid ${A.gold}`,
                    fontSize: 13, fontWeight: 600, color: "#fff", textDecoration: "none",
                  }}>
                    Go to S1 Rewrite <ArrowRight size={14} />
                  </a>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ── Always-visible sections ── */}
      <ToursReadySection
        tours={toursReady}
        loading={toursLoading}
        onRefresh={() => setRefreshKey(k => k + 1)}
      />
      <UploadHistorySection
        history={uploadHistory}
        loading={historyLoading}
        onRefresh={() => setRefreshKey(k => k + 1)}
      />

      {toast && <Toast msg={toast.msg} type={toast.type} />}
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

      {subTab === "manual" && (
        <div style={{ display: "flex", gap: 24, alignItems: "flex-start" }}>
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
