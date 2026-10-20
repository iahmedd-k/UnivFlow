'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { format, isValid, formatDistanceToNow } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import TutorPanel from '../TutorPanel';
import TurnInPanel from '../TurnInPanel';
import SolutionPanel from '../SolutionPanel';

const TABS = [
  { id: 'overview', label: 'Overview & Rubric', icon: 'clipboard' },
  { id: 'tutor', label: 'AI Tutor', icon: 'lightbulb' },
  { id: 'solver', label: 'Solver & Report', icon: 'code' },
  { id: 'turnin', label: 'Turn In', icon: 'upload' },
];

function getStatus(assignment) {
  const state = assignment.submission_state;
  if (state === 'TURNED_IN' || state === 'RETURNED') {
    return { label: 'Submitted', pillClass: 'inline-flex items-center rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700' };
  }
  if (state === 'DRAFT') {
    return { label: 'Draft', pillClass: 'inline-flex items-center rounded-full bg-neutral-100 px-2 py-1 text-xs font-semibold text-neutral-600' };
  }
  if (assignment.due_at && new Date(assignment.due_at) < new Date()) {
    return { label: 'Overdue', pillClass: 'inline-flex items-center rounded-full bg-red-50 px-2 py-1 text-xs font-semibold text-red-700' };
  }
  if (assignment.status === 'APPROVED') {
    return { label: 'Approved', pillClass: 'inline-flex items-center rounded-full bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700' };
  }
  return { label: 'Upcoming', pillClass: 'inline-flex items-center rounded-full bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-700' };
}

export default function AssignmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { getToken } = useAuth();
  const assignmentId = params.id;

  const [assignment, setAssignment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('overview');

  const loadAssignment = useCallback(async (options = {}) => {
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      // Try single endpoint or fallback to filtering list
      try {
        const single = await api.getAssignment(assignmentId, token, options);
        if (single && single.id) {
          setAssignment(single);
          return;
        }
      } catch {
        // Fallback to list search
      }
      const data = await api.getAssignments(null, token, null, options);
      const found = (data || []).find((a) => String(a.id) === String(assignmentId));
      if (!found) throw new Error('Assignment not found');
      setAssignment(found);
    } catch (e) {
      setError(e.message || 'Could not load assignment details.');
    } finally {
      setLoading(false);
    }
  }, [assignmentId, getToken]);

  useEffect(() => {
    const timer = setTimeout(() => loadAssignment(), 0);
    return () => clearTimeout(timer);
  }, [loadAssignment]);

  const handleTurnIn = async (id, templateId, files, token) => {
    await api.turnInAssignment(id, { template_id: templateId, files }, token);
    await loadAssignment({ noCache: true });
  };

  if (loading) {
    return (
      <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link href="/dashboard/assignments" className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 no-underline hover:bg-neutral-50">
            <Icon name="arrowLeft" size={13}/> Back to assignments
          </Link>
        </div>
        <div className="rounded-xl border border-neutral-200 bg-white p-10 text-center text-neutral-500">
          <span className="mb-2.5 inline-block h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
          <p style={{ fontSize: 13, margin: 0 }}>Loading assignment workspace…</p>
        </div>
      </main>
    );
  }

  if (error || !assignment) {
    return (
      <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link href="/dashboard/assignments" className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 no-underline hover:bg-neutral-50">
          <Icon name="arrowLeft" size={13}/> Back to assignments
          </Link>
        </div>
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-800" role="alert">
          <strong>Error loading assignment:</strong> {error || 'Assignment not found.'}
        </div>
      </main>
    );
  }

  const due = assignment.due_at ? new Date(assignment.due_at) : null;
  const hasValidDue = due && isValid(due);
  const dueDateStr = hasValidDue ? format(due, "MMMM d, yyyy 'at' h:mm a") : 'No deadline';
  const relativeStr = hasValidDue
    ? due < new Date()
      ? `Expired ${formatDistanceToNow(due)} ago`
      : `Due in ${formatDistanceToNow(due)}`
    : null;
  const isOverdue = hasValidDue && due < new Date();
  const isSubmitted = assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED';
  const status = getStatus(assignment);
  const materials = assignment.materials || [];

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-12">
      {/* Top Back and Navigation Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <Link
          href="/dashboard/assignments"
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 no-underline hover:bg-neutral-50"
          style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <Icon name="arrowLeft" size={13} />
          <span>Back to assignments</span>
        </Link>
        {assignment.url && (
          <a
            href={assignment.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 no-underline hover:bg-neutral-50"
            style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <span>Classroom post</span>
            <Icon name="externalLink" size={13}/>
          </a>
        )}
      </div>

      {/* Main Page Header */}
      <header className="flex flex-col items-start justify-between gap-4">
        <div style={{ maxWidth: '800px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: '#5b4cc6',
                background: '#f4f1ff',
                border: '1px solid #e6e1fb',
                borderRadius: 6,
                padding: '2px 8px',
              }}
            >
              {assignment.course_name}
            </span>
            <span className={status.pillClass}>{status.label}</span>
          </div>
          <h1 style={{ margin: '4px 0 6px', fontSize: 24, fontWeight: 700, color: '#252837', letterSpacing: '-0.6px', lineHeight: 1.3 }}>
            {assignment.title}
          </h1>
          <p style={{ color: '#858998', fontSize: 12 }}>
            Due {dueDateStr} {relativeStr ? ` · ${relativeStr}` : ''}
          </p>
        </div>
      </header>

      {/* 3 Overview Metric Cards */}
      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3" aria-label="Assignment metrics">
        <article className="flex items-center gap-3 rounded-xl border border-[#ededf2] bg-white p-4">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-purple-50 text-purple-700"><Icon name="book" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1 text-xs text-[#858998]">
            <span>Course & work type</span>
            <strong className="text-base font-semibold text-[#343746]">{assignment.course_name || 'Coursework'}</strong>
            <small className="capitalize">{assignment.work_type ? assignment.work_type.replace('_', ' ') : 'Graded Assignment'}</small>
          </div>
        </article>

        <article className="flex items-center gap-3 rounded-xl border border-[#ededf2] bg-white p-4">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-amber-50 text-amber-700"><Icon name="clock" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1 text-xs text-[#858998]">
            <span>Submission deadline</span>
            <strong className={`text-[15px] font-semibold ${isOverdue ? 'text-red-700' : 'text-[#2c2f3c]'}`}>
              {hasValidDue ? format(due, 'MMM d, yyyy') : 'No deadline'}
            </strong>
            <small className={`font-semibold ${isOverdue ? 'text-red-700' : 'text-[#6657d9]'}`}>
              {relativeStr || 'Open submission'}
            </small>
          </div>
        </article>

        <article className="flex items-center gap-3 rounded-xl border border-[#ededf2] bg-white p-4">
          <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${isSubmitted ? 'bg-emerald-50 text-emerald-700' : isOverdue ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}`}>
            <Icon name={isSubmitted ? 'checkCircle' : isOverdue ? 'alert' : 'clipboard'} size={18}/>
          </span>
          <div className="flex min-w-0 flex-col gap-1 text-xs text-[#858998]">
            <span>Current state</span>
            <strong className={`text-base font-semibold ${isSubmitted ? 'text-emerald-700' : isOverdue ? 'text-red-700' : 'text-[#2c2f3c]'}`}>
              {isSubmitted ? 'Turned in' : isOverdue ? 'Overdue' : 'Pending'}
            </strong>
            <small>{assignment.max_points ? `${assignment.max_points} Maximum Points` : 'Coursework Deliverable'}</small>
          </div>
        </article>
      </section>

      {/* Main Tab Bar Strip */}
      <div className="overflow-hidden rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <nav className="flex gap-1.5 overflow-auto border-b border-[#f0f0f3] bg-white px-4 py-3" aria-label="Assignment workspace tabs">
          {TABS.map((t) => {
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                aria-pressed={isActive}
                className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-3.5 py-2 text-xs ${isActive ? 'border-[#e9e5ff] bg-[#f2efff] font-semibold text-[#5e4fc5]' : 'border-transparent bg-transparent text-[#777b89] hover:bg-neutral-50'}`}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '9px 14px' }}
              >
                <Icon name={t.icon} size={14}/>
                <span>{t.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab Panel Body */}
        <div className="bg-[#fdfdfe] p-5 sm:p-6">
          {tab === 'overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Instructions Box */}
              <section className="rounded-xl border border-[#ebebf0] bg-white p-5 shadow-sm">
                <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f2f2f5', paddingBottom: 10, marginBottom: 12 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#858998', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Assignment Instructions
                  </span>
                  {assignment.url && (
                    <a href={assignment.url} target="_blank" rel="noreferrer" style={{ fontSize: 11, fontWeight: 600, color: '#6657d9', textDecoration: 'none' }}>
                      Open in Classroom <Icon name="externalLink" size={13}/>
                    </a>
                  )}
                </header>

                {assignment.description ? (
                  <div
                    style={{
                      background: '#fafafd',
                      padding: '16px 18px',
                      borderRadius: 8,
                      border: '1px solid #ececf2',
                      fontSize: 12,
                      lineHeight: 1.7,
                      color: '#2c2f3b',
                      whiteSpace: 'pre-wrap',
                      fontFamily: 'inherit',
                    }}
                  >
                    {assignment.description}
                  </div>
                ) : (
                  <p style={{ color: '#9a9cab', fontSize: 12, margin: 0, padding: '12px 0' }}>
                    No written instructions provided on this coursework post.
                  </p>
                )}
              </section>

              {/* Materials & References */}
              <section className="rounded-xl border border-[#ebebf0] bg-white p-5 shadow-sm">
                <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f2f2f5', paddingBottom: 10, marginBottom: 14 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#858998', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Materials & References ({materials.length})
                  </span>
                </header>

                {materials.length > 0 ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
                    {materials.map((m, idx) => (
                      <a
                        key={idx}
                        href={m.url || '#'}
                        target="_blank"
                        rel="noreferrer"
                        className="flex min-h-14 items-center gap-3 rounded-lg border border-neutral-200 bg-white p-3 text-neutral-800 no-underline transition hover:border-indigo-200 hover:bg-indigo-50/50"
                        style={{ minHeight: 56, padding: '10px 12px' }}
                      >
                        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-50 text-sm text-indigo-600">
                          <Icon name={m.material_type === 'drive_file' ? 'file' : m.material_type === 'link' ? 'link' : 'paperclip'} size={16}/>
                        </span>
                        <span>
                          <strong style={{ fontSize: 11 }}>{m.title || 'Attached Document'}</strong>
                          <small>{m.material_type ? m.material_type.replace('_', ' ') : 'File'} · Click to view <Icon name="externalLink" size={11}/></small>
                        </span>
                        <Icon name="arrowUpRight" size={13}/>
                      </a>
                    ))}
                  </div>
                ) : (
                  <p style={{ color: '#9a9cab', fontSize: 12, margin: 0, padding: '10px 0' }}>
                    No reference attachments or links provided for this post.
                  </p>
                )}
              </section>

              {/* Quick Navigation Action Hub */}
              <div
                style={{
                  background: '#f4f1ff',
                  border: '1px solid #e6e1fb',
                  borderRadius: 10,
                  padding: '16px 18px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <strong style={{ fontSize: 12, color: '#3d3968', display: 'block' }}>
                    Work on this assignment with Uniflow
                  </strong>
                  <span style={{ fontSize: 11, color: '#7f7aab' }}>
                    Ask the Socratic AI tutor, run the code solver in sandbox, or turn in directly to Google Classroom.
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    onClick={() => setTab('tutor')}
                    className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]"
                  >
                    <span><Icon name="lightbulb" size={14}/> Ask AI Tutor</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab('solver')}
                    className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]"
                  >
                    <span><Icon name="code" size={14}/> AI Solver</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab('turnin')}
                    className="inline-flex min-h-9 cursor-pointer items-center justify-center gap-2 rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1]"
                  >
                    <span><Icon name="upload" size={14}/> Turn In</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {tab === 'tutor' && <TutorPanel assignment={assignment} />}
          {tab === 'solver' && <SolutionPanel assignment={assignment} />}
          {tab === 'turnin' && (
            <TurnInPanel
              assignment={assignment}
              onTurnIn={handleTurnIn}
              onStatusChange={() => loadAssignment({ noCache: true })}
            />
          )}
        </div>
      </div>
    </main>
  );
}
