"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Upload, ClipboardList, BookOpen, LayoutDashboard } from "lucide-react";
import LogoutButton from "@/components/LogoutButton";
import { useEffect, useState } from "react";

const NAV = [
  { href:"/upload",  label:"Upload",       icon:Upload },
  { href:"/review",  label:"Review Queue", icon:ClipboardList },
  { href:"/catalog", label:"Catalog",      icon:BookOpen },
];

export default function InternalLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const role = document.cookie.split(";").find(c => c.trim().startsWith("cis_role="))?.split("=")[1];
    setIsAdmin(role === "admin");
  }, []);

  return (
    <div>
      <nav style={{
        background:"var(--brand-blackblue)",
        borderBottom:"1px solid rgba(219,150,40,0.2)",
        padding:"0 24px", height:56,
        display:"flex", alignItems:"center", gap:8,
        position:"sticky", top:0, zIndex:50,
      }}>
        {/* Logo */}
        <div style={{ display:"flex", alignItems:"center", gap:10, marginRight:8 }}>
          <div style={{ width:30, height:30, background:"var(--brand-gold)", borderRadius:7, display:"flex", alignItems:"center", justifyContent:"center", fontWeight:800, fontSize:11, color:"white" }}>AA</div>
          <span style={{ fontWeight:600, color:"#F8F6F2", fontSize:14 }}>CIS</span>
          <span style={{ fontSize:10, padding:"2px 7px", background:"rgba(219,150,40,0.15)", color:"var(--brand-gold)", border:"1px solid rgba(219,150,40,0.3)", borderRadius:20, fontWeight:700 }}>
            {isAdmin ? "ADMIN" : "CONTENT"}
          </span>
        </div>

        <div style={{ width:1, height:24, background:"rgba(219,150,40,0.2)" }} />

        {/* Admin-only: back to Dashboard */}
        {isAdmin && (
          <>
            <Link href="/dashboard" style={{
              display:"flex", alignItems:"center", gap:6,
              padding:"6px 14px", borderRadius:8, fontSize:13,
              textDecoration:"none", color:"#ef4444",
              background:"rgba(239,68,68,0.08)",
              border:"1px solid rgba(239,68,68,0.2)",
              fontWeight:600,
            }}>
              <LayoutDashboard size={14} /> Dashboard
            </Link>
            <div style={{ width:1, height:24, background:"var(--border)" }} />
          </>
        )}

        {/* Content nav */}
        {NAV.map(({ href, label, icon:Icon }) => (
          <Link key={href} href={href} style={{
            display:"flex", alignItems:"center", gap:6,
            padding:"6px 14px", borderRadius:8, fontSize:13,
            textDecoration:"none", transition:"all 0.15s",
            color: pathname === href ? "var(--brand-gold)" : "#8B9BB4",
            background: pathname === href ? "rgba(219,150,40,0.1)" : "transparent",
            fontWeight: pathname === href ? 600 : 400,
          }}>
            <Icon size={14} />{label}
          </Link>
        ))}

        <div style={{ flex:1 }} />
        <LogoutButton />
      </nav>
      <main style={{ maxWidth:1280, margin:"0 auto", padding:"32px" }}>
        {children}
      </main>
    </div>
  );
}
