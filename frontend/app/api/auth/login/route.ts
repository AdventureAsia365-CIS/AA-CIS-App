// frontend/app/api/auth/login/route.ts
// AA-232: admin login goes through JWT (/auth/admin-login) only.
//
// AA-252 (security fix): the legacy ADMIN_SECRET shared-secret fallback is
// retired. It used to trigger on JWT infra failure (network error/timeout/
// 500) and returned { token: password, role: "admin" } with NO cis_admin_token
// cookie — a session shape middleware.ts had to specially allow through
// without JWT verification. That carve-out was exploitable: cis_role is a
// plain client-writable cookie, so anyone could set it by hand and skip auth
// entirely, no secret required. Both real admins (nghiep, admin) already have
// JWT accounts in shared.admin_users — the fallback served no one. On infra
// failure we now return a real error instead of silently granting access.
import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_URL ?? "https://api-cis.lumiguides.it.com";

export async function POST(req: NextRequest) {
  const { username, password } = await req.json();

  if (!username || !password) {
    return NextResponse.json({ detail: "Missing credentials" }, { status: 400 });
  }

  // Content staff login — unchanged, verified against CONTENT_PASSWORD env var
  if (username === "content") {
    const contentPassword = process.env.CONTENT_PASSWORD;
    if (!contentPassword) {
      return NextResponse.json({ detail: "Content login not configured" }, { status: 503 });
    }
    if (password !== contentPassword) {
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }
    return NextResponse.json({ token: password, role: "content", name: "Content" });
  }

  // ── AA-232: real per-user JWT login (only path — AA-252 retired the
  // shared-secret fallback) ────────────────────────────────────────────────
  try {
    const res = await fetch(`${API_URL}/auth/admin-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(5000),
    });

    if (res.status === 401) {
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }

    if (!res.ok) {
      // Backend responded but not OK/401 (e.g. 500) — surface as a real
      // error. No more silent fallback into an unauthenticated session.
      return NextResponse.json({ detail: "Login failed — backend error" }, { status: 502 });
    }

    const data = await res.json();
    const response = NextResponse.json({
      token: data.token, // JWT — stored client-side too for API calls that need it directly
      role: data.role,   // 'admin' | 'reviewer'
      name: data.username,
      admin_id: data.admin_id,
    });
    // Server-readable cookie for middleware verification (see middleware.ts).
    // httpOnly so client JS can't read/tamper with it; the JSON body above
    // still carries the token for any client code that needs to attach it
    // to direct API calls.
    response.cookies.set("cis_admin_token", data.token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24, // 24h — matches backend JWT_EXPIRY_H
    });
    return response;
  } catch {
    // Network error / timeout / route unreachable — a real infra failure,
    // not a reason to grant access. Surface it instead of falling back.
    return NextResponse.json({ detail: "Backend connection error" }, { status: 502 });
  }
}
