import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const authHeader = request.headers.get("authorization");
  const body = await request.json().catch(() => ({}));

  try {
    const backendRes = await fetch(`${API_BASE}/assignments/${id}/request-changes`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authHeader ? { Authorization: authHeader } : {}),
      },
      body: JSON.stringify(body),
    });

    const data = await backendRes.json().catch(() => ({}));
    return NextResponse.json(data, { status: backendRes.status });
  } catch (err: any) {
    return NextResponse.json(
      { detail: err?.message || "Failed to forward request-changes to backend" },
      { status: 502 }
    );
  }
}