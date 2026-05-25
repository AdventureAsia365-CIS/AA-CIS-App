import { NextRequest, NextResponse } from "next/server";

const API_URL      = process.env.API_URL      ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET  ?? "";
const API_KEY      = process.env.INTERNAL_API_KEY ?? "";

function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return {
    "X-Admin-Secret": ADMIN_SECRET,
    ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    ...extra,
  };
}

export async function GET(_req: NextRequest) {
  const res = await fetch(`${API_URL}/admin/brand-identity`, {
    headers: apiHeaders(),
    cache: "no-store",
  });
  if (!res.ok) return NextResponse.json({ error: "Failed" }, { status: res.status });
  return NextResponse.json(await res.json());
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${API_URL}/admin/brand-identity`, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) return NextResponse.json({ error: "Failed" }, { status: res.status });
  return NextResponse.json(await res.json());
}
