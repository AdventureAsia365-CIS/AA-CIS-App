// frontend/app/api/auth/admin-logout/route.ts
// AA-521 — mirrors AA-427's /api/auth/tenant-logout for the admin session.
//
// AdminSidebar.tsx's logout() used to only clear the display cookies
// (cis_role/cis_user/cis_api_token) via `document.cookie = "...max-age=0"`.
// cis_admin_token (the real JWT middleware.ts/verifyAdminToken() checks) has
// been httpOnly since AA-232 — client JS can't see or overwrite it, so
// clicking Logout redirected to /login but left the real session alive until
// its natural 24h expiry (JWT_EXPIRY_H). Anyone who could later re-set
// cis_role=admin by hand (e.g. a shared/left-open browser) would sail back
// in, since verifyAdminToken() would find the old JWT still valid. This
// route clears cis_admin_token server-side (cookies().delete() works on
// httpOnly cookies; client JS still can't).
//
// cis_role/cis_user/cis_api_token are cleared here too even though the
// sidebar's client-side clear already handles them defensively — keeps this
// route the single source of truth for "log this admin session out",
// matching tenant-logout's shape.
import { NextResponse } from "next/server";

const ADMIN_COOKIES = ["cis_admin_token", "cis_role", "cis_user", "cis_api_token"];

export async function POST() {
  const response = NextResponse.json({ ok: true });
  for (const name of ADMIN_COOKIES) {
    response.cookies.set(name, "", { path: "/", maxAge: 0 });
  }
  return response;
}
