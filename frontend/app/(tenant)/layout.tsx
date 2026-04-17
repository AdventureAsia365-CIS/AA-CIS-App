"use client";
import { Key } from "lucide-react";
import LogoutButton from "@/components/LogoutButton";

export default function TenantLayout({ children }: { children: React.ReactNode }) {
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
            <span>Wanderlust Premium</span>
            <span style={{ padding:"2px 8px", background:"rgba(219,150,40,0.15)", color:"var(--brand-gold)", borderRadius:20, fontSize:11, fontWeight:700 }}>PRO</span>
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
