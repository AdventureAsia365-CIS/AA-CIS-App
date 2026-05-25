"use client";

import React, { useState, useEffect, useRef } from "react";
import { X, ChevronRight } from "lucide-react";
import { A, serif, sans, mono, Badge } from "./adminUi";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface TourDetailFull {
  raw: {
    tour_id: string;
    src_name: string;
    src_subtitle: string | null;
    src_summary: string | null;
    src_description: string | null;
    src_highlights: string[] | null;
    src_itineraries: string | null;
    country: string | null;
    duration: string | null;
    price_raw: string | null;
    group_size: string | null;
    period: string | null;
    provider: string | null;
    inclusions: string | null;
    exclusions: string | null;
    pipeline_status: string;
    ingest_at: string | null;
  };
  generated: {
    id: string;
    version_num: number;
    created_at: string | null;
    status: string;
    aa_name: string;
    aa_subtitle: string | null;
    aa_summary: string | null;
    aa_description: string | null;
    aa_highlights: string[] | null;
    aa_itineraries: string | null;
    seo_title: string | null;
    seo_meta: string | null;
    seo_keywords_used: string[] | null;
    model_editorial: string | null;
    score_overall: number | null;
    score_brand: number | null;
    score_seo: number | null;
    score_structure: number | null;
    score_quality: number | null;
  } | null;
  published: {
    id: string;
    aa_name: string;
    aa_subtitle: string | null;
    quality_score: number | null;
    published_at: string | null;
  } | null;
}

interface HistoryRow {
  id: string;
  version_num: number;
  created_at: string | null;
  status: string;
  model_editorial: string | null;
  score_overall: number | null;
  score_brand: number | null;
  score_seo: number | null;
  score_structure: number | null;
  llm_model: string | null;
  cost_usd: number | null;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

export function scoreColor(s: number | null | undefined): string {
  if (s == null) return A.muted2;
  if (s >= 9) return A.green;
  if (s >= 7) return A.amber;
  return A.red;
}

function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function modelShort(m: string | null | undefined): string {
  if (!m) return "—";
  return m.split(".").pop()?.replace(/-v\d+:\d+$/, "") ?? m;
}

function arrayToText(arr: string[] | null | undefined): string {
  return (arr || []).join("\n");
}
function textToArray(text: string): string[] {
  return text.split("\n").map(s => s.trim()).filter(Boolean);
}
function arrayToComma(arr: string[] | null | undefined): string {
  return (arr || []).join(", ");
}
function commaToArray(text: string): string[] {
  return text.split(",").map(s => s.trim()).filter(Boolean);
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ msg, type }: { msg: string; type: "success" | "error" }) {
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 999,
      background: type === "success" ? "#15803D" : "#DC2626",
      color: "#fff", padding: "11px 18px", borderRadius: 8,
      fontSize: 13, fontWeight: 500, boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
    }}>
      {msg}
    </div>
  );
}

// ── EditableField ─────────────────────────────────────────────────────────────

function EditableField({ label, initialValue, onSave, rows, charLimit, placeholder }: {
  label: string;
  initialValue: string;
  onSave: (v: string) => Promise<void>;
  rows?: number;
  charLimit?: number;
  placeholder?: string;
}) {
  const [value, setValue] = useState(initialValue);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const lastSavedRef = useRef(initialValue);

  useEffect(() => {
    setValue(initialValue);
    lastSavedRef.current = initialValue;
  }, [initialValue]);

  async function handleBlur() {
    if (value === lastSavedRef.current || state === "saving") return;
    setState("saving");
    try {
      await onSave(value);
      lastSavedRef.current = value;
      setState("saved");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 3000);
    }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "7px 11px", borderRadius: 7,
    border: `1px solid ${state === "error" ? A.red : A.line}`,
    background: "#fff", fontSize: 13, color: A.ink, fontFamily: sans,
    boxSizing: "border-box",
    resize: rows ? "vertical" : "none",
    outline: "none",
    lineHeight: 1.5,
  };

  const statusText = state === "saving" ? "Saving…" : state === "saved" ? "✓ Saved" : state === "error" ? "Save failed" : "";
  const statusColor = state === "saving" ? A.amber : state === "saved" ? A.green : state === "error" ? A.red : "transparent";

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
          {label}
        </span>
        <span style={{ fontSize: 11, color: statusColor }}>{statusText}</span>
      </div>
      {charLimit && (
        <div style={{ fontSize: 11, textAlign: "right", marginBottom: 3, color: value.length > charLimit * 0.9 ? A.amber : A.muted2 }}>
          {value.length}/{charLimit}
        </div>
      )}
      {rows ? (
        <textarea
          value={value}
          rows={rows}
          onChange={e => setValue(e.target.value)}
          onBlur={handleBlur}
          placeholder={placeholder}
          style={inputStyle}
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={e => setValue(e.target.value)}
          onBlur={handleBlur}
          placeholder={placeholder}
          style={inputStyle}
        />
      )}
    </div>
  );
}

// ── TourDetailPanelV2 ─────────────────────────────────────────────────────────

export function TourDetailPanelV2({ tourId, tourName, rewriteCount = 0, onClose }: {
  tourId: string;
  tourName: string;
  rewriteCount?: number;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<TourDetailFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"original" | "rewrite" | "history" | "published">("original");
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    fetch(`/api/admin/tours/${tourId}/detail`)
      .then(r => r.json())
      .then(setDetail)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [tourId]);

  useEffect(() => {
    if (tab !== "history") return;
    setLoadingHistory(true);
    fetch(`/api/admin/tours/${tourId}/history`)
      .then(r => r.json())
      .then(d => setHistory(d.history || []))
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  }, [tab, tourId]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  }

  async function saveRaw(field: string, value: string | string[]) {
    const res = await fetch(`/api/admin/tours/${tourId}/raw`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
    if (!res.ok) { showToast("Save failed", "error"); throw new Error("Save failed"); }
    showToast("Saved", "success");
  }

  async function saveGenerated(field: string, value: string | string[]) {
    const genId = detail?.generated?.id;
    if (!genId) { showToast("No generated content to save", "error"); throw new Error("No generated content"); }
    const res = await fetch(`/api/admin/tours/${tourId}/generated/${genId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
    if (!res.ok) { showToast("Save failed", "error"); throw new Error("Save failed"); }
    showToast("Saved", "success");
  }

  const tabBtn = (active: boolean, disabled = false): React.CSSProperties => ({
    padding: "8px 16px", fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? A.ink : A.muted,
    cursor: disabled ? "default" : "pointer",
    background: "none", border: "none",
    borderBottom: active ? `2px solid ${A.gold}` : "2px solid transparent",
    fontFamily: sans,
    opacity: disabled ? 0.4 : 1,
  });

  const raw = detail?.raw;
  const gen = detail?.generated;
  const pub = detail?.published;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 199 }}
      />

      {/* Panel */}
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0,
        width: "70vw", background: "#fff",
        boxShadow: "-4px 0 32px rgba(0,0,0,0.14)",
        zIndex: 200, display: "flex", flexDirection: "column",
        fontFamily: sans,
      }}>
        {/* Header */}
        <div style={{ padding: "16px 24px 0", borderBottom: `1px solid ${A.line}`, flexShrink: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
            <div style={{ flex: 1, paddingRight: 12 }}>
              {/* Badges */}
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                {raw?.country && <Badge color="blue">{raw.country}</Badge>}
                {raw?.pipeline_status && (
                  <Badge color={raw.pipeline_status === "published" ? "green" : "gray"}>
                    {raw.pipeline_status}
                  </Badge>
                )}
                {gen?.score_overall != null && (
                  <Badge color={gen.score_overall >= 9 ? "green" : gen.score_overall >= 7 ? "amber" : "red"}>
                    ★ {gen.score_overall.toFixed(1)}
                  </Badge>
                )}
              </div>
              {/* Name */}
              <div style={{ fontFamily: serif, fontSize: 17, fontWeight: 600, color: A.ink, lineHeight: 1.3, marginBottom: 5 }}>
                {gen?.aa_name || tourName}
              </div>
              {/* Meta */}
              <div style={{ fontSize: 11, color: A.muted, display: "flex", gap: 12, flexWrap: "wrap" }}>
                <span>ID: {tourId.slice(0, 8)}…</span>
                {rewriteCount > 0 && <span>Rewritten: {rewriteCount}×</span>}
                {pub?.published_at && <span>Published: {relTime(pub.published_at)}</span>}
              </div>
            </div>
            <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted, padding: 4 }}>
              <X size={18} />
            </button>
          </div>
          {/* Tabs */}
          <div style={{ display: "flex" }}>
            <button style={tabBtn(tab === "original")} onClick={() => setTab("original")}>Original Content</button>
            <button style={tabBtn(tab === "rewrite", !gen)} onClick={() => gen && setTab("rewrite")}>Latest Rewrite</button>
            <button style={tabBtn(tab === "history")} onClick={() => setTab("history")}>Rewrite History</button>
            <button style={tabBtn(tab === "published", !pub)} onClick={() => pub && setTab("published")}>Published</button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
          {loading ? (
            <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Loading…</div>
          ) : !detail ? (
            <div style={{ textAlign: "center", padding: 40, color: A.red }}>Failed to load detail</div>
          ) : tab === "original" ? (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 24px" }}>
                <EditableField label="Tour Name" initialValue={raw?.src_name || ""} onSave={v => saveRaw("src_name", v)} />
                <EditableField label="Country" initialValue={raw?.country || ""} onSave={v => saveRaw("country", v)} />
                <EditableField label="Duration" initialValue={raw?.duration || ""} onSave={v => saveRaw("duration", v)} />
                <EditableField label="Group Size" initialValue={raw?.group_size || ""} onSave={v => saveRaw("group_size", v)} />
                <EditableField label="Price" initialValue={raw?.price_raw || ""} onSave={v => saveRaw("price_raw", v)} />
                <EditableField label="Period" initialValue={raw?.period || ""} onSave={v => saveRaw("period", v)} />
                <EditableField label="Provider" initialValue={raw?.provider || ""} onSave={v => saveRaw("provider", v)} />
              </div>
              <EditableField label="Summary" initialValue={raw?.src_summary || ""} onSave={v => saveRaw("src_summary", v)} rows={6} />
              <EditableField
                label="Highlights (one per line)"
                initialValue={arrayToText(raw?.src_highlights)}
                onSave={v => saveRaw("src_highlights", textToArray(v))}
                rows={4}
                placeholder="One highlight per line"
              />
              <EditableField label="Itineraries" initialValue={raw?.src_itineraries || ""} onSave={v => saveRaw("src_itineraries", v)} rows={10} />
              <EditableField label="Description" initialValue={raw?.src_description || ""} onSave={v => saveRaw("src_description", v)} rows={6} />
              <EditableField label="Inclusions" initialValue={raw?.inclusions || ""} onSave={v => saveRaw("inclusions", v)} rows={4} />
              <EditableField label="Exclusions" initialValue={raw?.exclusions || ""} onSave={v => saveRaw("exclusions", v)} rows={4} />
            </div>
          ) : tab === "rewrite" ? (
            gen ? (
              <div>
                {/* Info bar */}
                <div style={{
                  display: "flex", gap: 16, flexWrap: "wrap", padding: "10px 14px",
                  background: A.bg, borderRadius: 8, marginBottom: 20, fontSize: 12, color: A.muted,
                }}>
                  <span>Model: <strong>{modelShort(gen.model_editorial)}</strong></span>
                  <span>Score: <strong style={{ color: scoreColor(gen.score_overall) }}>{gen.score_overall?.toFixed(1) ?? "—"}</strong></span>
                  <span>Generated: <strong>{relTime(gen.created_at)}</strong></span>
                  <span>Version: <strong>v{gen.version_num}</strong></span>
                </div>
                <EditableField label="AA Name" initialValue={gen.aa_name || ""} onSave={v => saveGenerated("aa_name", v)} />
                <EditableField label="Subtitle" initialValue={gen.aa_subtitle || ""} onSave={v => saveGenerated("aa_subtitle", v)} />
                <EditableField label="Summary" initialValue={gen.aa_summary || ""} onSave={v => saveGenerated("aa_summary", v)} rows={6} />
                <EditableField
                  label="Highlights (one per line)"
                  initialValue={arrayToText(gen.aa_highlights)}
                  onSave={v => saveGenerated("aa_highlights", textToArray(v))}
                  rows={4}
                />
                <EditableField label="Itineraries" initialValue={gen.aa_itineraries || ""} onSave={v => saveGenerated("aa_itineraries", v)} rows={10} />
                <EditableField label="SEO Title" initialValue={gen.seo_title || ""} onSave={v => saveGenerated("seo_title", v)} charLimit={70} />
                <EditableField label="SEO Meta" initialValue={gen.seo_meta || ""} onSave={v => saveGenerated("seo_meta", v)} rows={3} charLimit={170} />
                <EditableField
                  label="Keywords (comma-separated)"
                  initialValue={arrayToComma(gen.seo_keywords_used)}
                  onSave={v => saveGenerated("seo_keywords_used", commaToArray(v))}
                  placeholder="keyword1, keyword2, …"
                />
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: 40, color: A.muted }}>No rewrite data yet</div>
            )
          ) : tab === "history" ? (
            loadingHistory ? (
              <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Loading history…</div>
            ) : history.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40, color: A.muted, fontSize: 13 }}>No rewrites yet</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: A.line2 }}>
                    {["Version", "Model", "Overall", "Brand", "SEO", "Cost", "Date"].map(h => (
                      <th key={h} style={{
                        padding: "8px 12px", textAlign: "left" as const,
                        fontSize: 11, fontWeight: 600, color: A.muted,
                        textTransform: "uppercase" as const, letterSpacing: "0.1em",
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={h.id} style={{ borderTop: `1px solid ${A.line}`, background: i % 2 === 0 ? "#fff" : A.bg }}>
                      <td style={{ padding: "8px 12px" }}>
                        <span style={{ fontSize: 12, padding: "2px 8px", borderRadius: 10, background: A.goldTint, color: A.gold, fontWeight: 600 }}>
                          v{h.version_num}
                        </span>
                      </td>
                      <td style={{ padding: "8px 12px", fontFamily: mono, fontSize: 11, color: A.muted }}>{modelShort(h.model_editorial)}</td>
                      <td style={{ padding: "8px 12px", fontWeight: 700, color: scoreColor(h.score_overall) }}>{h.score_overall != null ? h.score_overall.toFixed(1) : "—"}</td>
                      <td style={{ padding: "8px 12px", color: scoreColor(h.score_brand) }}>{h.score_brand != null ? h.score_brand.toFixed(1) : "—"}</td>
                      <td style={{ padding: "8px 12px", color: scoreColor(h.score_seo) }}>{h.score_seo != null ? h.score_seo.toFixed(1) : "—"}</td>
                      <td style={{ padding: "8px 12px", color: A.gold }}>{h.cost_usd != null ? `$${h.cost_usd.toFixed(4)}` : "—"}</td>
                      <td style={{ padding: "8px 12px", color: A.muted2, fontSize: 12 }}>{relTime(h.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          ) : (
            /* Published tab */
            pub ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Published Name</div>
                  <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink }}>{pub.aa_name}</div>
                </div>
                {pub.aa_subtitle && (
                  <div>
                    <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>Subtitle</div>
                    <div style={{ fontSize: 14, fontStyle: "italic", color: A.body }}>{pub.aa_subtitle}</div>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>Quality Score</div>
                  <div style={{ fontFamily: mono, fontSize: 26, fontWeight: 700, color: scoreColor(pub.quality_score) }}>
                    {pub.quality_score?.toFixed(1) ?? "—"}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: A.muted, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>Published At</div>
                  <div style={{ fontSize: 13, color: A.body }}>{relTime(pub.published_at)}</div>
                </div>
                <div style={{ borderTop: `1px solid ${A.line}`, paddingTop: 16 }}>
                  <a
                    href={`/admin/s1-rewrite?tour_id=${tourId}`}
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 6,
                      padding: "9px 18px", borderRadius: 8,
                      background: A.gold, border: `1px solid ${A.gold}`,
                      fontSize: 13, fontWeight: 600, color: "#fff", textDecoration: "none",
                    }}
                  >
                    Re-run Rewrite <ChevronRight size={13} />
                  </a>
                </div>
              </div>
            ) : (
              <div style={{ textAlign: "center", padding: 40, color: A.muted }}>Not yet published</div>
            )
          )}
        </div>
      </div>

      {toast && <Toast msg={toast.msg} type={toast.type} />}
    </>
  );
}
