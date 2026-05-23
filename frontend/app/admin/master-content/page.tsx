"use client";
// app/(admin)/master-content/page.tsx — CIS Master Content overview
// GET /acp/s1/tours         → list all raw tours with review status
// GET /acp/s1/tours/{id}/versions → per-tour versions
// PATCH /acp/s1/versions/{id}/activate → activate version

import React, { useState, useEffect } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { CheckCircle, XCircle, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen, StatCard, TH, TD, CHART_TOOLTIP,
} from "../_components/adminUi";
import { BarChart2, Star, Layers, CalendarClock } from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/cis_api_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function apiGet(path: string) {
  return fetch(`${API_URL}${path}`, { headers: authHeaders() }).then(r => r.json());
}

function scoreColor(s: number): string {
  if (s >= 9) return A.green;
  if (s >= 7) return A.amber;
  return A.red;
}

interface RawTour {
  id: string;
  aa_name: string;
  country: string;
  supplier: string;
  updated_at: string | null;
}

interface Version {
  id: string;
  acp_run_id: string;
  run_config: { subtitle_focus?: string };
  content: {
    aa_name?: string;
    aa_subtitle?: string;
    seo_title?: string;
    failure_codes?: string[];
  };
  quality_score: number | null;
  status: string;
  is_active: boolean;
  failure_codes: string[];
  created_at: string;
}

interface TourWithVersions {
  tour: RawTour;
  versions: Version[];
  bestScore: number;
  bestVersion: Version | null;
}

// Score bucket helper
function scoreBucket(s: number): string {
  if (s >= 9) return "9.0–10.0";
  if (s >= 8) return "8.0–9.0";
  if (s >= 7) return "7.0–8.0";
  return "<7.0";
}

// ── Brand audit card ──────────────────────────────────────────────────────────

function BrandAuditCard({ tourData }: { tourData: TourWithVersions }) {
  const best = tourData.bestVersion;
  const flagKey = `brand_audit_${best?.id}`;
  const [flag, setFlag] = useState<"pass" | "revision" | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(flagKey) as "pass" | "revision" | null;
  });

  if (!best) return null;

  function save(f: "pass" | "revision") {
    setFlag(f);
    localStorage.setItem(flagKey, f);
  }

  return (
    <Card style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", gap: 16 }}>
        {/* Generated */}
        <div style={{ flex: 1 }}>
          <SLabel>Generated</SLabel>
          <div style={{ fontFamily: serif, fontSize: 15, fontWeight: 500, color: A.ink, marginBottom: 4 }}>
            {best.content.aa_name || tourData.tour.aa_name}
          </div>
          <div style={{ fontSize: 13, color: A.body, lineHeight: 1.5 }}>
            {best.content.aa_subtitle || "—"}
          </div>
          {best.failure_codes.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
              {best.failure_codes.map((fc, i) => (
                <span key={i} style={{ fontSize: 10, padding: "2px 6px", background: A.redSoft, color: A.red, borderRadius: 4 }}>{fc}</span>
              ))}
            </div>
          )}
        </div>
        {/* Original */}
        <div style={{ flex: 1, padding: "0 0 0 16px", borderLeft: `1px solid ${A.line}` }}>
          <SLabel>Original</SLabel>
          <div style={{ fontFamily: serif, fontSize: 15, fontWeight: 400, color: A.muted, marginBottom: 4 }}>
            {tourData.tour.aa_name}
          </div>
          <div style={{ fontSize: 12, color: A.muted2 }}>{tourData.tour.country} · {tourData.tour.supplier}</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14, paddingTop: 12, borderTop: `1px solid ${A.line2}` }}>
        <Btn size="sm" variant={flag === "pass" ? "secondary" : "ghost"} onClick={() => save("pass")}
          style={flag === "pass" ? { borderColor: A.green, color: A.green } : {}}>
          <CheckCircle size={12} /> Pass
        </Btn>
        <Btn size="sm" variant={flag === "revision" ? "danger" : "ghost"} onClick={() => save("revision")}>
          <XCircle size={12} /> Needs Revision
        </Btn>
        {flag && <span style={{ fontSize: 12, color: A.muted2, alignSelf: "center" }}>Saved locally</span>}
      </div>
    </Card>
  );
}

// ── Tour row ──────────────────────────────────────────────────────────────────

function TourRow({
  td,
  onActivate,
}: {
  td: TourWithVersions;
  onActivate: (versionId: string) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);

  async function handleActivate(versionId: string) {
    setActivating(versionId);
    await onActivate(versionId);
    setActivating(null);
  }

  const sortedVersions = [...td.versions].sort((a, b) => (b.quality_score ?? 0) - (a.quality_score ?? 0));

  return (
    <>
      <tr onClick={() => setExpanded(e => !e)} style={{ cursor: "pointer" }}>
        <td style={{ ...TD, fontWeight: 600, fontFamily: serif }}>
          {td.bestVersion?.content.aa_name || td.tour.aa_name}
        </td>
        <td style={TD}>{td.tour.country || "—"}</td>
        <td style={TD}>{td.tour.supplier || "—"}</td>
        <td style={TD}>
          <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 15, color: scoreColor(td.bestScore) }}>
            {td.bestScore > 0 ? td.bestScore.toFixed(1) : "—"}
          </span>
        </td>
        <td style={TD}><Badge color="blue">{td.versions.length}</Badge></td>
        <td style={TD}>
          {td.bestVersion?.is_active
            ? <Badge color="green">Active</Badge>
            : <Badge color="gray">Draft</Badge>}
        </td>
        <td style={{ ...TD, display: "flex", gap: 8 }}>
          {td.bestVersion && !td.bestVersion.is_active && (
            <Btn size="sm" variant="secondary" disabled={activating === td.bestVersion.id}
              onClick={() => { if (td.bestVersion) handleActivate(td.bestVersion.id); }}>
              {activating === td.bestVersion.id ? "…" : "Activate Best"}
            </Btn>
          )}
          {expanded ? <ChevronUp size={14} style={{ color: A.muted }} /> : <ChevronDown size={14} style={{ color: A.muted }} />}
        </td>
      </tr>

      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: 0, background: A.bg }}>
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${A.line}` }}>
              <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(sortedVersions.length, 3)}, 1fr)`, gap: 12 }}>
                {sortedVersions.slice(0, 3).map((v, i) => (
                  <div key={v.id} style={{ padding: 14, background: A.card, borderRadius: 8, border: `1px solid ${v.is_active ? A.gold : A.line}` }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                      <Badge color="blue">{v.run_config.subtitle_focus || `V${i + 1}`}</Badge>
                      {v.is_active && <Badge color="gold">Active</Badge>}
                    </div>
                    <div style={{ fontFamily: mono, fontWeight: 700, fontSize: 24, color: scoreColor(v.quality_score ?? 0), marginBottom: 6 }}>
                      {(v.quality_score ?? 0).toFixed(1)}
                    </div>
                    <div style={{ fontSize: 13, color: A.body, marginBottom: 4, fontStyle: "italic" }}>
                      {v.content.aa_subtitle || "—"}
                    </div>
                    <div style={{ fontSize: 12, color: A.muted2, marginBottom: 8 }}>
                      {v.content.seo_title || "—"}
                    </div>
                    {v.failure_codes.length > 0 && (
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginBottom: 8 }}>
                        {v.failure_codes.map((fc, j) => <span key={j} style={{ fontSize: 10, padding: "2px 5px", background: A.redSoft, color: A.red, borderRadius: 3 }}>{fc}</span>)}
                      </div>
                    )}
                    <Btn size="sm" disabled={v.is_active || activating === v.id} onClick={() => handleActivate(v.id)}>
                      {v.is_active ? "Active" : activating === v.id ? "…" : "Activate This"}
                    </Btn>
                  </div>
                ))}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MasterContentPage() {
  const [toursData, setToursData] = useState<TourWithVersions[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  async function loadAll() {
    try {
      const { data: tours } = await apiGet("/acp/s1/tours");
      const allTours: TourWithVersions[] = await Promise.all(
        (tours || []).map(async (t: RawTour) => {
          try {
            const { versions } = await apiGet(`/acp/s1/tours/${t.id}/versions`);
            const v = (versions || []) as Version[];
            const best = v.reduce<Version | null>((b, cur) => {
              if (!b || (cur.quality_score ?? 0) > (b.quality_score ?? 0)) return cur;
              return b;
            }, null);
            return { tour: t, versions: v, bestScore: best?.quality_score ?? 0, bestVersion: best };
          } catch {
            return { tour: t, versions: [], bestScore: 0, bestVersion: null };
          }
        })
      );
      setToursData(allTours);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadAll(); // eslint-disable-line react-hooks/set-state-in-effect
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function refresh() {
    setRefreshing(true);
    await loadAll();
  }

  async function activateVersion(versionId: string) {
    await fetch(`${API_URL}/acp/s1/versions/${versionId}/activate`, {
      method: "PATCH",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
    });
    await loadAll();
  }

  if (loading) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}><LoadingScreen msg="Loading master content…" /></main>
      </div>
    );
  }

  const totalVersions = toursData.reduce((s, t) => s + t.versions.length, 0);
  const scoredVersions = toursData.flatMap(t => t.versions).filter(v => v.quality_score !== null);
  const avgScore = scoredVersions.length
    ? scoredVersions.reduce((s, v) => s + (v.quality_score ?? 0), 0) / scoredVersions.length
    : 0;

  // Score distribution by config (use run_config.subtitle_focus as proxy for config type)
  const buckets = ["9.0–10.0", "8.0–9.0", "7.0–8.0", "<7.0"];
  const allVersions = toursData.flatMap(t => t.versions.map(v => ({ ...v, configName: v.run_config.subtitle_focus || "standard" })));
  const configs = [...new Set(allVersions.map(v => v.configName))].slice(0, 3);
  const COLORS = ["#3B82F6", "#8B5CF6", "#DB9628"];

  const chartData = buckets.map(bucket => {
    const row: Record<string, string | number> = { name: bucket };
    configs.forEach(cfg => {
      row[cfg] = allVersions.filter(v => v.configName === cfg && scoreBucket(v.quality_score ?? 0) === bucket).length;
    });
    return row;
  });

  // 3 random tours for brand audit
  const auditSample = toursData.filter(t => t.bestVersion).slice(0, 3);

  const lastUpdated = toursData
    .flatMap(t => t.versions)
    .map(v => v.created_at)
    .sort()
    .reverse()[0];

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
              Master Content
            </div>
            <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
              All tours · all versions · activate best performing content
            </div>
          </div>
          <Btn size="sm" variant="ghost" onClick={refresh}>
            <RefreshCw size={13} style={refreshing ? { animation: "spin 1s linear infinite" } : undefined} />
            {refreshing ? "Refreshing…" : "Refresh"}
          </Btn>
        </div>

        {/* Stats bar */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
          <StatCard label="Total Tours" value={String(toursData.length)} icon={<BarChart2 size={16} />} accent={A.gold} />
          <StatCard label="Total Versions" value={String(totalVersions)} icon={<Layers size={16} />} accent={A.gold} />
          <StatCard label="Avg Score" value={avgScore > 0 ? avgScore.toFixed(1) + "/10" : "—"} icon={<Star size={16} />} accent={scoreColor(avgScore)} />
          <StatCard label="Last Updated" value={lastUpdated ? new Date(lastUpdated).toLocaleDateString() : "—"} icon={<CalendarClock size={16} />} accent={A.gold} />
        </div>

        {/* Tour table */}
        <Card style={{ padding: 0, marginBottom: 28 }}>
          <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${A.line}` }}>
            <SLabel>All Tours</SLabel>
          </div>
          {toursData.length === 0 ? (
            <div style={{ padding: 24, fontSize: 13, color: A.muted2 }}>
              No tours with versions yet. Run S1 Rewrite first.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={TH}>Tour Name</th>
                    <th style={TH}>Country</th>
                    <th style={TH}>Supplier</th>
                    <th style={TH}>Best Score</th>
                    <th style={TH}># Versions</th>
                    <th style={TH}>Status</th>
                    <th style={TH}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {toursData.map(td => (
                    <TourRow key={td.tour.id} td={td} onActivate={activateVersion} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Score distribution chart */}
        {allVersions.length > 0 && (
          <Card style={{ marginBottom: 28 }}>
            <SLabel>Score Distribution by Config</SLabel>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} barCategoryGap="30%" barGap={4}>
                <XAxis dataKey="name" tick={{ fontSize: 12, fill: A.muted }} />
                <YAxis tick={{ fontSize: 11, fill: A.muted }} allowDecimals={false} />
                <Tooltip {...CHART_TOOLTIP} />
                {configs.map((cfg, i) => (
                  <Bar key={cfg} dataKey={cfg} name={cfg} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
                ))}
              </BarChart>
            </ResponsiveContainer>
            <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
              {configs.map((cfg, i) => (
                <div key={cfg} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: A.muted }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: COLORS[i % COLORS.length], display: "inline-block" }} />
                  {cfg}
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Brand Voice Audit */}
        {auditSample.length > 0 && (
          <div>
            <div style={{ marginBottom: 14 }}>
              <SLabel>Brand Voice Audit</SLabel>
              <div style={{ fontSize: 12, color: A.muted2 }}>3 sample tours — compare generated vs original · flag for revision</div>
            </div>
            {auditSample.map(td => <BrandAuditCard key={td.tour.id} tourData={td} />)}
          </div>
        )}
      </main>
    </div>
  );
}
