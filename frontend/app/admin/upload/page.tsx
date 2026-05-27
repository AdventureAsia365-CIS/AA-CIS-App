"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  Upload, CheckCircle, XCircle, ArrowRight, Loader2,
  ChevronDown, ChevronUp, FileText, Copy, RefreshCw, Search,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Btn, TH, TD, Badge,
} from "../_components/adminUi";
import { Pagination } from "../_components/Pagination";

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

const READY_PAGE_SIZE = 10;

function ToursReadySection({ tours, loading, onRefresh }: {
  tours: TourReadyItem[]; loading: boolean; onRefresh: () => void;
}) {
  const [page, setPage]               = useState(1);
  const [filterCountry, setFilterCountry] = useState("");
  const [filterFile, setFilterFile]   = useState("");

  const uniqueCountries = Array.from(new Set(
    tours.map(t => t.country).filter((c): c is string => Boolean(c))
  )).sort();
  const uniqueFiles = Array.from(new Set(
    tours.map(t => t.filename).filter((f): f is string => Boolean(f))
  )).sort();

  const filtered = tours.filter(t => {
    if (filterCountry && t.country !== filterCountry) return false;
    if (filterFile && t.filename !== filterFile) return false;
    return true;
  });
  const paginated = filtered.slice((page - 1) * READY_PAGE_SIZE, page * READY_PAGE_SIZE);

  function handleCountry(v: string) { setFilterCountry(v); setPage(1); }
  function handleFile(v: string)    { setFilterFile(v);    setPage(1); }

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
            }}>{filtered.length}</span>
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

      {/* Filters */}
      {!loading && tours.length > 0 && (
        <div style={{ padding: "10px 16px", borderBottom: `1px solid ${A.line}`, display: "flex", gap: 10 }}>
          <select value={filterCountry} onChange={e => handleCountry(e.target.value)}
            style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 12, fontFamily: sans, background: "#fff" }}>
            <option value="">All Countries</option>
            {uniqueCountries.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={filterFile} onChange={e => handleFile(e.target.value)}
            style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 12, fontFamily: sans, background: "#fff", maxWidth: 220 }}>
            <option value="">All Files</option>
            {uniqueFiles.map(f => <option key={f} value={f}>{stripUuidPrefix(f)}</option>)}
          </select>
        </div>
      )}

      {loading ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite", marginRight: 8 }} />
          Loading…
        </div>
      ) : tours.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No tours ready. Upload an Excel file above to get started.
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No tours match selected filters.
        </div>
      ) : (
        <>
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
                {paginated.map((t, i) => (
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
          {filtered.length > READY_PAGE_SIZE && (
            <div style={{ padding: "12px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
              <Pagination page={page} total={filtered.length} pageSize={READY_PAGE_SIZE} onPage={setPage} />
            </div>
          )}
        </>
      )}
    </Card>
  );
}

// ─── Section: Upload History ───────────────────────────────────────────────────

const HISTORY_PAGE_SIZE = 10;

function UploadHistorySection({ history, loading, onRefresh }: {
  history: UploadHistoryItem[]; loading: boolean; onRefresh: () => void;
}) {
  const [copied, setCopied]       = useState<string | null>(null);
  const [page, setPage]           = useState(1);
  const [dateFilter, setDateFilter] = useState("all");
  const [search, setSearch]       = useState("");

  function copyBatchId(id: string) {
    navigator.clipboard.writeText(id).catch(() => {});
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  const now = Date.now();
  const filtered = history.filter(h => {
    if (search && !stripUuidPrefix(h.filename).toLowerCase().includes(search.toLowerCase())) return false;
    if (dateFilter === "today" && (!h.parsed_at || now - new Date(h.parsed_at).getTime() > 86400000)) return false;
    if (dateFilter === "week"  && (!h.parsed_at || now - new Date(h.parsed_at).getTime() > 7 * 86400000)) return false;
    return true;
  });
  const paginated = filtered.slice((page - 1) * HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE);

  function handleSearch(v: string)   { setSearch(v);      setPage(1); }
  function handleDate(v: string)     { setDateFilter(v);  setPage(1); }

  return (
    <Card style={{ padding: 0, marginTop: 20 }}>
      <div style={{
        padding: "14px 20px", borderBottom: `1px solid ${A.line}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontFamily: serif, fontSize: 16, fontWeight: 500, color: A.ink }}>
          Upload History
        </span>
        <button onClick={onRefresh} title="Refresh"
          style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, padding: 4 }}>
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Filters */}
      {!loading && history.length > 0 && (
        <div style={{ padding: "10px 16px", borderBottom: `1px solid ${A.line}`, display: "flex", gap: 10, alignItems: "center" }}>
          <select value={dateFilter} onChange={e => handleDate(e.target.value)}
            style={{ padding: "5px 8px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 12, fontFamily: sans, background: "#fff" }}>
            <option value="all">All Time</option>
            <option value="today">Today</option>
            <option value="week">Last 7 Days</option>
          </select>
          <div style={{ display: "flex", alignItems: "center", gap: 6, border: `1px solid ${A.line}`, borderRadius: 6, padding: "5px 8px", background: "#fff", flex: 1, maxWidth: 260 }}>
            <Search size={12} style={{ color: A.muted2, flexShrink: 0 }} />
            <input
              placeholder="Search filename…"
              value={search}
              onChange={e => handleSearch(e.target.value)}
              style={{ border: "none", outline: "none", fontSize: 12, fontFamily: sans, width: "100%", background: "transparent" }}
            />
          </div>
        </div>
      )}

      {loading ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          <Loader2 size={16} style={{ animation: "spin 1s linear infinite", marginRight: 8 }} />
          Loading…
        </div>
      ) : history.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No uploads yet.
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: A.muted, fontSize: 13 }}>
          No uploads match your filters.
        </div>
      ) : (
        <>
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
                {paginated.map((h, i) => (
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
          {filtered.length > HISTORY_PAGE_SIZE && (
            <div style={{ padding: "12px 20px", borderTop: `1px solid ${A.line}`, display: "flex", justifyContent: "flex-end" }}>
              <Pagination page={page} total={filtered.length} pageSize={HISTORY_PAGE_SIZE} onPage={setPage} />
            </div>
          )}
        </>
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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function UploadPage() {
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
          <div style={{ marginBottom: 20 }}>
            <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink,
              margin: "0 0 6px", letterSpacing: "-0.01em" }}>Upload (S0)</h1>
            <p style={{ fontSize: 13, color: A.muted, margin: "0 0 4px" }}>
              Tour Content ingestion
            </p>
            <p style={{ fontSize: 12, color: A.muted2, margin: 0 }}>
              Manage brand identity settings →{" "}
              <a href="/admin/brand" style={{ color: A.gold, textDecoration: "none", fontWeight: 500 }}>
                Brand Identity page
              </a>
            </p>
          </div>
          <TourContentTab />
        </main>
      </div>
    </div>
  );
}
