import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ADMIN_PATHS    = ["/dashboard"];
const INTERNAL_PATHS = ["/upload", "/review", "/catalog"];
const TENANT_PATHS   = ["/portal"];
const PUBLIC_PATHS   = ["/login", "/tenant-login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip public paths
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const role = request.cookies.get("cis_role")?.value;

  // Admin only
  if (ADMIN_PATHS.some(p => pathname.startsWith(p))) {
    if (role !== "admin") return NextResponse.redirect(new URL("/login", request.url));
  }

  // Internal (admin + content)
  if (INTERNAL_PATHS.some(p => pathname.startsWith(p))) {
    if (!role || role === "tenant") return NextResponse.redirect(new URL("/login", request.url));
  }

  // Tenant only
  if (TENANT_PATHS.some(p => pathname.startsWith(p))) {
    if (role !== "tenant" && role !== "admin") return NextResponse.redirect(new URL("/tenant-login", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/upload/:path*", "/review/:path*", "/catalog/:path*", "/portal/:path*", "/login", "/tenant-login"],
};
