"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

interface Requirement {
  id: string;
  description: string;
  type: string;
  priority: string;
  deliverable: string;
  constraints: Record<string, any>;
  rubric_criteria: Array<{criterion: string; weight: number}>;
}

interface GeneratedFile {
  name: string;
  content: string;
  mime_type: string;
  requirement_ids: string[];
}

interface GoogleDocInfo {
  doc_id: string;
  url: string;
  drive_file_id: string;
  title: string;
  editable_url: string;
}

interface AssignmentReviewData {
  assignment: {
    id: string;
    title: string;
    description: string;
    course_code: string;
    course_name: string;
    due_date: string;
    status: string;
  };
  requirements: {
    task_type: string;
    requirements: Requirement[];
    deliverables: Array<{name: string; type: string; required: boolean}>;
    submission_format: string;
    confidence: number;
  };
  generated_solution: {
    files: GeneratedFile[];
    content: Record<string, any>;
    confidence: number;
    requirements_met: string[];
    requirements_partial: string[];
    requirements_failed: string[];
    reviewer_feedback: string;
  };
  google_doc: GoogleDocInfo;
  confidence_score: number;
  ai_reasoning: string;
  can_auto_approve: boolean;
  auto_approval_reason: string | null;
}

export default function AssignmentReviewPage() {
  const params = useParams();
  const router = useRouter();
  const assignmentId = params.id as string;

  const [data, setData] = useState<AssignmentReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "requirements" | "files" | "doc" | "ai">("overview");
  const [submitting, setSubmitting] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);

  useEffect(() => {
    fetchReviewData();
  }, [assignmentId]);

  const fetchReviewData = async () => {
    try {
      const res = await fetch(`/api/assignments/${assignmentId}/review`);
      if (!res.ok) throw new Error("Failed to fetch review data");
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const handleApprove = async (mode: "MANUAL" | "AUTO") => {
    setSubmitting(true);
    try {
      const res = await fetch(`/api/assignments/${assignmentId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, auto_approve_future: mode === "AUTO" }),
      });
      if (!res.ok) throw new Error("Approval failed");
      router.push(`/dashboard/assignments/${assignmentId}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRequestChanges = () => {
    const feedback = prompt("Describe what changes you need:");
    if (!feedback) return;

    fetch(`/api/assignments/${assignmentId}/request-changes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ feedback, priority: "HIGH" }),
    }).then(() => {
      alert("Changes requested. AI will regenerate the solution.");
      fetchReviewData();
    });
  };

  const handleAutoApproveToggle = async (enabled: boolean) => {
    setAutoApprove(enabled);
    // In production: call API to update user config
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">Loading assignment review...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center p-8">
          <h1 className="text-2xl font-bold text-red-600 mb-2">Error</h1>
          <p className="text-gray-600">{error || "Failed to load assignment"}</p>
          <Link href="/dashboard/assignments" className="mt-4 text-blue-600 hover:underline">
            Back to Assignments
          </Link>
        </div>
      </div>
    );
  }

  const { assignment, requirements, generated_solution, google_doc, confidence_score, ai_reasoning, can_auto_approve, auto_approval_reason } = data;

  const getRequirementStatus = (reqId: string) => {
    if (generated_solution.requirements_met.includes(reqId)) return "met";
    if (generated_solution.requirements_partial.includes(reqId)) return "partial";
    if (generated_solution.requirements_failed.includes(reqId)) return "failed";
    return "pending";
  };

  const formatDate = (dateStr: string) => new Date(dateStr).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-4">
              <Link href="/dashboard" className="text-gray-500 hover:text-gray-700">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                </svg>
              </Link>
              <h1 className="text-xl font-bold text-gray-900">{assignment.title}</h1>
              <span className="px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800">
                {assignment.course_code}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <a 
                href={google_doc.editable_url} 
                target="_blank" 
                rel="noopener noreferrer"
                className="px-3 py-1.5 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
                Open in Google Docs
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Assignment Meta */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-lg p-4 border border-gray-200">
            <p className="text-sm text-gray-500">Due Date</p>
            <p className="text-lg font-semibold text-gray-900">{formatDate(assignment.due_date)}</p>
          </div>
          <div className="bg-white rounded-lg p-4 border border-gray-200">
            <p className="text-sm text-gray-500">Course</p>
            <p className="text-lg font-semibold text-gray-900">{assignment.course_name}</p>
          </div>
          <div className="bg-white rounded-lg p-4 border border-gray-200">
            <p className="text-sm text-gray-500">Status</p>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
              {assignment.status.replace(/_/g, " ")}
            </span>
          </div>
          <div className="bg-white rounded-lg p-4 border border-gray-200">
            <p className="text-sm text-gray-500">AI Confidence</p>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div 
                  className="h-full bg-gradient-to-r from-red-500 via-yellow-500 to-green-500 rounded-full transition-all duration-500"
                  style={{ width: `${confidence_score * 100}%` }}
                ></div>
              </div>
              <span className="text-lg font-bold text-gray-900">{Math.round(confidence_score * 100)}%</span>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <nav className="border-b border-gray-200" aria-label="Tabs">
            <ul className="flex flex-wrap -mb-px">
              {[
                { id: "overview", label: "Overview", icon: "📋" },
                { id: "requirements", label: "Requirements", icon: "✅" },
                { id: "files", label: "Generated Files", icon: "📁" },
                { id: "doc", label: "Google Doc", icon: "📄" },
                { id: "ai", label: "AI Analysis", icon: "🤖" },
              ].map((tab) => (
                <li key={tab.id}>
                  <button
                    onClick={() => setActiveTab(tab.id as any)}
                    className={`inline-flex items-center gap-1 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                      activeTab === tab.id
                        ? "border-blue-600 text-blue-600"
                        : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                    }`}
                  >
                    <span>{tab.icon}</span> {tab.label}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          {/* Tab Panels */}
          <div className="p-6">
            {activeTab === "overview" && (
              <OverviewPanel assignment={assignment} requirements={requirements} solution={generated_solution} />
            )}
            {activeTab === "requirements" && (
              <RequirementsPanel requirements={requirements.requirements} solution={generated_solution} getStatus={getRequirementStatus} />
            )}
            {activeTab === "files" && (
              <FilesPanel files={generated_solution.files} content={generated_solution.content} />
            )}
            {activeTab === "doc" && (
              <GoogleDocPanel doc={google_doc} />
            )}
            {activeTab === "ai" && (
              <AIAnalysisPanel reasoning={ai_reasoning} feedback={generated_solution.reviewer_feedback} />
            )}
          </div>

          {/* Approval Actions - Sticky at bottom */}
          <div className="border-t border-gray-200 p-4 bg-gray-50 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4 w-full sm:w-auto">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoApprove}
                  onChange={(e) => handleAutoApproveToggle(e.target.checked)}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">Enable auto-approval for similar assignments</span>
              </label>
              {can_auto_approve && (
                <span className="px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                  ✓ Eligible for auto-approval
                </span>
              )}
              {!can_auto_approve && auto_approval_reason && (
                <span className="px-2 py-1 text-xs font-medium bg-yellow-100 text-yellow-800 rounded">
                  ⚠ {auto_approval_reason}
                </span>
              )}
            </div>

            <div className="flex gap-3 w-full sm:w-auto">
              <button
                onClick={handleRequestChanges}
                disabled={submitting}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-500 disabled:opacity-50"
              >
                Request Changes
              </button>
              <button
                onClick={() => handleApprove(autoApprove ? "AUTO" : "MANUAL")}
                disabled={submitting}
                className="px-6 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 flex items-center gap-2"
              >
                {submitting ? (
                  <>
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Submitting...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                    </svg>
                    {autoApprove ? "Auto-Approve & Submit" : "Approve & Submit"}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

// ============================================================
// SUB-COMPONENTS
// ============================================================

function OverviewPanel({ assignment, requirements, solution }: any) {
  return (
    <div className="space-y-6">
      <div className="prose max-w-none">
        <h2 className="text-xl font-semibold text-gray-900 mb-2">Assignment Description</h2>
        <p className="text-gray-700 whitespace-pre-wrap">{assignment.description || "No description provided"}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Task Type" value={requirements.task_type} icon="🎯" />
        <StatCard label="Requirements" value={requirements.requirements.length} icon="📝" />
        <StatCard label="Deliverables" value={requirements.deliverables.length} icon="📦" />
      </div>

      <div className="border-t border-gray-200 pt-6">
        <h3 className="text-lg font-medium text-gray-900 mb-3">Deliverables Expected</h3>
        <ul className="space-y-2">
          {requirements.deliverables.map((d: any, i: number) => (
            <li key={i} className="flex items-center gap-2 text-gray-700">
              <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
              <strong>{d.name}</strong> ({d.type}) {d.required && <span className="text-red-500 text-sm">*</span>}
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-gray-200 pt-6">
        <h3 className="text-lg font-medium text-gray-900 mb-3">Submission Format</h3>
        <p className="text-gray-700">{requirements.submission_format.replace(/_/g, " ")}</p>
      </div>
    </div>
  );
}

function RequirementsPanel({ requirements, solution, getStatus }: any) {
  return (
    <div className="space-y-4">
      {requirements.map((req: any) => {
        const status = getStatus(req.id);
        const statusConfig = {
          met: { label: "Met", color: "bg-green-100 text-green-800", icon: "✓" },
          partial: { label: "Partial", color: "bg-yellow-100 text-yellow-800", icon: "⚠" },
          failed: { label: "Failed", color: "bg-red-100 text-red-800", icon: "✗" },
          pending: { label: "Pending", color: "bg-gray-100 text-gray-800", icon: "○" },
        }[status];

        return (
          <details key={req.id} className="group border border-gray-200 rounded-lg bg-white">
            <summary className="flex items-center gap-3 p-4 cursor-pointer list-none">
              <span className={`px-2 py-1 text-xs font-medium rounded-full ${statusConfig.color}`}>
                {statusConfig.icon} {statusConfig.label}
              </span>
              <span className="font-medium text-gray-900 flex-1">{req.description}</span>
              <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded">
                {req.type}
              </span>
              <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded">
                {req.priority}
              </span>
              <svg className="w-5 h-5 text-gray-400 group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </summary>
            <div className="px-4 pb-4 border-t border-gray-100 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Deliverable: </span>
                  <span className="font-medium">{req.deliverable}</span>
                </div>
                <div>
                  <span className="text-gray-500">Priority: </span>
                  <span className="font-medium">{req.priority}</span>
                </div>
              </div>

              {Object.keys(req.constraints).length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-900 mb-2">Constraints</h4>
                  <ul className="space-y-1 text-sm text-gray-700">
                    {Object.entries(req.constraints).map(([key, value]) => (
                      <li key={key} className="flex gap-2">
                        <span className="text-gray-500">{key}:</span>
                        <span>{Array.isArray(value) ? value.join(", ") : value}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {req.rubric_criteria.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-900 mb-2">Rubric Criteria</h4>
                  <ul className="space-y-1 text-sm text-gray-700">
                    {req.rubric_criteria.map((c: any, i: number) => (
                      <li key={i} className="flex justify-between">
                        <span>{c.criterion}</span>
                        <span className="font-medium">{c.weight}%</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function FilesPanel({ files, content }: any) {
  if (!files || files.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <svg className="w-16 h-16 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <p>No files generated yet</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {files.map((file: any, i: number) => (
        <div key={i} className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <FileIcon mimeType={file.mime_type} />
            <div>
              <p className="font-medium text-gray-900">{file.name}</p>
              <p className="text-sm text-gray-500">
                {file.mime_type} • {formatFileSize(file.size_bytes)}
                {file.requirement_ids.length > 0 && (
                  <> • For: {file.requirement_ids.join(", ")}</>
                )}
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="px-3 py-1.5 text-sm text-blue-600 hover:text-blue-700 font-medium">
              Preview
            </button>
            <a 
              href={`data:${file.mime_type};base64,${btoa(file.content)}`}
              download={file.name}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-700 font-medium border border-gray-300 rounded-lg"
            >
              Download
            </a>
          </div>
        </div>
      ))}
    </div>
  );
}

function GoogleDocPanel({ doc }: any) {
  return (
    <div className="space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
        <h3 className="text-lg font-medium text-blue-900 mb-2">Google Document Ready</h3>
        <p className="text-blue-700 mb-4">The solution has been formatted into your Google Docs template with all placeholders filled.</p>
        <div className="flex gap-3">
          <a
            href={doc.editable_url}
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            Open in Google Docs
          </a>
          <a
            href={doc.url}
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2 bg-white text-blue-600 border border-blue-600 rounded-lg hover:bg-blue-50 font-medium"
          >
            View Only
          </a>
        </div>
      </div>

      <div className="bg-gray-50 rounded-lg p-4">
        <h4 className="font-medium text-gray-900 mb-2">Document Details</h4>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
          <dt className="text-gray-500">Document ID</dt>
          <dd className="font-mono text-gray-900">{doc.doc_id}</dd>
          <dt className="text-gray-500">Drive File ID</dt>
          <dd className="font-mono text-gray-900">{doc.drive_file_id}</dd>
          <dt className="text-gray-500">Title</dt>
          <dd className="text-gray-900">{doc.title}</dd>
          <dt className="text-gray-500">Created</dt>
          <dd className="text-gray-900">{new Date(doc.created_at).toLocaleString()}</dd>
        </dl>
      </div>
    </div>
  );
}

function AIAnalysisPanel({ reasoning, feedback }: any) {
  return (
    <div className="space-y-6">
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
        <h3 className="text-lg font-medium text-blue-900 mb-3 flex items-center gap-2">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          AI Reasoning
        </h3>
        <div className="prose max-w-none text-blue-800 whitespace-pre-wrap">{reasoning || "No reasoning available"}</div>
      </div>

      {feedback && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-3 flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Reviewer Feedback
          </h3>
          <div className="prose max-w-none text-gray-700 whitespace-pre-wrap">{feedback}</div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, icon }: any) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <div className="flex items-center gap-3">
        <span className="text-2xl">{icon}</span>
        <div>
          <p className="text-sm text-gray-500">{label}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
        </div>
      </div>
    </div>
  );
}

function FileIcon({ mimeType }: any) {
  if (mimeType.includes("python") || mimeType.includes("javascript") || mimeType.includes("code")) {
    return <svg className="w-10 h-10 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" /></svg>;
  }
  if (mimeType.includes("pdf")) {
    return <svg className="w-10 h-10 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>;
  }
  return <svg className="w-10 h-10 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>;
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}