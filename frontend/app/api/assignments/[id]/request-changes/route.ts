import { NextRequest, NextResponse } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  
  const { feedback, specific_requirements, priority } = body;
  
  // In production: call backend API
  console.log(`Requesting changes for assignment ${id}:`, feedback);
  
  return NextResponse.json({
    success: true,
    message: "Changes requested. AI will regenerate the solution.",
    assignment: {
      id,
      status: "GENERATING",
      changes_requested: feedback,
      priority,
    },
  });
}