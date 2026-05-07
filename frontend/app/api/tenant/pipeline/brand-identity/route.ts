import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
  const adminSecret = process.env.ADMIN_SECRET || "";

  const res = await fetch(`${apiUrl}/v1/pipeline/brand-identity`, {
    headers: { "X-Admin-Secret": adminSecret },
    cache: "no-store",
  });

  if (!res.ok) return NextResponse.json({ error: "Failed" }, { status: res.status });
  return NextResponse.json(await res.json());
}

export async function POST(req: NextRequest) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
  const adminSecret = process.env.ADMIN_SECRET || "";
  const body = await req.json();

  const res = await fetch(`${apiUrl}/v1/pipeline/brand-identity`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Secret": adminSecret,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!res.ok) return NextResponse.json({ error: "Failed" }, { status: res.status });
  return NextResponse.json(await res.json());
}
