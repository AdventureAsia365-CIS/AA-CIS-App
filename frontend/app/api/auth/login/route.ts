// frontend/app/api/auth/login/route.ts
// AA-232: admin login now tries JWT (/auth/admin-login) first.
// Falls back to the legacy shared-secret check ONLY on infra failure
// (network error / non-2xx-non-401 / JSON parse failure from the JWT
// endpoint) — e.g. admin-login route not yet deployed, or backend
// temporarily unreachable. A 401 from /auth/admin-login (wrong
// username/password) does NOT fall back — it must fail closed, otherwise
// anyone who knows ADMIN_SECRET could bypass a correctly-rejected JWT
// login, defeating the whole point of AA-232.
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

  // ── AA-232: try real per-user JWT login first ────────────────────────────
  let jwtInfraFailed = false;
  try {
    const res = await fetch(`${API_URL}/auth/admin-login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(5000),
    });

    if (res.status === 401) {
      // Correctly rejected — real credentials check failed. Do NOT fall
      // back to the shared-secret path; that would let a wrong username/
      // password succeed anyway as long as the caller also knows ADMIN_SECRET.
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }

    if (res.ok) {
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
    }

    // Any other status (500, etc.) from a route that DID respond — treat as
    // infra failure, allow fallback below.
    jwtInfraFailed = true;
  } catch {
    // Network error / timeout / route not deployed yet — infra failure.
    jwtInfraFailed = true;
  }

  if (!jwtInfraFailed) {
    // Should be unreachable (every branch above either returns or sets the
    // flag), but fail closed rather than silently falling through.
    return NextResponse.json({ detail: "Login failed" }, { status: 502 });
  }

  // ── Legacy fallback: shared ADMIN_SECRET check ──────────────────────────
  // AA-232 interim only — remove once /auth/admin-login is confirmed stable
  // in prod and all real admins have accounts in shared.admin_users.
  try {
    const res = await fetch(`${API_URL}/admin/tenants`, {
      method: "GET",
      headers: { "x-admin-secret": password, "Content-Type": "application/json" },
    });

    if (!res.ok) {
      return NextResponse.json({ detail: "Invalid credentials" }, { status: 401 });
    }

    return NextResponse.json({ token: password, role: "admin", name: username || "Admin" });
  } catch {
    return NextResponse.json({ detail: "Backend connection error" }, { status: 502 });
  }
}
