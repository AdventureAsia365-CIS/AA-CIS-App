const KEY = "cis_admin_secret";

export function getAdminSecret(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(KEY);
}

export function setAdminSecret(secret: string): void {
  sessionStorage.setItem(KEY, secret);
}

export function clearAdminSecret(): void {
  sessionStorage.removeItem(KEY);
}

export function adminHeaders(): HeadersInit {
  const s = getAdminSecret();
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (s) h["x-admin-secret"] = s;
  return h;
}
