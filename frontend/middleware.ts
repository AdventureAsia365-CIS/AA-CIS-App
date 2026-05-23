import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ADMIN_PATHS    = ["/admin/dashboard", "/admin/tenants"];
const INTERNAL_PATHS = ["/admin/upload", "/admin/pipeline", "/admin/master-content", "/upload", "/review", "/catalog"];
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
  }

  // ── Internal (admin + content) ────────────────────────────────────────────
  if (INTERNAL_PATHS.some(p => pathname.startsWith(p))) {
    if (!role || role === "tenant") {
      return NextResponse.redirect(new URL("/login", request.url));
    }
  }

  // ── Tenant portal — verify JWT ────────────────────────────────────────────
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

export const config = {
  matcher: [
    "/admin/:path*",
    "/dashboard/:path*",
    "/upload/:path*",
    "/review/:path*",
    "/catalog/:path*",
    "/portal/:path*",
    "/login",
    "/tenant-login",
  ],
};
