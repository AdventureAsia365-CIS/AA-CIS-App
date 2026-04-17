"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { User, Lock } from "lucide-react";

const MOCK_USERS = [
  { username:"admin",   password:"admin2026",   role:"admin",   name:"Nghiep (DevOps)" },
  { username:"content", password:"content2026", role:"content", name:"Trang (Content)" },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]       = useState("");
  const router = useRouter();

  const login = () => {
    const user = MOCK_USERS.find(u => u.username === username && u.password === password);
    if (!user) { setError("Invalid username or password"); return; }
    document.cookie = `cis_role=${user.role}; path=/; max-age=86400`;
    document.cookie = `cis_user=${user.name}; path=/; max-age=86400`;
    router.push(user.role === "admin" ? "/dashboard" : "/upload");
  };

  return (
    <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"var(--bg-primary)" }}>
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:16, padding:40, width:380 }}>
        {/* Logo */}
        <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:32 }}>
          <div style={{ width:36, height:36, background:"var(--brand-gold)", borderRadius:8, display:"flex", alignItems:"center", justifyContent:"center", fontWeight:800, color:"white" }}>AA</div>
          <div>
            <div style={{ fontWeight:700, color:"var(--text-primary)", fontSize:16 }}>CIS Internal</div>
            <div style={{ fontSize:11, color:"var(--text-muted)" }}>Staff Login</div>
          </div>
        </div>

        {/* Username */}
        <div style={{ marginBottom:14 }}>
          <label style={{ fontSize:11, fontWeight:600, color:"var(--text-muted)", textTransform:"uppercase" as const, letterSpacing:1, display:"block", marginBottom:8 }}>Username</label>
          <div style={{ position:"relative" }}>
            <User size={13} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"var(--text-muted)" }} />
            <input type="text" value={username} onChange={e => { setUsername(e.target.value); setError(""); }}
              placeholder="admin or content"
              onKeyDown={e => e.key === "Enter" && login()}
              style={{ width:"100%", padding:"10px 12px 10px 34px", background:"var(--bg-primary)", border:`1px solid ${error ? "#ef4444" : "var(--border)"}`, borderRadius:8, color:"var(--text-primary)", fontSize:13, outline:"none" }} />
          </div>
        </div>

        {/* Password */}
        <div style={{ marginBottom:20 }}>
          <label style={{ fontSize:11, fontWeight:600, color:"var(--text-muted)", textTransform:"uppercase" as const, letterSpacing:1, display:"block", marginBottom:8 }}>Password</label>
          <div style={{ position:"relative" }}>
            <Lock size={13} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"var(--text-muted)" }} />
            <input type="password" value={password} onChange={e => { setPassword(e.target.value); setError(""); }}
              placeholder="••••••••"
              onKeyDown={e => e.key === "Enter" && login()}
              style={{ width:"100%", padding:"10px 12px 10px 34px", background:"var(--bg-primary)", border:`1px solid ${error ? "#ef4444" : "var(--border)"}`, borderRadius:8, color:"var(--text-primary)", fontSize:13, outline:"none" }} />
          </div>
          {error && <div style={{ fontSize:12, color:"#ef4444", marginTop:6 }}>{error}</div>}
        </div>

        <button onClick={login} style={{ width:"100%", padding:12, background:"var(--brand-gold)", border:"none", borderRadius:8, color:"white", fontSize:14, fontWeight:700, cursor:"pointer" }}>
          Login
        </button>

        {/* Demo hint */}
        <div style={{ marginTop:16, padding:12, background:"rgba(219,150,40,0.06)", border:"1px solid rgba(219,150,40,0.2)", borderRadius:8, fontSize:12, color:"var(--text-muted)", lineHeight:1.6 }}>
          Demo: <code style={{ color:"var(--brand-gold)" }}>admin / admin2026</code><br/>
          or: <code style={{ color:"var(--brand-gold)" }}>content / content2026</code>
        </div>

        <div style={{ marginTop:16, textAlign:"center" as const }}>
          <a href="/tenant-login" style={{ fontSize:12, color:"var(--text-muted)", textDecoration:"none" }}>
            B2B Tenant login →
          </a>
        </div>
      </div>
    </div>
  );
}
