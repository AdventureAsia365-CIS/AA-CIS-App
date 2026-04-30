"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Upload, ClipboardList, BookOpen, Sun, Moon, Users } from "lucide-react";
import { useState, useEffect } from "react";
import LogoutButton from "@/components/LogoutButton";

const ADMIN_NAV = [
  { href:"/dashboard", label:"Dashboard", icon:LayoutDashboard },
  { href:"/tenants",   label:"Tenants",   icon:Users },
];
const CONTENT_NAV = [
  { href:"/upload",  label:"Upload",  icon:Upload },
  { href:"/review",  label:"Review",  icon:ClipboardList },
  { href:"/catalog", label:"Catalog", icon:BookOpen },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [theme, setTheme] = useState<"dark"|"light">("light");
  useEffect(() => {
    const saved = localStorage.getItem("cis_theme") as "dark"|"light" | null;
    const t = saved || "light";
    setTheme(t);
    document.documentElement.setAttribute("data-theme", t);
  }, []);
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("cis_theme", next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const linkStyle = (href: string, color = "#ef4444"): React.CSSProperties => ({
    display:"flex", alignItems:"center", gap:6,
    padding:"6px 14px", borderRadius:8, fontSize:13,
    textDecoration:"none", transition:"all 0.15s",
    color: pathname === href ? color : "#8B9BB4",
    background: pathname === href ? `${color}18` : "transparent",
    fontWeight: pathname === href ? 600 : 400,
  });

  return (
    <div>
      <nav style={{
        background:"#0F1419",
        borderBottom:"1px solid rgba(239,68,68,0.3)",
        padding:"0 24px", height:56,
        display:"flex", alignItems:"center", gap:16,
        position:"sticky", top:0, zIndex:50,
      }}>
        {/* Logo + role */}
        <div style={{ display:"flex", alignItems:"center", gap:10, marginRight:8 }}>
          <div style={{ width:30, height:30, background:"#ef4444", borderRadius:7, display:"flex", alignItems:"center", justifyContent:"center", fontWeight:800, fontSize:11, color:"white" }}>AA</div>
          <span style={{ fontWeight:600, color:"#F8F6F2", fontSize:14 }}>CIS</span>
          <span style={{ fontSize:10, padding:"2px 7px", background:"rgba(239,68,68,0.15)", color:"#ef4444", border:"1px solid rgba(239,68,68,0.3)", borderRadius:20, fontWeight:700 }}>ADMIN</span>
        </div>

        {/* Divider */}
        <div style={{ width:1, height:24, background:"rgba(239,68,68,0.2)" }} />

        {/* Admin nav */}
        {ADMIN_NAV.map(({ href, label, icon:Icon }) => (
          <Link key={href} href={href} style={linkStyle(href, "#ef4444")}>
            <Icon size={14} />{label}
          </Link>
        ))}

        {/* Divider */}
        <div style={{ width:1, height:24, background:"var(--border)" }} />

        {/* Content nav (admin can access) */}
        <span style={{ fontSize:11, color:"var(--text-muted)" }}>Content:</span>
        {CONTENT_NAV.map(({ href, label, icon:Icon }) => (
          <Link key={href} href={href} style={linkStyle(href, "var(--brand-gold)")}>
            <Icon size={14} />{label}
          </Link>
        ))}

        {/* Spacer */}
        <div style={{ flex:1 }} />

        <button onClick={toggleTheme} title="Toggle theme"
          style={{ padding:"6px 10px", borderRadius:8, border:"1px solid var(--border)",
            background:"none", cursor:"pointer", color:"#8B9BB4",
            display:"flex", alignItems:"center", gap:6, fontSize:12,
          }}>
          {theme === "dark" ? <Sun size={14}/> : <Moon size={14}/>}
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <LogoutButton />
      </nav>
      <main style={{ maxWidth:1280, margin:"0 auto", padding:"32px" }}>
        {children}
      </main>
    </div>
  );
}
