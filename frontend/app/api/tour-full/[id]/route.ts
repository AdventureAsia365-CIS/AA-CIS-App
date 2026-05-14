import { NextRequest, NextResponse } from "next/server";

const API_URL      = process.env.API_URL      ?? "https://api-cis.lumiguides.it.com";
const ADMIN_SECRET = process.env.ADMIN_SECRET  ?? "";
const API_KEY      = process.env.INTERNAL_API_KEY ?? "";

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const res = await fetch(`${API_URL}/v1/tours/${id}/full`, {
    headers: {
      "X-Admin-Secret": ADMIN_SECRET,
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    },
    cache: "no-store",
  });

  if (!res.ok) {
    return NextResponse.json({ error: "Failed" }, { status: res.status });
  }

  return NextResponse.json(await res.json());
}
