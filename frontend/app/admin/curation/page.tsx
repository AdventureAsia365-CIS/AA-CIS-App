"use client";
// app/admin/curation/page.tsx — AA-300 atom curation, redesigned per
// Nghiep's direct feedback after reviewing the live card-grid version:
// table rows (not cards), grouped by tour (accordion, default-open for
// thin/unreviewed tours per the curation rule in the original issue),
// multi-select with a floating bulk-action bar, a full dashboard of
// counts, and load-more instead of Pagination.tsx.
//
// Patterns reused verbatim from frontend/app/admin/master-content/page.tsx
// (this repo's own established convention for exactly this shape of page):
// checkbox multi-select via `Set<string>` state + toggleSelect(), StatCard
// row for dashboard counts, <table>/<thead>/<tbody> instead of a card grid.
// No small centered confirm-dialog convention existed anywhere in the repo
// (CompareModal.tsx is a full-screen modal, a different shape) — the
// delete-confirmation dialog here is a self-chosen minimal adaptation of
// the same fixed/backdrop overlay technique, not a new pattern invented
// from scratch.

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Star, Trash2, ImageIcon, Sparkles, Pencil, Check, X as XIcon,
  Grid3x3, ChevronDown, ChevronRight, AlertTriangle,
} from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { FilterBar } from "../_components/FilterBar";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen, StatCard } from "../_components/adminUi";

const LOAD_LIMIT = 150;

interface Atom {
  atom_id: string;
  tour_id: string;
  tour_name: string;
  text: string;
  activity_type: string | null;
  emotional_hook: string | null;
  visual_potential: number;
  distinctiveness: "HIGH" | "MED" | "LOW";
  media: { has_photo?: boolean; has_video?: boolean; media_refs?: string[] };
  starred: boolean;
  deleted: boolean;
  unreviewed: boolean;
  tour_atom_count: number;
}

interface TourSummary {
  tour_id: string;
  tour_name: string;
  atom_count: number;
  is_thin: boolean;
  unreviewed_count: number;
}

interface Summary {
  distinctiveness_breakdown: { HIGH: number; MED: number; LOW: number };
  total_count: number;
  reviewed_count: number;
  by_tour: TourSummary[];
}

const DIST_BADGE: Record<string, "green" | "amber" | "gray"> = { HIGH: "green", MED: "amber", LOW: "gray" };

// Clearance so the fixed floating bulk-action bar (~56px tall, sitting 24px
// off the viewport bottom) never covers the Load More button underneath it.
const FLOATING_BAR_CLEARANCE = 92;

type SortKey = "" | "atoms_asc" | "atoms_desc" | "unreviewed_desc" | "name_asc";

const SORT_OPTIONS: { label: string; value: SortKey }[] = [
  { label: "Atom count (asc)", value: "atoms_asc" },
  { label: "Atom count (desc)", value: "atoms_desc" },
  { label: "% unreviewed (most first)", value: "unreviewed_desc" },
  { label: "Tour name (A–Z)", value: "name_asc" },
];

export default function CurationPage() {
  const router = useRouter();

  const [summary, setSummary] = useState<Summary | null>(null);
  const [atoms, setAtoms] = useState<Atom[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [distinctiveness, setDistinctiveness] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [thinOnly, setThinOnly] = useState(false);
  const [sortBy, setSortBy] = useState<SortKey>("");

  const [expandedTourIds, setExpandedTourIds] = useState<Set<string>>(new Set());
  const didInitExpand = useRef(false);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // ── dashboard summary — independent of the atom list's current filter ────
  const loadSummary = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/atoms/summary");
      if (!res.ok) throw new Error(`Failed to load summary (${res.status})`);
      const data: Summary = await res.json();
      setSummary(data);
      if (!didInitExpand.current) {
        didInitExpand.current = true;
        setExpandedTourIds(new Set(
          data.by_tour.filter(t => t.is_thin || t.unreviewed_count > 0).map(t => t.tour_id),
        ));
      }
    } catch (err: any) {
      setError(err.message || "Failed to load summary.");
    }
  }, []);

  // ── atom list — resets on filter change, appends on "Load more" ──────────
  const loadAtoms = useCallback(async (reset: boolean) => {
    const nextOffset = reset ? 0 : offset;
    if (reset) setLoading(true); else setLoadingMore(true);
    setError("");
    const params = new URLSearchParams({ limit: String(LOAD_LIMIT), offset: String(nextOffset) });
    if (distinctiveness) params.set("distinctiveness", distinctiveness);
    if (unreviewedOnly) params.set("unreviewed_only", "true");
    if (thinOnly) params.set("thin_only", "true");
    try {
      const res = await fetch(`/api/admin/atoms?${params}`);
      if (!res.ok) throw new Error(`Failed to load atoms (${res.status})`);
      const data = await res.json();
      setAtoms(prev => (reset ? data.atoms : [...prev, ...data.atoms]));
      setTotal(data.total);
      setOffset(nextOffset + data.atoms.length);
    } catch (err: any) {
      setError(err.message || "Failed to load atoms.");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [distinctiveness, unreviewedOnly, thinOnly]);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { loadAtoms(true); }, [loadAtoms]);

  // ── single-atom actions ────────────────────────────────────────────────
  async function patchAtom(atomId: string, body: Record<string, unknown>) {
    setBusyIds(prev => new Set(prev).add(atomId));
    try {
      const res = await fetch(`/api/admin/atoms/${atomId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Update failed (${res.status})`);
      }
      const updated = await res.json();
      if (updated.deleted) {
        setAtoms(prev => prev.filter(a => a.atom_id !== atomId));
        setTotal(t => Math.max(0, t - 1));
        setSelectedIds(prev => { const n = new Set(prev); n.delete(atomId); return n; });
      } else {
        setAtoms(prev => prev.map(a => (a.atom_id === atomId ? { ...a, ...updated } : a)));
      }
      loadSummary();
    } catch (err: any) {
      setError(err.message || "Update failed.");
    } finally {
      setBusyIds(prev => { const n = new Set(prev); n.delete(atomId); return n; });
    }
  }

  function toggleStar(atom: Atom) { patchAtom(atom.atom_id, { starred: !atom.starred }); }
  function deleteAtom(atom: Atom) { patchAtom(atom.atom_id, { deleted: true }); }
  function startEdit(atom: Atom) { setEditingId(atom.atom_id); setEditText(atom.text); }
  function saveEdit(atomId: string) {
    if (!editText.trim()) return;
    patchAtom(atomId, { text: editText.trim() });
    setEditingId(null);
  }

  // ── bulk actions ───────────────────────────────────────────────────────
  async function bulkPatch(body: Record<string, unknown>) {
    const ids = [...selectedIds];
    if (ids.length === 0) return;
    setBulkBusy(true);
    try {
      const res = await fetch("/api/admin/atoms/bulk", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ atom_ids: ids, ...body }),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        throw new Error(e.detail || `Bulk update failed (${res.status})`);
      }
      if (body.deleted) {
        setAtoms(prev => prev.filter(a => !selectedIds.has(a.atom_id)));
        setTotal(t => Math.max(0, t - ids.length));
      } else {
        const idSet = new Set(ids);
        setAtoms(prev => prev.map(a => (idSet.has(a.atom_id) ? { ...a, ...body } : a)));
      }
      setSelectedIds(new Set());
      loadSummary();
    } catch (err: any) {
      setError(err.message || "Bulk update failed.");
    } finally {
      setBulkBusy(false);
      setShowDeleteConfirm(false);
    }
  }

  function toggleSelectRow(atomId: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(atomId) ? next.delete(atomId) : next.add(atomId);
      return next;
    });
  }

  function toggleSelectSection(sectionAtoms: Atom[]) {
    const ids = sectionAtoms.map(a => a.atom_id);
    const allSelected = ids.every(id => selectedIds.has(id));
    setSelectedIds(prev => {
      const next = new Set(prev);
      ids.forEach(id => (allSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  }

  function toggleTourExpand(tourId: string) {
    setExpandedTourIds(prev => {
      const next = new Set(prev);
      next.has(tourId) ? next.delete(tourId) : next.add(tourId);
      return next;
    });
  }

  // ── keyboard shortcuts: X = delete, S = star (hovered row) ───────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      if (!hoveredId) return;
      const atom = atoms.find(a => a.atom_id === hoveredId);
      if (!atom) return;
      if (e.key === "x" || e.key === "X") { e.preventDefault(); deleteAtom(atom); }
      if (e.key === "s" || e.key === "S") { e.preventDefault(); toggleStar(atom); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hoveredId, atoms]);

  // ── group loaded atoms by tour, in summary.by_tour order ─────────────────
  const atomsByTour = useMemo(() => {
    const map = new Map<string, Atom[]>();
    for (const a of atoms) {
      if (!map.has(a.tour_id)) map.set(a.tour_id, []);
      map.get(a.tour_id)!.push(a);
    }
    return map;
  }, [atoms]);

  const orderedSections = useMemo(() => {
    if (!summary) return [];
    const order = summary.by_tour.filter(t => atomsByTour.has(t.tour_id));
    // tours with loaded atoms but not (yet) in the summary snapshot — keep them visible
    const known = new Set(order.map(t => t.tour_id));
    const extra: TourSummary[] = [];
    for (const [tourId, list] of atomsByTour) {
      if (!known.has(tourId)) {
        extra.push({ tour_id: tourId, tour_name: list[0].tour_name, atom_count: list.length, is_thin: false, unreviewed_count: 0 });
      }
    }
    const combined = [...order, ...extra];
    if (!sortBy) return combined; // default — unchanged order from summary.by_tour
    const sorted = [...combined];
    if (sortBy === "atoms_asc") sorted.sort((a, b) => a.atom_count - b.atom_count);
    else if (sortBy === "atoms_desc") sorted.sort((a, b) => b.atom_count - a.atom_count);
    else if (sortBy === "unreviewed_desc") {
      sorted.sort((a, b) => (b.unreviewed_count / (b.atom_count || 1)) - (a.unreviewed_count / (a.atom_count || 1)));
    } else if (sortBy === "name_asc") sorted.sort((a, b) => a.tour_name.localeCompare(b.tour_name));
    return sorted;
  }, [summary, atomsByTour, sortBy]);

  const searchLower = search.trim().toLowerCase();

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1400, margin: "0 auto", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <Sparkles size={18} color={A.gold} />
          <h1 style={{ fontFamily: serif, fontSize: 22, fontWeight: 500, color: A.ink, margin: 0 }}>
            Atom Curation
          </h1>
          <div style={{ flex: 1 }} />
          <Btn size="sm" variant="secondary" onClick={() => router.push("/admin/curation/preview")}>
            <Grid3x3 size={12} /> Preview Slot Grid (N6)
          </Btn>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 16 }}>
          Grouped by tour — thin tours (&lt; 5 atoms) or tours with unreviewed atoms open by
          default. Hover a row and press <b>X</b> to delete, <b>S</b> to star.
        </p>

        {/* ── Dashboard ──────────────────────────────────────────────────── */}
        {summary && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 10, marginBottom: 18 }}>
            <StatCard icon={<Sparkles size={16} />} label="Total Atoms" value={String(summary.total_count)} />
            {(["HIGH", "MED", "LOW"] as const).map(level => {
              const count = summary.distinctiveness_breakdown[level];
              return (
                <div key={level} style={{ opacity: count === 0 ? 0.45 : 1 }}>
                  <StatCard
                    icon={<Star size={16} />} label={level} value={String(count)}
                    accent={count === 0 ? A.muted2 : DIST_BADGE[level] === "green" ? A.green : DIST_BADGE[level] === "amber" ? A.amber : A.muted}
                    sub={count === 0 ? "chưa có (AA-317)" : "distinctiveness"}
                  />
                </div>
              );
            })}
            <StatCard
              icon={<Check size={16} />} label="Reviewed"
              value={`${summary.reviewed_count} / ${summary.total_count}`}
            />
          </div>
        )}

        <FilterBar
          search={search}
          onSearch={setSearch}
          placeholder="Filter loaded batch by text or tour…"
          filters={[
            {
              label: "Distinctiveness", value: distinctiveness, current: distinctiveness,
              options: [
                { label: "All", value: "" },
                { label: "HIGH", value: "HIGH" },
                { label: "MED", value: "MED" },
                { label: "LOW", value: "LOW" },
              ],
              onChange: setDistinctiveness,
            },
            {
              label: "Sort", value: sortBy, current: sortBy,
              allLabel: "Default",
              options: SORT_OPTIONS,
              onChange: v => setSortBy(v as SortKey),
            },
          ]}
          extra={
            <>
              <Btn variant={unreviewedOnly ? "primary" : "secondary"} size="sm" onClick={() => setUnreviewedOnly(v => !v)}>
                Unreviewed only
              </Btn>
              <Btn variant={thinOnly ? "primary" : "secondary"} size="sm" onClick={() => setThinOnly(v => !v)}>
                Thin tours only
              </Btn>
            </>
          }
        />

        {error && (
          <div style={{ fontSize: 12, padding: "8px 12px", borderRadius: 6, marginBottom: 14, background: A.redSoft, color: A.red }}>
            {error}
          </div>
        )}

        {loading ? (
          <LoadingScreen msg="Loading atoms…" />
        ) : orderedSections.length === 0 ? (
          <Card><div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: 20 }}>
            No atoms match the current filters.
          </div></Card>
        ) : (
          // Fixed-height scroll container, not a page-length scroll + separate
          // Pagination — replaces Pagination.tsx per Nghiep's direct feedback.
          <div style={{
            flex: 1, minHeight: 0, overflowY: "auto", border: `1px solid ${A.line}`, borderRadius: 10, background: "#fff",
            // Room for Load More to scroll clear of the floating bulk-action
            // bar, which is position:fixed and would otherwise sit on top of it.
            paddingBottom: selectedIds.size > 0 ? FLOATING_BAR_CLEARANCE : 0,
          }}>
            {orderedSections.map(section => {
              const sectionAtoms = (atomsByTour.get(section.tour_id) || []).filter(a =>
                !searchLower || a.text.toLowerCase().includes(searchLower) || a.tour_name.toLowerCase().includes(searchLower));
              if (sectionAtoms.length === 0 && searchLower) return null;
              const isExpanded = expandedTourIds.has(section.tour_id);
              const allSelected = sectionAtoms.length > 0 && sectionAtoms.every(a => selectedIds.has(a.atom_id));

              return (
                <div key={section.tour_id} style={{ borderBottom: `1px solid ${A.line}` }}>
                  <div
                    onClick={() => toggleTourExpand(section.tour_id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8, padding: "10px 16px",
                      cursor: "pointer", background: A.line2, fontFamily: sans,
                    }}
                  >
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onClick={e => e.stopPropagation()}
                      onChange={() => toggleSelectSection(sectionAtoms)}
                      style={{ accentColor: A.gold }}
                    />
                    <span style={{ fontWeight: 600, color: A.ink, fontSize: 13 }}>{section.tour_name}</span>
                    <Badge color="gray">{section.atom_count} atoms</Badge>
                    {section.is_thin && <Badge color="red">thin</Badge>}
                    {section.unreviewed_count > 0 && <Badge color="blue">{section.unreviewed_count} unreviewed</Badge>}
                  </div>

                  {isExpanded && (
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr>
                          <th style={{ width: 30 }} />
                          <th style={thStyle}>Distinctiveness</th>
                          <th style={thStyle}>Text</th>
                          <th style={{ ...thStyle, width: 70 }}>Visual</th>
                          <th style={{ ...thStyle, width: 60 }}>Photo</th>
                          <th style={{ ...thStyle, width: 110 }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sectionAtoms.map((atom, i) => (
                          <tr
                            key={atom.atom_id}
                            onMouseEnter={() => setHoveredId(atom.atom_id)}
                            onMouseLeave={() => setHoveredId(id => (id === atom.atom_id ? null : id))}
                            style={{
                              background: hoveredId === atom.atom_id ? `${A.gold}10` : i % 2 === 0 ? "#fff" : A.bg,
                              opacity: busyIds.has(atom.atom_id) ? 0.5 : 1,
                            }}
                          >
                            <td style={tdStyle}>
                              <input
                                type="checkbox"
                                checked={selectedIds.has(atom.atom_id)}
                                onChange={() => toggleSelectRow(atom.atom_id)}
                                style={{ accentColor: A.gold }}
                              />
                            </td>
                            <td style={tdStyle}><Badge color={DIST_BADGE[atom.distinctiveness]}>{atom.distinctiveness}</Badge></td>
                            <td style={{ ...tdStyle, maxWidth: 480 }}>
                              {editingId === atom.atom_id ? (
                                <div>
                                  <textarea
                                    value={editText}
                                    onChange={e => setEditText(e.target.value)}
                                    style={{
                                      width: "100%", boxSizing: "border-box", fontFamily: sans, fontSize: 13,
                                      padding: "6px 8px", borderRadius: 6, border: `1px solid ${A.line}`, minHeight: 50,
                                    }}
                                  />
                                  <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                                    <Btn size="sm" variant="primary" onClick={() => saveEdit(atom.atom_id)}><Check size={11} /> Save</Btn>
                                    <Btn size="sm" variant="ghost" onClick={() => setEditingId(null)}><XIcon size={11} /> Cancel</Btn>
                                  </div>
                                </div>
                              ) : (
                                <span style={{ fontSize: 13, color: A.body }}>{atom.text}</span>
                              )}
                            </td>
                            <td style={tdStyle}>
                              <span style={{ fontSize: 11, color: A.muted2 }}>
                                {"●".repeat(atom.visual_potential)}{"○".repeat(3 - atom.visual_potential)}
                              </span>
                            </td>
                            <td style={tdStyle}>{atom.media?.has_photo && <ImageIcon size={13} color={A.muted2} />}</td>
                            <td style={tdStyle}>
                              <div style={{ display: "flex", gap: 6 }}>
                                <button title="Star (S)" onClick={() => toggleStar(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: atom.starred ? A.gold : A.muted2, display: "flex" }}>
                                  <Star size={14} fill={atom.starred ? A.gold : "none"} />
                                </button>
                                <button title="Edit text" onClick={() => startEdit(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex" }}>
                                  <Pencil size={13} />
                                </button>
                                <button title="Delete (X)" onClick={() => deleteAtom(atom)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: A.red, display: "flex" }}>
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              );
            })}

            {atoms.length < total && (
              <div style={{ padding: 16, textAlign: "center" }}>
                <Btn variant="secondary" onClick={() => loadAtoms(false)} disabled={loadingMore}>
                  {loadingMore ? "Loading…" : `Load more (${atoms.length} / ${total})`}
                </Btn>
              </div>
            )}
          </div>
        )}

        {/* ── Floating bulk-action bar ─────────────────────────────────────── */}
        {selectedIds.size > 0 && (
          <div style={{
            position: "fixed", bottom: 24, left: "50%", transform: "translateX(-50%)",
            background: A.ink, color: "#fff", borderRadius: 10, padding: "10px 16px",
            display: "flex", alignItems: "center", gap: 12, boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
            zIndex: 200, fontFamily: sans,
          }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.size} atoms selected</span>
            <Btn size="sm" variant="secondary" disabled={bulkBusy} onClick={() => bulkPatch({ starred: true })}>
              <Star size={12} /> Star all
            </Btn>
            <Btn size="sm" variant="danger" disabled={bulkBusy} onClick={() => setShowDeleteConfirm(true)}>
              <Trash2 size={12} /> Delete all
            </Btn>
            <button onClick={() => setSelectedIds(new Set())}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#C9CFD8", fontSize: 12 }}>
              Clear
            </button>
          </div>
        )}

        {/* ── Delete-all confirmation dialog ───────────────────────────────── */}
        {showDeleteConfirm && (
          <div style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 300,
          }}>
            <div style={{ background: "#fff", borderRadius: 12, padding: 24, maxWidth: 380, fontFamily: sans }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <AlertTriangle size={18} color={A.red} />
                <span style={{ fontFamily: serif, fontSize: 17, color: A.ink }}>Delete {selectedIds.size} atoms?</span>
              </div>
              <p style={{ fontSize: 13, color: A.muted, marginBottom: 18 }}>
                Không thể hoàn tác. Các atom này sẽ không bao giờ xuất hiện trong slot allocator nữa.
              </p>
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <Btn variant="ghost" onClick={() => setShowDeleteConfirm(false)}>Cancel</Btn>
                <Btn variant="danger" disabled={bulkBusy} onClick={() => bulkPatch({ deleted: true })}>
                  {bulkBusy ? "Deleting…" : "Confirm Delete"}
                </Btn>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: "8px 12px", fontSize: 10, fontWeight: 600, textTransform: "uppercase",
  letterSpacing: "0.08em", color: A.muted, textAlign: "left", borderBottom: `1px solid ${A.line}`,
};
const tdStyle: React.CSSProperties = {
  padding: "8px 12px", fontSize: 13, color: A.body, borderBottom: `1px solid ${A.line2}`,
};
