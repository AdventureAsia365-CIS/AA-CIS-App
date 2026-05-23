"use client";
// app/(admin)/upload/page.tsx — CIS S0 Upload stage
// POST /v1/pipeline/run → parse Excel → run pipeline → show results

import React, { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Upload, FileText, CheckCircle, XCircle, ChevronDown, ChevronUp, ArrowRight, X } from "lucide-react";
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

interface TourResult {
  idx: number;
  src_name: string;
  country: string;
  duration: string;
  status: "success" | "failed";
  quality_score: number;
  failure_codes: string[];
  generated: {
    aa_name?: string;
    aa_subtitle?: string;
    aa_summary?: string;
    aa_description?: string;
    aa_highlights?: string[];
    aa_itineraries?: string;
    mobile_card_text?: string;
    seo_title?: string;
    seo_meta?: string;
    seo_keywords_used?: string[];
  };
  cost_usd: number;
  model_used: string;
}

interface RunResult {
  batch_id: string;
  filename: string;
  run_at: string;
  summary: {
    total: number;
    successful: number;
    failed: number;
    avg_quality_score: number;
    total_cost_usd: number;
  };
  results: TourResult[];
}

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
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: scoreColor(tour.quality_score) }}>
              {tour.quality_score.toFixed(1)}
            </span>
          ) : "—"}
        </td>
        <td style={TD}>
          <Badge color={tour.status === "success" ? "green" : "red"}>
            {tour.status}
          </Badge>
        </td>
        <td style={{ ...TD, color: A.muted2 }}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} style={{ padding: "0 0 2px 0", background: A.bg }}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${A.line}` }}>
              {/* Tab bar */}
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
                  {g.aa_name && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Name</span><div style={{ fontFamily: serif, fontSize: 17, fontWeight: 500, color: A.ink, marginTop: 2 }}>{g.aa_name}</div></div>}
                  {g.aa_subtitle && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Subtitle</span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{g.aa_subtitle}</div></div>}
                  {g.aa_summary && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Summary</span><div style={{ fontSize: 13, color: A.body, marginTop: 2, lineHeight: 1.6 }}>{g.aa_summary}</div></div>}
                  {g.aa_highlights && g.aa_highlights.length > 0 && (
                    <div>
                      <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Highlights</span>
                      <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                        {g.aa_highlights.map((h, i) => <li key={i} style={{ fontSize: 13, color: A.body, marginBottom: 2 }}>{h}</li>)}
                      </ul>
                    </div>
                  )}
                  {g.mobile_card_text && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Mobile Card</span><div style={{ fontSize: 12, color: A.body, marginTop: 2, background: A.bg, padding: "6px 10px", borderRadius: 6 }}>{g.mobile_card_text} <span style={{ color: g.mobile_card_text.length > 80 ? A.red : A.muted2 }}>({g.mobile_card_text.length}/80)</span></div></div>}
                </div>
              )}

              {tab === "seo" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {g.seo_title && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>SEO Title <span style={{ color: g.seo_title.length > 70 ? A.red : A.muted2 }}>({g.seo_title.length}/70)</span></span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{g.seo_title}</div></div>}
                  {g.seo_meta && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Meta Description <span style={{ color: g.seo_meta.length > 170 ? A.red : A.muted2 }}>({g.seo_meta.length}/170)</span></span><div style={{ fontSize: 13, color: A.body, marginTop: 2, lineHeight: 1.5 }}>{g.seo_meta}</div></div>}
                  {g.seo_keywords_used && g.seo_keywords_used.length > 0 && (
                    <div>
                      <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Keywords Used</span>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                        {g.seo_keywords_used.map((k, i) => <span key={i} style={{ fontSize: 11, padding: "3px 8px", background: A.line2, borderRadius: 4, color: A.body }}>{k}</span>)}
                      </div>
                    </div>
                  )}
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

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [maxTours, setMaxTours] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RunResult | null>(null);

  const ACCEPT = ".xlsx,.xls";

  function handleFile(f: File) {
    if (!f.name.match(/\.(xlsx|xls)$/i)) {
      setError("Only .xlsx / .xls files are supported");
      return;
    }
    setFile(f);
    setError("");
  }

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, []);

  async function runUpload() {
    if (!file) return;
    setLoading(true);
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
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  const successCount = result?.results.filter(r => r.status === "success").length ?? 0;
  const avgScore = result
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
            S0 — Parse Excel · Run pipeline · Review output
          </div>
        </div>

        {/* Input card */}
        <Card style={{ marginBottom: 24 }}>
          <SLabel>Source File</SLabel>

          {/* Dropzone */}
          <div
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? A.gold : A.line}`,
              borderRadius: 10,
              padding: "36px 24px",
              textAlign: "center",
              cursor: "pointer",
              background: dragging ? A.goldTint : A.bg,
              transition: "all .15s",
              marginBottom: 16,
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
            <Upload size={28} style={{ color: A.muted2, marginBottom: 10 }} />
            <div style={{ fontSize: 14, fontWeight: 600, color: A.ink }}>
              {file ? file.name : "Drop Excel file here or click to browse"}
            </div>
            <div style={{ fontSize: 12, color: A.muted2, marginTop: 4 }}>
              {file
                ? `${(file.size / 1024).toFixed(1)} KB · ${new Date().toLocaleTimeString()}`
                : "Supported: .xlsx · .xls"}
            </div>
          </div>

          {/* File chip */}
          {file && (
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "6px 12px", background: A.goldTint,
              border: `1px solid ${A.gold}30`, borderRadius: 6, marginBottom: 16,
            }}>
              <FileText size={13} style={{ color: A.gold }} />
              <span style={{ fontSize: 12, color: A.body, fontWeight: 500 }}>{file.name}</span>
              <span style={{ fontSize: 11, color: A.muted2 }}>{(file.size / 1024).toFixed(1)} KB</span>
              <button onClick={e => { e.stopPropagation(); setFile(null); }}
                style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex", alignItems: "center" }}>
                <X size={12} />
              </button>
            </div>
          )}

          {/* Config row */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div>
              <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>
                Tenant
              </label>
              <select disabled style={{
                padding: "7px 12px", borderRadius: 6, border: `1px solid ${A.line}`,
                background: A.bg, fontSize: 13, color: A.muted, fontFamily: sans,
              }}>
                <option>aa_internal (locked)</option>
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>
                Max Tours
              </label>
              <select
                value={maxTours}
                onChange={e => setMaxTours(Number(e.target.value))}
                style={{
                  padding: "7px 12px", borderRadius: 6, border: `1px solid ${A.line}`,
                  background: "#fff", fontSize: 13, color: A.body, fontFamily: sans,
                }}
              >
                {[1, 2, 3, 5, 10, 20].map(n => <option key={n} value={n}>{n} tours</option>)}
              </select>
            </div>
            <div style={{ marginTop: 18 }}>
              <Btn
                variant="primary"
                size="lg"
                disabled={!file || loading}
                onClick={runUpload}
                style={{ background: loading ? A.muted : A.gold, border: `1px solid ${A.gold}` }}
              >
                {loading ? "Processing…" : "Upload & Process"}
              </Btn>
            </div>
          </div>

          {error && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, color: A.red, fontSize: 13 }}>
              <XCircle size={14} />{error}
            </div>
          )}
        </Card>

        {/* Loading state */}
        {loading && (
          <Card>
            <LoadingScreen msg="Running pipeline… this may take 30–90s per tour" />
          </Card>
        )}

        {/* Results */}
        {result && !loading && (
          <>
            {/* Stats bar */}
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
              <div style={{ fontSize: 13, color: A.muted2 }}>
                cost: ${result.summary.total_cost_usd.toFixed(4)}
              </div>
              <div style={{ width: 1, height: 16, background: A.line }} />
              <div style={{ fontSize: 12, color: A.muted2 }}>
                batch: {result.batch_id.slice(0, 8)} · {relativeTime(result.run_at)}
              </div>
              <div style={{ marginLeft: "auto" }}>
                <Btn
                  variant="primary"
                  size="sm"
                  onClick={() => router.push("/pipeline/s1")}
                  style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 6 }}
                >
                  S1 Rewrite <ArrowRight size={13} />
                </Btn>
              </div>
            </div>

            {/* Results table */}
            <Card style={{ padding: 0 }}>
              <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${A.line}` }}>
                <SLabel>Ingested Tours — {result.filename}</SLabel>
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
