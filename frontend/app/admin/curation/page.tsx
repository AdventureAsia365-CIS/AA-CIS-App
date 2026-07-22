"use client";
// app/admin/curation/page.tsx — AA-300 atom curation (batch review/star/delete)
// Batch of 50 atoms/screen (not one at a time). Keyboard shortcuts X (delete)
// and S (star) apply to whichever card the mouse is currently hovering, per
// the issue's "mỗi giây đều đáng" framing — Trang works through many tours
// in one sitting, so shortcuts should not require an extra click to select
// a card first. Ignored while a text field is focused (editing text) so
// typing "x"/"s" doesn't fire a shortcut by accident.

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Star, Trash2, ImageIcon, Sparkles, Pencil, Check, X as XIcon, Grid3x3 } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { FilterBar } from "../_components/FilterBar";
import { Pagination } from "../_components/Pagination";
import { A, sans, serif, Card, Btn, Badge, LoadingScreen } from "../_components/adminUi";

const PAGE_SIZE = 50;

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

const DIST_BADGE: Record<string, "green" | "amber" | "gray"> = { HIGH: "green", MED: "amber", LOW: "gray" };

export default function CurationPage() {
  const router = useRouter();
  const [atoms, setAtoms] = useState<Atom[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [distinctiveness, setDistinctiveness] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [thinOnly, setThinOnly] = useState(false);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    });
    if (distinctiveness) params.set("distinctiveness", distinctiveness);
    if (unreviewedOnly) params.set("unreviewed_only", "true");
    if (thinOnly) params.set("thin_only", "true");
    try {
      const res = await fetch(`/api/admin/atoms?${params}`);
      if (!res.ok) throw new Error(`Failed to load atoms (${res.status})`);
      const data = await res.json();
      setAtoms(data.atoms);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || "Failed to load atoms.");
    } finally {
      setLoading(false);
    }
  }, [page, distinctiveness, unreviewedOnly, thinOnly]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(1); }, [distinctiveness, unreviewedOnly, thinOnly]);

  async function patchAtom(atomId: string, body: Record<string, unknown>) {
    setBusyId(atomId);
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
        // Issue: "Atom bị xoá -> không bao giờ xuất hiện trong slot" — the
        // list endpoint already excludes deleted=true by default, so drop
        // it from the current view immediately rather than waiting for a
        // refetch.
        setAtoms(prev => prev.filter(a => a.atom_id !== atomId));
        setTotal(t => Math.max(0, t - 1));
      } else {
        setAtoms(prev => prev.map(a => (a.atom_id === atomId ? { ...a, ...updated } : a)));
      }
    } catch (err: any) {
      setError(err.message || "Update failed.");
    } finally {
      setBusyId(null);
    }
  }

  function toggleStar(atom: Atom) {
    patchAtom(atom.atom_id, { starred: !atom.starred });
  }

  function deleteAtom(atom: Atom) {
    patchAtom(atom.atom_id, { deleted: true });
  }

  function startEdit(atom: Atom) {
    setEditingId(atom.atom_id);
    setEditText(atom.text);
  }

  function saveEdit(atomId: string) {
    if (!editText.trim()) return;
    patchAtom(atomId, { text: editText.trim() });
    setEditingId(null);
  }

  // ── keyboard shortcuts: X = delete, S = star (hovered card) ──────────────
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return; // don't fire while editing text
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

  const visibleAtoms = search.trim()
    ? atoms.filter(a =>
        a.text.toLowerCase().includes(search.toLowerCase()) ||
        a.tour_name.toLowerCase().includes(search.toLowerCase()))
    : atoms;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "28px 32px", maxWidth: 1400 }}>
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
        <p style={{ fontSize: 13, color: A.muted, marginTop: 4, marginBottom: 18 }}>
          Batch of {PAGE_SIZE} atoms per screen — star good ones, delete wrong ones, lightly edit
          text. Hover a card and press <b>X</b> to delete, <b>S</b> to star.
        </p>

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
          ]}
          extra={
            <>
              <Btn
                variant={unreviewedOnly ? "primary" : "secondary"} size="sm"
                onClick={() => setUnreviewedOnly(v => !v)}
              >
                Unreviewed only
              </Btn>
              <Btn
                variant={thinOnly ? "primary" : "secondary"} size="sm"
                onClick={() => setThinOnly(v => !v)}
              >
                Thin tours only
              </Btn>
            </>
          }
        />

        {error && (
          <div style={{
            fontSize: 12, padding: "8px 12px", borderRadius: 6, marginBottom: 14,
            background: A.redSoft, color: A.red,
          }}>{error}</div>
        )}

        {loading ? (
          <LoadingScreen msg="Loading atoms…" />
        ) : visibleAtoms.length === 0 ? (
          <Card><div style={{ fontSize: 13, color: A.muted, textAlign: "center", padding: 20 }}>
            No atoms match the current filters.
          </div></Card>
        ) : (
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 12, marginBottom: 20,
          }}>
            {visibleAtoms.map(atom => (
              <div
                key={atom.atom_id}
                onMouseEnter={() => setHoveredId(atom.atom_id)}
                onMouseLeave={() => setHoveredId(id => (id === atom.atom_id ? null : id))}
              >
                <Card style={{
                  padding: 14,
                  border: `1px solid ${hoveredId === atom.atom_id ? A.gold : A.line}`,
                  opacity: busyId === atom.atom_id ? 0.6 : 1,
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
                    <Badge color={DIST_BADGE[atom.distinctiveness]}>{atom.distinctiveness}</Badge>
                    {atom.tour_atom_count < 5 && <Badge color="red">thin tour ({atom.tour_atom_count})</Badge>}
                    {atom.unreviewed && <Badge color="blue">unreviewed</Badge>}
                    <div style={{ flex: 1 }} />
                    {atom.media?.has_photo && <ImageIcon size={13} color={A.muted2} />}
                  </div>

                  <div style={{ fontSize: 11, color: A.muted, marginBottom: 4, fontFamily: sans }}>
                    {atom.tour_name}
                  </div>

                  {editingId === atom.atom_id ? (
                    <div>
                      <textarea
                        value={editText}
                        onChange={e => setEditText(e.target.value)}
                        style={{
                          width: "100%", boxSizing: "border-box", fontFamily: sans, fontSize: 13,
                          padding: "6px 8px", borderRadius: 6, border: `1px solid ${A.line}`,
                          minHeight: 60, resize: "vertical",
                        }}
                      />
                      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                        <Btn size="sm" variant="primary" onClick={() => saveEdit(atom.atom_id)}>
                          <Check size={12} /> Save
                        </Btn>
                        <Btn size="sm" variant="ghost" onClick={() => setEditingId(null)}>
                          <XIcon size={12} /> Cancel
                        </Btn>
                      </div>
                    </div>
                  ) : (
                    <div style={{ fontSize: 13, color: A.body, lineHeight: 1.5, marginBottom: 10 }}>
                      {atom.text}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <div style={{ fontSize: 10, color: A.muted2 }}>
                      visual: {"●".repeat(atom.visual_potential)}{"○".repeat(3 - atom.visual_potential)}
                    </div>
                    <div style={{ flex: 1 }} />
                    <button
                      title="Star (S)"
                      onClick={() => toggleStar(atom)}
                      style={{
                        background: "none", border: "none", cursor: "pointer",
                        color: atom.starred ? A.gold : A.muted2, display: "flex",
                      }}
                    >
                      <Star size={16} fill={atom.starred ? A.gold : "none"} />
                    </button>
                    <button
                      title="Edit text"
                      onClick={() => startEdit(atom)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: A.muted2, display: "flex" }}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      title="Delete (X)"
                      onClick={() => deleteAtom(atom)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: A.red, display: "flex" }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </Card>
              </div>
            ))}
          </div>
        )}

        <Pagination page={page} total={total} pageSize={PAGE_SIZE} onPage={setPage} />
      </main>
    </div>
  );
}
