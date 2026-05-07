"use client";
// app/(admin)/tenants/page.tsx
// All API logic preserved — /api/admin/tenants, generate-key, usage
// Design: Fraunces + IBM Plex Sans, light theme, red accent

import { useState, useEffect, useCallback } from "react";
import { Users, Plus, Key, RefreshCw, ChevronDown, ChevronUp, AlertCircle, Loader2, CheckCircle, Eye, EyeOff, Copy, X } from "lucide-react";
import AdminSidebar from "../_components/AdminSidebar";
import {
  A, serif, mono, sans,
  Card, SLabel, Btn, Badge, LoadingScreen, TH, TD,
} from "../_components/adminUi";

// ─── Types ────────────────────────────────────────────────────────────────────
interface Tenant {
  tenant_id: string; name: string; slug: string; plan_tier: string;
  rate_limit_rpm: number; is_active: boolean; created_at: string;
  plan: { tours_quota_monthly: number; api_calls_quota_monthly: number; price_usd_monthly: number };
  this_month: { tours_rewritten: number; api_calls_used: number; quota_tours_pct: number; quota_calls_pct: number; tours_overage: number; overage_usd: number; llm_cost_usd: number };
}
interface NewApiKey { tenant_id: string; tenant_name: string; api_key: string; }

const PLAN_OPTIONS = ["starter", "growth", "business"];
const PLAN_BADGE: Record<string, "blue"|"purple"|"green"|"red"> = {
  starter: "blue", growth: "purple", business: "green", internal: "red",
};

// ─── Create Tenant Modal ──────────────────────────────────────────────────────
function CreateModal({ onClose, onCreated }: { onClose: () => void; onCreated: (k: NewApiKey) => void }) {
  const [name, setName]   = useState("");
  const [slug, setSlug]   = useState("");
  const [plan, setPlan]   = useState("starter");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const autoSlug = (n: string) => n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  async function submit() {
    if (!name.trim() || !slug.trim()) { setError("Name and slug are required"); return; }
    setLoading(true); setError("");
    try {
      const res = await fetch("/api/admin/tenants", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), slug: slug.trim(), plan_tier: plan }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? "Failed to create tenant"); return; }
      onCreated({ tenant_id: data.tenant_id, tenant_name: data.name, api_key: data.api_key });
    } catch { setError("Connection error"); } finally { setLoading(false); }
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100 }}>
      <div style={{ background: A.card, border: `1px solid ${A.line}`, borderRadius: 16, padding: 32, width: 440 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: A.ink, letterSpacing: "-0.01em" }}>New Tenant</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: A.muted }}><X size={16} /></button>
        </div>
        {[
          { label: "Company Name", value: name, onChange: (v: string) => { setName(v); setSlug(autoSlug(v)); }, placeholder: "WanderLux Travel" },
          { label: "Slug",         value: slug, onChange: setSlug, placeholder: "wanderlux-travel" },
        ].map(f => (
          <div key={f.label} style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em", display: "block", marginBottom: 6 }}>{f.label}</label>
            <input value={f.value} onChange={e => f.onChange(e.target.value)} placeholder={f.placeholder}
              style={{ width: "100%", padding: "10px 12px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, color: A.body, fontSize: 13, outline: "none", boxSizing: "border-box", fontFamily: sans }} />
          </div>
        ))}
        <div style={{ marginBottom: 24 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em", display: "block", marginBottom: 8 }}>Plan</label>
          <div style={{ display: "flex", gap: 8 }}>
            {PLAN_OPTIONS.map(p => (
              <button key={p} onClick={() => setPlan(p)} style={{
                flex: 1, padding: "9px 0", borderRadius: 8, cursor: "pointer", fontFamily: sans,
                border: `1px solid ${plan === p ? A.red : A.line}`,
                background: plan === p ? A.redTint : A.bg,
                color: plan === p ? A.red : A.muted,
                fontSize: 13, fontWeight: plan === p ? 700 : 400,
              }}>{p}</button>
            ))}
          </div>
        </div>
        {error && (
          <div style={{ marginBottom: 14, padding: "9px 12px", background: A.redSoft, border: `1px solid ${A.redBorder}`, borderRadius: 8, fontSize: 12, color: A.red }}>
            {error}
          </div>
        )}
        <div style={{ display: "flex", gap: 10 }}>
          <Btn variant="secondary" onClick={onClose} style={{ flex: 1 }}>Cancel</Btn>
          <Btn variant="primary" disabled={loading} onClick={submit} style={{ flex: 2 }}>
            {loading ? <><Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> Creating…</> : "Create Tenant"}
          </Btn>
        </div>
      </div>
    </div>
  );
}

// ─── API Key Modal ────────────────────────────────────────────────────────────
function ApiKeyModal({ keyData, onClose }: { keyData: NewApiKey; onClose: () => void }) {
  const [show, setShow]   = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = () => { navigator.clipboard.writeText(keyData.api_key); setCopied(true); setTimeout(() => setCopied(false), 2000); };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200 }}>
      <div style={{ background: A.card, border: `1px solid #86EFAC`, borderRadius: 16, padding: 32, width: 460 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <CheckCircle size={20} color="#22C55E" />
          <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: "#22C55E" }}>Tenant Created</div>
        </div>
        <p style={{ fontSize: 13, color: A.muted, marginBottom: 24 }}>
          <strong style={{ color: A.ink }}>{keyData.tenant_name}</strong> — share this API key once. It will <strong style={{ color: A.red }}>never be shown again</strong>.
        </p>
        <div style={{ marginBottom: 20 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: A.muted, textTransform: "uppercase", letterSpacing: "0.1em", display: "block", marginBottom: 8 }}>API Key</label>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{
              flex: 1, fontFamily: mono, fontSize: 12, padding: "10px 14px",
              background: A.bg, border: "1px solid #86EFAC", borderRadius: 8,
              color: show ? "#22C55E" : A.muted, letterSpacing: show ? 0.3 : 3, wordBreak: "break-all",
            }}>
              {show ? keyData.api_key : "•".repeat(32)}
            </div>
            <button onClick={() => setShow(!show)} style={{ padding: "0 12px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 8, cursor: "pointer", color: A.muted }}>
              {show ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={copy} style={{ flex: 1, padding: "10px 0", background: copied ? "#D1FAE5" : "#F0FDF4", border: "1px solid #86EFAC", borderRadius: 8, color: "#22C55E", fontSize: 13, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
            <Copy size={13} />{copied ? "Copied!" : "Copy Key"}
          </button>
          <Btn variant="secondary" onClick={onClose} style={{ flex: 1 }}>Done</Btn>
        </div>
      </div>
    </div>
  );
}

// ─── Usage Detail ─────────────────────────────────────────────────────────────
function UsageDetail({ tenantId }: { tenantId: string }) {
  const [usage, setUsage]   = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch(`/api/admin/tenants/${tenantId}/usage?months=3`)
      .then(r => r.json()).then(setUsage).catch(() => setUsage(null)).finally(() => setLoading(false));
  }, [tenantId]);
  if (loading) return <div style={{ padding: "10px 0", fontSize: 12, color: A.muted }}>Loading…</div>;
  if (!usage)  return <div style={{ padding: "10px 0", fontSize: 12, color: A.red }}>Failed to load</div>;
  return (
    <div style={{ background: A.bg, borderRadius: 10, padding: 16, border: `1px solid ${A.line}`, marginTop: 4 }}>
      <div style={{ display: "flex", gap: 24, marginBottom: 14 }}>
        {[
          ["Tours Published", usage.tours_published, A.gold],
          ["Rate Limit", `${usage.limits?.rate_limit_rpm}/min`, A.body],
          ["Tours/Month", usage.limits?.tours_per_month === 999999 ? "∞" : usage.limits?.tours_per_month?.toLocaleString(), A.body],
        ].map(([l, v, c]) => (
          <div key={l as string}>
            <div style={{ fontSize: 10.5, color: A.muted, marginBottom: 2 }}>{l}</div>
            <div style={{ fontFamily: serif, fontSize: 20, fontWeight: 500, color: c as string }}>{v}</div>
          </div>
        ))}
      </div>
      {usage.monthly_usage?.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead><tr>{["Month","Total Calls","Successful","Rate Limited","Avg Latency"].map((h,i) => (
            <th key={h} style={{ ...TH, fontSize: 10, textAlign: i === 0 ? "left" : "right" }}>{h}</th>
          ))}</tr></thead>
          <tbody>{usage.monthly_usage.map((m: any) => (
            <tr key={m.month}>
              <td style={TD}>{m.month}</td>
              <td style={{ ...TD, textAlign: "right" }}>{m.total_calls.toLocaleString()}</td>
              <td style={{ ...TD, textAlign: "right", color: "#22C55E" }}>{m.successful_calls.toLocaleString()}</td>
              <td style={{ ...TD, textAlign: "right", color: m.rate_limited_calls > 0 ? A.amber : A.muted }}>{m.rate_limited_calls}</td>
              <td style={{ ...TD, textAlign: "right", color: A.muted }}>{Math.round(m.avg_response_ms)}ms</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

// ─── Tenant Row ───────────────────────────────────────────────────────────────
function TenantRow({ tenant, onRotateKey }: { tenant: Tenant; onRotateKey: (t: Tenant) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [isActive, setIsActive] = useState(tenant.is_active);

  async function toggle() {
    setToggling(true);
    try {
      await fetch(`/api/admin/tenants/${tenant.tenant_id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !isActive }),
      });
      setIsActive(!isActive);
    } finally { setToggling(false); }
  }

  return (
    <>
      <tr style={{ borderBottom: `1px solid ${A.line2}` }}>
        <td style={TD}>
          <div style={{ fontWeight: 600, color: A.ink, fontSize: 13 }}>{tenant.name}</div>
          <div style={{ fontSize: 10.5, color: A.muted, fontFamily: mono, marginTop: 2 }}>{tenant.slug}</div>
        </td>
        <td style={TD}>
          <Badge color={PLAN_BADGE[tenant.plan_tier] ?? "gray"}>{tenant.plan_tier}</Badge>
        </td>
        <td style={{ ...TD, textAlign: "right", fontFamily: mono, fontSize: 12 }}>{tenant.rate_limit_rpm}/min</td>
        <td style={{ ...TD, textAlign: "right" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: A.ink }}>{tenant.this_month.tours_rewritten} tours</div>
          <div style={{ fontSize: 11, color: "#22C55E" }}>{tenant.this_month.api_calls_used.toLocaleString()} calls</div>
        </td>
        <td style={{ ...TD, textAlign: "right", fontSize: 12, color: A.muted }}>
          {tenant.this_month.quota_tours_pct}% quota used
        </td>
        <td style={TD}>
          <button onClick={toggle} disabled={toggling} style={{
            padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontSize: 11, fontWeight: 700,
            background: isActive ? "#D1FAE5" : A.redSoft,
            color: isActive ? "#22C55E" : A.red,
          }}>
            {toggling ? "…" : isActive ? "Active" : "Inactive"}
          </button>
        </td>
        <td style={TD}>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button onClick={() => onRotateKey(tenant)} style={{ padding: "5px 10px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, cursor: "pointer", color: A.muted, display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
              <Key size={12} /> Key
            </button>
            <button onClick={() => setExpanded(!expanded)} style={{ padding: "5px 10px", background: A.bg, border: `1px solid ${A.line}`, borderRadius: 6, cursor: "pointer", color: A.muted, display: "flex", alignItems: "center" }}>
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: "0 16px 14px", background: A.bg }}>
            <UsageDetail tenantId={tenant.tenant_id} />
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function TenantsPage() {
  const [tenants, setTenants]     = useState<Tenant[]>([]);
  const [loading, setLoading]     = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey]       = useState<NewApiKey | null>(null);
  const [error, setError]         = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await fetch("/api/admin/tenants");
      if (!res.ok) { setError("Failed to load tenants"); return; }
      const data = await res.json();
      setTenants(data.tenants ?? []);
    } catch { setError("Connection error"); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function rotateKey(tenant: Tenant) {
    if (!confirm(`Rotate API key for ${tenant.name}? Old key stops working immediately.`)) return;
    try {
      const res = await fetch(`/api/admin/tenants/${tenant.tenant_id}/generate-key`, { method: "POST" });
      const data = await res.json();
      if (res.ok) setNewKey({ tenant_id: tenant.tenant_id, tenant_name: tenant.name, api_key: data.api_key });
    } catch { /* silent */ }
  }

  const totalActive = tenants.filter(t => t.is_active).length;
  const totalCalls  = tenants.reduce((s, t) => s + t.this_month.api_calls_used, 0);

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: sans, background: A.bg }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{ height: 56, background: "#fff", borderBottom: `1px solid ${A.line}`, display: "flex", alignItems: "center", padding: "0 32px", gap: 8, position: "sticky", top: 0, zIndex: 10 }}>
          <span style={{ fontSize: 12, color: A.muted2 }}>Admin /</span>
          <span style={{ fontSize: 12, fontWeight: 500, color: A.body }}>Tenants</span>
        </header>
        <main style={{ flex: 1, overflowY: "auto", padding: "28px 36px 56px" }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24 }}>
            <div>
              <h1 style={{ fontFamily: serif, fontSize: 24, fontWeight: 500, color: A.ink, margin: "0 0 6px", letterSpacing: "-0.01em" }}>
                Tenants
              </h1>
              <p style={{ fontSize: 13, color: A.muted, margin: 0 }}>
                {totalActive} active · {totalCalls.toLocaleString()} API calls this month
              </p>
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <Btn variant="secondary" onClick={load}>
                <RefreshCw size={13} /> Refresh
              </Btn>
              <Btn variant="primary" onClick={() => setShowCreate(true)}>
                <Plus size={14} /> New Tenant
              </Btn>
            </div>
          </div>

          {error && (
            <div style={{ marginBottom: 16, padding: "10px 14px", background: A.redSoft, border: `1px solid ${A.redBorder}`, borderRadius: 8, fontSize: 13, color: A.red, display: "flex", alignItems: "center", gap: 8 }}>
              <AlertCircle size={14} /> {error}
            </div>
          )}

          {/* Summary cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 14, marginBottom: 20 }}>
            {[
              { label: "Total Tenants",    value: String(tenants.length),     color: A.red },
              { label: "Active",           value: String(totalActive),         color: "#22C55E" },
              { label: "API Calls (Mo)",   value: totalCalls.toLocaleString(), color: A.gold },
            ].map(c => (
              <Card key={c.label}>
                <SLabel>{c.label}</SLabel>
                <div style={{ fontFamily: serif, fontSize: 26, fontWeight: 500, color: c.color, letterSpacing: "-0.02em" }}>{c.value}</div>
              </Card>
            ))}
          </div>

          {/* Table */}
          <Card style={{ padding: 0, overflow: "hidden" }}>
            {loading ? <LoadingScreen msg="Loading tenants…" /> : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Tenant","Plan","Rate Limit","This Month","Quota","Status",""].map((h,i) => (
                      <th key={i} style={{ ...TH, textAlign: i >= 2 && i <= 4 ? "right" : "left" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {tenants.length === 0 ? (
                    <tr><td colSpan={7} style={{ padding: 48, textAlign: "center", color: A.muted, fontSize: 13 }}>No tenants yet</td></tr>
                  ) : tenants.map(t => (
                    <TenantRow key={t.tenant_id} tenant={t} onRotateKey={rotateKey} />
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </main>
      </div>

      {showCreate && <CreateModal onClose={() => setShowCreate(false)} onCreated={k => { setShowCreate(false); setNewKey(k); load(); }} />}
      {newKey && <ApiKeyModal keyData={newKey} onClose={() => setNewKey(null)} />}
    </div>
  );
}
