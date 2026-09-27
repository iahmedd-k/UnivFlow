import { NextRequest, NextResponse } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  
  // In production: call backend API
  console.log(`Submitting assignment ${id}`);
  
  return NextResponse.json({
    success: true,
    message: "Assignment submitted successfully",
    receipt: {
      confirmation_id: `SUB-${Date.now()}`,
      submitted_at: new Date().toISOString(),
      method: "GCR_API",
      portal_submission_id: `gcr_${id}`,
    },
    assignment: {
      id,
      status: "SUBMITTED",
      submitted_at: new Date().toISOString(),
    },
  });
}