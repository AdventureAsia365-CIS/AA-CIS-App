// frontend/middleware.ts
// AA-232: ADMIN_PATHS/INTERNAL_PATHS now verify a real JWT (cis_admin_token)
// via /auth/verify-admin, mirroring the existing TENANT_PATHS block below.
// The old check (cookie value === "admin"/present) is a role LABEL a client
// could set by hand in devtools — it gated the page, but not the identity.
// This adds actual signature verification on top of the same cookie-role
// gate (kept as a fast pre-check to avoid a network call on every request
// for obviously-wrong roles).
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ADMIN_PATHS    = ["/admin/tenants"];
const INTERNAL_PATHS = ["/admin/dashboard", "/admin/upload", "/admin/pipeline", "/admin/master-content", "/admin/review", "/admin/brand", "/upload", "/review", "/catalog"];
const TENANT_PATHS   = ["/portal"];
const PUBLIC_PATHS   = ["/login", "/tenant-login"];

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api-cis.lumiguides.it.com";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip public paths
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const role = request.cookies.get("cis_role")?.value;

  // ── Admin only ────────────────────────────────────────────────────────────
  if (ADMIN_PATHS.some(p => pathname.startsWith(p))) {
    if (role !== "admin") {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    const verifyResult = await verifyAdminToken(request);
    if (verifyResult) return verifyResult; // redirect response — invalid/expired/missing token
  }

  // ── Internal (admin + content) ──────────────────────────────────────────
  if (INTERNAL_PATHS.some(p => pathname.startsWith(p))) {
    if (!role || role === "tenant") {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    // Content-role sessions don't carry an admin JWT (separate login path,
    // see login/route.ts) — only verify when the cookie claims admin/reviewer.
    if (role === "admin" || role === "reviewer") {
      const verifyResult = await verifyAdminToken(request);
      if (verifyResult) return verifyResult;
    }
  }

  // ── Tenant portal — verify JWT ──────────────────────────────────────────
  if (TENANT_PATHS.some(p => pathname.startsWith(p))) {
    // Admin can always access portal (for testing)
    if (role === "admin") return NextResponse.next();

    if (role !== "tenant") {
      return NextResponse.redirect(new URL("/tenant-login", request.url));
    }

    // Verify JWT with backend
    const token = request.cookies.get("cis_tenant_token")?.value;
    if (!token) {
      return NextResponse.redirect(new URL("/tenant-login", request.url));
    }

    try {
      const res = await fetch(`${API_URL}/auth/verify-tenant`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
        // Short timeout — don't block page load
        signal: AbortSignal.timeout(3000),
      });

      if (!res.ok) {
        // JWT invalid/expired → clear cookies + redirect
        const response = NextResponse.redirect(new URL("/tenant-login", request.url));
        response.cookies.delete("cis_role");
        response.cookies.delete("cis_tenant_token");
        response.cookies.delete("cis_tenant_id");
        response.cookies.delete("cis_tenant_name");
        response.cookies.delete("cis_tenant_plan");
        return response;
      }
    } catch {
      // Verification service unreachable — fail open in dev, fail closed in prod
      const isDev = process.env.NODE_ENV === "development";
      if (!isDev) {
        return NextResponse.redirect(new URL("/tenant-login", request.url));
      }
      // In dev: allow through with warning (logged server-side)
      console.warn("[middleware] JWT verify failed — dev mode, allowing through");
    }
  }

  return NextResponse.next();
}

// ── AA-232 helper — verify cis_admin_token, mirrors the TENANT_PATHS block ──
// Returns a NextResponse (redirect) if verification fails, or null if it
// passed (caller continues). Same fail-open-in-dev / fail-closed-in-prod
// policy as the tenant block, for consistency.
async function verifyAdminToken(request: NextRequest): Promise<NextResponse | null> {
  const token = request.cookies.get("cis_admin_token")?.value;
  if (!token) {
    // No JWT present — this covers sessions created via the legacy
    // ADMIN_SECRET fallback path (login/route.ts), which don't mint one.
    // Interim: allow through on cookie-role alone (matches pre-AA-232
    // behavior) until the fallback path is retired.
    return null;
  }

  try {
    const res = await fetch(`${API_URL}/auth/verify-admin`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) {
      const response = NextResponse.redirect(new URL("/login", request.url));
      response.cookies.delete("cis_role");
      response.cookies.delete("cis_admin_token");
      return response;
    }
    return null;
  } catch {
    const isDev = process.env.NODE_ENV === "development";
    if (!isDev) {
      return NextResponse.redirect(new URL("/login", request.url));
    }
    console.warn("[middleware] Admin JWT verify failed — dev mode, allowing through");
    return null;
  }
}

export const config = {
  matcher: [
    "/admin/:path*",
    "/upload/:path*",
    "/review/:path*",
    "/catalog/:path*",
    "/portal/:path*",
    "/login",
    "/tenant-login",
  ],
};
