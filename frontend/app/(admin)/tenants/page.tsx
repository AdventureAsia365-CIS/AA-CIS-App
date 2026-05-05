"use client";
import { useState, useEffect, useCallback } from "react";
import {
  Users, Plus, Key, RefreshCw, CheckCircle, XCircle,
  Copy, Eye, EyeOff, Loader2,
  ChevronDown, ChevronUp, AlertCircle,
} from "lucide-react";








// ── Types ─────────────────────────────────────────────────────────────────────
interface Tenant {
  tenant_id: string;
  name: string;
  slug: string;
  plan_tier: string;
  rate_limit_rpm: number;
  is_active: boolean;
  created_at: string;
  plan: {
    tours_quota_monthly: number;
    api_calls_quota_monthly: number;
    price_usd_monthly: number;
  };
  this_month: {
    tours_rewritten: number;
    api_calls_used: number;
    quota_tours_pct: number;
    quota_calls_pct: number;
    tours_overage: number;
    overage_usd: number;
    llm_cost_usd: number;
  };
}

interface NewApiKey {
  tenant_id: string;
  tenant_name: string;
  api_key: string;
}

const PLAN_COLORS: Record<string, string> = {
  starter:  "#60a5fa",
  growth:   "#a78bfa",
  business: "#34d399",
  internal: "#f87171",
};

const PLAN_OPTIONS = ["starter", "growth", "business"];

// ── Create Tenant Modal ───────────────────────────────────────────────────────
function CreateTenantModal({ onClose, onCreated }: {
  onClose: () => void;
  onCreated: (key: NewApiKey) => void;
}) {
  const [name, setName]       = useState("");
  const [slug, setSlug]       = useState("");
  const [plan, setPlan]       = useState("starter");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  const autoSlug = (n: string) =>
    n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  const handleNameChange = (v: string) => {
    setName(v);
    setSlug(autoSlug(v));
  };

  const submit = async () => {
    if (!name.trim() || !slug.trim()) { setError("Name and slug are required"); return; }
    setLoading(true); setError("");
    try {
      const res = await fetch(`/api/admin/tenants`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          
        },
        body: JSON.stringify({ name: name.trim(), slug: slug.trim(), plan_tier: plan }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail ?? "Failed to create tenant"); return; }
      onCreated({ tenant_id: data.tenant_id, tenant_name: data.name, api_key: data.api_key });
    } catch { setError("Connection error"); }
    finally { setLoading(false); }
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div style={{
        background: "var(--bg-card)", border: "1px solid var(--border)",
        borderRadius: 16, padding: 32, width: 420,
      }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)", marginBottom: 24 }}>
          Create New Tenant
        </div>

        {[
          { label: "Company Name", value: name, onChange: handleNameChange, placeholder: "e.g. WanderLux Travel" },
          { label: "Slug", value: slug, onChange: setSlug, placeholder: "e.g. wanderlux-travel" },
        ].map(f => (
          <div key={f.label} style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase" as const, letterSpacing: 1, display: "block", marginBottom: 6 }}>{f.label}</label>
            <input value={f.value} onChange={e => f.onChange(e.target.value)} placeholder={f.placeholder}
              style={{ width: "100%", padding: "10px 12px", background: "var(--bg-primary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-primary)", fontSize: 13, outline: "none", boxSizing: "border-box" as const }} />
          </div>
        ))}

        <div style={{ marginBottom: 24 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase" as const, letterSpacing: 1, display: "block", marginBottom: 6 }}>Plan</label>
          <div style={{ display: "flex", gap: 8 }}>
            {PLAN_OPTIONS.map(p => (
              <button key={p} onClick={() => setPlan(p)} style={{
                flex: 1, padding: "10px 0", borderRadius: 8, cursor: "pointer", border: "none",
                background: plan === p ? `${PLAN_COLORS[p]}20` : "var(--bg-primary)",
                color: plan === p ? PLAN_COLORS[p] : "var(--text-muted)",
                fontSize: 13, fontWeight: plan === p ? 700 : 400,
                outline: plan === p ? `1px solid ${PLAN_COLORS[p]}60` : "1px solid var(--border)",
              }}>{p}</button>
            ))}
          </div>
        </div>

        {error && (
          <div style={{ marginBottom: 16, padding: "10px 12px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 8, fontSize: 12, color: "#ef4444" }}>
            {error}
          </div>
        )}

        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onClose} style={{ flex: 1, padding: "10px 0", background: "var(--bg-primary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-secondary)", fontSize: 13, cursor: "pointer" }}>Cancel</button>
          <button onClick={submit} disabled={loading} style={{
            flex: 2, padding: "10px 0", background: loading ? "var(--border)" : "#ef4444",
            border: "none", borderRadius: 8, color: "white", fontSize: 13, fontWeight: 700, cursor: loading ? "not-allowed" : "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            {loading ? <><Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />Creating...</> : "Create Tenant"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── API Key Modal ─────────────────────────────────────────────────────────────
function ApiKeyModal({ keyData, onClose }: { keyData: NewApiKey; onClose: () => void }) {
  const [showKey, setShowKey] = useState(false);
  const [copied, setCopied]   = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(keyData.api_key);
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200 }}>
      <div style={{ background: "var(--bg-card)", border: "1px solid rgba(34,197,94,0.3)", borderRadius: 16, padding: 32, width: 460 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <CheckCircle size={20} color="#22c55e" />
          <div style={{ fontSize: 16, fontWeight: 700, color: "#22c55e" }}>Tenant Created</div>
        </div>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 24 }}>
          <strong style={{ color: "var(--text-primary)" }}>{keyData.tenant_name}</strong> — share this API key with the tenant. It will <strong style={{ color: "#ef4444" }}>never be shown again</strong>.
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase" as const, letterSpacing: 1, display: "block", marginBottom: 8 }}>API Key</label>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{
              flex: 1, fontFamily: "monospace", fontSize: 12,
              padding: "10px 14px", background: "var(--bg-primary)",
              border: "1px solid rgba(34,197,94,0.3)", borderRadius: 8,
              color: showKey ? "#22c55e" : "var(--text-muted)",
              letterSpacing: showKey ? 0.3 : 3, wordBreak: "break-all" as const,
            }}>
              {showKey ? keyData.api_key : "•".repeat(32)}
            </div>
            <button onClick={() => setShowKey(!showKey)} style={{ padding: "0 12px", background: "var(--bg-primary)", border: "1px solid var(--border)", borderRadius: 8, cursor: "pointer", color: "var(--text-secondary)" }}>
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={copy} style={{
            flex: 1, padding: "10px 0", background: copied ? "rgba(34,197,94,0.1)" : "rgba(34,197,94,0.08)",
            border: `1px solid ${copied ? "rgba(34,197,94,0.4)" : "rgba(34,197,94,0.2)"}`,
            borderRadius: 8, color: "#22c55e", fontSize: 13, fontWeight: 600, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
          }}>
            <Copy size={13} />{copied ? "Copied!" : "Copy Key"}
          </button>
          <button onClick={onClose} style={{ flex: 1, padding: "10px 0", background: "var(--bg-primary)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--text-secondary)", fontSize: 13, cursor: "pointer" }}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tenant Row ────────────────────────────────────────────────────────────────
function TenantRow({ tenant, onRotateKey }: {
  tenant: Tenant;
  onRotateKey: (t: Tenant) => void;
}) {
  const [expanded, setExpanded]     = useState(false);
  const [toggling, setToggling]     = useState(false);
  const [isActive, setIsActive]     = useState(tenant.is_active);

  const toggleActive = async () => {
    setToggling(true);
    try {
      await fetch(`/api/admin/tenants/${tenant.tenant_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json",  },
        body: JSON.stringify({ is_active: !isActive }),
      });
      setIsActive(!isActive);
    } catch { /* silent */ }
    finally { setToggling(false); }
  };

  const planColor = PLAN_COLORS[tenant.plan_tier] ?? "#8B9BB4";

  return (
    <>
      <tr style={{ borderBottom: "1px solid var(--border)", background: expanded ? "rgba(219,150,40,0.03)" : "transparent" }}>
        {/* Name + slug */}
        <td style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{tenant.name}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", fontFamily: "monospace", marginTop: 2 }}>{tenant.slug}</div>
        </td>
        {/* Plan */}
        <td style={{ padding: "14px 16px" }}>
          <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 20, background: `${planColor}18`, color: planColor, border: `1px solid ${planColor}33`, textTransform: "capitalize" as const }}>
            {tenant.plan_tier}
          </span>
        </td>
        {/* RPM */}
        <td style={{ padding: "14px 16px", fontSize: 13, color: "var(--text-secondary)", textAlign: "right" as const }}>
          {tenant.rate_limit_rpm}/min
        </td>
        {/* This month calls */}
        <td style={{ padding: "14px 16px", textAlign: "right" as const }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>{tenant.this_month.tours_rewritten} tours</div>
          <div style={{ fontSize: 11, color: "#22c55e" }}>{tenant.this_month.api_calls_used.toLocaleString()} API calls</div>
        </td>
        {/* Avg latency */}
        <td style={{ padding: "14px 16px", fontSize: 12, color: "var(--text-muted)", textAlign: "right" as const }}>
          {tenant.plan ? `${tenant.this_month.quota_tours_pct}% quota used` : "—"}
        </td>
        {/* Status */}
        <td style={{ padding: "14px 16px" }}>
          <button onClick={toggleActive} disabled={toggling} style={{
            padding: "4px 12px", borderRadius: 20, border: "none", cursor: "pointer", fontSize: 11, fontWeight: 700,
            background: isActive ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
            color: isActive ? "#22c55e" : "#ef4444",
          }}>
            {toggling ? "..." : isActive ? "Active" : "Inactive"}
          </button>
        </td>
        {/* Actions */}
        <td style={{ padding: "14px 16px" }}>
          <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
            <button onClick={() => onRotateKey(tenant)} title="Rotate API Key" style={{
              padding: "6px 10px", background: "var(--bg-primary)", border: "1px solid var(--border)",
              borderRadius: 6, cursor: "pointer", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: 4, fontSize: 12,
            }}>
              <Key size={12} /> Key
            </button>
            <button onClick={() => setExpanded(!expanded)} title="Usage details" style={{
              padding: "6px 10px", background: "var(--bg-primary)", border: "1px solid var(--border)",
              borderRadius: 6, cursor: "pointer", color: "var(--text-secondary)", display: "flex", alignItems: "center",
            }}>
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr style={{ borderBottom: "1px solid var(--border)" }}>
          <td colSpan={7} style={{ padding: "0 16px 16px" }}>
            <UsageDetail tenantId={tenant.tenant_id} tenantName={tenant.name} />
          </td>
        </tr>
      )}
    </>
  );
}

// ── Usage Detail ──────────────────────────────────────────────────────────────
function UsageDetail({ tenantId, tenantName }: { tenantId: string; tenantName: string }) {
  const [usage, setUsage]   = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/admin/tenants/${tenantId}/usage?months=3`, {
      headers: {  },
    })
      .then(r => r.json())
      .then(setUsage)
      .catch(() => setUsage(null))
      .finally(() => setLoading(false));
  }, [tenantId]);

  if (loading) return <div style={{ padding: "12px 0", fontSize: 12, color: "var(--text-muted)" }}>Loading usage…</div>;
  if (!usage)  return <div style={{ padding: "12px 0", fontSize: 12, color: "#ef4444" }}>Failed to load usage</div>;

  return (
    <div style={{ background: "var(--bg-primary)", borderRadius: 10, padding: 16, border: "1px solid var(--border)" }}>
      <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 2 }}>Tours Published</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--brand-gold)" }}>{usage.tours_published}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 2 }}>Rate Limit</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text-primary)" }}>{usage.limits?.rate_limit_rpm}/min</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginBottom: 2 }}>Tours/Month Limit</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--text-primary)" }}>
            {usage.limits?.tours_per_month === 999999 ? "∞" : usage.limits?.tours_per_month?.toLocaleString()}
          </div>
        </div>
      </div>
      {usage.monthly_usage?.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["Month", "Total Calls", "Successful", "Rate Limited", "Avg Latency"].map((h, i) => (
                <th key={h} style={{ padding: "4px 8px", color: "var(--text-muted)", fontWeight: 600, textAlign: i === 0 ? "left" : "right" as const, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {usage.monthly_usage.map((m: any) => (
              <tr key={m.month} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", color: "var(--text-primary)" }}>{m.month}</td>
                <td style={{ padding: "6px 8px", textAlign: "right" as const, color: "var(--text-secondary)" }}>{m.total_calls.toLocaleString()}</td>
                <td style={{ padding: "6px 8px", textAlign: "right" as const, color: "#22c55e" }}>{m.successful_calls.toLocaleString()}</td>
                <td style={{ padding: "6px 8px", textAlign: "right" as const, color: m.rate_limited_calls > 0 ? "#f59e0b" : "var(--text-muted)" }}>{m.rate_limited_calls}</td>
                <td style={{ padding: "6px 8px", textAlign: "right" as const, color: "var(--text-muted)" }}>{Math.round(m.avg_response_ms)}ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function TenantsPage() {
  const [tenants, setTenants]       = useState<Tenant[]>([]);
  const [loading, setLoading]       = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey]         = useState<NewApiKey | null>(null);
  const [error, setError]           = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await fetch(`/api/admin/tenants`, {
        headers: {  },
      });
      if (!res.ok) { setError("Failed to load tenants — check admin secret"); return; }
      const data = await res.json();
      setTenants(data.tenants ?? []);
    } catch { setError("Connection error"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreated = (key: NewApiKey) => {
    setShowCreate(false);
    setNewKey(key);
    load();
  };

  const handleRotateKey = async (tenant: Tenant) => {
    if (!confirm(`Rotate API key for ${tenant.name}? The old key will stop working immediately.`)) return;
    try {
      const res = await fetch(`/api/admin/tenants/${tenant.tenant_id}/generate-key`, {
        method: "POST",
        headers: {  },
      });
      const data = await res.json();
      if (res.ok) setNewKey({ tenant_id: tenant.tenant_id, tenant_name: tenant.name, api_key: data.api_key });
    } catch { /* silent */ }
  };

  const totalActive = tenants.filter(t => t.is_active).length;
  const totalCalls  = tenants.reduce((s, t) => s + t.this_month.api_calls_used, 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Tenants</h1>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 4, margin: 0 }}>
            Manage B2B partners · {totalActive} active · {totalCalls.toLocaleString()} calls this month
          </p>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={load} style={{ padding: "8px 14px", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, cursor: "pointer", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <RefreshCw size={13} /> Refresh
          </button>
          <button onClick={() => setShowCreate(true)} style={{ padding: "8px 18px", background: "#ef4444", border: "none", borderRadius: 8, cursor: "pointer", color: "white", fontWeight: 700, fontSize: 13, display: "flex", alignItems: "center", gap: 6 }}>
            <Plus size={14} /> New Tenant
          </button>
        </div>
      </div>

      {error && (
        <div style={{ padding: "12px 16px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: 8, fontSize: 13, color: "#ef4444", display: "flex", alignItems: "center", gap: 8 }}>
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Table */}
      <div style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 12, overflow: "hidden" }}>
        {loading ? (
          <div style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
            <Loader2 size={20} style={{ animation: "spin 1s linear infinite", margin: "0 auto 8px", display: "block" }} />
            Loading tenants…
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", background: "rgba(255,255,255,0.02)" }}>
                {["Tenant", "Plan", "Rate Limit", "This Month", "Avg Latency", "Status", ""].map((h, i) => (
                  <th key={i} style={{ padding: "10px 16px", fontSize: 11, fontWeight: 600, color: "var(--text-muted)", textTransform: "uppercase" as const, letterSpacing: 1, textAlign: i >= 2 && i <= 4 ? "right" as const : "left" as const }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tenants.length === 0 ? (
                <tr><td colSpan={7} style={{ padding: 48, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>No tenants yet — create one above</td></tr>
              ) : tenants.map(t => (
                <TenantRow key={t.tenant_id} tenant={t} onRotateKey={handleRotateKey} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showCreate && <CreateTenantModal onClose={() => setShowCreate(false)} onCreated={handleCreated} />}
      {newKey && <ApiKeyModal keyData={newKey} onClose={() => setNewKey(null)} />}
    </div>
  );
}
