"use client";
// app/(internal)/catalog/page.tsx — P4 rebuild
// Full before/after review panel: raw_tours (BEFORE) vs published_tours (AFTER)
// Inline editing + field-level save

import { useState, useEffect, useCallback } from "react";
import { Search, X, ChevronDown, ChevronUp, Edit2, Check, RotateCcw } from "lucide-react";
import InternalSidebar from "../_components/InternalSidebar";
import { A, serif, mono, sans, Card, SLabel, Btn, LoadingScreen, TopBar, TH, TD } from "../_components/internalUi";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken() {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/cis_api_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

interface Tour {
  id: string; tour_id: string; aa_name: string; aa_subtitle: string;
  seo_title: string; quality_score: number | null; published_at: string;
  country?: string; duration?: string; seo_meta?: string;
  aa_summary?: string; aa_highlights?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function parseJson(v: any): any {
  if (!v) return null;
  if (typeof v === "string") { try { return JSON.parse(v); } catch { return v; } }
  return v;
}

function scoreColor(s: number | null) {
  if (!s) return A.muted;
  return s >= 9 ? "#16A34A" : s >= 8 ? A.gold : s >= 7 ? "#D97706" : "#DC2626";
}

function scoreBg(s: number | null) {
  if (!s) return A.bg;
  return s >= 9 ? "#DCFCE7" : s >= 8 ? "#FEF9C3" : s >= 7 ? "#FEF3C7" : "#FEE2E2";
}

// ─── Supplier value renderer: JSON arrays, pipe-separated, newline-split ─────
function tryParseJson(v: string): any {
  try { return JSON.parse(v); } catch {}
  // Sanitize unescaped control chars (e.g. real \n inside JSON strings) then retry
  try { return JSON.parse(v.replace(/[\r\n\t]+/g, " ")); } catch {}
  return null;
}

function renderSupplierValue(v: any) {
  if (v === null || v === undefined || v === "")
    return <span style={{ color: A.muted2, fontStyle: "italic" }}>—</span>;

  let parsed: any = v;
  if (typeof v === "string") {
    const p = tryParseJson(v);
    parsed = p !== null ? p : v;
  }

  // Flatten everything into a string[] of items
  const items: string[] = [];
  if (Array.isArray(parsed)) {
    for (const el of parsed) {
      const s = typeof el === "object" ? JSON.stringify(el) : String(el);
      // pipe-separated within array element
      s.split("|").map(x => x.trim()).filter(Boolean).forEach(x => items.push(x));
    }
  } else {
    const s = (typeof parsed === "object" && parsed !== null)
      ? JSON.stringify(parsed, null, 2)
      : String(parsed);
    if (s.includes("|")) {
      s.split("|").map(x => x.trim()).filter(Boolean).forEach(x => items.push(x));
    } else if (s.includes("\n")) {
      s.split("\n").map(x => x.trim()).filter(Boolean).forEach(x => items.push(x));
    } else if (s.includes(",") && s.split(",").length > 1) {
      // comma-delimited (common in Excel inclusions/exclusions cells)
      s.split(",").map(x => x.trim()).filter(Boolean).forEach(x => items.push(x));
    } else {
      items.push(s);
    }
  }

  if (items.length > 1) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {items.map((item, i) => (
          <div key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
            <span style={{ color: A.gold, fontWeight: 700, flexShrink: 0, lineHeight: 1.5 }}>•</span>
            <span style={{ fontSize: 12.5, color: A.body, lineHeight: 1.5 }}>{item}</span>
          </div>
        ))}
      </div>
    );
  }
  return <span style={{ fontSize: 12.5, color: A.body, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{items[0] ?? ""}</span>;
}

// ─── Diff Field Row ───────────────────────────────────────────────────────────
function DiffRow({
  label, before, after, field, tourId, onSaved,
  multiline = false, isJson = false,
}: {
  label: string; before: any; after: any; field: string; tourId: string;
  onSaved: (field: string, val: string) => void;
  multiline?: boolean; isJson?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const renderVal = (v: any) => {
    if (v === null || v === undefined || v === "") return <span style={{ color: A.muted2, fontStyle: "italic" }}>—</span>;
    if (isJson) {
      let parsed: any = v;
      if (typeof v === "string") {
        const p = tryParseJson(v);
        parsed = p !== null ? p : v;
      }
      if (Array.isArray(parsed)) {
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {parsed.map((item: any, i: number) => (
              <div key={i} style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                <span style={{ color: A.gold, fontWeight: 700, flexShrink: 0, lineHeight: 1.5 }}>•</span>
                <span style={{ fontSize: 12.5, color: A.body, lineHeight: 1.5 }}>
                  {typeof item === "object" ? JSON.stringify(item) : String(item)}
                </span>
              </div>
            ))}
          </div>
        );
      }
      return renderSupplierValue(parsed);
    }
    return <span style={{ fontSize: 12.5, color: A.body, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{String(v)}</span>;
  };

  const changed = JSON.stringify(before) !== JSON.stringify(after) && after !== null && after !== undefined;

  async function save() {
    setSaving(true);
    const token = getToken();
    try {
      const r = await fetch(`${API_URL}/v1/tours/${tourId}/approve`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ field, value: val }),
      });
      if (r.ok) { setSaved(true); onSaved(field, val); setEditing(false); setTimeout(() => setSaved(false), 2000); }
    } finally { setSaving(false); }
  }

  return (
    <div style={{
      display: "grid", gridTemplateColumns: "120px 1fr 1fr auto",
      gap: 0, borderBottom: `1px solid ${A.line}`,
      background: changed ? "#FFFDF7" : "transparent",
    }}>
      {/* Label */}
      <div style={{
        padding: "10px 12px", fontSize: 11, fontWeight: 700, color: A.muted,
        textTransform: "uppercase", letterSpacing: "0.08em", borderRight: `1px solid ${A.line}`,
        display: "flex", alignItems: "flex-start", paddingTop: 12,
        background: changed ? "#FEF9C3" : A.bg,
      }}>
        {changed && <span style={{ width: 6, height: 6, borderRadius: "50%", background: A.gold, display: "inline-block", marginRight: 6, marginTop: 3, flexShrink: 0 }} />}
        {label}
      </div>

      {/* BEFORE */}
      <div style={{ padding: "10px 14px", borderRight: `1px solid ${A.line}`, background: "rgba(239,68,68,0.03)" }}>
        {renderVal(before)}
      </div>

      {/* AFTER / editing */}
      <div style={{ padding: "10px 14px", background: changed ? "rgba(34,197,94,0.04)" : "transparent" }}>
        {editing ? (
          multiline ? (
            <textarea value={val} onChange={e => setVal(e.target.value)}
              style={{ width: "100%", minHeight: 80, fontSize: 12.5, fontFamily: sans, padding: "6px 8px",
                border: `1px solid ${A.gold}`, borderRadius: 6, resize: "vertical", outline: "none", color: A.ink, boxSizing: "border-box" }} />
          ) : (
            <input value={val} onChange={e => setVal(e.target.value)} autoFocus
              style={{ width: "100%", fontSize: 12.5, fontFamily: sans, padding: "5px 8px",
                border: `1px solid ${A.gold}`, borderRadius: 6, outline: "none", color: A.ink, boxSizing: "border-box" }} />
          )
        ) : renderVal(after)}
      </div>

      {/* Actions */}
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "flex-start", gap: 4, flexShrink: 0 }}>
        {editing ? (
          <>
            <button onClick={save} disabled={saving}
              style={{ padding: "4px 10px", fontSize: 11, fontWeight: 600, background: saving ? A.line : "#16A34A",
                color: "#fff", border: "none", borderRadius: 5, cursor: "pointer", fontFamily: sans }}>
              {saving ? "…" : "Save"}
            </button>
            <button onClick={() => setEditing(false)}
              style={{ padding: "4px 8px", fontSize: 11, background: A.bg, border: `1px solid ${A.line}`,
                color: A.muted, borderRadius: 5, cursor: "pointer", fontFamily: sans }}>
              ✕
            </button>
          </>
        ) : (
          <button onClick={() => { setVal(typeof after === "object" ? JSON.stringify(after, null, 2) : String(after ?? "")); setEditing(true); }}
            title="Edit this field"
            style={{ padding: "4px 8px", fontSize: 11, background: "none", border: `1px solid ${A.line}`,
              color: A.muted, borderRadius: 5, cursor: "pointer", fontFamily: sans, display: "flex", alignItems: "center", gap: 4 }}>
            <Edit2 size={10} /> Edit
          </button>
        )}
        {saved && <span style={{ fontSize: 10, color: "#16A34A", paddingTop: 6 }}>✓</span>}
      </div>
    </div>
  );
}

// ─── Section Toggle ───────────────────────────────────────────────────────────
function Section({ title, children, defaultOpen = true }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ border: `1px solid ${A.line}`, borderRadius: 10, overflow: "hidden", marginBottom: 12 }}>
      <button onClick={() => setOpen(p => !p)}
        style={{ width: "100%", display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "10px 16px", background: A.bg, border: "none", cursor: "pointer", fontFamily: sans }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: A.ink, textTransform: "uppercase", letterSpacing: "0.1em" }}>{title}</span>
        {open ? <ChevronUp size={14} color={A.muted} /> : <ChevronDown size={14} color={A.muted} />}
      </button>
      {open && (
        <div>
          {/* Column headers */}
          <div style={{ display: "grid", gridTemplateColumns: "120px 1fr 1fr auto",
            background: "#F1F5F9", borderTop: `1px solid ${A.line}`, borderBottom: `1px solid ${A.line}` }}>
            <div style={{ padding: "6px 12px", fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.1em", borderRight: `1px solid ${A.line}` }}>Field</div>
            <div style={{ padding: "6px 14px", fontSize: 10, fontWeight: 700, color: "#DC2626", textTransform: "uppercase", letterSpacing: "0.1em", borderRight: `1px solid ${A.line}` }}>BEFORE (Raw Supplier)</div>
            <div style={{ padding: "6px 14px", fontSize: 10, fontWeight: 700, color: "#16A34A", textTransform: "uppercase", letterSpacing: "0.1em" }}>AFTER (AI Rewrite)</div>
            <div style={{ padding: "6px 10px", fontSize: 10, color: A.muted2, width: 80 }}></div>
          </div>
          {children}
        </div>
      )}
    </div>
  );
}

// ─── Full Review Panel ────────────────────────────────────────────────────────
function ReviewPanel({ tour, onClose }: { tour: Tour; onClose: () => void }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [published, setPublished] = useState<any>(null);

  useEffect(() => {
    const token = getToken();
    const adminSecret = process.env.NEXT_PUBLIC_ADMIN_SECRET || "";
    fetch(`/api/tour-full/${tour.id}`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(adminSecret ? { "X-Admin-Secret": adminSecret } : {}),
      },
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => { setData(d); setPublished(d?.published); setLoading(false); })
      .catch(() => setLoading(false));
  }, [tour.id]);

  function handleSaved(field: string, val: string) {
    setPublished((p: any) => ({ ...p, [field]: val }));
  }

  const raw = data?.raw ?? {};
  const pt  = published ?? data?.published ?? {};
  const gen = data?.generated ?? {};
  const qs  = data?.quality ?? {};
  const seo = data?.seo ?? {};
  const sc  = tour.quality_score;

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 100,
      display: "flex", alignItems: "stretch", justifyContent: "flex-end",
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: "min(1100px, 92vw)", background: A.card, display: "flex", flexDirection: "column",
        boxShadow: "-8px 0 40px rgba(0,0,0,0.18)", overflowY: "auto",
      }}>
        {/* Header */}
        <div style={{
          padding: "16px 24px", borderBottom: `1px solid ${A.line}`,
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          position: "sticky", top: 0, background: A.card, zIndex: 10,
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: serif, fontSize: 18, fontWeight: 500, color: A.ink, letterSpacing: "-0.01em", marginBottom: 4 }}>
              {pt.aa_name || tour.aa_name}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              {raw.country && <span style={{ fontSize: 11, padding: "2px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 20, color: A.muted }}>{raw.country}</span>}
              {raw.duration && <span style={{ fontSize: 11, padding: "2px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 20, color: A.muted }}>{raw.duration}</span>}
              {raw.price_raw && <span style={{ fontSize: 11, padding: "2px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 20, color: A.muted }}>{raw.price_raw}</span>}
              {raw.provider && <span style={{ fontSize: 11, padding: "2px 8px", background: "#EFF6FF", border: "1px solid #BFDBFE", borderRadius: 20, color: "#2563EB" }}>Provider: {raw.provider}</span>}
              {raw.sku && <span style={{ fontSize: 11, fontFamily: mono, padding: "2px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 20, color: A.muted2 }}>SKU: {raw.sku}</span>}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0, marginLeft: 16 }}>
            {sc !== null && (
              <div style={{ textAlign: "center", padding: "6px 14px", background: scoreBg(sc), borderRadius: 8, border: `1px solid ${scoreColor(sc)}40` }}>
                <div style={{ fontFamily: mono, fontSize: 22, fontWeight: 700, color: scoreColor(sc) }}>★ {sc.toFixed(1)}</div>
                <div style={{ fontSize: 10, color: scoreColor(sc), fontWeight: 600, marginTop: 1 }}>Quality Score</div>
              </div>
            )}
            {gen.model_editorial && (
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 10, color: A.muted2, marginBottom: 2 }}>Model</div>
                <code style={{ fontSize: 11, color: A.gold, fontFamily: mono }}>{gen.model_editorial?.split("/").pop()}</code>
              </div>
            )}
            <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted, padding: 4 }}>
              <X size={20} />
            </button>
          </div>
        </div>

        {loading ? <LoadingScreen msg="Loading full tour data…" /> : !data ? (
          <div style={{ padding: 40, textAlign: "center", color: "#DC2626", fontSize: 13 }}>Failed to load tour data</div>
        ) : (
          <div style={{ padding: "20px 24px 48px" }}>

            {/* Pipeline info bar */}
            <div style={{ display: "flex", gap: 16, padding: "10px 16px", background: A.bg, borderRadius: 8, border: `1px solid ${A.line}`, marginBottom: 16, flexWrap: "wrap" }}>
              {[
                { l: "Status",     v: gen.status ?? pt.approved_by ? "exported" : "—" },
                { l: "Version",    v: gen.version_num ? `v${gen.version_num}` : "—" },
                { l: "Brand Rules v", v: gen.brand_rules_version ?? "—" },
                { l: "Prompt",     v: gen.prompt_version ?? "—" },
                { l: "Approved by", v: pt.approved_by ?? "auto" },
                { l: "Published",  v: pt.published_at ? new Date(pt.published_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—" },
              ].map(({ l, v }) => (
                <div key={l} style={{ minWidth: 100 }}>
                  <div style={{ fontSize: 10, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>{l}</div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: A.ink, fontFamily: mono }}>{String(v)}</div>
                </div>
              ))}
            </div>

            {/* Core content */}
            <Section title="Core Content">
              <DiffRow label="Name"        before={raw.src_name}        after={pt.aa_name}        field="aa_name"        tourId={tour.id} onSaved={handleSaved} />
              <DiffRow label="Subtitle"    before={raw.src_subtitle}    after={pt.aa_subtitle}    field="aa_subtitle"    tourId={tour.id} onSaved={handleSaved} />
              <DiffRow label="Summary"     before={raw.src_summary}     after={pt.aa_summary}     field="aa_summary"     tourId={tour.id} onSaved={handleSaved} multiline />
              {/* <DiffRow label="Description" before={raw.src_description} after={pt.aa_description} field="aa_description" tourId={tour.id} onSaved={handleSaved} multiline /> */}
              {/* <DiffRow label="Mobile Card" before={null}                after={pt.mobile_card_text} field="mobile_card_text" tourId={tour.id} onSaved={handleSaved} /> */}
            </Section>

            {/* Highlights */}
            <Section title="Highlights">
              <DiffRow label="Highlights" before={raw.src_highlights} after={pt.aa_highlights} field="aa_highlights" tourId={tour.id} onSaved={handleSaved} isJson multiline />
            </Section>

            {/* Itineraries */}
            <Section title="Itineraries" defaultOpen={false}>
              <DiffRow label="Itineraries" before={raw.src_itineraries} after={pt.aa_itineraries} field="aa_itineraries" tourId={tour.id} onSaved={handleSaved} multiline />
            </Section>

            {/* SEO */}
            <Section title="SEO">
              <DiffRow label="SEO Title"       before={raw.src_name}       after={pt.seo_title}       field="seo_title" tourId={tour.id} onSaved={handleSaved} />
              <DiffRow label="Meta Desc"       before={null}               after={pt.seo_meta}        field="seo_meta"  tourId={tour.id} onSaved={handleSaved} multiline />
              <DiffRow label="Keyword Search"  before={null}               after={seo.keyword_search} field="seo_meta"  tourId={tour.id} onSaved={handleSaved} />
              <DiffRow label="Top Keywords"    before={null}               after={seo.top_keywords}   field="seo_meta"  tourId={tour.id} onSaved={handleSaved} isJson />
              <DiffRow label="Keyword Ideas"   before={null}               after={seo.keyword_ideas}  field="seo_meta"  tourId={tour.id} onSaved={handleSaved} isJson />
              {seo.fetched_at && (
                <div style={{ padding: "6px 14px", fontSize: 10.5, color: A.muted2, borderTop: `1px solid ${A.line}`, fontFamily: mono }}>
                  SEO data fetched: {new Date(seo.fetched_at).toLocaleString("en-GB")}
                </div>
              )}
            </Section>

            {/* Audit / Validation */}
            {qs && Object.keys(qs).length > 0 && (
              <Section title="Audit / Validation" defaultOpen={false}>
                <div style={{ padding: "14px 16px", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))", gap: 12 }}>
                  {[
                    { l: "Overall",   v: qs.score_overall },
                    { l: "Brand",     v: qs.score_brand },
                    { l: "SEO",       v: qs.score_seo },
                    { l: "Structure", v: qs.score_structure },
                    { l: "Quality",   v: qs.score_quality },
                  ].map(({ l, v }) => {
                    const score = typeof v === "number" ? v : parseFloat(v ?? 0);
                    const color = score >= 9 ? "#16A34A" : score >= 7 ? A.gold : "#DC2626";
                    return (
                      <div key={l} style={{ background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, padding: "10px 12px" }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>{l}</div>
                        <div style={{ fontFamily: mono, fontSize: 20, fontWeight: 700, color }}>{score.toFixed(1)}</div>
                      </div>
                    );
                  })}
                  <div style={{ background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, padding: "10px 12px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Passed</div>
                    <div style={{ fontFamily: mono, fontSize: 20, fontWeight: 700, color: "#16A34A" }}>{qs.passed_count ?? 0}</div>
                  </div>
                  <div style={{ background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, padding: "10px 12px" }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Failed</div>
                    <div style={{ fontFamily: mono, fontSize: 20, fontWeight: 700, color: qs.failed_count > 0 ? "#DC2626" : A.muted2 }}>{qs.failed_count ?? 0}</div>
                  </div>
                </div>
                {qs.evaluated_at && (
                  <div style={{ padding: "6px 14px 10px", fontSize: 10.5, color: A.muted2, fontFamily: mono }}>
                    Evaluated: {new Date(qs.evaluated_at).toLocaleString("en-GB")}
                  </div>
                )}
              </Section>
            )}

            {/* Raw supplier extras */}
            <Section title="Supplier Data (Read Only)" defaultOpen={false}>
              {[
                { l: "Inclusions",    v: raw.inclusions },
                { l: "Exclusions",    v: raw.exclusions },
                { l: "Activities",    v: raw.activities },
                { l: "Group Size",    v: raw.group_size },
                { l: "Period",        v: raw.period },
                { l: "Best Time",     v: raw.best_time_to_go },
                { l: "Feature",       v: raw.feature },
              ].map(({ l, v }) => (
                <div key={l} style={{ display: "grid", gridTemplateColumns: "120px 1fr", borderBottom: `1px solid ${A.line}` }}>
                  <div style={{ padding: "8px 12px", fontSize: 11, fontWeight: 700, color: A.muted, textTransform: "uppercase", letterSpacing: "0.08em", background: A.bg, borderRight: `1px solid ${A.line}` }}>{l}</div>
                  <div style={{ padding: "8px 14px" }}>{renderSupplierValue(v)}</div>
                </div>
              ))}
            </Section>

          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function CatalogPage() {
  const [tours, setTours]     = useState<Tour[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [search, setSearch]   = useState("");
  const [page, setPage]       = useState(1);
  const [total, setTotal]     = useState(0);
  const [selected, setSelected] = useState<Tour | null>(null);
  const [isAdmin, setIsAdmin]   = useState(false);
  const [userName, setUserName] = useState("Content");

  // ── AA-27 filters ──────────────────────────────────────────────────────────
  const [filterCountry,  setFilterCountry]  = useState("");
  const [filterStatus,   setFilterStatus]   = useState("");   // quality tier
  const [filterProvider, setFilterProvider] = useState("");   // UI only (not in list response)
  const [filterMinScore, setFilterMinScore] = useState("");
  const [filterMaxScore, setFilterMaxScore] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo,   setFilterDateTo]   = useState("");

  // ── AA-28 multi-select ─────────────────────────────────────────────────────
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const role = document.cookie.split(";").find(c => c.trim().startsWith("cis_role="))?.split("=")[1];
    const name = document.cookie.split(";").find(c => c.trim().startsWith("cis_user="))?.split("=")[1];
    setIsAdmin(role === "admin");
    if (name) setUserName(decodeURIComponent(name));
  }, []);

  useEffect(() => {
    const token = getToken();
    if (!token) { setError("Not authenticated"); setLoading(false); return; }
    fetch(`${API_URL}/v1/tours?page=${page}&page_size=20`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => { setTours(d.data || []); setTotal(d.pagination?.total || 0); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [page]);

  const filtered = tours.filter(t => {
    if (search && !t.aa_name?.toLowerCase().includes(search.toLowerCase()) &&
        !t.aa_subtitle?.toLowerCase().includes(search.toLowerCase())) return false;
    if (filterCountry && !(t.country ?? "").toLowerCase().includes(filterCountry.toLowerCase())) return false;
    const sc = t.quality_score;
    if (filterStatus === "excellent"    && (sc == null || sc < 9))  return false;
    if (filterStatus === "good"         && (sc == null || sc < 8 || sc >= 9)) return false;
    if (filterStatus === "needs_review" && (sc != null && sc >= 8)) return false;
    if (filterMinScore !== "" && (sc == null || sc < parseFloat(filterMinScore))) return false;
    if (filterMaxScore !== "" && (sc == null || sc > parseFloat(filterMaxScore))) return false;
    if (filterDateFrom && t.published_at < filterDateFrom) return false;
    if (filterDateTo   && t.published_at > filterDateTo + "T23:59:59") return false;
    return true;
  });

  function exportSelected(fmt: "csv" | "xlsx") {
    const rows = filtered.filter(t => selectedIds.has(t.id));
    const cols: (keyof Tour)[] = ["aa_name","aa_subtitle","country","duration","seo_title","seo_meta","aa_summary","aa_highlights","quality_score","published_at"];
    const headers = ["Name","Subtitle","Country","Duration","SEO Title","SEO Meta","Summary","Highlights","Quality Score","Published At"];

    function cellVal(t: Tour, col: keyof Tour): string {
      const v = t[col];
      if (col === "aa_highlights" && v) {
        try {
          const parsed = typeof v === "string" ? JSON.parse(v as string) : v;
          if (Array.isArray(parsed)) return parsed.map((x: any) => (typeof x === "string" ? x : JSON.stringify(x))).join(" | ");
        } catch {}
      }
      if (col === "quality_score") return v != null ? String(v) : "";
      if (col === "published_at" && v) return new Date(v as string).toLocaleDateString("en-GB");
      return String(v ?? "");
    }

    if (fmt === "csv") {
      const csv = [headers, ...rows.map(t => cols.map(c => `"${cellVal(t, c).replace(/"/g,'""')}"`))].map(r => r.join(",")).join("\n");
      const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "catalog-export.csv"; a.click(); URL.revokeObjectURL(url);
    } else {
      const tsv = [headers, ...rows.map(t => cols.map(c => cellVal(t, c)))].map(r => r.join("\t")).join("\n");
      const blob = new Blob(["﻿" + tsv], { type: "application/vnd.ms-excel" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "catalog-export.xls"; a.click(); URL.revokeObjectURL(url);
    }
  }

  const allPageSelected = filtered.length > 0 && filtered.every(t => selectedIds.has(t.id));

  function toggleAll() {
    if (allPageSelected) {
      setSelectedIds(prev => { const n = new Set(prev); filtered.forEach(t => n.delete(t.id)); return n; });
    } else {
      setSelectedIds(prev => { const n = new Set(prev); filtered.forEach(t => n.add(t.id)); return n; });
    }
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <InternalSidebar isAdmin={isAdmin} userName={userName} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <TopBar breadcrumb={["Content", "Catalog"]} />
        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          {/* Header */}
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em" }}>Published Catalog</h1>
              <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>Gold layer — {total} tours. Click any row to review before/after AI rewrite.</p>
            </div>
            <div style={{ display: "flex", gap: 28 }}>
              {[
                { label: "Total Tours", value: total,        color: "#16A34A" },
                { label: "This Page",   value: tours.length, color: A.gold },
              ].map(s => (
                <div key={s.label} style={{ textAlign: "center" }}>
                  <div style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: s.color, letterSpacing: "-0.02em" }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: A.muted, marginTop: 2 }}>{s.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Filter bar — AA-27 */}
          <div style={{ background: A.card, border: `1px solid ${A.line}`, borderRadius: 10, padding: "14px 16px", marginBottom: 16, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
            {/* Search */}
            <div style={{ flex: "1 1 200px", minWidth: 160 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Search</div>
              <div style={{ position: "relative" }}>
                <Search size={12} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: A.muted2 }} />
                <input type="text" placeholder="Name or subtitle…" value={search} onChange={e => setSearch(e.target.value)}
                  style={{ width: "100%", padding: "7px 10px 7px 28px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 12, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
              </div>
            </div>
            {/* Country */}
            <div style={{ flex: "0 1 130px", minWidth: 100 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Country</div>
              <input type="text" placeholder="e.g. Sri Lanka" value={filterCountry} onChange={e => setFilterCountry(e.target.value)}
                style={{ width: "100%", padding: "7px 10px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 12, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
            </div>
            {/* Status (quality tier) */}
            <div style={{ flex: "0 1 150px", minWidth: 120 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Status</div>
              <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
                style={{ width: "100%", padding: "7px 10px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 12, outline: "none", fontFamily: sans, boxSizing: "border-box" }}>
                <option value="">All</option>
                <option value="excellent">Excellent (9+)</option>
                <option value="good">Good (8–9)</option>
                <option value="needs_review">Needs Review (&lt;8)</option>
              </select>
            </div>
            {/* Quality score range */}
            <div style={{ flex: "0 1 160px", minWidth: 130 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Score Range</div>
              <div style={{ display: "flex", gap: 4 }}>
                <input type="number" placeholder="Min" min={0} max={10} step={0.1} value={filterMinScore} onChange={e => setFilterMinScore(e.target.value)}
                  style={{ flex: 1, padding: "7px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 12, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
                <input type="number" placeholder="Max" min={0} max={10} step={0.1} value={filterMaxScore} onChange={e => setFilterMaxScore(e.target.value)}
                  style={{ flex: 1, padding: "7px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 12, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
              </div>
            </div>
            {/* Date range */}
            <div style={{ flex: "0 1 240px", minWidth: 200 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: A.muted2, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Published Date</div>
              <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <input type="date" value={filterDateFrom} onChange={e => setFilterDateFrom(e.target.value)}
                  style={{ flex: 1, padding: "6px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 11, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
                <span style={{ color: A.muted2, fontSize: 11 }}>–</span>
                <input type="date" value={filterDateTo} onChange={e => setFilterDateTo(e.target.value)}
                  style={{ flex: 1, padding: "6px 8px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, color: A.body, fontSize: 11, outline: "none", fontFamily: sans, boxSizing: "border-box" }} />
              </div>
            </div>
            {/* Clear + export */}
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexShrink: 0 }}>
              {(search || filterCountry || filterStatus || filterMinScore || filterMaxScore || filterDateFrom || filterDateTo) && (
                <button onClick={() => { setSearch(""); setFilterCountry(""); setFilterStatus(""); setFilterProvider(""); setFilterMinScore(""); setFilterMaxScore(""); setFilterDateFrom(""); setFilterDateTo(""); }}
                  style={{ padding: "7px 14px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, fontSize: 12, color: A.muted, cursor: "pointer", fontFamily: sans }}>
                  ✕ Clear
                </button>
              )}
              {selectedIds.size > 0 && (
                <div style={{ display: "flex", gap: 6 }}>
                  <button onClick={() => exportSelected("csv")}
                    style={{ padding: "7px 14px", background: "#22C55E", border: "none", borderRadius: 6, fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: sans }}>
                    ↓ CSV ({selectedIds.size})
                  </button>
                  <button onClick={() => exportSelected("xlsx")}
                    style={{ padding: "7px 14px", background: A.gold, border: "none", borderRadius: 6, fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: sans }}>
                    ↓ Excel ({selectedIds.size})
                  </button>
                </div>
              )}
            </div>
          </div>

          {error && <div style={{ padding: "10px 14px", background: "#FEE2E2", borderRadius: 8, color: "#DC2626", fontSize: 13, marginBottom: 14 }}>{error}</div>}

          {loading ? <LoadingScreen msg="Loading catalog…" /> : (
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={{ ...TH, width: 36, paddingRight: 0 }}>
                      <input type="checkbox" checked={allPageSelected} onChange={toggleAll}
                        style={{ cursor: "pointer", accentColor: A.gold }} />
                    </th>
                    {["Tour Name", "Subtitle", "Country", "SEO Title", "Score", "Published"].map((h, i) => (
                      <th key={h} style={{ ...TH, textAlign: i >= 4 ? "right" : "left" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(item => {
                    const sc = item.quality_score;
                    const isChecked = selectedIds.has(item.id);
                    return (
                      <tr key={item.id}
                        style={{ cursor: "pointer", transition: "background .1s", background: isChecked ? "#FFFDF7" : undefined }}
                        onMouseEnter={e => { if (!isChecked) (e.currentTarget as HTMLElement).style.background = "#FFFDF7"; }}
                        onMouseLeave={e => { if (!isChecked) (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
                        <td style={{ ...TD, paddingRight: 0, width: 36 }} onClick={e => e.stopPropagation()}>
                          <input type="checkbox" checked={isChecked}
                            onChange={() => setSelectedIds(prev => { const n = new Set(prev); isChecked ? n.delete(item.id) : n.add(item.id); return n; })}
                            style={{ cursor: "pointer", accentColor: A.gold }} />
                        </td>
                        <td style={{ ...TD, fontWeight: 600, color: A.ink, maxWidth: 180 }} onClick={() => setSelected(item)}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.aa_name}</div>
                        </td>
                        <td style={{ ...TD, color: A.muted, fontSize: 12, maxWidth: 200 }} onClick={() => setSelected(item)}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.aa_subtitle}</div>
                        </td>
                        <td style={{ ...TD, fontSize: 12, color: A.muted2 }} onClick={() => setSelected(item)}>{item.country ?? "—"}</td>
                        <td style={{ ...TD, color: A.muted2, fontSize: 11, fontFamily: mono, maxWidth: 180 }} onClick={() => setSelected(item)}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.seo_title}</div>
                        </td>
                        <td style={{ ...TD, textAlign: "right" }} onClick={() => setSelected(item)}>
                          <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 13, color: scoreColor(sc),
                            background: scoreBg(sc), padding: "2px 8px", borderRadius: 6 }}>
                            ★ {sc?.toFixed(1) ?? "—"}
                          </span>
                        </td>
                        <td style={{ ...TD, textAlign: "right", fontSize: 11.5, color: A.muted, fontFamily: mono }} onClick={() => setSelected(item)}>
                          {item.published_at ? new Date(item.published_at).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                  {filtered.length === 0 && (
                    <tr><td colSpan={7} style={{ padding: "48px 0", textAlign: "center", color: A.muted, fontSize: 13 }}>No tours found</td></tr>
                  )}
                </tbody>
              </table>
            </Card>
          )}

          {total > 20 && (
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
              <Btn variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(p => Math.max(1, p-1))}>← Prev</Btn>
              <span style={{ padding: "5px 14px", fontSize: 12, color: A.muted, alignSelf: "center" }}>Page {page} of {Math.ceil(total/20)}</span>
              <Btn variant="secondary" size="sm" disabled={tours.length < 20} onClick={() => setPage(p => p+1)}>Next →</Btn>
            </div>
          )}
        </main>
      </div>

      {selected && <ReviewPanel tour={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
