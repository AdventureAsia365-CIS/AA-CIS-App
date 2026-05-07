import { NextRequest, NextResponse } from "next/server";

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "";
  const adminSecret = process.env.ADMIN_SECRET || "";

  const res = await fetch(`${apiUrl}/v1/tours/${params.id}/full`, {
    headers: { "X-Admin-Secret": adminSecret },
    cache: "no-store",
  });

  if (!res.ok) {
    return NextResponse.json({ error: "Failed" }, { status: res.status });
  }

  const data = await res.json();
  return NextResponse.json(data);
}
