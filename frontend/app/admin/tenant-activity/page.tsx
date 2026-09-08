"use client";
// app/admin/tenant-activity/page.tsx — AA-551, new page.
//
// Split out of the original single-page `/admin/atom-curation` (AA-527 bổ sung, 05/09/2026) per
// AA-550's audit finding: sections 06-08 (Write/Gate, Review, Publish) show a specific TENANT's
// activity on a specific Tour — a genuinely different subject than 01-05's platform-wide Master
// Content monitoring (see `/admin/atom-curation`'s own header comment). Putting both under one
// sidebar/header, as the original page did, "lẫn lộn nội dung của tầng admin và tenant" (Nghiệp,
// AA-550 point C.8) — this page is the fix: same Tour-picker requirement as before (unchanged,
// this genuinely IS per-Tour tenant data), separate page/nav entry so the boundary is visible in
// the URL and sidebar, not just a comment in the code.
//
// Content/behavior of all 3 sections is UNCHANGED from the original page — only the page shell
// (header, Tour-picker, inner section-nav) is new here, and the section components themselves
// moved to `../_components/auditPanels.tsx` (shared, in case a future page needs them again)
// rather than being copy-pasted between this file and `/admin/atom-curation`'s.
//
// Backend: GET /api/admin/a4/content-log?tour_id= (Write/Gate + Review) and
// GET /api/admin/a4/publish-log?tour_id= (Publish) — both admin_a4.py, unchanged by AA-551.
// Tour list reuses the same GET /api/admin/atoms/summary the Atomize section already calls (its
// `by_tour` array) rather than a new endpoint — this page doesn't need Atom-specific fields from
// it, just the Tour id/name list.
import { useState, useEffect, useCallback } from "react";
import { PenSquare, Eye, Send } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import { A, serif, sans, Card, Badge, LoadingScreen } from "../_components/adminUi";
import { fetchJson, WriteGateSection, ReviewSection, PublishSection } from "../_components/auditPanels";

interface TourSummary {
  tour_id: string; tour_name: string; atom_count: number;
  lifecycle_stage: "active" | "phasing_out" | "retired";
}
interface Summary { by_tour: TourSummary[]; }

type SectionKey = "write_gate" | "review" | "publish";

const SECTIONS: { key: SectionKey; label: string; icon: React.ReactNode }[] = [
  { key: "write_gate", label: "06 · Write/Gate", icon: <PenSquare size={15} /> },
  { key: "review",     label: "07 · Review",     icon: <Eye size={15} /> },
  { key: "publish",    label: "08 · Publish",    icon: <Send size={15} /> },
];

const LIFECYCLE_COLOR: Record<string, "green" | "amber" | "gray"> = {
  active: "green", phasing_out: "amber", retired: "gray",
};

const selectStyle: React.CSSProperties = {
  padding: "8px 12px", background: A.card, border: `1px solid ${A.line}`, borderRadius: 8,
  fontSize: 13, fontFamily: sans, color: A.body, cursor: "pointer",
};

function useSectionCounts(tourId: string | null) {
  const [counts, setCounts] = useState<Partial<Record<SectionKey, number>>>({});

  useEffect(() => {
    if (!tourId) { setCounts({}); return; }
    let cancelled = false;
    const specs: [SectionKey, string][] = [
      ["write_gate", "/api/admin/a4/content-log"], ["review", "/api/admin/a4/content-log"],
      ["publish", "/api/admin/a4/publish-log"],
    ];
    // AA-551 — this page's own version of the concurrency the 401 investigation flagged: up to 3
    // simultaneous /api/admin/* calls per Tour selection (was up to 7 on the original combined
    // page). requireAdmin()'s new verify-token cache (frontend/lib/auth-server.ts) covers this
    // regardless of which page triggers it.
    Promise.all(specs.map(([, url]) => fetchJson<{ total: number }>(`${url}?tour_id=${encodeURIComponent(tourId)}`).then(d => d.total).catch(() => undefined)))
      .then(totals => {
        if (cancelled) return;
        const next: Partial<Record<SectionKey, number>> = {};
        specs.forEach(([key], i) => { next[key] = totals[i]; });
        setCounts(next);
      });
    return () => { cancelled = true; };
  }, [tourId]);

  return counts;
}

export default function TenantActivityPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [selectedTour, setSelectedTour] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionKey>("write_gate");

  const loadSummary = useCallback(() => {
    setSummaryLoading(true);
    fetchJson<Summary>("/api/admin/atoms/summary")
      .then(setSummary)
      .catch(() => {})
      .finally(() => setSummaryLoading(false));
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  const counts = useSectionCounts(selectedTour);
  const selectedTourMeta = summary?.by_tour.find(t => t.tour_id === selectedTour) ?? null;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <style>{`
        @media (max-width: 980px) {
          .a551-inner-sidebar { flex-direction: row !important; overflow-x: auto !important; width: 100% !important; border-right: none !important; border-bottom: 1px solid ${A.line}; position: static !important; }
          .a551-dash-body { flex-direction: column !important; }
        }
      `}</style>
      <AdminSidebar />
      {/* AA-551 sticky fix (AA-550 A.4 root cause): the header is now a normal, non-scrolling
          flex item OUTSIDE the scroll region entirely — no `position: sticky` needed for it to
          stay visible, which was the original page's actual bug (a sticky header with no defined
          scroll-container relationship). Only the section-nav column below still uses `sticky`,
          now correctly scoped to ITS OWN scroll container (the "body" div right below), verified
          by a real Playwright scroll test post-build (see implementation notes), not just CSS. */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100vh" }}>
        <div className="a551-header" style={{
          flexShrink: 0, background: A.bg, padding: "28px 32px 16px", borderBottom: `1px solid ${A.line}`,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 12 }}>
            <div>
              <h1 style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, margin: 0 }}>
                Tenant Activity — Write / Review / Publish
              </h1>
              <div style={{ fontSize: 12, color: A.muted, marginTop: 4 }}>
                Per-Tour, per-tenant monitoring — every row below belongs to a specific tenant&apos;s
                own write/review/publish activity on the selected Tour. Platform-wide Master
                Content data (Atomize/Segment/Score/Route/Slate) moved to{" "}
                <a href="/admin/atom-curation" style={{ color: A.gold }}>Social Content</a>.
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 12, color: A.muted }}>Tour:</span>
              <select
                value={selectedTour ?? ""}
                onChange={e => setSelectedTour(e.target.value || null)}
                style={{ ...selectStyle, minWidth: 240, fontWeight: 600 }}
              >
                <option value="">Select a Tour…</option>
                {(summary?.by_tour ?? []).map(t => (
                  <option key={t.tour_id} value={t.tour_id}>{t.tour_name}</option>
                ))}
              </select>
              {selectedTourMeta && selectedTourMeta.lifecycle_stage !== "active" && (
                <Badge color={LIFECYCLE_COLOR[selectedTourMeta.lifecycle_stage]}>{selectedTourMeta.lifecycle_stage}</Badge>
              )}
            </div>
          </div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px 32px 32px" }}>
          {summaryLoading ? <LoadingScreen msg="Loading tours…" /> : (
            <div className="a551-dash-body" style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
              <div className="a551-inner-sidebar" style={{
                width: 200, flexShrink: 0, display: "flex", flexDirection: "column", gap: 2,
                background: A.card, border: `1px solid ${A.line}`, borderRadius: 10, padding: 6,
                position: "sticky", top: 0,
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
                          fontFamily: "monospace", fontSize: 10.5, background: active ? A.gold : A.line2,
                          color: active ? "#fff" : A.muted, borderRadius: 999, padding: "1px 7px",
                        }}>{count}</span>
                      )}
                    </button>
                  );
                })}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                {!selectedTour ? (
                  <Card>
                    <div style={{ textAlign: "center", padding: "40px 20px" }}>
                      <div style={{ fontSize: 32, marginBottom: 10 }}>🗒️</div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: A.ink, marginBottom: 6 }}>Select a Tour</div>
                      <div style={{ fontSize: 13, color: A.muted }}>
                        Write/Gate, Review, and Publish all show one Tour&apos;s tenant activity —
                        pick a Tour above to view it.
                      </div>
                    </div>
                  </Card>
                ) : (
                  <>
                    {activeSection === "write_gate" && <WriteGateSection tourId={selectedTour} />}
                    {activeSection === "review" && <ReviewSection tourId={selectedTour} />}
                    {activeSection === "publish" && <PublishSection tourId={selectedTour} />}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
