"use client";
// app/admin/atom-curation/page.tsx — AA-527, admin-only Atom Curation.
//
// Replaces the tenant-facing T6 (/portal/t6-atoms, AtomsTab.tsx) that AA-526 removed along with
// atoms ever being tenant-visible — per the 04/09/2026 architecture decision, atoms are now a
// shared, platform-wide backend resource (owner_scope='platform', from A3), and it's AA-admin,
// not the tenant, who decides which atoms are good to use. AA-525 Phần 1.2's own finding: the
// reference repo (aa-social-media) has NO manual curation step at all — this page has no
// original pattern to port, it's a new design (per this issue's own text).
//
// Backend needed ZERO changes to its actual behavior (AA-525 Phần 5 mục 3 confirmed this before
// build) — api/routers/admin_atoms.py's list/summary/patch endpoints already resolve owner_scope
// via `_resolve_atom_owner_scope()`: a tenant Bearer JWT scopes to that tenant's own atoms
// (unchanged, still used by nothing tenant-facing after AA-526, kept for API stability), while
// X-Admin-Secret (this page's own path, via the existing `/api/admin/[...path]` BFF + its
// `requireAdmin()`) resolves to `owner_scope=None` — no filter, every atom across every
// owner_scope. The one small ADDITIVE change made alongside this page: `ta.owner_scope` is now
// selected in the atom list, and `by_tour` now returns each tour's distinct `owner_scopes` — so
// this page can flag legacy pre-AA-526 tenant-scoped atoms distinctly from the new
// platform-scope ones, rather than silently mixing 2 kinds of data an admin has no way to tell
// apart otherwise (a real, live, currently-mixed state — see AA-526's own implementation notes).
//
// UI/component logic (Segment grouping, atom card, star/delete) is ported near-verbatim from the
// deleted AtomsTab.tsx (git history, AA-509/AA-519) — same interaction model, just re-skinned
// onto adminUi.tsx's tokens (this admin app's own design system) instead of the tenant portal's
// ui.tsx, and grouped by TOUR first (this page's own left rail, from `summary.by_tour`) since an
// admin curates across every tour platform-wide, not one tenant's own handful.
//
// API (via /api/admin/[...path] -> X-Admin-Secret, same BFF every other /admin/* page uses):
//   GET   /api/admin/atoms/summary                          — stats + by-tour list (left rail)
//   GET   /api/admin/atoms?tour_id=&distinctiveness=&unreviewed_only=&limit=&offset=
//   PATCH /api/admin/atoms/{atom_id}                         — star / soft-delete
//
// Access: admin-only (Nghiệp's explicit choice among 2 options presented, 05/09/2026) — same
// tier as /admin/a4-oversight / /admin/tenants / /admin/llm-usage, not the broader
// admin+reviewer+content tier /admin/master-content uses. See frontend/middleware.ts's
// PROTECTED_ROUTES entry for this route.

import { useState, useEffect, useCallback } from "react";
import { Star, Trash2, ChevronDown, ChevronRight, Layers, Milestone, Puzzle } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, mono, sans, Card, Badge, Btn, LoadingScreen, StatCard } from "../_components/adminUi";

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
}

interface TourSummary {
  tour_id: string;
  tour_name: string;
  atom_count: number;
  is_thin: boolean;
  unreviewed_count: number;
  atomized_at: string | null;
  owner_scopes: string[];
}

interface Summary {
  distinctiveness_breakdown: { HIGH: number; MED: number; LOW: number };
  total_count: number;
  reviewed_count: number;
  by_tour: TourSummary[];
}

const DIST_COLOR: Record<string, "green" | "amber" | "gray"> = {
  HIGH: "green", MED: "amber", LOW: "gray",
};

const PAGE_SIZE = 50;

// A tour/atom's owner_scope is "platform" (the shared pool every tour now atomizes into, AA-526)
// or a real tenant_id UUID (a pre-AA-526 legacy row, not yet cleaned up — flagged, not hidden).
function isLegacyScope(scope: string): boolean {
  return scope !== "platform";
}

function OwnerBadge({ scope }: { scope: string }) {
  return isLegacyScope(scope)
    ? <Badge color="amber">Legacy tenant-owned</Badge>
    : <Badge color="gold">Platform</Badge>;
}

export default function AtomCurationPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [selectedTour, setSelectedTour] = useState<string | null>(null);

  const [atoms, setAtoms] = useState<Atom[]>([]);
  const [total, setTotal] = useState(0);
  const [distinctiveness, setDistinctiveness] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [atomsLoading, setAtomsLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [collapsedSegments, setCollapsedSegments] = useState<Set<string>>(new Set());

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    fetch("/api/admin/atoms/summary")
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d) setSummary(d); })
      .catch(() => {})
      .finally(() => setSummaryLoading(false));
  }, []);

  const loadAtoms = useCallback((offset: number, append: boolean) => {
    if (append) setLoadingMore(true); else setAtomsLoading(true);
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (distinctiveness) params.set("distinctiveness", distinctiveness);
    if (unreviewedOnly) params.set("unreviewed_only", "true");
    if (selectedTour) params.set("tour_id", selectedTour);
    fetch(`/api/admin/atoms?${params}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        if (!d) return;
        setAtoms(prev => (append ? [...prev, ...d.atoms] : d.atoms));
        setTotal(d.total ?? 0);
      })
      .finally(() => { setAtomsLoading(false); setLoadingMore(false); });
  }, [distinctiveness, unreviewedOnly, selectedTour]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadAtoms(0, false); }, [loadAtoms]);

  async function toggleStar(atom: Atom) {
    const next = !atom.starred;
    setAtoms(prev => prev.map(a => (a.atom_id === atom.atom_id ? { ...a, starred: next } : a)));
    await fetch(`/api/admin/atoms/${atom.atom_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ starred: next }),
    });
  }

  async function deleteAtom(atom: Atom) {
    if (!confirm("Remove this atom from the curated pool? It will no longer be used for any tenant's content going forward.")) return;
    setAtoms(prev => prev.filter(a => a.atom_id !== atom.atom_id));
    await fetch(`/api/admin/atoms/${atom.atom_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deleted: true }),
    });
    loadSummary();
  }

  const breakdown = summary?.distinctiveness_breakdown ?? { HIGH: 0, MED: 0, LOW: 0 };

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <div style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
            Atom Curation
          </h1>
          <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
            Decide which content atoms are good to use across every tenant's social content —
            atoms are a shared, platform-wide resource (extracted once per tour at Master Content
            approval), curated here, never by the tenant directly.
          </div>
        </div>

        {summaryLoading ? <LoadingScreen msg="Loading curation dashboard…" /> : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 24 }}>
              <StatCard label="Total atoms" value={String(summary?.total_count ?? 0)} icon={<Puzzle size={16} />} accent={A.gold} />
              <StatCard label="Reviewed" value={String(summary?.reviewed_count ?? 0)} accent={A.green} />
              <StatCard label="High distinctiveness" value={String(breakdown.HIGH)} accent={A.green} />
              <StatCard label="Medium" value={String(breakdown.MED)} accent={A.amber} />
              <StatCard label="Low" value={String(breakdown.LOW)} accent={A.muted2} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 18, alignItems: "start" }}>
              {/* Left rail — tours, from summary.by_tour */}
              <Card style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "12px 16px", borderBottom: `1px solid ${A.line}`, fontSize: 12, fontWeight: 600, color: A.ink3, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Tours ({summary?.by_tour.length ?? 0})
                </div>
                <div style={{ maxHeight: 640, overflowY: "auto" }}>
                  <button
                    onClick={() => setSelectedTour(null)}
                    style={{
                      display: "block", width: "100%", textAlign: "left", padding: "10px 16px",
                      background: selectedTour === null ? A.bg : "transparent", border: "none",
                      borderBottom: `1px solid ${A.line2}`, cursor: "pointer", fontFamily: sans,
                      fontSize: 12.5, fontWeight: selectedTour === null ? 700 : 500, color: A.ink,
                    }}
                  >
                    All tours
                  </button>
                  {(summary?.by_tour ?? []).map(t => (
                    <button
                      key={t.tour_id}
                      onClick={() => setSelectedTour(t.tour_id)}
                      style={{
                        display: "block", width: "100%", textAlign: "left", padding: "10px 16px",
                        background: selectedTour === t.tour_id ? A.bg : "transparent", border: "none",
                        borderBottom: `1px solid ${A.line2}`, cursor: "pointer", fontFamily: sans,
                      }}
                    >
                      <div style={{ fontSize: 12.5, fontWeight: selectedTour === t.tour_id ? 700 : 500, color: A.ink, marginBottom: 3 }}>
                        {t.tour_name}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 11, color: A.muted }}>{t.atom_count} atoms</span>
                        {t.is_thin && <Badge color="red">Thin</Badge>}
                        {t.unreviewed_count > 0 && <Badge color="blue">{t.unreviewed_count} new</Badge>}
                        {t.owner_scopes.map(s => <OwnerBadge key={s} scope={s} />)}
                      </div>
                    </button>
                  ))}
                </div>
              </Card>

              {/* Right panel — filters + atom list */}
              <div>
                <div style={{ display: "flex", gap: 10, marginBottom: 14, alignItems: "center" }}>
                  <select value={distinctiveness} onChange={e => setDistinctiveness(e.target.value)}
                    style={{ padding: "8px 12px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8, fontSize: 13, fontFamily: sans, color: A.body, cursor: "pointer" }}>
                    <option value="">All distinctiveness</option>
                    <option value="HIGH">High</option>
                    <option value="MED">Medium</option>
                    <option value="LOW">Low</option>
                  </select>
                  <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: A.body, cursor: "pointer" }}>
                    <input type="checkbox" checked={unreviewedOnly} onChange={e => setUnreviewedOnly(e.target.checked)} />
                    Unreviewed only
                  </label>
                </div>

                {atomsLoading ? <LoadingScreen msg="Loading atoms…" /> : atoms.length === 0 ? (
                  <Card>
                    <div style={{ textAlign: "center", padding: "40px 20px" }}>
                      <div style={{ fontSize: 32, marginBottom: 10 }}>🧩</div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: A.ink, marginBottom: 6 }}>No atoms match this filter</div>
                      <div style={{ fontSize: 13, color: A.muted }}>
                        Atoms are extracted automatically once a tour is approved into Master Content — nothing to trigger here.
                      </div>
                    </div>
                  </Card>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {groupBySegment(atoms).map(row =>
                      row.kind === "atom" ? (
                        <AtomCard key={row.atom.atom_id} atom={row.atom} showTour={!selectedTour} onStar={toggleStar} onDelete={deleteAtom} />
                      ) : (
                        <SegmentGroup
                          key={row.segmentId}
                          place={row.place}
                          action={row.action}
                          atoms={row.atoms}
                          score={row.score}
                          routeHubName={row.routeHubName}
                          showTour={!selectedTour}
                          collapsed={collapsedSegments.has(row.segmentId)}
                          onToggle={() => setCollapsedSegments(prev => {
                            const next = new Set(prev);
                            next.has(row.segmentId) ? next.delete(row.segmentId) : next.add(row.segmentId);
                            return next;
                          })}
                          onStar={toggleStar}
                          onDelete={deleteAtom}
                        />
                      )
                    )}
                  </div>
                )}

                {atoms.length < total && (
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
      </div>
    </div>
  );
}

// Same row-grouping shape/logic AtomsTab.tsx used (AA-509) — a Segment with >=2 currently-loaded
// members renders as one collapsible group, everything else as a lone atom card. Evaluated over
// whatever page is currently loaded; a Segment split across 2 pages renders as separate singleton
// rows on each (same known limitation as before, unchanged by this port).
type AtomRow =
  | { kind: "atom"; atom: Atom }
  | {
      kind: "segment"; segmentId: string; place: string; action: string; atoms: Atom[];
      score: number | null; routeHubName: string | null;
    };

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
        kind: "segment",
        segmentId: atom.segment_id!,
        place: members[0].canonical_place ?? "",
        action: members[0].canonical_action ?? "",
        atoms: members,
        score: members.find(m => m.segment_score != null)?.segment_score ?? null,
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
          {showTour && (
            <div style={{ fontSize: 11, color: A.muted2, marginBottom: 4, fontFamily: mono }}>{atom.tour_name}</div>
          )}
          <div style={{ fontSize: 13.5, color: A.body, lineHeight: 1.5 }}>{atom.text}</div>
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <Badge color={DIST_COLOR[atom.distinctiveness] ?? "gray"}>{atom.distinctiveness}</Badge>
            {atom.activity_type && <Badge color="gray">{atom.activity_type}</Badge>}
            {atom.unreviewed && <Badge color="blue">New</Badge>}
            <OwnerBadge scope={atom.owner_scope} />
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
  place: string; action: string; atoms: Atom[];
  score: number | null; routeHubName: string | null; showTour: boolean; collapsed: boolean;
  onToggle: () => void; onStar: (a: Atom) => void; onDelete: (a: Atom) => void;
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
          <span style={{
            fontFamily: mono, fontSize: 11, color: A.ink3, background: A.card,
            border: `1px solid ${A.line}`, borderRadius: 6, padding: "2px 7px",
          }} title="Rank-sum — lower is better">
            Score {score}
          </span>
        )}
        {routeHubName && (
          <Badge color="gold">
            <Milestone size={11} style={{ verticalAlign: -2, marginRight: 3 }} />
            Part of Route: {routeHubName}
          </Badge>
        )}
        <span style={{ fontSize: 11.5, color: A.muted2, marginLeft: "auto" }}>
          {atoms.length} atoms, same moment
        </span>
      </button>
      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8, background: A.card }}>
          {atoms.map(atom => (
            <AtomCard key={atom.atom_id} atom={atom} showTour={showTour} onStar={onStar} onDelete={onDelete} />
          ))}
        </div>
      )}
    </div>
  );
}
