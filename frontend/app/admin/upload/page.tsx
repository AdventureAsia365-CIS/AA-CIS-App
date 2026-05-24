"use client";
// app/admin/upload/page.tsx — S0 Upload: parse → data quality review → approve → run pipeline

import React, { useState, useRef, useCallback } from "react";
import * as XLSX from "xlsx";
import { useRouter } from "next/navigation";
import { Upload, FileText, CheckCircle, XCircle, ChevronDown, ChevronUp, ArrowRight, X, AlertTriangle } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans,
  Card, SLabel, Badge, Btn, LoadingScreen, TH, TD,
} from "../_components/adminUi";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/cis_api_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function scoreColor(score: number): string {
  if (score >= 9) return A.green;
  if (score >= 7) return A.amber;
  return A.red;
}

function relativeTime(dt: string): string {
  const diff = Date.now() - new Date(dt).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface ParsedRow {
  idx: number;
  name: string;
  country: string;
  duration: string;
  price: string;
  errors: string[]; // names of missing required fields
}

interface TourResult {
  idx: number;
  src_name: string;
  country: string;
  duration: string;
  status: "success" | "failed";
  quality_score: number;
  failure_codes: string[];
  generated: {
    aa_name?: string; aa_subtitle?: string; aa_summary?: string;
    aa_description?: string; aa_highlights?: string[];
    aa_itineraries?: string; mobile_card_text?: string;
    seo_title?: string; seo_meta?: string; seo_keywords_used?: string[];
  };
  cost_usd: number;
  model_used: string;
}

interface RunResult {
  batch_id: string;
  filename: string;
  run_at: string;
  summary: { total: number; successful: number; failed: number; avg_quality_score: number; total_cost_usd: number };
  results: TourResult[];
}

// ─── Excel parse ──────────────────────────────────────────────────────────────

function parseExcelFile(file: File): Promise<ParsedRow[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const wb   = XLSX.read(e.target?.result, { type: "binary" });
        const ws   = wb.Sheets[wb.SheetNames[0]];
        const rows: any[][] = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });

        // Find header row — first row whose cells include "name" or "tour"
        let headerIdx = 0;
        for (let i = 0; i < Math.min(5, rows.length); i++) {
          const lower = rows[i].map((c: any) => String(c).toLowerCase().trim());
          if (lower.some(c => c.includes("name") || c.includes("tour"))) {
            headerIdx = i;
            break;
          }
        }

        const headers = rows[headerIdx].map((c: any) => String(c).toLowerCase().trim());

        const col = (aliases: string[]) => {
          for (const a of aliases) {
            const i = headers.findIndex(h => h.includes(a));
            if (i >= 0) return i;
          }
          return -1;
        };

        const nameCol     = col(["name", "tour"]);
        const countryCol  = col(["country", "destination", "location"]);
        const durationCol = col(["duration", "nights", "days", "length"]);
        const priceCol    = col(["price", "cost", "rate", "usd"]);

        const dataRows = rows.slice(headerIdx + 1).filter(r => r.some((c: any) => String(c).trim() !== ""));

        const parsed: ParsedRow[] = dataRows.map((row, i) => {
          const name     = nameCol    >= 0 ? String(row[nameCol]    || "").trim() : "";
          const country  = countryCol >= 0 ? String(row[countryCol] || "").trim() : "";
          const duration = durationCol >= 0 ? String(row[durationCol] || "").trim() : "";
          const price    = priceCol   >= 0 ? String(row[priceCol]   || "").trim() : "";
          const errors: string[] = [];
          if (!name) errors.push("name");
          if (!country) errors.push("country");
          return { idx: i + 1, name, country, duration, price, errors };
        });

        resolve(parsed);
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = reject;
    reader.readAsBinaryString(file);
  });
}

// ─── Tour result row (expandable) ────────────────────────────────────────────

function TourRow({ tour, idx }: { tour: TourResult; idx: number }) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<"content" | "seo" | "quality">("content");
  const g = tour.generated;

  return (
    <>
      <tr style={{ cursor: "pointer" }} onClick={() => setExpanded(e => !e)}>
        <td style={TD}>{idx}</td>
        <td style={{ ...TD, fontWeight: 600 }}>{tour.src_name}</td>
        <td style={TD}>{tour.country || "—"}</td>
        <td style={TD}>{tour.duration || "—"}</td>
        <td style={{ ...TD, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {g.aa_name || "—"}
        </td>
        <td style={TD}>
          {tour.status === "success" ? (
            <span style={{ fontWeight: 700, color: scoreColor(tour.quality_score) }}>
              {tour.quality_score.toFixed(1)}
            </span>
          ) : "—"}
        </td>
        <td style={TD}>
          <Badge color={tour.status === "success" ? "green" : "red"}>{tour.status}</Badge>
        </td>
        <td style={{ ...TD, color: A.muted2 }}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} style={{ padding: "0 0 2px 0", background: A.bg }}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${A.line}` }}>
              <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                {(["content", "seo", "quality"] as const).map(t => (
                  <button key={t} onClick={e => { e.stopPropagation(); setTab(t); }} style={{
                    padding: "5px 14px", borderRadius: 6, border: "none",
                    background: tab === t ? A.ink : A.line2,
                    color: tab === t ? "#fff" : A.muted,
                    fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: sans,
                  }}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
                ))}
              </div>
              {tab === "content" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {g.aa_name && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>Name</span><div style={{ fontFamily: serif, fontSize: 17, fontWeight: 500, color: A.ink, marginTop: 2 }}>{g.aa_name}</div></div>}
                  {g.aa_subtitle && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>Subtitle</span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{g.aa_subtitle}</div></div>}
                  {g.aa_summary && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>Summary</span><div style={{ fontSize: 13, color: A.body, marginTop: 2, lineHeight: 1.6 }}>{g.aa_summary}</div></div>}
                  {g.aa_highlights && g.aa_highlights.length > 0 && (
                    <div>
                      <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>Highlights</span>
                      <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                        {g.aa_highlights.map((h, i) => <li key={i} style={{ fontSize: 13, color: A.body, marginBottom: 2 }}>{h}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              )}
              {tab === "seo" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {g.seo_title && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>SEO Title <span style={{ color: g.seo_title.length > 70 ? A.red : A.muted2 }}>({g.seo_title.length}/70)</span></span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{g.seo_title}</div></div>}
                  {g.seo_meta && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase" as const, letterSpacing: "0.1em" }}>Meta Description <span style={{ color: g.seo_meta.length > 170 ? A.red : A.muted2 }}>({g.seo_meta.length}/170)</span></span><div style={{ fontSize: 13, color: A.body, marginTop: 2, lineHeight: 1.5 }}>{g.seo_meta}</div></div>}
                </div>
              )}
              {tab === "quality" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                    <span style={{ fontFamily: serif, fontSize: 40, fontWeight: 600, color: scoreColor(tour.quality_score), lineHeight: 1 }}>
                      {tour.status === "success" ? tour.quality_score.toFixed(1) : "—"}
                    </span>
                    <div>
                      <div style={{ fontSize: 12, color: A.muted }}>Overall Score</div>
                      <div style={{ fontSize: 11, color: A.muted2 }}>Model: {tour.model_used || "—"} · Cost: ${tour.cost_usd?.toFixed(4)}</div>
                    </div>
                  </div>
                  {tour.failure_codes.length > 0 && (
                    <div>
                      <SLabel>Failure Codes</SLabel>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {tour.failure_codes.map((fc, i) => (
                          <span key={i} style={{ fontSize: 11, padding: "3px 8px", background: A.redSoft, color: A.red, borderRadius: 4, fontWeight: 600 }}>{fc}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {tour.failure_codes.length === 0 && tour.status === "success" && (
                    <div style={{ display: "flex", alignItems: "center", gap: 6, color: A.green }}>
                      <CheckCircle size={14} /><span style={{ fontSize: 13 }}>All quality checks passed</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

type Phase = "idle" | "parsing" | "previewing" | "running" | "done";

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragging, setDragging]   = useState(false);
  const [file, setFile]           = useState<File | null>(null);
  const [maxTours, setMaxTours]   = useState(5);
  const [phase, setPhase]         = useState<Phase>("idle");
  const [parseError, setParseError] = useState("");
  const [parsed, setParsed]       = useState<ParsedRow[] | null>(null);
  const [error, setError]         = useState("");
  const [result, setResult]       = useState<RunResult | null>(null);

  const ACCEPT = ".xlsx,.xls";

  async function handleFile(f: File) {
    if (!f.name.match(/\.(xlsx|xls)$/i)) {
      setParseError("Only .xlsx / .xls files are supported");
      return;
    }
    setFile(f);
    setParseError("");
    setPhase("parsing");
    try {
      const rows = await parseExcelFile(f);
      setParsed(rows);
      setPhase("previewing");
    } catch {
      setParseError("Could not parse file — check format");
      setPhase("idle");
    }
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, []);

  function resetFile() {
    setFile(null);
    setParsed(null);
    setPhase("idle");
    setParseError("");
    setError("");
    setResult(null);
  }

  async function runUpload() {
    if (!file) return;
    setPhase("running");
    setError("");
    setResult(null);

    try {
      const form = new FormData();
      form.append("file", file);
      form.append("max_tours", String(maxTours));

      const token = getToken();
      const res = await fetch(`${API_URL}/v1/pipeline/run`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Upload failed");
      }

      const data = await res.json();
      setResult({ ...data, run_at: new Date().toISOString() });
      setPhase("done");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setPhase("previewing");
    }
  }

  const errorCount   = parsed?.filter(r => r.errors.length > 0).length ?? 0;
  const successCount = result?.results.filter(r => r.status === "success").length ?? 0;
  const avgScore     = result
    ? result.results.filter(r => r.status === "success").reduce((s, r) => s + r.quality_score, 0) / (successCount || 1)
    : 0;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>

        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
            Upload Tours
          </div>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            S0 — Select Excel · Review data quality · Approve & run pipeline
          </div>
        </div>

        {/* ── Step indicator ── */}
        <div style={{ display: "flex", gap: 0, marginBottom: 28 }}>
          {[
            { n: 1, label: "Select File",     active: phase === "idle" || phase === "parsing" },
            { n: 2, label: "Data Review",     active: phase === "previewing" },
            { n: 3, label: "Run Pipeline",    active: phase === "running" },
            { n: 4, label: "Results",         active: phase === "done" },
          ].map((step, i) => {
            const done = (step.n === 1 && ["previewing","running","done"].includes(phase))
                      || (step.n === 2 && ["running","done"].includes(phase))
                      || (step.n === 3 && phase === "done");
            return (
              <div key={step.n} style={{ display: "flex", alignItems: "center", gap: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 14px", borderRadius: 20, background: step.active ? A.gold : done ? A.greenSoft : A.line2 }}>
                  <div style={{
                    width: 20, height: 20, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                    background: step.active ? "#fff" : done ? A.green : A.muted2,
                    color: step.active ? A.gold : "#fff", fontSize: 11, fontWeight: 700,
                  }}>
                    {done ? "✓" : step.n}
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: step.active ? "#fff" : done ? A.green : A.muted, whiteSpace: "nowrap" }}>
                    {step.label}
                  </span>
                </div>
                {i < 3 && <div style={{ width: 24, height: 1, background: A.line }} />}
              </div>
            );
          })}
        </div>

        {/* ── Step 1: File picker ── */}
        {(phase === "idle" || phase === "parsing") && (
          <Card style={{ marginBottom: 24 }}>
            <SLabel>Source File</SLabel>
            <div
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragging ? A.gold : A.line}`,
                borderRadius: 10, padding: "40px 24px",
                textAlign: "center" as const, cursor: "pointer",
                background: dragging ? A.goldTint : A.bg,
                transition: "all .15s", marginBottom: 16,
              }}
            >
              <input ref={fileInputRef} type="file" accept={ACCEPT} style={{ display: "none" }}
                onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
              {phase === "parsing" ? (
                <>
                  <div style={{ fontSize: 14, fontWeight: 600, color: A.gold }}>Parsing file…</div>
                  <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>Reading column headers and rows</div>
                </>
              ) : (
                <>
                  <Upload size={28} style={{ color: A.muted2, marginBottom: 10 }} />
                  <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>Drop Excel file here or click to browse</div>
                  <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>Supported: .xlsx · .xls</div>
                </>
              )}
            </div>
            {parseError && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: A.red, fontSize: 13 }}>
                <XCircle size={14} />{parseError}
              </div>
            )}
          </Card>
        )}

        {/* ── Step 2: Data quality review ── */}
        {phase === "previewing" && parsed && (
          <Card style={{ marginBottom: 24, padding: 0 }}>
            <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: `1px solid ${A.line}` }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.14em", color: A.muted }}>Data Quality Review</div>
                  {errorCount > 0
                    ? <Badge color="red">{errorCount} rows with errors</Badge>
                    : <Badge color="green">All rows valid</Badge>}
                </div>
                <div style={{ fontSize: 13, color: A.muted, marginTop: 6 }}>
                  <strong style={{ color: A.ink }}>{parsed.length}</strong> tours parsed from{" "}
                  <span style={{ color: A.gold, fontWeight: 500 }}>{file?.name}</span>
                  {errorCount > 0 && <> · <strong style={{ color: A.red }}>{errorCount}</strong> missing required fields</>}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div>
                  <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Max Tours</label>
                  <select value={maxTours} onChange={e => setMaxTours(Number(e.target.value))}
                    style={{ padding: "6px 10px", borderRadius: 6, border: `1px solid ${A.line}`, background: "#fff", fontSize: 13, color: A.body, fontFamily: sans }}>
                    {[1, 2, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n} tours</option>)}
                  </select>
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
                  <Btn variant="secondary" size="sm" onClick={resetFile}>
                    <X size={12} /> Change File
                  </Btn>
                  <Btn
                    variant="primary"
                    size="sm"
                    disabled={errorCount > 0}
                    onClick={runUpload}
                    style={{ background: errorCount > 0 ? A.muted : A.gold, border: `1px solid ${errorCount > 0 ? A.muted : A.gold}`, display: "flex", alignItems: "center", gap: 6 }}
                  >
                    {errorCount > 0
                      ? <><AlertTriangle size={12} /> Fix Errors First</>
                      : <><CheckCircle size={12} /> Approve &amp; Run S1 <ArrowRight size={12} /></>}
                  </Btn>
                </div>
              </div>
            </div>

            {error && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 20px", color: A.red, fontSize: 13, borderBottom: `1px solid ${A.line}` }}>
                <XCircle size={14} />{error}
              </div>
            )}

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={TH}>#</th>
                    <th style={TH}>Tour Name</th>
                    <th style={TH}>Country</th>
                    <th style={TH}>Duration</th>
                    <th style={TH}>Price</th>
                    <th style={TH}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.map(row => (
                    <tr key={row.idx} style={{ background: row.errors.length > 0 ? "#FFF5F5" : undefined }}>
                      <td style={TD}>{row.idx}</td>
                      <td style={{ ...TD, fontWeight: 600, color: row.errors.includes("name") ? A.red : A.ink }}>
                        {row.name || <em style={{ color: A.red, fontWeight: 400 }}>Missing</em>}
                      </td>
                      <td style={{ ...TD, color: row.errors.includes("country") ? A.red : A.body }}>
                        {row.country || <em style={{ color: A.red }}>Missing</em>}
                      </td>
                      <td style={TD}>{row.duration || "—"}</td>
                      <td style={TD}>{row.price || "—"}</td>
                      <td style={TD}>
                        {row.errors.length > 0
                          ? <Badge color="red">Missing: {row.errors.join(", ")}</Badge>
                          : <Badge color="green">OK</Badge>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        {/* ── Step 3: Running ── */}
        {phase === "running" && (
          <Card>
            <LoadingScreen msg="Running pipeline… this may take 30–90s per tour" />
          </Card>
        )}

        {/* ── Step 4: Results ── */}
        {phase === "done" && result && (
          <>
            <div style={{
              display: "flex", gap: 24, alignItems: "center",
              padding: "14px 20px", background: A.card,
              border: `1px solid ${A.line}`, borderRadius: 10,
              marginBottom: 20, flexWrap: "wrap",
            }}>
              <div style={{ fontSize: 13, color: A.body }}>
                <strong style={{ color: A.ink }}>{result.summary.total}</strong> tours imported
              </div>
              <div style={{ width: 1, height: 16, background: A.line }} />
              <div style={{ fontSize: 13, color: A.body }}>
                <strong style={{ color: A.green }}>{result.summary.successful}</strong> succeeded
                {result.summary.failed > 0 && <> · <strong style={{ color: A.red }}>{result.summary.failed}</strong> failed</>}
              </div>
              <div style={{ width: 1, height: 16, background: A.line }} />
              <div style={{ fontSize: 13, color: A.body }}>
                avg score <strong style={{ color: scoreColor(avgScore) }}>{avgScore.toFixed(1)}/10</strong>
              </div>
              <div style={{ width: 1, height: 16, background: A.line }} />
              <div style={{ fontSize: 13, color: A.muted2 }}>cost: ${result.summary.total_cost_usd.toFixed(4)}</div>
              <div style={{ width: 1, height: 16, background: A.line }} />
              <div style={{ fontSize: 12, color: A.muted2 }}>
                batch: {result.batch_id.slice(0, 8)} · {relativeTime(result.run_at)}
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <Btn variant="secondary" size="sm" onClick={resetFile}>Upload Another</Btn>
                <Btn variant="primary" size="sm" onClick={() => router.push("/admin/pipeline/s1")}
                  style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 6 }}>
                  S1 Rewrite <ArrowRight size={13} />
                </Btn>
              </div>
            </div>

            <Card style={{ padding: 0 }}>
              <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${A.line}` }}>
                <SLabel>Pipeline Results — {result.filename}</SLabel>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th style={TH}>#</th>
                      <th style={TH}>Source Name</th>
                      <th style={TH}>Country</th>
                      <th style={TH}>Duration</th>
                      <th style={TH}>Generated Name</th>
                      <th style={TH}>Score</th>
                      <th style={TH}>Status</th>
                      <th style={{ ...TH, width: 32 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.results.map((tour, i) => (
                      <TourRow key={i} tour={tour} idx={i + 1} />
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )}
      </main>
    </div>
  );
}
