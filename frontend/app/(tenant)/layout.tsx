"use client";
import { useEffect, useState } from "react";
import { Key } from "lucide-react";
import LogoutButton from "@/components/LogoutButton";

function getCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : "";
}

const PLAN_LABELS: Record<string, string> = {
  starter:    "STARTER",
  growth:     "GROWTH",
  business:   "BUSINESS",
  enterprise: "ENTERPRISE",
  internal:   "INTERNAL",
};

const PLAN_COLORS: Record<string, string> = {
  starter:    "rgba(100,149,237,0.15)",
  growth:     "rgba(219,150,40,0.15)",
  business:   "rgba(80,200,120,0.15)",
  enterprise: "rgba(180,100,255,0.15)",
  internal:   "rgba(150,150,150,0.15)",
};

export default function TenantLayout({ children }: { children: React.ReactNode }) {
  const [tenantName, setTenantName] = useState("Partner");
  const [planTier, setPlanTier]     = useState("growth");

  useEffect(() => {
    const name = getCookie("cis_tenant_name");
    const plan = getCookie("cis_tenant_plan");
    if (name) setTenantName(name);
    if (plan) setPlanTier(plan);
  }, []);

  const planLabel = PLAN_LABELS[planTier] ?? planTier.toUpperCase();
  const planBg    = PLAN_COLORS[planTier] ?? PLAN_COLORS.growth;

  return (
    <div>
      <nav style={{
        background:"#0F1419",
        borderBottom:"1px solid rgba(219,150,40,0.15)",
        padding:"0 24px", height:56,
        display:"flex", alignItems:"center", justifyContent:"space-between",
        position:"sticky", top:0, zIndex:50,
      }}>
        <div style={{ display:"flex", alignItems:"center", gap:12 }}>
          <div style={{ width:30, height:30, background:"var(--brand-gold)", borderRadius:7, display:"flex", alignItems:"center", justifyContent:"center", fontWeight:800, fontSize:11, color:"white" }}>AA</div>
          <span style={{ fontWeight:600, color:"#F8F6F2", fontSize:14 }}>Adventure Asia</span>
          <span style={{ fontSize:11, color:"#8B9BB4" }}>Partner Portal</span>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:12 }}>
          <div style={{ display:"flex", alignItems:"center", gap:6, fontSize:12, color:"#8B9BB4" }}>
            <Key size={12} />
            <span>{tenantName}</span>
            <span style={{
              padding:"2px 8px",
              background: planBg,
              color:"var(--brand-gold)",
              borderRadius:20, fontSize:11, fontWeight:700,
            }}>
              {planLabel}
            </span>
          </div>
          <LogoutButton redirectTo="/tenant-login" />
        </div>
      </nav>
      <main style={{ maxWidth:1280, margin:"0 auto", padding:"32px" }}>
        {children}
      </main>
    </div>
  );
}
