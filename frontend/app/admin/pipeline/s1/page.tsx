"use client";
// app/(admin)/pipeline/s1/page.tsx — CIS S1 Rewrite stage
// GET  /acp/s1/tours    → available raw tours
// GET  /acp/s1/runs     → list historical runs
// POST /acp/s1/run      → start new run
// GET  /acp/s1/run/{id}/stream → SSE progress
// GET  /acp/s1/tours/{id}/versions → per-tour versions
// PATCH /acp/s1/versions/{id}/activate → activate version

import React, { useState, useEffect, useRef } from "react";
import { Play, RefreshCw, ChevronDown, ChevronUp, CheckCircle, Clock, Zap, ArrowRight } from "lucide-react";
import AdminSidebar from "../../_components/AdminSidebar";
import {
  A, serif, sans, mono,
  Card, SLabel, Badge, Btn, LoadingScreen, TabBar,
} from "../../_components/adminUi";

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

// ── Types ─────────────────────────────────────────────────────────────────────

interface RawTour {
  id: string;
  aa_name: string;
  country: string;
  supplier: string;
  updated_at: string | null;
}

interface Run {
  run_id: string;
  status: string;
  created_at: string;
  total_tours: number;
  done_count: number;
  failed_count: number;
  run_config: { model_id?: string; seo_mode?: string; language?: string };
}

interface Version {
  id: string;
  acp_run_id: string;
  run_config: { subtitle_focus?: string; model_id?: string };
  content: {
    aa_name?: string;
    aa_subtitle?: string;
    aa_summary?: string;
    aa_description?: string;
    aa_highlights?: string[];
    aa_itineraries?: string;
    mobile_card_text?: string;
    seo_title?: string;
    seo_meta?: string;
    seo_keywords_used?: string[];
    score_brand?: number;
    score_seo?: number;
    score_quality?: number;
    score_structure?: number;
    failure_codes?: string[];
    passed_count?: number;
    failed_count?: number;
    model_editorial?: string;
    version_num?: number;
    prompt_version?: string;
    brand_rules_version?: string;
  };
  quality_score: number | null;
  status: string;
  is_active: boolean;
  failure_codes: string[];
  created_at: string;
}

// ── Tour version expand ───────────────────────────────────────────────────────

function TourVersionCard({
  tourId, tourName,
}: { tourId: string; tourName: string }) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState("content");
  const [compare, setCompare] = useState(false);
  const [activating, setActivating] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const d = await apiGet(`/acp/s1/tours/${tourId}/versions`);
      setVersions(d.versions || []);
    } finally {
      setLoading(false);
    }
  }

  async function activate(versionId: string) {
    setActivating(versionId);
    try {
      await fetch(`${API_URL}/acp/s1/versions/${versionId}/activate`, {
        method: "PATCH", headers: { ...authHeaders(), "Content-Type": "application/json" },
      });
      await load();
    } finally {
      setActivating(null);
    }
  }

  function toggle() {
    if (!expanded) load();
    setExpanded(e => !e);
  }

  const bestVersion = versions.reduce<Version | null>((best, v) => {
    if (!best || (v.quality_score ?? 0) > (best.quality_score ?? 0)) return v;
    return best;
  }, null);

  return (
    <Card style={{ marginBottom: 10 }}>
      <div
        onClick={toggle}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ fontFamily: serif, fontSize: 15, fontWeight: 500, color: A.ink }}>{tourName}</div>
          {bestVersion && (
            <span style={{ fontWeight: 700, color: scoreColor(bestVersion.quality_score ?? 0), fontSize: 13, fontFamily: mono }}>
              {(bestVersion.quality_score ?? 0).toFixed(1)}
            </span>
          )}
          {versions.length > 0 && (
            <Badge color="blue">{versions.length} version{versions.length > 1 ? "s" : ""}</Badge>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {versions.length >= 2 && (
            <Btn size="sm" variant="ghost" onClick={() => setCompare(c => !c)}>
              {compare ? "List View" : "Compare Versions"}
            </Btn>
          )}
          {expanded ? <ChevronUp size={15} style={{ color: A.muted }} /> : <ChevronDown size={15} style={{ color: A.muted }} />}
        </div>
      </div>

      {expanded && (
        <div style={{ marginTop: 16 }}>
          {loading && <LoadingScreen msg="Loading versions…" />}

          {!loading && versions.length === 0 && (
            <div style={{ fontSize: 13, color: A.muted2, padding: "12px 0" }}>No versions generated yet.</div>
          )}

          {/* Compare mode: side-by-side V1/V2/V3 */}
          {!loading && compare && versions.length >= 2 && (
            <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(versions.length, 3)}, 1fr)`, gap: 12 }}>
              {versions.slice(0, 3).map((v, i) => (
                <div key={v.id} style={{ padding: 14, background: A.bg, borderRadius: 8, border: `1px solid ${v.is_active ? A.gold : A.line}` }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <Badge color="blue">V{i + 1} — {v.run_config.subtitle_focus || "standard"}</Badge>
                    {v.is_active && <Badge color="gold">Active</Badge>}
                  </div>
                  <div style={{ fontSize: 13, color: A.body, marginBottom: 6, fontStyle: "italic" }}>{v.content.aa_subtitle || "—"}</div>
                  <div style={{ fontWeight: 700, color: scoreColor(v.quality_score ?? 0), fontFamily: mono, fontSize: 20, marginBottom: 8 }}>
                    {(v.quality_score ?? 0).toFixed(1)}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
                    {(v.failure_codes || []).map((fc, j) => (
                      <span key={j} style={{ fontSize: 10, padding: "2px 6px", background: A.redSoft, color: A.red, borderRadius: 4 }}>{fc}</span>
                    ))}
                  </div>
                  <Btn
                    size="sm"
                    variant={v.is_active ? "ghost" : "secondary"}
                    disabled={v.is_active || activating === v.id}
                    onClick={() => activate(v.id)}
                  >
                    {v.is_active ? "Active" : activating === v.id ? "Activating…" : "Activate"}
                  </Btn>
                </div>
              ))}
            </div>
          )}

          {/* List mode: per-version tabs */}
          {!loading && !compare && versions.map((v, i) => (
            <div key={v.id} style={{ marginBottom: 14, padding: 14, background: A.bg, borderRadius: 8, border: `1px solid ${v.is_active ? A.gold : A.line}` }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                <Badge color="blue">V{i + 1}</Badge>
                {v.is_active && <Badge color="gold">Active</Badge>}
                <span style={{ fontFamily: mono, fontWeight: 700, fontSize: 18, color: scoreColor(v.quality_score ?? 0) }}>
                  {(v.quality_score ?? 0).toFixed(1)}
                </span>
                <Badge color={v.status === "published" ? "green" : v.status === "failed" ? "red" : "amber"}>
                  {v.status}
                </Badge>
                <div style={{ marginLeft: "auto" }}>
                  <Btn size="sm" disabled={v.is_active || activating === v.id} onClick={() => activate(v.id)}>
                    {v.is_active ? "Active" : activating === v.id ? "…" : "Activate"}
                  </Btn>
                </div>
              </div>

              <TabBar
                tabs={[
                  { key: "content", label: "Content" },
                  { key: "seo", label: "SEO" },
                  { key: "quality", label: "Quality" },
                  { key: "meta", label: "Meta" },
                ]}
                active={tab}
                onChange={setTab}
              />

              <div style={{ marginTop: 14 }}>
                {tab === "content" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {v.content.aa_name && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Name</span><div style={{ fontFamily: serif, fontSize: 17, fontWeight: 500, color: A.ink, marginTop: 2 }}>{v.content.aa_name}</div></div>}
                    {v.content.aa_subtitle && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Subtitle</span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{v.content.aa_subtitle}</div></div>}
                    {v.content.aa_summary && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Summary</span><div style={{ fontSize: 13, color: A.body, marginTop: 2, lineHeight: 1.6 }}>{v.content.aa_summary}</div></div>}
                    {v.content.aa_highlights && v.content.aa_highlights.length > 0 && (
                      <div>
                        <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Highlights</span>
                        <ul style={{ marginTop: 4, paddingLeft: 18 }}>
                          {v.content.aa_highlights.map((h, j) => <li key={j} style={{ fontSize: 13, color: A.body, marginBottom: 2 }}>{h}</li>)}
                        </ul>
                      </div>
                    )}
                    {v.content.mobile_card_text && (
                      <div>
                        <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>
                          Mobile Card <span style={{ color: (v.content.mobile_card_text.length > 80) ? A.red : A.muted2 }}>({v.content.mobile_card_text.length}/80)</span>
                        </span>
                        <div style={{ fontSize: 12, color: A.body, marginTop: 2 }}>{v.content.mobile_card_text}</div>
                      </div>
                    )}
                  </div>
                )}

                {tab === "seo" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {v.content.seo_title && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>SEO Title <span style={{ color: v.content.seo_title.length > 70 ? A.red : A.muted2 }}>({v.content.seo_title.length}/70)</span></span><div style={{ fontSize: 14, color: A.body, marginTop: 2 }}>{v.content.seo_title}</div></div>}
                    {v.content.seo_meta && <div><span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Meta <span style={{ color: v.content.seo_meta.length > 170 ? A.red : A.muted2 }}>({v.content.seo_meta.length}/170)</span></span><div style={{ fontSize: 13, color: A.body, marginTop: 2 }}>{v.content.seo_meta}</div></div>}
                    {v.content.seo_keywords_used && v.content.seo_keywords_used.length > 0 && (
                      <div>
                        <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>Keywords</span>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                          {v.content.seo_keywords_used.map((k, j) => <span key={j} style={{ fontSize: 11, padding: "3px 8px", background: A.line2, borderRadius: 4, color: A.body }}>{k}</span>)}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {tab === "quality" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
                      <span style={{ fontFamily: serif, fontSize: 40, fontWeight: 600, color: scoreColor(v.quality_score ?? 0), lineHeight: 1 }}>
                        {(v.quality_score ?? 0).toFixed(1)}
                      </span>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 20px" }}>
                        {[
                          ["Brand", v.content.score_brand],
                          ["SEO", v.content.score_seo],
                          ["Quality", v.content.score_quality],
                          ["Structure", v.content.score_structure],
                        ].map(([label, val]) => (
                          <div key={label as string} style={{ fontSize: 12, color: A.muted }}>
                            {label}: <strong style={{ color: val ? scoreColor(val as number) : A.muted2 }}>{val ?? "—"}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                    {v.failure_codes.length > 0 && (
                      <div>
                        <SLabel>Failure Codes</SLabel>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {v.failure_codes.map((fc, j) => (
                            <span key={j} style={{ fontSize: 11, padding: "3px 8px", background: A.redSoft, color: A.red, borderRadius: 4, fontWeight: 600 }}>{fc}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    {v.failure_codes.length === 0 && <div style={{ display: "flex", alignItems: "center", gap: 6, color: A.green }}><CheckCircle size={14} /><span style={{ fontSize: 13 }}>All checks passed</span></div>}
                  </div>
                )}

                {tab === "meta" && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, fontSize: 13 }}>
                    {[
                      ["Model", v.content.model_editorial],
                      ["Version #", v.content.version_num],
                      ["Prompt Ver.", v.content.prompt_version],
                      ["Brand Rules", v.content.brand_rules_version],
                      ["Status", v.status],
                      ["Run ID", v.acp_run_id?.slice(0, 8)],
                    ].map(([label, val]) => (
                      <div key={label as string}>
                        <span style={{ fontSize: 11, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em" }}>{label}</span>
                        <div style={{ color: A.body, marginTop: 2 }}>{String(val ?? "—")}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ── SSE progress log ──────────────────────────────────────────────────────────

function SseLog({ runId, onDone }: { runId: string; onDone: () => void }) {
  const logRef = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!runId) return;
    const token = getToken();
    const url = `${API_URL}/acp/s1/run/${runId}/stream${token ? `?token=${token}` : ""}`;
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        const msg = data.message || JSON.stringify(data);
        setLines(prev => [...prev, msg]);
        if (data.status === "done" || data.status === "failed" || data.event === "done") {
          setDone(true);
          es.close();
          onDone();
        }
      } catch {
        setLines(prev => [...prev, e.data]);
      }
      setTimeout(() => {
        logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
      }, 50);
    };

    es.onerror = () => {
      setLines(prev => [...prev, "[stream ended]"]);
      setDone(true);
      es.close();
      onDone();
    };

    return () => es.close();
  }, [runId, onDone]);

  return (
    <div>
      <div
        ref={logRef}
        style={{
          height: 180, overflowY: "auto", background: A.ink,
          borderRadius: 8, padding: "10px 14px", fontFamily: mono,
          fontSize: 12, color: "#C9CFD8", lineHeight: 1.6,
        }}
      >
        {lines.length === 0 && <span style={{ color: "#6E7681" }}>Waiting for events…</span>}
        {lines.map((l, i) => <div key={i}>{l}</div>)}
        {!done && <span style={{ color: A.amber, animation: "pulse 1s infinite" }}>▋</span>}
      </div>
      {done && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, color: A.green, fontSize: 13 }}>
          <CheckCircle size={13} /> Pipeline run complete
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function S1Page() {
  const [tours, setTours] = useState<RawTour[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedTourIds, setSelectedTourIds] = useState<string[]>([]);
  const [modelId, setModelId] = useState("us.anthropic.claude-haiku-4-5-20251001-v1:0");
  const [seoMode, setSeoMode] = useState("informational");
  const [configName, setConfigName] = useState("V1-Standard");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runDone, setRunDone] = useState(false);
  const [error, setError] = useState("");
  const [selectedRun, setSelectedRun] = useState<string>("");

  async function loadData() {
    setLoading(true);
    try {
      const [toursData, runsData] = await Promise.all([
        apiGet("/acp/s1/tours"),
        apiGet("/acp/s1/runs"),
      ]);
      setTours(toursData.data || []);
      setRuns(runsData.data || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData(); // eslint-disable-line react-hooks/set-state-in-effect
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function toggleTour(id: string) {
    setSelectedTourIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function startRun() {
    if (selectedTourIds.length === 0) return;
    setRunning(true);
    setRunDone(false);
    setError("");
    try {
      const res = await fetch(`${API_URL}/acp/s1/run`, {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          tour_ids: selectedTourIds,
          run_config: { model_id: modelId, seo_mode: seoMode, language: "EN-US" },
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Run failed");
      }
      const data = await res.json();
      setActiveRunId(data.run_id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Run failed");
      setRunning(false);
    }
  }

  function onRunDone() {
    setRunning(false);
    setRunDone(true);
    loadData();
  }

  const viewRun = runs.find(r => r.run_id === (selectedRun || activeRunId));
  const viewTours = tours.filter(t => selectedTourIds.length > 0
    ? selectedTourIds.includes(t.id)
    : true);

  if (loading) {
    return (
      <div style={{ display: "flex", minHeight: "100vh", background: A.bg }}>
        <AdminSidebar />
        <main style={{ flex: 1, padding: "32px 36px" }}><LoadingScreen msg="Loading tours and runs…" /></main>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: A.bg, fontFamily: sans }}>
      <AdminSidebar />
      <main style={{ flex: 1, padding: "32px 36px", overflowY: "auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: A.ink, letterSpacing: "-0.02em" }}>
            S1 Rewrite
          </div>
          <div style={{ fontSize: 13, color: A.muted, marginTop: 4 }}>
            Select tours · configure model · run pipeline · review generated versions
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
          {/* Tour selector */}
          <Card>
            <SLabel>Available Tours ({tours.length})</SLabel>
            {tours.length === 0 ? (
              <div style={{ fontSize: 13, color: A.muted2 }}>
                No approved tours. Upload via <strong>Upload (S0)</strong> first.
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 260, overflowY: "auto" }}>
                {tours.map(t => (
                  <label key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", background: selectedTourIds.includes(t.id) ? A.goldTint : A.bg, borderRadius: 6, cursor: "pointer", border: `1px solid ${selectedTourIds.includes(t.id) ? A.gold : A.line}` }}>
                    <input type="checkbox" checked={selectedTourIds.includes(t.id)} onChange={() => toggleTour(t.id)} style={{ accentColor: A.gold }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: A.ink }}>{t.aa_name}</div>
                      <div style={{ fontSize: 11, color: A.muted2 }}>{t.country} · {t.supplier}</div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </Card>

          {/* Config + run */}
          <Card>
            <SLabel>Run Config</SLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 16 }}>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Model</label>
                <select value={modelId} onChange={e => setModelId(e.target.value)} style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}>
                  <option value="us.anthropic.claude-haiku-4-5-20251001-v1:0">Bedrock · Haiku 4.5 (fast, ~$0.002/tour)</option>
                  <option value="us.anthropic.claude-sonnet-4-5-20251001-v1:0">Bedrock · Sonnet 4.5 (quality, ~$0.02/tour)</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>SEO Mode</label>
                <select value={seoMode} onChange={e => setSeoMode(e.target.value)} style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }}>
                  <option value="dataforseo">DataForSEO (live)</option>
                  <option value="informational">Informational (mock)</option>
                  <option value="disabled">Disabled</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: A.muted, display: "block", marginBottom: 4 }}>Config Name</label>
                <input value={configName} onChange={e => setConfigName(e.target.value)} style={{ width: "100%", padding: "7px 10px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff" }} />
              </div>
            </div>
            <Btn
              variant="primary"
              size="lg"
              disabled={selectedTourIds.length === 0 || running}
              onClick={startRun}
              style={{ background: running ? A.muted : A.gold, border: `1px solid ${A.gold}`, width: "100%", justifyContent: "center" }}
            >
              <Play size={14} />
              {running ? "Running…" : `Run S1 Rewrite (${selectedTourIds.length} tour${selectedTourIds.length !== 1 ? "s" : ""})`}
            </Btn>
            {error && <div style={{ marginTop: 10, color: A.red, fontSize: 13 }}>{error}</div>}
          </Card>
        </div>

        {/* SSE log */}
        {activeRunId && (
          <Card style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
              <SLabel>Pipeline Progress</SLabel>
              {running && <Zap size={13} style={{ color: A.amber }} />}
              <span style={{ fontSize: 11, color: A.muted2, fontFamily: mono }}>run: {activeRunId.slice(0, 8)}</span>
            </div>
            <SseLog runId={activeRunId} onDone={onRunDone} />
          </Card>
        )}

        {/* Historical run selector */}
        {runs.length > 0 && (
          <Card style={{ marginBottom: 24 }}>
            <SLabel>Historical Runs</SLabel>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <select
                value={selectedRun}
                onChange={e => setSelectedRun(e.target.value)}
                style={{ padding: "7px 12px", borderRadius: 6, border: `1px solid ${A.line}`, fontSize: 13, fontFamily: sans, background: "#fff", minWidth: 280 }}
              >
                <option value="">— Select a run to inspect —</option>
                {runs.map(r => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id.slice(0, 8)} · {r.total_tours}t · {r.done_count}/{r.total_tours} done · {new Date(r.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
              <Btn size="sm" variant="ghost" onClick={loadData}><RefreshCw size={13} /></Btn>
            </div>
            {viewRun && (
              <div style={{ display: "flex", gap: 20, fontSize: 13, color: A.body, flexWrap: "wrap" }}>
                <span><Clock size={12} style={{ display: "inline", marginRight: 4 }} />{new Date(viewRun.created_at).toLocaleString()}</span>
                <Badge color={viewRun.status === "running" ? "amber" : viewRun.status === "completed" ? "green" : "gray"}>{viewRun.status}</Badge>
                <span>{viewRun.done_count}/{viewRun.total_tours} done</span>
                {viewRun.failed_count > 0 && <span style={{ color: A.red }}>{viewRun.failed_count} failed</span>}
              </div>
            )}
          </Card>
        )}

        {/* Tour version output */}
        {(runDone || selectedRun) && tours.length > 0 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
              <SLabel>Generated Versions</SLabel>
              <Btn size="sm" variant="primary" onClick={() => window.location.href = "/master-content"}
                style={{ background: A.gold, border: `1px solid ${A.gold}`, display: "flex", alignItems: "center", gap: 6 }}>
                Master Content <ArrowRight size={12} />
              </Btn>
            </div>
            {(selectedTourIds.length > 0 ? viewTours : tours).map(t => (
              <TourVersionCard key={t.id} tourId={t.id} tourName={t.aa_name} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
