"use client";
// app/admin/tenant-activity/page.tsx — AA-568, replaces AA-551's 3-tab page (Write/Gate/Review/
// Publish) with ONE merged "06 · Content Trace" table.
//
// STEP0 (this issue's own Linear comment, 09/09/2026 — full trace docs/implementation-notes/
// AA-568.md) confirmed no gap blocks this build: Angle (all 3 + chosen flag) and Gate (specific
// violation text, not just counts) are both fully available on `GET /admin/a4/content-log`.
// Retry has REAL data (which gate blocked a round + the exact violation text fed back to the
// writer, from `repair_log`) but NOT a content diff — the intermediate attempt's prose was never
// persisted anywhere (traced to `services/acp_content_writing/service.py`'s write loop, which
// overwrites one `content_text` variable per attempt). Per Nghiệp's confirmed default (STEP0
// comment), retries below are labeled "Retry reason" / "what was fed back to the writer to
// rewrite", never "what changed" — a real content-diff view is AA-570's separate scope.
//
// This page also confirms AA-558's finding for real: the old "06 Write/Gate" and "07 Review" tabs
// called the exact same endpoint (`/admin/a4/content-log`) for the exact same rows, just under 2
// tab labels — merging removes that literal duplication, not just a UI simplification. "08
// Publish" (`/admin/a4/publish-log`) is now folded in too: AA-568 extended `content-log` itself
// to carry `publish_external_url`/`publish_published_at` so this page needs exactly ONE backend
// call, not three.
//
// Per-tenant, cross-tenant-by-default (A4 pattern, AA-437) — Tenant filter defaults to "All
// tenants", never hard-scoped to one. Admin-only route (unchanged from AA-551,
// middleware.ts PROTECTED_ROUTES already allowlists `/admin/tenant-activity`), genuinely a peer
// of 01-05 in Social Content — see AdminSidebar.tsx / atom-curation/page.tsx's inner-nav link,
// both restyled by this same build to read as one equal list, not a visually-demoted "06-08"
// link tacked on below a divider.
import { Fragment, useState, useEffect, useCallback, useMemo } from "react";
import { ChevronDown, ChevronRight, Radio } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, Badge, LoadingScreen } from "../_components/adminUi";
import { fetchJson, EmptyState, ErrorState } from "../_components/auditPanels";

// ── Types — match GET /api/admin/a4/content-log's response (AA-568 extension) ──────────────────

interface AngleOption {
  option_id: string; idx: number; name: string; why_it_works: string; formula_fit: string;
  best_final_style: string; recommended: boolean; chosen: boolean;
}
interface GateEntry { gate?: string; passed?: boolean; violations?: string[]; repairable?: boolean; blocking?: boolean; }
interface RepairRound { attempt?: number; gate_targeted?: string; violations?: string[]; repairable?: boolean; }
type ContentSource =
  | { kind: "segment"; segment_id: string; place: string | null; action: string | null }
  | { kind: "route"; route_id: string; hub_name: string | null; first_day: number | null; last_day: number | null }
  | { kind: "direct_atom" };

interface ContentLogRow {
  piece_id: string; tenant_id: string; tenant_name: string | null; tenant_slug: string | null;
  goal: string | null; topic: string; channel: string; status: string; held_reason: string | null;
  gate_ledger: GateEntry[]; gate_pass_count: number; gate_total_count: number;
  repair_log: RepairRound[]; retry_count: number; attempt_number: number;
  content_text: string; cta: string | null; angles: AngleOption[];
  atom: { text: string; activity_type: string | null; emotional_hook: string | null; season_note: string | null } | null;
  tour: { name: string; destination: string | null } | null;
  source: ContentSource; is_buffer_retry: boolean; sibling_piece_count: number;
  publish_status: "published" | "pending_publish" | "n/a";
  publish_external_url: string | null; publish_published_at: string | null;
  created_at: string;
}

interface Tenant { tenant_id: string; name: string; slug: string; }

const STATUS_COLOR: Record<string, "green" | "amber" | "red" | "gray"> = {
  approved: "green", held: "amber", processing: "gray", failed: "red",
};

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "processing", label: "Processing" },
  { value: "approved", label: "Approved" },
  { value: "held", label: "Held" },
  { value: "failed", label: "Failed" },
];

// Real channel values only (SlateTab.tsx's own CHANNEL_TABS — the one place this codebase
// enumerates every channel a piece can actually be written for), never a fabricated list.
const CHANNEL_OPTIONS = [
  { value: "", label: "All channels" },
  { value: "blog", label: "Blog" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "facebook", label: "Facebook" },
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "email", label: "Email" },
  { value: "landing_page", label: "Landing Page" },
  { value: "ads", label: "Ads" },
];

const PUBLISHED_OPTIONS = [
  { value: "", label: "Any" },
  { value: "yes", label: "Published" },
  { value: "no", label: "Not published" },
];

function sourceLabel(source: ContentSource): string {
  if (source.kind === "segment") return `Segment — ${source.place ?? "?"}${source.action ? ` (${source.action})` : ""}`;
  if (source.kind === "route") return `Route/Hub — ${source.hub_name ?? "?"} (Day ${source.first_day}-${source.last_day})`;
  return "Chosen atom directly (not via Slate)";
}

const selectStyle: React.CSSProperties = {
  padding: "8px 12px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8,
  fontSize: 12.5, fontFamily: sans, color: A.body, cursor: "pointer",
};

export default function ContentTracePage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [tenantId, setTenantId] = useState("");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const [published, setPublished] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [rows, setRows] = useState<ContentLogRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    fetchJson<{ tenants: Tenant[] }>("/api/admin/tenants")
      .then(d => setTenants(d.tenants))
      .catch(() => {});
  }, []);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (tenantId) p.set("tenant_id", tenantId);
    if (channel) p.set("channel", channel);
    if (status) p.set("status", status);
    if (published) p.set("published", published);
    if (dateFrom) p.set("date_from", dateFrom);
    if (dateTo) p.set("date_to", dateTo);
    return p.toString();
  }, [tenantId, channel, status, published, dateFrom, dateTo]);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchJson<{ data: ContentLogRow[]; total: number }>(`/api/admin/a4/content-log?${query}`)
      .then(d => setRows(d.data))
      .catch(e => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [query]);

  useEffect(() => { load(); }, [load]);

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh" }}>
        <div style={{ flexShrink: 0, background: A.bg, padding: "28px 32px 16px", borderBottom: `1px solid ${A.line}` }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
            06 · Content Trace
          </h1>
          <div style={{ fontSize: 12, color: A.muted, marginTop: 4, maxWidth: 760 }}>
            Every content piece written across ALL tenants, one row per write attempt — full
            lineage, all 3 generated angles, gate detail, and retry reasoning on click. Admin-only
            lesson log, not the tenant&apos;s own view of their content.
          </div>

          {/* Filter bar — Tenant is the primary lens ("All" is a real, always-valid choice, never
              a placeholder that must be replaced before the table shows anything). */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 16 }}>
            <FilterField label="Tenant">
              <select value={tenantId} onChange={e => setTenantId(e.target.value)} style={{ ...selectStyle, minWidth: 180, fontWeight: 600 }}>
                <option value="">All tenants</option>
                {tenants.map(t => <option key={t.tenant_id} value={t.tenant_id}>{t.name}</option>)}
              </select>
            </FilterField>
            <FilterField label="Channel">
              <select value={channel} onChange={e => setChannel(e.target.value)} style={{ ...selectStyle, minWidth: 140 }}>
                {CHANNEL_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </FilterField>
            <FilterField label="Status">
              <select value={status} onChange={e => setStatus(e.target.value)} style={{ ...selectStyle, minWidth: 140 }}>
                {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </FilterField>
            <FilterField label="Published">
              <select value={published} onChange={e => setPublished(e.target.value)} style={{ ...selectStyle, minWidth: 130 }}>
                {PUBLISHED_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </FilterField>
            <FilterField label="From">
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ ...selectStyle, cursor: "text" }} />
            </FilterField>
            <FilterField label="To">
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={{ ...selectStyle, cursor: "text" }} />
            </FilterField>
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px 32px 32px" }}>
          {loading ? (
            <LoadingScreen msg="Loading Content Trace…" />
          ) : error ? (
            <ErrorState message={error} onRetry={load} />
          ) : !rows || rows.length === 0 ? (
            <EmptyState
              title="No content pieces match these filters"
              body="Nothing has been written yet for this combination of tenant/channel/status/date — try widening a filter, or 'All tenants' to check whether the data exists elsewhere."
            />
          ) : (
            <ContentTraceTable rows={rows} expandedId={expandedId}
              onToggle={id => setExpandedId(prev => prev === id ? null : id)} />
          )}
        </div>
      </div>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 11.5, color: A.muted }}>{label}:</span>
      {children}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Main table — 1 row = 1 write attempt, click to expand the accordion below it (SlateTab.tsx /
// AA-564 SubjectRow pattern: one shared `expandedId` at the table level, at most one row open).
// ══════════════════════════════════════════════════════════════════════════

const COLS = 10;

function ContentTraceTable({ rows, expandedId, onToggle }: {
  rows: ContentLogRow[]; expandedId: string | null; onToggle: (id: string) => void;
}) {
  return (
    <div style={{ overflowX: "auto", border: `1px solid ${A.line}`, borderRadius: 10 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
        <thead>
          <tr>
            {["", "Topic", "Tenant", "Tour", "Channel", "Angle chosen", "Status", "Gate count", "Retry count", "Published", "Created at"].map((h, i) => (
              <th key={i} style={{
                padding: "10px 14px", fontSize: 11, fontWeight: 600, textTransform: "uppercase",
                letterSpacing: "0.08em", color: A.muted, textAlign: "left", background: A.bg,
                borderBottom: `1px solid ${A.line}`, whiteSpace: "nowrap",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const expanded = expandedId === r.piece_id;
            const chosenAngle = r.angles.find(a => a.chosen);
            return (
              <Fragment key={r.piece_id}>
                <tr onClick={() => onToggle(r.piece_id)} style={{
                  cursor: "pointer", background: expanded ? A.goldTint : "transparent",
                }}>
                  <td style={rowTd}>{expanded ? <ChevronDown size={14} color={A.gold} /> : <ChevronRight size={14} color={A.muted2} />}</td>
                  <td style={{ ...rowTd, maxWidth: 260, whiteSpace: "normal" }}>{r.topic}</td>
                  <td style={rowTd}>{r.tenant_name ?? "—"}</td>
                  <td style={rowTd}>{r.tour?.name ?? "—"}</td>
                  <td style={rowTd}><Badge color="gray">{r.channel}</Badge></td>
                  <td style={{ ...rowTd, maxWidth: 200, whiteSpace: "normal" }}>{chosenAngle?.name ?? "—"}</td>
                  <td style={rowTd}><Badge color={STATUS_COLOR[r.status] ?? "gray"}>{r.status}</Badge></td>
                  <td style={{ ...rowTd, fontFamily: mono }}>{r.gate_pass_count}/{r.gate_total_count}</td>
                  <td style={{ ...rowTd, fontFamily: mono }}>
                    {r.retry_count}{r.is_buffer_retry && <span title="Also a buffer-retry of an earlier held piece"> +buffer</span>}
                  </td>
                  <td style={rowTd}>
                    {r.publish_status === "published" ? (
                      r.publish_external_url ? (
                        <a href={r.publish_external_url} target="_blank" rel="noreferrer"
                          onClick={e => e.stopPropagation()} style={{ color: A.gold }}>Yes ↗</a>
                      ) : <Badge color="green">Yes</Badge>
                    ) : r.publish_status === "pending_publish" ? (
                      <Badge color="amber">Not yet</Badge>
                    ) : <Badge color="gray">No</Badge>}
                  </td>
                  <td style={rowTd}>{new Date(r.created_at).toLocaleString()}</td>
                </tr>
                {expanded && (
                  <tr>
                    <td colSpan={COLS} style={{ padding: "0 14px 18px", background: A.bg, borderBottom: `1px solid ${A.line}` }}>
                      <ContentTraceAccordion row={r} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const rowTd: React.CSSProperties = {
  padding: "11px 14px", fontSize: 12.5, color: A.body, borderBottom: `1px solid ${A.line2}`,
  whiteSpace: "nowrap",
};

// ══════════════════════════════════════════════════════════════════════════
// Accordion — full lineage + all 3 angles (chosen marked) + content + gate detail + retry
// reasoning ("Lý do yêu cầu viết lại", never a content diff — see file header) + publish status.
// ══════════════════════════════════════════════════════════════════════════

function ContentTraceAccordion({ row: p }: { row: ContentLogRow }) {
  return (
    <Card style={{ padding: "16px 18px", marginTop: 4 }}>
      {/* Lineage — Tour -> Atom -> Segment/Route/Hub -> Slate Subject, always visible, never a
          blank cell (the pre-Slate direct-atom path is a real, explicitly-labeled state). */}
      <SectionLabel>Lineage</SectionLabel>
      <div style={{ fontSize: 12.5, color: A.body, marginBottom: 4, lineHeight: 1.7 }}>
        <strong>Tour:</strong> {p.tour?.name ?? "—"}{p.tour?.destination ? ` (${p.tour.destination})` : ""}
        {p.atom && <> → <strong>Atom:</strong> {p.atom.text}</>}
        {" → "}<strong>{p.source.kind === "direct_atom" ? "Path:" : "Slate:"}</strong> {sourceLabel(p.source)}
      </div>
      {p.goal && <div style={{ fontSize: 12.5, color: A.body, marginBottom: 12 }}><strong>Goal:</strong> {p.goal}</div>}
      {p.cta && <div style={{ fontSize: 12.5, color: A.body, marginBottom: 12 }}><strong>CTA:</strong> {p.cta}</div>}

      {/* All 3 angles, chosen one marked — never just the pick. */}
      <SectionLabel>Angles generated ({p.angles.length}) — chosen one marked</SectionLabel>
      {p.angles.length === 0 ? (
        <div style={{ fontSize: 12, color: A.muted2, marginBottom: 14 }}>No angle options on record for this request.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
          {p.angles.map(a => (
            <div key={a.option_id} style={{
              border: `1px solid ${a.chosen ? A.gold : A.line}`, borderRadius: 8, padding: "8px 10px",
              background: a.chosen ? A.goldTint : "transparent",
            }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: A.body, marginBottom: 2, display: "flex", alignItems: "center", gap: 6 }}>
                {a.name}
                {a.chosen && <Badge color="gold">chosen</Badge>}
                {a.recommended && !a.chosen && <Badge color="gray">recommended</Badge>}
              </div>
              <div style={{ fontSize: 11.5, color: A.muted }}>{a.why_it_works}</div>
            </div>
          ))}
        </div>
      )}

      {/* Full content. */}
      <SectionLabel>Content</SectionLabel>
      <div style={{
        fontSize: 12.5, color: A.body, lineHeight: 1.6, marginBottom: 14, whiteSpace: "pre-wrap",
        maxHeight: 260, overflowY: "auto", border: `1px solid ${A.line}`, borderRadius: 8, padding: "10px 12px",
        background: A.card,
      }}>
        {p.content_text || "(no content text on record)"}
      </div>
      {p.held_reason && (
        <div style={{ fontSize: 12, color: A.red, marginBottom: 14 }}><strong>Held reason:</strong> {p.held_reason}</div>
      )}

      {/* Gate ledger — specific violation text, not just counts. */}
      <SectionLabel>Gate ledger ({p.gate_pass_count}/{p.gate_total_count} passed)</SectionLabel>
      {p.gate_ledger.length === 0 ? (
        <div style={{ fontSize: 12, color: A.muted2, marginBottom: 14 }}>No gate results on record.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
          {p.gate_ledger.map((g, i) => (
            <div key={i} style={{ fontSize: 12, color: A.body }}>
              <Badge color={g.passed ? "green" : "red"}>{g.gate ?? "gate"}</Badge>
              {!g.passed && g.violations && g.violations.length > 0 && (
                <ul style={{ margin: "4px 0 0 20px", padding: 0, color: A.muted }}>
                  {g.violations.map((v, j) => <li key={j} style={{ fontSize: 11.5 }}>{v}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Retry — real reason, labeled honestly. Never "content changed" — that data was never
          persisted (STEP0, confirmed structural, AA-570 is the separate follow-up). */}
      <SectionLabel>Retry history ({p.retry_count})</SectionLabel>
      {p.repair_log.length === 0 ? (
        <div style={{ fontSize: 12, color: A.muted2, marginBottom: 4 }}>
          {p.status === "approved" || p.status === "held" ? "No retries — this attempt reached its final state on the first pass." : "No retries recorded."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 4 }}>
          {p.repair_log.map((round, i) => (
            <div key={i} style={{ fontSize: 12, color: A.body, border: `1px solid ${A.line}`, borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontWeight: 600, marginBottom: 3 }}>
                Round {round.attempt ?? i + 1} — Lý do yêu cầu viết lại{round.gate_targeted ? ` (${round.gate_targeted})` : ""}
              </div>
              {round.violations && round.violations.length > 0 ? (
                <ul style={{ margin: 0, paddingLeft: 18, color: A.muted }}>
                  {round.violations.map((v, j) => <li key={j} style={{ fontSize: 11.5 }}>{v}</li>)}
                </ul>
              ) : (
                <div style={{ fontSize: 11.5, color: A.muted2 }}>No violation text on record for this round.</div>
              )}
            </div>
          ))}
        </div>
      )}
      {p.is_buffer_retry && (
        <div style={{ fontSize: 11.5, color: A.muted, marginTop: 6 }}>
          This attempt is also a buffer-retry of an earlier held piece for the same request
          ({p.sibling_piece_count} write attempts total for this request).
        </div>
      )}

      {/* Publish status. */}
      <SectionLabel style={{ marginTop: 14 }}>Publish</SectionLabel>
      <div style={{ fontSize: 12.5, color: A.body, display: "flex", alignItems: "center", gap: 8 }}>
        <Badge color={p.publish_status === "published" ? "green" : p.publish_status === "pending_publish" ? "amber" : "gray"}>
          {p.publish_status}
        </Badge>
        {p.publish_external_url && (
          <a href={p.publish_external_url} target="_blank" rel="noreferrer" style={{ color: A.gold }}>View published post ↗</a>
        )}
        {p.publish_published_at && (
          <span style={{ fontSize: 11.5, color: A.muted2 }}>published {new Date(p.publish_published_at).toLocaleString()}</span>
        )}
      </div>
    </Card>
  );
}

function SectionLabel({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 600, color: A.ink3, textTransform: "uppercase",
      letterSpacing: "0.06em", marginBottom: 6, display: "flex", alignItems: "center", gap: 6, ...style,
    }}>
      <Radio size={11} style={{ opacity: 0.5 }} />{children}
    </div>
  );
}
