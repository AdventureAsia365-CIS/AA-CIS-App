"use client";
// app/admin/atom-curation/page.tsx — AA-527 original build, rebuilt AA-551 (07/09/2026).
//
// AA-551 STEP0 (docs/investigation/AA-550-admin-ui-real-audit.md): the original 8-section page
// (AA-527 "bổ sung") required a single selected Tour for sections 02-08, which meant Segment/
// Score/Route/Hub could never show anything in "All tours" mode — directly contradicting AA-545's
// own platform-wide redesign of exactly those 3 (dropped `tenant_id` from the schema entirely,
// same day, but the API layer here stayed hard-scoped to one Tour regardless). This page is now
// SPLIT in two, per Nghiệp's decision (AA-551, "Phương án B"):
//   - THIS page (`/admin/atom-curation`, same URL) = 01 Atomize + 02 Segment + 03 Score +
//     04 Route/Hub + 05 Slate — genuinely platform-wide Master Content monitoring. A common
//     Tour+Market filter applies to 01-04 at once (05 Slate is the one deliberate exception, see
//     below); each of 02-04 also has its own extra filter row. A header stat bar (Tour/Atom/
//     Segment/Score-row/Route/Hub counts) re-filters live with the same common filter.
//   - `/admin/tenant-activity` (new page) = 06 Write/Gate + 07 Review + 08 Publish — a specific
//     TENANT's activity on a specific Tour, a different subject entirely (AA-550 point C.8: the
//     original single page "lẫn lộn nội dung của tầng admin và tenant").
//
// 05 Slate is NOT part of the platform-wide fix (AA-550 A.3, confirmed real schema:
// `acp_shared.subject.tenant_id NOT NULL`) — it keeps requiring one selected Tour, unchanged
// behavior, only its prompt copy is now English.
//
// Backend (api/routers/admin_dashboard.py, AA-551): `tour_id` is now OPTIONAL on
// `segments`/`score`/`routes` (each also gained a `market` filter + a section-specific filter +
// pagination + `tour_id`/`tour_name` on every row); `slate` is unchanged. New
// `GET /admin/dashboard/summary` feeds the header stat bar.
import { useState, useEffect, useCallback } from "react";
import {
  Star, Trash2, ChevronDown, ChevronRight, Layers, Milestone, Puzzle,
  TrendingUp, GitBranch, FileStack,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, Badge, Btn, LoadingScreen } from "../_components/adminUi";
import { fetchJson, EmptyState, ErrorState, AuditTable, Col } from "../_components/auditPanels";

const MARKETS = ["US", "UK", "AU", "DE", "FR", "NL"];

// ── Shared types ─────────────────────────────────────────────────────────────

interface TourSummary {
  tour_id: string;
  tour_name: string;
  atom_count: number;
  is_thin: boolean;
  unreviewed_count: number;
  used_atom_count: number;
  lifecycle_stage: "active" | "phasing_out" | "retired";
  atomized_at: string | null;
  owner_scopes: string[];
}

interface Summary {
  distinctiveness_breakdown: { HIGH: number; MED: number; LOW: number };
  total_count: number;
  reviewed_count: number;
  by_tour: TourSummary[];
}

interface DashboardSummary {
  tour_count: number; atom_count: number; segment_count: number;
  score_count: number; route_count: number; hub_count: number;
}

type SectionKey = "atomize" | "segment" | "score" | "route_hub" | "slate";

const SECTIONS: { key: SectionKey; label: string; icon: React.ReactNode }[] = [
  { key: "atomize",    label: "01 · Atomize",   icon: <Puzzle size={15} /> },
  { key: "segment",    label: "02 · Segment",   icon: <Layers size={15} /> },
  { key: "score",      label: "03 · Score",     icon: <TrendingUp size={15} /> },
  { key: "route_hub",  label: "04 · Route/Hub", icon: <GitBranch size={15} /> },
  { key: "slate",      label: "05 · Slate",     icon: <FileStack size={15} /> },
];

const LIFECYCLE_COLOR: Record<string, "green" | "amber" | "gray"> = {
  active: "green", phasing_out: "amber", retired: "gray",
};

const selectStyle: React.CSSProperties = {
  padding: "8px 12px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8,
  fontSize: 13, fontFamily: sans, color: A.body, cursor: "pointer",
};

const inputStyle: React.CSSProperties = {
  padding: "7px 10px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8,
  fontSize: 12.5, fontFamily: sans, color: A.body, width: 140,
};

// ══════════════════════════════════════════════════════════════════════════
// Section 01 — Atomize (PR #311's original build, unchanged by AA-551)
// ══════════════════════════════════════════════════════════════════════════

interface Atom {
  atom_id: string;
  tour_id: string;
  tour_name: string;
  text: string;
  activity_type: string | null;
  distinctiveness: "HIGH" | "MED" | "LOW";
  starred: boolean;
  deleted: boolean;
  unreviewed: boolean;
  segment_id: string | null;
  canonical_place: string | null;
  canonical_action: string | null;
  segment_score: number | null;
  route_id: string | null;
  route_hub_name: string | null;
  owner_scope: string;
  recurrence: number | null;
  usage_count: number;
  lifecycle_stage: "active" | "phasing_out" | "retired";
}

const DIST_COLOR: Record<string, "green" | "amber" | "gray"> = { HIGH: "green", MED: "amber", LOW: "gray" };
const PAGE_SIZE = 50;

function isLegacyScope(scope: string): boolean { return scope !== "platform"; }

function OwnerBadge({ scope }: { scope: string }) {
  return isLegacyScope(scope) ? <Badge color="amber">Legacy tenant-owned</Badge> : <Badge color="gold">Platform</Badge>;
}

function AtomizeSection({ summary, summaryLoading, selectedTour, onTourChange, onSummaryChange }: {
  summary: Summary | null; summaryLoading: boolean;
  selectedTour: string | null; onTourChange: (t: string | null) => void;
  onSummaryChange: () => void;
}) {
  const [atoms, setAtoms] = useState<Atom[]>([]);
  const [total, setTotal] = useState(0);
  const [distinctiveness, setDistinctiveness] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [ownerScopeClass, setOwnerScopeClass] = useState("");
  const [lifecycleFilter, setLifecycleFilter] = useState("");
  const [atomsLoading, setAtomsLoading] = useState(true);
  const [atomsError, setAtomsError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [collapsedSegments, setCollapsedSegments] = useState<Set<string>>(new Set());

  const loadAtoms = useCallback((offset: number, append: boolean) => {
    if (append) setLoadingMore(true); else setAtomsLoading(true);
    setAtomsError(null);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (distinctiveness) params.set("distinctiveness", distinctiveness);
    if (unreviewedOnly) params.set("unreviewed_only", "true");
    if (selectedTour) params.set("tour_id", selectedTour);
    if (ownerScopeClass) params.set("owner_scope_class", ownerScopeClass);
    if (lifecycleFilter) params.set("lifecycle_stage", lifecycleFilter);
    fetchJson<{ atoms: Atom[]; total: number }>(`/api/admin/atoms?${params}`)
      .then(d => {
        setAtoms(prev => (append ? [...prev, ...d.atoms] : d.atoms));
        setTotal(d.total ?? 0);
      })
      .catch(e => setAtomsError(String(e.message || e)))
      .finally(() => { setAtomsLoading(false); setLoadingMore(false); });
  }, [distinctiveness, unreviewedOnly, selectedTour, ownerScopeClass, lifecycleFilter]);

  useEffect(() => { loadAtoms(0, false); }, [loadAtoms]);

  async function toggleStar(atom: Atom) {
    const next = !atom.starred;
    setAtoms(prev => prev.map(a => (a.atom_id === atom.atom_id ? { ...a, starred: next } : a)));
    await fetch(`/api/admin/atoms/${atom.atom_id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starred: next }),
    });
  }

  async function deleteAtom(atom: Atom) {
    if (!confirm("Remove this atom from the curated pool? It will no longer be used for any tenant's content going forward.")) return;
    setAtoms(prev => prev.filter(a => a.atom_id !== atom.atom_id));
    await fetch(`/api/admin/atoms/${atom.atom_id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deleted: true }),
    });
    onSummaryChange();
  }

  const breakdown = summary?.distinctiveness_breakdown ?? { HIGH: 0, MED: 0, LOW: 0 };

  return (
    <>
      {summaryLoading ? <LoadingScreen msg="Loading curation dashboard…" /> : (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 20 }}>
            {[
              ["Total atoms", summary?.total_count ?? 0, A.gold],
              ["Reviewed", summary?.reviewed_count ?? 0, A.green],
              ["High distinctiveness", breakdown.HIGH, A.green],
              ["Medium", breakdown.MED, A.amber],
              ["Low", breakdown.LOW, A.muted2],
            ].map(([label, value, accent]) => (
              <Card key={label as string} style={{ padding: "14px 16px" }}>
                <div style={{ fontSize: 11.5, color: A.muted, marginBottom: 6 }}>{label}</div>
                <div style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: accent as string }}>{value}</div>
              </Card>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 18, alignItems: "start" }}>
            <Card style={{ padding: 0, overflow: "hidden" }}>
              <div style={{ padding: "12px 16px", borderBottom: `1px solid ${A.line}`, fontSize: 12, fontWeight: 600, color: A.ink3, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Tours ({summary?.by_tour.length ?? 0})
              </div>
              <div style={{ maxHeight: 640, overflowY: "auto" }}>
                <button onClick={() => onTourChange(null)} style={{
                  display: "block", width: "100%", textAlign: "left", padding: "10px 16px",
                  background: selectedTour === null ? A.bg : "transparent", border: "none",
                  borderBottom: `1px solid ${A.line2}`, cursor: "pointer", fontFamily: sans,
                  fontSize: 12.5, fontWeight: selectedTour === null ? 700 : 500, color: A.ink,
                }}>
                  All tours
                </button>
                {(summary?.by_tour ?? []).map(t => (
                  <button key={t.tour_id} onClick={() => onTourChange(t.tour_id)} style={{
                    display: "block", width: "100%", textAlign: "left", padding: "10px 16px",
                    background: selectedTour === t.tour_id ? A.bg : "transparent", border: "none",
                    borderBottom: `1px solid ${A.line2}`, cursor: "pointer", fontFamily: sans,
                  }}>
                    <div style={{ fontSize: 12.5, fontWeight: selectedTour === t.tour_id ? 700 : 500, color: A.ink, marginBottom: 3 }}>
                      {t.tour_name}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, color: A.muted }}>{t.atom_count} atoms</span>
                      {t.is_thin && <Badge color="red">Thin</Badge>}
                      {t.unreviewed_count > 0 && <Badge color="blue">{t.unreviewed_count} new</Badge>}
                      {t.lifecycle_stage !== "active" && <Badge color={LIFECYCLE_COLOR[t.lifecycle_stage]}>{t.lifecycle_stage}</Badge>}
                      {t.owner_scopes.map(s => <OwnerBadge key={s} scope={s} />)}
                    </div>
                    <div style={{ fontSize: 10.5, color: A.muted2, marginTop: 3 }}>
                      {t.used_atom_count} / {t.atom_count} atoms used in written content
                    </div>
                  </button>
                ))}
              </div>
            </Card>

            <div>
              <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                <select value={distinctiveness} onChange={e => setDistinctiveness(e.target.value)}
                  style={selectStyle}>
                  <option value="">All distinctiveness</option>
                  <option value="HIGH">High</option>
                  <option value="MED">Medium</option>
                  <option value="LOW">Low</option>
                </select>
                <select value={ownerScopeClass} onChange={e => setOwnerScopeClass(e.target.value)} style={selectStyle}>
                  <option value="">All owners</option>
                  <option value="platform">Platform only</option>
                  <option value="legacy">Legacy tenant-owned only</option>
                </select>
                <select value={lifecycleFilter} onChange={e => setLifecycleFilter(e.target.value)} style={selectStyle}>
                  <option value="">All lifecycle stages</option>
                  <option value="active">Active</option>
                  <option value="phasing_out">Phasing out</option>
                  <option value="retired">Retired</option>
                </select>
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: A.body, cursor: "pointer" }}>
                  <input type="checkbox" checked={unreviewedOnly} onChange={e => setUnreviewedOnly(e.target.checked)} />
                  Unreviewed only
                </label>
              </div>

              {atomsError ? <ErrorState message={atomsError} onRetry={() => loadAtoms(0, false)} /> :
                atomsLoading ? <LoadingScreen msg="Loading atoms…" /> : atoms.length === 0 ? (
                <EmptyState title="No atoms match this filter"
                  body="Atoms are extracted automatically once a tour is approved into Master Content — nothing to trigger here." />
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {groupBySegment(atoms).map(row =>
                    row.kind === "atom" ? (
                      <AtomCard key={row.atom.atom_id} atom={row.atom} showTour={!selectedTour} onStar={toggleStar} onDelete={deleteAtom} />
                    ) : (
                      <SegmentGroup key={row.segmentId} place={row.place} action={row.action} atoms={row.atoms}
                        score={row.score} routeHubName={row.routeHubName} showTour={!selectedTour}
                        collapsed={collapsedSegments.has(row.segmentId)}
                        onToggle={() => setCollapsedSegments(prev => {
                          const next = new Set(prev);
                          next.has(row.segmentId) ? next.delete(row.segmentId) : next.add(row.segmentId);
                          return next;
                        })}
                        onStar={toggleStar} onDelete={deleteAtom} />
                    )
                  )}
                </div>
              )}

              {atoms.length < total && !atomsError && (
                <div style={{ textAlign: "center", marginTop: 16 }}>
                  <Btn variant="secondary" disabled={loadingMore} onClick={() => loadAtoms(atoms.length, true)}>
                    {loadingMore ? "Loading…" : `Load more (${atoms.length} / ${total})`}
                  </Btn>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </>
  );
}

type AtomRow =
  | { kind: "atom"; atom: Atom }
  | { kind: "segment"; segmentId: string; place: string; action: string; atoms: Atom[]; score: number | null; routeHubName: string | null };

function groupBySegment(atoms: Atom[]): AtomRow[] {
  const bySegment = new Map<string, Atom[]>();
  for (const atom of atoms) {
    if (!atom.segment_id) continue;
    const list = bySegment.get(atom.segment_id) ?? [];
    list.push(atom);
    bySegment.set(atom.segment_id, list);
  }
  const rows: AtomRow[] = [];
  const emitted = new Set<string>();
  for (const atom of atoms) {
    const members = atom.segment_id ? bySegment.get(atom.segment_id) : undefined;
    if (members && members.length > 1) {
      if (emitted.has(atom.segment_id!)) continue;
      emitted.add(atom.segment_id!);
      rows.push({
        kind: "segment", segmentId: atom.segment_id!,
        place: members[0].canonical_place ?? "", action: members[0].canonical_action ?? "",
        atoms: members, score: members.find(m => m.segment_score != null)?.segment_score ?? null,
        routeHubName: members.find(m => m.route_hub_name != null)?.route_hub_name ?? null,
      });
    } else {
      rows.push({ kind: "atom", atom });
    }
  }
  return rows;
}

function AtomCard({ atom, showTour, onStar, onDelete }: {
  atom: Atom; showTour: boolean; onStar: (a: Atom) => void; onDelete: (a: Atom) => void;
}) {
  return (
    <Card style={{ padding: "14px 18px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {showTour && <div style={{ fontSize: 11, color: A.muted2, marginBottom: 4, fontFamily: mono }}>{atom.tour_name}</div>}
          <div style={{ fontSize: 13.5, color: A.body, lineHeight: 1.5 }}>{atom.text}</div>
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Badge color={DIST_COLOR[atom.distinctiveness] ?? "gray"}>{atom.distinctiveness}</Badge>
            {atom.activity_type && <Badge color="gray">{atom.activity_type}</Badge>}
            {atom.unreviewed && <Badge color="blue">New</Badge>}
            <OwnerBadge scope={atom.owner_scope} />
            {atom.lifecycle_stage !== "active" && <Badge color={LIFECYCLE_COLOR[atom.lifecycle_stage]}>{atom.lifecycle_stage}</Badge>}
            {atom.recurrence != null && atom.recurrence > 0 && (
              <span style={{ fontSize: 10.5, fontFamily: mono, color: A.muted }}>↻ {atom.recurrence} itineraries</span>
            )}
            <span style={{ fontSize: 10.5, fontFamily: mono, color: atom.usage_count > 0 ? A.ink3 : A.muted2 }}>
              {atom.usage_count > 0 ? `✎ used ${atom.usage_count}×` : "not yet used"}
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button onClick={() => onStar(atom)} title={atom.starred ? "Unstar" : "Star"}
            style={{ background: atom.starred ? A.goldTint : "none", border: `1px solid ${atom.starred ? A.gold : A.line}`, borderRadius: 6, padding: 6, cursor: "pointer", color: atom.starred ? A.gold : A.muted2, display: "flex" }}>
            <Star size={14} fill={atom.starred ? A.gold : "none"} />
          </button>
          <button onClick={() => onDelete(atom)} title="Remove"
            style={{ background: "none", border: `1px solid ${A.line}`, borderRadius: 6, padding: 6, cursor: "pointer", color: A.red, display: "flex" }}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </Card>
  );
}

function SegmentGroup({ place, action, atoms, score, routeHubName, showTour, collapsed, onToggle, onStar, onDelete }: {
  place: string; action: string; atoms: Atom[]; score: number | null; routeHubName: string | null;
  showTour: boolean; collapsed: boolean; onToggle: () => void; onStar: (a: Atom) => void; onDelete: (a: Atom) => void;
}) {
  return (
    <div style={{ border: `1px solid ${A.line}`, borderRadius: 10, overflow: "hidden" }}>
      <button onClick={onToggle} style={{
        width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
        background: A.goldTint, border: "none", cursor: "pointer", textAlign: "left", flexWrap: "wrap",
      }}>
        {collapsed ? <ChevronRight size={14} color={A.muted} /> : <ChevronDown size={14} color={A.muted} />}
        <Layers size={13} color={A.gold} />
        <span style={{ fontSize: 13, fontWeight: 600, color: A.body, fontFamily: sans }}>
          {place}{action ? ` — ${action}` : ""}
        </span>
        {score != null && (
          <span style={{ fontFamily: mono, fontSize: 11, color: A.ink3, background: A.card, border: `1px solid ${A.line}`, borderRadius: 6, padding: "2px 7px" }} title="Rank-sum — lower is better">
            Score {score}
          </span>
        )}
        {routeHubName && (
          <Badge color="gold"><Milestone size={11} style={{ verticalAlign: -2, marginRight: 3 }} />Part of Route: {routeHubName}</Badge>
        )}
        <span style={{ fontSize: 11.5, color: A.muted2, marginLeft: "auto" }}>{atoms.length} atoms, same moment</span>
      </button>
      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8, background: A.card }}>
          {atoms.map(atom => <AtomCard key={atom.atom_id} atom={atom} showTour={showTour} onStar={onStar} onDelete={onDelete} />)}
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Sections 02-04 — Segment / Score / Route-Hub — AA-551: platform-wide, paginated,
// common Tour+Market filter + own extra filter row each.
// ══════════════════════════════════════════════════════════════════════════

// `enabled` (default true) guards the actual fetch — Segment/Score/Route pass no guard (they
// support `tour_id` omitted, "All tours" mode, AA-551's whole point); Slate passes
// `enabled: !!tourId` since its backend endpoint still hard-requires `tour_id` (AA-550 A.3, real
// per-tenant exception, not touched by this task) — without this guard, deselecting the Tour
// filter would fire a request Slate's own API 422s on (found live during this task's own
// Playwright verify, fixed before merge).
function usePlatformFetch<T>(
  endpoint: string, params: Record<string, string | number | undefined>, enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Stable dep key — `params` is a fresh object every render otherwise.
  const key = JSON.stringify(params);

  const load = useCallback(() => {
    if (!enabled) { setData(null); setLoading(false); setError(null); return; }
    setLoading(true); setError(null);
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== "") qs.set(k, String(v)); });
    fetchJson<T>(`${endpoint}?${qs}`)
      .then(setData)
      .catch(e => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, key, enabled]);

  useEffect(() => { load(); }, [load]);
  return { data, loading, error, reload: load };
}

const filterBarStyle: React.CSSProperties = {
  display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap",
};

interface SegmentRow {
  tour_id: string; tour_name: string | null;
  segment_id: string; canonical_place: string; canonical_action: string;
  member_count: number; market: string | null; total_rank: number | null; recurrence: number | null;
  excluded_reason: string | null; route_id: string | null; route_hub_name: string | null;
}

function SegmentSection({ tourId, market }: { tourId: string | null; market: string }) {
  const [placeSearch, setPlaceSearch] = useState("");
  const [minRecurrence, setMinRecurrence] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(0); }, [tourId, market, placeSearch, minRecurrence]);

  const { data, loading, error, reload } = usePlatformFetch<{ data: SegmentRow[]; total: number }>(
    "/api/admin/dashboard/segments",
    { tour_id: tourId ?? undefined, market: market || undefined, place_search: placeSearch || undefined,
      min_recurrence: minRecurrence || undefined, limit: PAGE_SIZE, offset },
  );

  return (
    <>
      <div style={filterBarStyle}>
        <input style={inputStyle} placeholder="Search place/verb…" value={placeSearch}
          onChange={e => setPlaceSearch(e.target.value)} />
        <input style={{ ...inputStyle, width: 110 }} type="number" min={0} placeholder="Min recurrence"
          value={minRecurrence} onChange={e => setMinRecurrence(e.target.value)} />
      </div>
      {error ? <ErrorState message={error} onRetry={reload} /> :
        loading ? <LoadingScreen msg="Loading Segments…" /> :
        (!data || data.total === 0) ? <EmptyState title="No Segments match this filter" body="No atom_segment row (services/acp_contract/segment_matching.py) matches the current Tour/Market/search filter." /> : (
        <>
          {/* AA-548's Market column (no more Tenant — atom_segment is platform-wide, AA-545).
              AA-551 adds a Tour column back since a row is no longer scoped to one Tour by
              default — showing which tour each row came from is the whole point of the
              "All tours" view. */}
          <AuditTable rows={data.data} rowKey={r => `${r.tour_id}-${r.segment_id}-${r.market ?? "none"}`} columns={[
            { key: "tour", label: "Tour", render: r => r.tour_name ?? "—" },
            { key: "place", label: "Place — Action", render: r => <>{r.canonical_place} — {r.canonical_action}</> },
            { key: "market", label: "Market", render: r => r.market ?? "—" },
            { key: "members", label: "Atoms", render: r => r.member_count },
            { key: "rank", label: "Total rank", render: r => r.excluded_reason ? <Badge color="gray">{r.excluded_reason}</Badge> : (r.total_rank ?? "—") },
            { key: "recurrence", label: "Recurrence", render: r => r.recurrence ?? "—" },
            { key: "route", label: "Route", render: r => r.route_hub_name ? <Badge color="gold">{r.route_hub_name}</Badge> : "—" },
          ] as Col<SegmentRow>[]} />
          <PageFooter total={data.total} offset={offset} pageSize={PAGE_SIZE} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

interface ScoreRow {
  tour_id: string; tour_name: string | null;
  market: string | null; segment_id: string; canonical_place: string | null; canonical_action: string | null;
  demand_rank: number | null; recurrence_rank: number | null; questions_rank: number | null; said_rank: number | null;
  total_rank: number | null; demand_market: string | null; demand_volume: number | null;
  recurrence: number; questions: number; said: number; excluded_reason: string | null;
}

function ScoreSection({ tourId, market }: { tourId: string | null; market: string }) {
  const [minRank, setMinRank] = useState("");
  const [maxRank, setMaxRank] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(0); }, [tourId, market, minRank, maxRank]);

  const { data, loading, error, reload } = usePlatformFetch<{ data: ScoreRow[]; total: number }>(
    "/api/admin/dashboard/score",
    { tour_id: tourId ?? undefined, market: market || undefined,
      min_total_rank: minRank || undefined, max_total_rank: maxRank || undefined, limit: PAGE_SIZE, offset },
  );

  return (
    <>
      <div style={filterBarStyle}>
        <input style={{ ...inputStyle, width: 110 }} type="number" placeholder="Min total rank" value={minRank} onChange={e => setMinRank(e.target.value)} />
        <input style={{ ...inputStyle, width: 110 }} type="number" placeholder="Max total rank" value={maxRank} onChange={e => setMaxRank(e.target.value)} />
      </div>
      {error ? <ErrorState message={error} onRetry={reload} /> :
        loading ? <LoadingScreen msg="Loading Score…" /> :
        (!data || data.total === 0) ? <EmptyState title="No ranked Segments match this filter" body="atom_ranking has no rows matching the current Tour/Market/rank filter — Score runs as part of Route detection (AA-515)." /> : (
        <>
          <AuditTable rows={data.data} rowKey={r => `${r.tour_id}-${r.segment_id}-${r.market ?? "none"}`} columns={[
            { key: "tour", label: "Tour", render: r => r.tour_name ?? "—" },
            { key: "place", label: "Segment", render: r => r.canonical_place ? `${r.canonical_place} — ${r.canonical_action}` : "—" },
            { key: "market", label: "Market", render: r => r.market ?? "—" },
            { key: "total", label: "Total rank", render: r => r.excluded_reason ? <Badge color="gray">{r.excluded_reason}</Badge> : (r.total_rank ?? "—") },
            { key: "demand", label: "Demand", render: r => r.demand_rank != null ? `#${r.demand_rank} (${r.demand_volume ?? "—"} · ${r.demand_market ?? "—"})` : "—" },
            { key: "recurrence", label: "Recurrence", render: r => r.recurrence_rank != null ? `#${r.recurrence_rank} (${r.recurrence})` : "—" },
            { key: "questions", label: "Questions", render: r => r.questions_rank != null ? `#${r.questions_rank} (${r.questions})` : "—" },
            { key: "said", label: "Said", render: r => r.said_rank != null ? `#${r.said_rank} (${r.said})` : "—" },
          ] as Col<ScoreRow>[]} />
          <PageFooter total={data.total} offset={offset} pageSize={PAGE_SIZE} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

interface RouteRow {
  route_id: string; tour_id: string; tour_name: string | null; hub_name: string; market: string | null;
  ordered_segment_ids: string[]; first_day: number; last_day: number; score: number | null; created_at: string;
  version: number; superseded_at: string | null;
}

function RouteHubSection({ tourId, market }: { tourId: string | null; market: string }) {
  const [minDays, setMinDays] = useState("");
  const [maxDays, setMaxDays] = useState("");
  const [hubSearch, setHubSearch] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(0); }, [tourId, market, minDays, maxDays, hubSearch]);

  const { data, loading, error, reload } = usePlatformFetch<{ data: RouteRow[]; total: number }>(
    "/api/admin/dashboard/routes",
    { tour_id: tourId ?? undefined, market: market || undefined, min_days: minDays || undefined,
      max_days: maxDays || undefined, hub_name_search: hubSearch || undefined, limit: PAGE_SIZE, offset },
  );

  return (
    <>
      <div style={filterBarStyle}>
        <input style={{ ...inputStyle, width: 100 }} type="number" min={1} placeholder="Min days" value={minDays} onChange={e => setMinDays(e.target.value)} />
        <input style={{ ...inputStyle, width: 100 }} type="number" min={1} placeholder="Max days" value={maxDays} onChange={e => setMaxDays(e.target.value)} />
        <input style={inputStyle} placeholder="Search hub name…" value={hubSearch} onChange={e => setHubSearch(e.target.value)} />
        {!tourId && (
          <span style={{ fontSize: 11.5, color: A.muted2, fontStyle: "italic" }}>
            Showing current Routes only — pick a Tour to see superseded versions too.
          </span>
        )}
      </div>
      {error ? <ErrorState message={error} onRetry={reload} /> :
        loading ? <LoadingScreen msg="Loading Routes…" /> :
        (!data || data.total === 0) ? <EmptyState title="No Routes match this filter" body="acp_contract.route has no rows matching the current Tour/Market/day-span/hub filter — Route detection (route_detection.py) hasn't run, or found no consecutive-day span of ranked Segments." /> : (
        <>
          <AuditTable rows={data.data} rowKey={r => `${r.route_id}-${r.market ?? "none"}`} columns={[
            { key: "status", label: "Status", render: r => r.superseded_at
              ? <Badge color="gray">superseded v{r.version}</Badge>
              : <Badge color="green">current{r.version > 1 ? ` v${r.version}` : ""}</Badge> },
            { key: "tour", label: "Tour", render: r => r.tour_name ?? "—" },
            { key: "hub", label: "Hub name", render: r => r.hub_name },
            { key: "market", label: "Market", render: r => r.market ?? "—" },
            { key: "days", label: "Days", render: r => `${r.first_day}–${r.last_day}` },
            { key: "segments", label: "Segments", render: r => (r.ordered_segment_ids || []).length },
            { key: "score", label: "Score", render: r => r.score ?? "—" },
            { key: "created", label: "Created", render: r => new Date(r.created_at).toLocaleString() },
          ] as Col<RouteRow>[]} />
          <PageFooter total={data.total} offset={offset} pageSize={PAGE_SIZE} onOffset={setOffset} />
        </>
      )}
    </>
  );
}

function PageFooter({ total, offset, pageSize, onOffset }: {
  total: number; offset: number; pageSize: number; onOffset: (o: number) => void;
}) {
  if (total <= pageSize) return null;
  const page = Math.floor(offset / pageSize) + 1;
  const pages = Math.ceil(total / pageSize);
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 12, marginTop: 16 }}>
      <Btn variant="secondary" size="sm" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - pageSize))}>Previous</Btn>
      <span style={{ fontSize: 12, color: A.muted, fontFamily: mono }}>Page {page} / {pages} ({total} total)</span>
      <Btn variant="secondary" size="sm" disabled={offset + pageSize >= total} onClick={() => onOffset(offset + pageSize)}>Next</Btn>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section 05 — Slate: UNCHANGED, still per-Tour (AA-550 A.3 — real per-tenant exception)
// ══════════════════════════════════════════════════════════════════════════

interface SlateRow {
  subject_id: string; tenant_name: string | null; channel: string; state: string; score: number | null;
  segment_id: string | null; route_id: string | null; created_at: string;
}

const SLATE_STATE_COLOR: Record<string, "gray" | "blue" | "green" | "red"> = {
  proposed: "gray", picked: "blue", used: "green", cut: "red",
};

function SlateSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = usePlatformFetch<{ data: SlateRow[]; total: number; by_state: Record<string, number> }>(
    "/api/admin/dashboard/slate", { tour_id: tourId ?? undefined }, !!tourId,
  );
  if (!tourId) {
    return <EmptyState title="Select a Tour" body="Slate is per-tenant, per-Tour data (acp_shared.subject.tenant_id is a real, required column — not part of AA-545's platform-wide fix) — pick one Tour above to view it." />;
  }
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Slate…" />;
  if (!data || data.total === 0) return <EmptyState title="No Slate proposals yet" body="acp_shared.subject has no rows for this tour — the Slate (AA-511) proposes a Subject once a Segment/Route clears a Channel's Bar." />;
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        {Object.entries(data.by_state).map(([state, count]) => (
          <Badge key={state} color={SLATE_STATE_COLOR[state] ?? "gray"}>{state}: {count}</Badge>
        ))}
      </div>
      <AuditTable rows={data.data} rowKey={r => r.subject_id} columns={[
        { key: "channel", label: "Channel", render: r => r.channel },
        { key: "state", label: "State", render: r => <Badge color={SLATE_STATE_COLOR[r.state] ?? "gray"}>{r.state}</Badge> },
        { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
        { key: "score", label: "Score", render: r => r.score ?? "—" },
        { key: "kind", label: "Kind", render: r => r.route_id ? "Route" : "Segment" },
        { key: "created", label: "Proposed", render: r => new Date(r.created_at).toLocaleString() },
      ] as Col<SlateRow>[]} />
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Page shell — sticky header (common Tour+Market filter + stat bar) + sticky inner nav (01-05)
// ══════════════════════════════════════════════════════════════════════════

export default function AtomCurationDashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [selectedTour, setSelectedTour] = useState<string | null>(null);
  const [selectedMarket, setSelectedMarket] = useState("");
  const [activeSection, setActiveSection] = useState<SectionKey>("atomize");
  const [stats, setStats] = useState<DashboardSummary | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    fetchJson<Summary>("/api/admin/atoms/summary")
      .then(setSummary)
      .catch(() => {})
      .finally(() => setSummaryLoading(false));
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  // AA-551 — header stat bar, re-fetched whenever the common Tour/Market filter changes,
  // independent of which section tab is open (GET /admin/dashboard/summary).
  useEffect(() => {
    setStatsLoading(true);
    const qs = new URLSearchParams();
    if (selectedTour) qs.set("tour_id", selectedTour);
    if (selectedMarket) qs.set("market", selectedMarket);
    fetchJson<DashboardSummary>(`/api/admin/dashboard/summary?${qs}`)
      .then(setStats)
      .catch(() => {})
      .finally(() => setStatsLoading(false));
  }, [selectedTour, selectedMarket]);

  const selectedTourMeta = summary?.by_tour.find(t => t.tour_id === selectedTour) ?? null;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <style>{`
        @media (max-width: 980px) {
          .a527-inner-sidebar { flex-direction: row !important; overflow-x: auto !important; width: 100% !important; border-right: none !important; border-bottom: 1px solid ${A.line}; position: static !important; }
          .a527-inner-sidebar button { white-space: nowrap; }
          .a527-dash-body { flex-direction: column !important; }
        }
      `}</style>
      <AdminSidebar />
      {/* AA-551 sticky fix (AA-550 A.4): header is a normal, non-scrolling flex item OUTSIDE
          the scroll region — the original bug was a `position: sticky` header with no defined
          scroll-container relationship, not a missing style. Only the inner section-nav below
          still uses `sticky`, now correctly scoped to its own immediate scroll container. Both
          verified by a real Playwright scroll test post-build (see implementation notes). */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh" }}>
        <div style={{ flexShrink: 0, background: A.bg, padding: "24px 32px 16px", borderBottom: `1px solid ${A.line}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12, marginBottom: 16 }}>
            <div>
              <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
                Master Content Pipeline (01–05)
              </h1>
              <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
                Platform-wide monitoring — Atomize is the only section AA acts on; 02–05 show what
                the pipeline has already produced across ALL tours, not just one. Per-tenant
                write/review/publish activity moved to{" "}
                <a href="/admin/tenant-activity" style={{ color: A.gold }}>Tenant Activity</a>.
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 12, color: A.muted }}>Tour:</span>
              <select
                value={selectedTour ?? ""}
                onChange={e => setSelectedTour(e.target.value || null)}
                style={{ ...selectStyle, minWidth: 200, fontWeight: 600 }}
              >
                <option value="">All tours</option>
                {(summary?.by_tour ?? []).map(t => (
                  <option key={t.tour_id} value={t.tour_id}>{t.tour_name}</option>
                ))}
              </select>
              <span style={{ fontSize: 12, color: A.muted }}>Market:</span>
              <select value={selectedMarket} onChange={e => setSelectedMarket(e.target.value)} style={{ ...selectStyle, minWidth: 130 }}>
                <option value="">All markets</option>
                {MARKETS.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              {selectedTourMeta && selectedTourMeta.lifecycle_stage !== "active" && (
                <Badge color={LIFECYCLE_COLOR[selectedTourMeta.lifecycle_stage]}>{selectedTourMeta.lifecycle_stage}</Badge>
              )}
            </div>
          </div>

          {/* Header stat bar — AA-551, AA-550 mục F point 3/4: auto-updates with the filter above. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10 }}>
            {([
              ["Tours", stats?.tour_count],
              ["Atoms", stats?.atom_count],
              ["Segments", stats?.segment_count],
              ["Score rows", stats?.score_count],
              ["Routes", stats?.route_count],
              ["Hubs", stats?.hub_count],
            ] as [string, number | undefined][]).map(([label, value]) => (
              <div key={label} style={{
                background: A.card, border: `1px solid ${A.line}`, borderRadius: 8, padding: "8px 12px",
              }}>
                <div style={{ fontSize: 10.5, color: A.muted, textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
                <div style={{ fontFamily: mono, fontSize: 17, fontWeight: 600, color: A.ink }}>
                  {statsLoading ? "…" : (value ?? "—")}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px 32px" }}>
          <div className="a527-dash-body" style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
            <div className="a527-inner-sidebar" style={{
              width: 200, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2,
              background: A.card, border: `1px solid ${A.line}`, borderRadius: 10, padding: 6,
              position: "sticky", top: 0,
            }}>
              {SECTIONS.map(s => {
                const active = activeSection === s.key;
                return (
                  <button key={s.key} onClick={() => setActiveSection(s.key)} style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderRadius: 7,
                    border: "none", background: active ? A.goldTint : "transparent",
                    color: active ? A.gold : A.body, cursor: "pointer", fontFamily: sans,
                    fontSize: 12.5, fontWeight: active ? 700 : 500, textAlign: "left",
                  }}>
                    {s.icon}
                    <span style={{ flex: 1 }}>{s.label}</span>
                  </button>
                );
              })}
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              {activeSection === "atomize" && (
                <AtomizeSection
                  summary={summary} summaryLoading={summaryLoading}
                  selectedTour={selectedTour} onTourChange={setSelectedTour}
                  onSummaryChange={loadSummary}
                />
              )}
              {activeSection === "segment" && <SegmentSection tourId={selectedTour} market={selectedMarket} />}
              {activeSection === "score" && <ScoreSection tourId={selectedTour} market={selectedMarket} />}
              {activeSection === "route_hub" && <RouteHubSection tourId={selectedTour} market={selectedMarket} />}
              {activeSection === "slate" && <SlateSection tourId={selectedTour} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
