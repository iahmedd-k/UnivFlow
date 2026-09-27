import { NextRequest, NextResponse } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  
  const { mode, changes_requested, auto_approve_future } = body;
  
  // In production: call backend API
  // const res = await fetch(`${process.env.BACKEND_URL}/assignments/${id}/approve`, {
  //   method: "POST",
  //   headers: { "Content-Type": "application/json" },
  //   body: JSON.stringify(body),
  // });
  
  // Mock response
  console.log(`Approving assignment ${id} with mode: ${mode}`);
  
  if (mode === "AUTO") {
    // Auto-approve and submit
    return NextResponse.json({
      success: true,
      message: "Assignment auto-approved and submitted",
      assignment: {
        id,
        status: "SUBMITTED",
        approval_mode: "AUTO",
        approved_at: new Date().toISOString(),
        submitted_at: new Date().toISOString(),
      },
    });
  }
  
  return NextResponse.json({
    success: true,
    message: "Assignment approved",
    assignment: {
      id,
      status: "APPROVED",
      approval_mode: "MANUAL",
      approved_at: new Date().toISOString(),
    },
  });
}