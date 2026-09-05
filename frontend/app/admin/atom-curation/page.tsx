"use client";
// app/admin/atom-curation/page.tsx — AA-527, admin-only Atom Curation dashboard.
//
// AA-527 ORIGINAL SCOPE (PR #311, merged, NOT rebuilt here): the Atomize page itself — AA
// decides which atoms are good to use, ported near-verbatim from the deleted tenant-facing
// AtomsTab.tsx (AA-526 removed T6). See that PR / this file's git history for the full original
// docstring; it's preserved below inside <AtomizeSection>.
//
// AA-527 BỔ SUNG (05/09/2026, "Quyết định bố cục — Phương án C" comment, Nghiệp): this page is
// now a full 8-section dashboard, not a single atom-curation screen — sidebar (this page's own
// INNER sidebar, nested inside the site-wide <AdminSidebar>) listing all 8 T5-T11 pipeline
// stages (Atomize/Segment/Score/Route-Hub/Slate/Write-Gate/Review/Publish) with real counts, a
// header dropdown that picks ONE Tour as the whole page's filter anchor, and 7 new read-only
// AUDIT panels (Atomize, section 01, is the only section with actions — star/delete/edit; the
// other 7 show data that already exists elsewhere in the schema, per AA-525 Phần 12's own
// inventory, never let a reader believe more exists than actually does).
//
// New backend surface used by the 7 non-Atomize panels (all admin-only, x-admin-secret):
//   GET /api/admin/dashboard/segments?tour_id=   — acp_contract.atom_segment (+ranking, +route)
//   GET /api/admin/dashboard/score?tour_id=      — acp_contract.atom_ranking, rank order
//   GET /api/admin/dashboard/routes?tour_id=     — acp_contract.route
//   GET /api/admin/dashboard/slate?tour_id=      — acp_shared.subject (the Slate proposal)
//   GET /api/admin/a4/content-log?tour_id=       — Write-Gate AND Review both read this (2 lenses
//                                                   on 1 dataset — no duplicate query, see below)
//   GET /api/admin/a4/publish-log?tour_id=       — Publish
// (admin_dashboard.py is new; admin_a4.py's content-log/publish-log gained an optional tour_id
// filter in this same change — both already existed for AA-437/AA-455/AA-469/AA-501.)
//
// Sections 2-8 all REQUIRE one selected Tour (their endpoints are Tour-scoped by schema) — the
// header's "All tours" option is only meaningful for Atomize (section 01), which predates the
// Tour-anchor concept and still supports browsing every tour's atom pool at once.

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Star, Trash2, ChevronDown, ChevronRight, Layers, Milestone, Puzzle,
  TrendingUp, GitBranch, FileStack, PenSquare, Eye, Send, AlertTriangle, RotateCw,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, Badge, Btn, LoadingScreen, TH, TD } from "../_components/adminUi";

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

type SectionKey =
  | "atomize" | "segment" | "score" | "route_hub" | "slate"
  | "write_gate" | "review" | "publish";

const SECTIONS: { key: SectionKey; label: string; icon: React.ReactNode; requiresTour: boolean }[] = [
  { key: "atomize",    label: "01 · Atomize",   icon: <Puzzle size={15} />,      requiresTour: false },
  { key: "segment",    label: "02 · Segment",   icon: <Layers size={15} />,      requiresTour: true },
  { key: "score",      label: "03 · Score",     icon: <TrendingUp size={15} />,  requiresTour: true },
  { key: "route_hub",  label: "04 · Route/Hub", icon: <GitBranch size={15} />,   requiresTour: true },
  { key: "slate",      label: "05 · Slate",     icon: <FileStack size={15} />,   requiresTour: true },
  { key: "write_gate", label: "06 · Write/Gate",icon: <PenSquare size={15} />,   requiresTour: true },
  { key: "review",     label: "07 · Review",    icon: <Eye size={15} />,         requiresTour: true },
  { key: "publish",    label: "08 · Publish",   icon: <Send size={15} />,        requiresTour: true },
];

const LIFECYCLE_COLOR: Record<string, "green" | "amber" | "gray"> = {
  active: "green", phasing_out: "amber", retired: "gray",
};

// ── Small shared UI helpers (not yet in adminUi.tsx — audit-panel specific) ──

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <Card>
      <div style={{ textAlign: "center", padding: "40px 20px" }}>
        <div style={{ fontSize: 32, marginBottom: 10 }}>🗒️</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: A.ink, marginBottom: 6 }}>{title}</div>
        <div style={{ fontSize: 13, color: A.muted }}>{body}</div>
      </div>
    </Card>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card style={{ borderColor: A.redBorder }}>
      <div style={{ textAlign: "center", padding: "32px 20px" }}>
        <AlertTriangle size={26} color={A.red} style={{ marginBottom: 10 }} />
        <div style={{ fontSize: 14, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Could not load this panel</div>
        <div style={{ fontSize: 12.5, color: A.muted, marginBottom: 14 }}>{message}</div>
        <Btn variant="secondary" size="sm" onClick={onRetry}><RotateCw size={13} /> Retry</Btn>
      </div>
    </Card>
  );
}

function PickTourPrompt({ sectionLabel }: { sectionLabel: string }) {
  return (
    <EmptyState
      title="Chọn 1 Tour cụ thể"
      body={`${sectionLabel} là dữ liệu theo Tour — chọn 1 Tour ở dropdown phía trên (không phải "All tours") để xem.`}
    />
  );
}

function BacklogNote({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 8, padding: "10px 14px",
      background: A.amberSoft, border: `1px solid ${A.amber}40`, borderRadius: 8,
      fontSize: 12, color: A.ink3, marginBottom: 14, fontFamily: sans,
    }}>
      <AlertTriangle size={14} color={A.amber} style={{ flexShrink: 0, marginTop: 1 }} />
      <div>{children}</div>
    </div>
  );
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return res.json();
}

// ── Generic audit table ────────────────────────────────────────────────────

interface Col<T> { key: string; label: string; render: (row: T) => React.ReactNode; }

function AuditTable<T>({ rows, columns, rowKey }: {
  rows: T[]; columns: Col<T>[]; rowKey: (row: T) => string;
}) {
  return (
    <div style={{ overflowX: "auto", border: `1px solid ${A.line}`, borderRadius: 10 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: sans }}>
        <thead><tr>{columns.map(c => <th key={c.key} style={TH}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map(row => (
            <tr key={rowKey(row)}>
              {columns.map(c => <td key={c.key} style={TD}>{c.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section 01 — Atomize (PR #311's original build, bổ sung filter/recurrence/usage per STEP0)
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
  owner_scope: string; // "platform" (A3, AA-526+) or a real tenant_id (pre-AA-526 legacy row)
  recurrence: number | null; // AA-527 bổ sung — atom_ranking.recurrence (N itinerary/Segment)
  usage_count: number;       // AA-527 bổ sung — real content_piece write count (via T8 request)
  lifecycle_stage: "active" | "phasing_out" | "retired"; // AA-527 bổ sung
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
  const [ownerScopeClass, setOwnerScopeClass] = useState(""); // AA-527 bổ sung, kiểm tra điểm 1
  const [lifecycleFilter, setLifecycleFilter] = useState("");  // AA-527 bổ sung, kiểm tra điểm 2
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
                {/* AA-527 bổ sung, kiểm tra điểm 1 — owner_scope filter (Platform vs Legacy) */}
                <select value={ownerScopeClass} onChange={e => setOwnerScopeClass(e.target.value)} style={selectStyle}>
                  <option value="">All owners</option>
                  <option value="platform">Platform only</option>
                  <option value="legacy">Legacy tenant-owned only</option>
                </select>
                {/* AA-527 bổ sung, kiểm tra điểm 2 — tour lifecycle_stage filter */}
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

const selectStyle: React.CSSProperties = {
  padding: "8px 12px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8,
  fontSize: 13, fontFamily: sans, color: A.body, cursor: "pointer",
};

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
            {/* AA-527 bổ sung: recurrence (atom_ranking.recurrence) + usage_count (real content_piece writes) */}
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
// Sections 02-05 — Segment / Score / Route-Hub / Slate (new, read-only audit)
// ══════════════════════════════════════════════════════════════════════════

function useTourScopedFetch<T>(endpoint: string, tourId: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!tourId) { setData(null); setLoading(false); setError(null); return; }
    setLoading(true); setError(null);
    fetchJson<T>(`${endpoint}?tour_id=${encodeURIComponent(tourId)}`)
      .then(setData)
      .catch(e => setError(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [endpoint, tourId]);

  useEffect(() => { load(); }, [load]);
  return { data, loading, error, reload: load };
}

interface SegmentRow {
  segment_id: string; canonical_place: string; canonical_action: string; tenant_name: string | null;
  member_count: number; total_rank: number | null; recurrence: number | null; excluded_reason: string | null;
  route_id: string | null; route_hub_name: string | null;
}

function SegmentSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: SegmentRow[]; total: number }>("/api/admin/dashboard/segments", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Segment" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Segments…" />;
  if (!data || data.total === 0) return <EmptyState title="No Segments yet" body="No atom on this tour has been grouped into a Segment (services/acp_contract/segment_matching.py) yet." />;
  return (
    <AuditTable rows={data.data} rowKey={r => r.segment_id} columns={[
      { key: "place", label: "Place — Action", render: r => <>{r.canonical_place} — {r.canonical_action}</> },
      { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
      { key: "members", label: "Atoms", render: r => r.member_count },
      { key: "rank", label: "Total rank", render: r => r.excluded_reason ? <Badge color="gray">{r.excluded_reason}</Badge> : (r.total_rank ?? "—") },
      { key: "recurrence", label: "Recurrence", render: r => r.recurrence ?? "—" },
      { key: "route", label: "Route", render: r => r.route_hub_name ? <Badge color="gold">{r.route_hub_name}</Badge> : "—" },
    ]} />
  );
}

interface ScoreRow {
  segment_id: string; canonical_place: string | null; canonical_action: string | null; tenant_name: string | null;
  demand_rank: number | null; recurrence_rank: number | null; questions_rank: number | null; said_rank: number | null;
  total_rank: number | null; demand_market: string | null; demand_volume: number | null;
  recurrence: number; questions: number; said: number; excluded_reason: string | null;
}

function ScoreSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: ScoreRow[]; total: number }>("/api/admin/dashboard/score", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Score" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Score…" />;
  if (!data || data.total === 0) return <EmptyState title="No ranked Segments yet" body="atom_ranking has no rows for this tour — Score runs as part of Route detection (AA-515)." />;
  return (
    <AuditTable rows={data.data} rowKey={r => r.segment_id} columns={[
      { key: "place", label: "Segment", render: r => r.canonical_place ? `${r.canonical_place} — ${r.canonical_action}` : "—" },
      { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
      { key: "total", label: "Total rank", render: r => r.excluded_reason ? <Badge color="gray">{r.excluded_reason}</Badge> : (r.total_rank ?? "—") },
      { key: "demand", label: "Demand", render: r => r.demand_rank != null ? `#${r.demand_rank} (${r.demand_volume ?? "—"} · ${r.demand_market ?? "—"})` : "—" },
      { key: "recurrence", label: "Recurrence", render: r => r.recurrence_rank != null ? `#${r.recurrence_rank} (${r.recurrence})` : "—" },
      { key: "questions", label: "Questions", render: r => r.questions_rank != null ? `#${r.questions_rank} (${r.questions})` : "—" },
      { key: "said", label: "Said", render: r => r.said_rank != null ? `#${r.said_rank} (${r.said})` : "—" },
    ]} />
  );
}

interface RouteRow {
  route_id: string; tenant_name: string | null; hub_name: string;
  ordered_segment_ids: string[]; first_day: number; last_day: number; score: number; created_at: string;
  version: number; superseded_at: string | null; // AA-532 — versioning, never delete-and-reinsert
}

function RouteHubSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: RouteRow[]; total: number; hub_grouping_backlog: boolean }>("/api/admin/dashboard/routes", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Route/Hub" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Routes…" />;
  return (
    <>
      <BacklogNote>
        <strong>Backlog (AA-525 Phần 12 mục 8):</strong> chưa có UI liệt kê Hub/Family (tour nào được
        gộp chung 1 hành trình, vì sao) — bảng dưới đây chỉ hiện Route.hub_name (text), không hiện lý
        do gộp Hub.
      </BacklogNote>
      {(!data || data.total === 0) ? (
        <EmptyState title="No Routes yet" body="acp_contract.route has no rows for this tour — Route detection (route_detection.py) hasn't run, or found no consecutive-day span of ranked Segments." />
      ) : (
        <AuditTable rows={data.data} rowKey={r => r.route_id} columns={[
          // AA-532 — status/version: this panel shows the full version history on purpose
          // (route rows are versioned/superseded, never deleted), unlike every other reader of
          // this table which only ever sees the current one.
          { key: "status", label: "Status", render: r => r.superseded_at
            ? <Badge color="gray">superseded v{r.version}</Badge>
            : <Badge color="green">current{r.version > 1 ? ` v${r.version}` : ""}</Badge> },
          { key: "hub", label: "Hub name", render: r => r.hub_name },
          { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
          { key: "days", label: "Days", render: r => `${r.first_day}–${r.last_day}` },
          { key: "segments", label: "Segments", render: r => (r.ordered_segment_ids || []).length },
          { key: "score", label: "Score", render: r => r.score },
          { key: "created", label: "Created", render: r => new Date(r.created_at).toLocaleString() },
        ]} />
      )}
    </>
  );
}

interface SlateRow {
  subject_id: string; tenant_name: string | null; channel: string; state: string; score: number | null;
  segment_id: string | null; route_id: string | null; created_at: string;
}

const SLATE_STATE_COLOR: Record<string, "gray" | "blue" | "green" | "red"> = {
  proposed: "gray", picked: "blue", used: "green", cut: "red",
};

function SlateSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: SlateRow[]; total: number; by_state: Record<string, number> }>("/api/admin/dashboard/slate", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Slate" />;
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
      ]} />
    </>
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Sections 06-07 — Write/Gate + Review (both read admin_a4.py's content-log — 2 lenses, 1 dataset)
// ══════════════════════════════════════════════════════════════════════════

interface ContentLogRow {
  piece_id: string; tenant_name: string | null; channel: string; status: string; held_reason: string | null;
  gate_ledger: { gate?: string; passed?: boolean; violations?: string[] }[];
  gate_pass_count: number; gate_total_count: number; repair_log: unknown[]; attempt_number: number;
  content_preview: string; publish_status: string; created_at: string;
  tour: { name: string; destination: string } | null;
}

function useContentLog(tourId: string | null) {
  return useTourScopedFetch<{ data: ContentLogRow[]; total: number }>("/api/admin/a4/content-log", tourId);
}

const STATUS_COLOR: Record<string, "green" | "amber" | "red" | "gray"> = {
  approved: "green", held: "amber", processing: "gray", failed: "red",
};

function WriteGateSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useContentLog(tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Write/Gate" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Write/Gate…" />;
  if (!data || data.total === 0) return <EmptyState title="No write attempts yet" body="acp_shared.content_piece has no rows for this tour — T9 write hasn't run for any Slate/angle pick here yet." />;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {data.data.map(p => (
        <Card key={p.piece_id} style={{ padding: "14px 18px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 8 }}>
            <div>
              <span style={{ fontSize: 12, fontFamily: mono, color: A.muted2, marginRight: 8 }}>#{p.attempt_number}</span>
              <Badge color={STATUS_COLOR[p.status] ?? "gray"}>{p.status}</Badge>{" "}
              <Badge color="gray">{p.channel}</Badge>{" "}
              <span style={{ fontSize: 12, color: A.muted }}>{p.tenant_name}</span>
            </div>
            <span style={{ fontSize: 11.5, fontFamily: mono, color: A.muted2 }}>{p.gate_pass_count}/{p.gate_total_count} gates</span>
          </div>
          <div style={{ fontSize: 13, color: A.body, marginBottom: 8 }}>{p.content_preview}…</div>
          {p.held_reason && <div style={{ fontSize: 12, color: A.red, marginBottom: 6 }}>Held: {p.held_reason}</div>}
          {p.gate_ledger.filter(g => g.passed === false).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {p.gate_ledger.filter(g => g.passed === false).map((g, i) => (
                <Badge key={i} color="red">{g.gate ?? "gate"}</Badge>
              ))}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

function ReviewSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useContentLog(tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Review" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Review…" />;
  if (!data || data.total === 0) return <EmptyState title="Nothing to review yet" body="No content_piece rows for this tour." />;
  // Review = same content-log dataset as Write/Gate, a queue-status lens instead of gate-detail —
  // "which pieces are waiting on what" rather than "why did this attempt hold" (per AA-501: AA's
  // review need is already fully served by content-log, no separate table/query).
  return (
    <AuditTable rows={data.data} rowKey={r => r.piece_id} columns={[
      { key: "tour", label: "Tour", render: r => r.tour?.name ?? "—" },
      { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
      { key: "channel", label: "Channel", render: r => r.channel },
      { key: "status", label: "Gate status", render: r => <Badge color={STATUS_COLOR[r.status] ?? "gray"}>{r.status}</Badge> },
      { key: "publish", label: "Publish status", render: r => <Badge color={r.publish_status === "published" ? "green" : r.publish_status === "pending_publish" ? "amber" : "gray"}>{r.publish_status}</Badge> },
      { key: "created", label: "Written", render: r => new Date(r.created_at).toLocaleString() },
    ]} />
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Section 08 — Publish (admin_a4.py's publish-log, tour_id filter added this task)
// ══════════════════════════════════════════════════════════════════════════

interface PublishRow {
  publish_id: string; tenant_name: string | null; channel: string; status: string;
  external_url: string | null; last_error: string | null; published_at: string | null; created_at: string;
}

function PublishSection({ tourId }: { tourId: string | null }) {
  const { data, loading, error, reload } = useTourScopedFetch<{ data: PublishRow[]; total: number }>("/api/admin/a4/publish-log", tourId);
  if (!tourId) return <PickTourPrompt sectionLabel="Publish" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading) return <LoadingScreen msg="Loading Publish…" />;
  if (!data || data.total === 0) return <EmptyState title="Nothing published yet" body="acp_shared.publish_log has no rows for this tour — T11 hasn't published any piece from it yet." />;
  return (
    <AuditTable rows={data.data} rowKey={r => r.publish_id} columns={[
      { key: "tenant", label: "Tenant", render: r => r.tenant_name ?? "—" },
      { key: "channel", label: "Channel", render: r => r.channel },
      { key: "status", label: "Status", render: r => <Badge color={r.status === "published" ? "green" : r.status === "failed" ? "red" : "gray"}>{r.status}</Badge> },
      { key: "url", label: "URL", render: r => r.external_url ? <a href={r.external_url} target="_blank" rel="noreferrer" style={{ color: A.gold }}>Link ↗</a> : "—" },
      { key: "error", label: "Last error", render: r => r.last_error ?? "—" },
      { key: "when", label: "When", render: r => new Date(r.published_at ?? r.created_at).toLocaleString() },
    ]} />
  );
}

// ══════════════════════════════════════════════════════════════════════════
// Page shell — header (Tour anchor) + inner sidebar (8 sections) + active panel
// ══════════════════════════════════════════════════════════════════════════

function useSectionCounts(tourId: string | null, summary: Summary | null) {
  const [counts, setCounts] = useState<Partial<Record<SectionKey, number>>>({});

  useEffect(() => {
    const atomizeCount = tourId
      ? summary?.by_tour.find(t => t.tour_id === tourId)?.atom_count ?? 0
      : summary?.total_count ?? 0;
    setCounts(prev => ({ ...prev, atomize: atomizeCount }));
  }, [tourId, summary]);

  useEffect(() => {
    if (!tourId) {
      setCounts(prev => ({ ...prev, segment: undefined, score: undefined, route_hub: undefined, slate: undefined, write_gate: undefined, review: undefined, publish: undefined }));
      return;
    }
    let cancelled = false;
    const specs: [SectionKey, string][] = [
      ["segment", "/api/admin/dashboard/segments"], ["score", "/api/admin/dashboard/score"],
      ["route_hub", "/api/admin/dashboard/routes"], ["slate", "/api/admin/dashboard/slate"],
      ["write_gate", "/api/admin/a4/content-log"], ["review", "/api/admin/a4/content-log"],
      ["publish", "/api/admin/a4/publish-log"],
    ];
    Promise.all(specs.map(([, url]) => fetchJson<{ total: number }>(`${url}?tour_id=${encodeURIComponent(tourId)}`).then(d => d.total).catch(() => undefined)))
      .then(totals => {
        if (cancelled) return;
        setCounts(prev => {
          const next = { ...prev };
          specs.forEach(([key], i) => { next[key] = totals[i]; });
          return next;
        });
      });
    return () => { cancelled = true; };
  }, [tourId]);

  return counts;
}

export default function AtomCurationDashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [selectedTour, setSelectedTour] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("atomize");

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    fetchJson<Summary>("/api/admin/atoms/summary")
      .then(setSummary)
      .catch(() => {})
      .finally(() => setSummaryLoading(false));
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  const counts = useSectionCounts(selectedTour, summary);
  const selectedTourMeta = useMemo(
    () => summary?.by_tour.find(t => t.tour_id === selectedTour) ?? null,
    [summary, selectedTour],
  );

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <style>{`
        @media (max-width: 980px) {
          .a527-inner-sidebar { flex-direction: row !important; overflow-x: auto !important; width: 100% !important; border-right: none !important; border-bottom: 1px solid ${A.line}; }
          .a527-inner-sidebar button { white-space: nowrap; }
          .a527-dash-body { flex-direction: column !important; }
        }
      `}</style>
      <AdminSidebar />
      <div style={{ flex: 1, padding: "28px 32px", overflowY: "auto" }}>
        <div style={{ marginBottom: 20, display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
              T5–T11 Content Pipeline
            </h1>
            <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
              8-section audit dashboard — Atomize is the only section AA acts on; the other 7 show
              what the pipeline has already produced for the selected Tour.
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 12, color: A.muted }}>Tour:</span>
            <select
              value={selectedTour ?? ""}
              onChange={e => setSelectedTour(e.target.value || null)}
              style={{ ...selectStyle, minWidth: 220, fontWeight: 600 }}
            >
              <option value="">All tours (Atomize only)</option>
              {(summary?.by_tour ?? []).map(t => (
                <option key={t.tour_id} value={t.tour_id}>{t.tour_name}</option>
              ))}
            </select>
            {selectedTourMeta && selectedTourMeta.lifecycle_stage !== "active" && (
              <Badge color={LIFECYCLE_COLOR[selectedTourMeta.lifecycle_stage]}>{selectedTourMeta.lifecycle_stage}</Badge>
            )}
          </div>
        </div>

        <div className="a527-dash-body" style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
          <div className="a527-inner-sidebar" style={{
            width: 200, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2,
            background: A.card, border: `1px solid ${A.line}`, borderRadius: 10, padding: 6,
            position: "sticky", top: 28,
          }}>
            {SECTIONS.map(s => {
              const active = activeSection === s.key;
              const count = counts[s.key];
              return (
                <button key={s.key} onClick={() => setActiveSection(s.key)} style={{
                  display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", borderRadius: 7,
                  border: "none", background: active ? A.goldTint : "transparent",
                  color: active ? A.gold : A.body, cursor: "pointer", fontFamily: sans,
                  fontSize: 12.5, fontWeight: active ? 700 : 500, textAlign: "left",
                }}>
                  {s.icon}
                  <span style={{ flex: 1 }}>{s.label}</span>
                  {count != null && (
                    <span style={{
                      fontFamily: mono, fontSize: 10.5, background: active ? A.gold : A.line2,
                      color: active ? "#fff" : A.muted, borderRadius: 999, padding: "1px 7px",
                    }}>{count}</span>
                  )}
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
            {activeSection === "segment" && <SegmentSection tourId={selectedTour} />}
            {activeSection === "score" && <ScoreSection tourId={selectedTour} />}
            {activeSection === "route_hub" && <RouteHubSection tourId={selectedTour} />}
            {activeSection === "slate" && <SlateSection tourId={selectedTour} />}
            {activeSection === "write_gate" && <WriteGateSection tourId={selectedTour} />}
            {activeSection === "review" && <ReviewSection tourId={selectedTour} />}
            {activeSection === "publish" && <PublishSection tourId={selectedTour} />}
          </div>
        </div>
      </div>
    </div>
  );
}
