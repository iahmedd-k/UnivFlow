'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { format, isValid, formatDistanceToNow } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import TutorPanel from '../TutorPanel';
import ReviewPanel from '../ReviewPanel';
import TurnInPanel from '../TurnInPanel';
import SolutionPanel from '../SolutionPanel';

const TABS = [
  { id: 'overview', label: 'Overview & Rubric', icon: 'clipboard' },
  { id: 'tutor', label: 'AI Tutor', icon: 'lightbulb' },
  { id: 'solver', label: 'Solver & Report', icon: 'code' },
  { id: 'review', label: 'Pre-Submit Review', icon: 'search' },
  { id: 'turnin', label: 'Turn In', icon: 'upload' },
];

function getStatus(assignment) {
  const state = assignment.submission_state;
  if (state === 'TURNED_IN' || state === 'RETURNED') {
    return { label: 'Submitted', pillClass: 'product-pill success' };
  }
  if (state === 'DRAFT') {
    return { label: 'Draft', pillClass: 'product-pill' };
  }
  if (assignment.due_at && new Date(assignment.due_at) < new Date()) {
    return { label: 'Overdue', pillClass: 'product-pill error' };
  }
  if (assignment.status === 'APPROVED') {
    return { label: 'Approved', pillClass: 'product-pill success' };
  }
  return { label: 'Upcoming', pillClass: 'product-pill warning' };
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

  const loadAssignment = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = getToken ? await getToken() : null;
      // Try single endpoint or fallback to filtering list
      try {
        const single = await api.getAssignment(assignmentId, token);
        if (single && single.id) {
          setAssignment(single);
          return;
        }
      } catch {
        // Fallback to list search
      }
      const data = await api.getAssignments(null, token);
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
    loadAssignment();
  }, [loadAssignment]);

  const handleTurnIn = async (id, templateId, fileNames, token) => {
    await api.turnInAssignment(id, { template_id: templateId, templateId, fileNames }, token);
    await loadAssignment();
  };

  if (loading) {
    return (
      <main className="product-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link href="/dashboard/assignments" className="product-action secondary" style={{ textDecoration: 'none' }}>
            <Icon name="arrowLeft" size={13}/> Back to assignments
          </Link>
        </div>
        <div className="product-card" style={{ padding: 40, textAlign: 'center', color: '#858998' }}>
          <span className="loading-dot" style={{ display: 'inline-block', marginBottom: 10 }} />
          <p style={{ fontSize: 13, margin: 0 }}>Loading assignment workspace…</p>
        </div>
      </main>
    );
  }

  if (error || !assignment) {
    return (
      <main className="product-page" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Link href="/dashboard/assignments" className="product-action secondary" style={{ textDecoration: 'none' }}>
          <Icon name="arrowLeft" size={13}/> Back to assignments
          </Link>
        </div>
        <div className="product-alert" role="alert">
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
    <main className="product-page pb-12" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Top Back and Navigation Bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <Link
          href="/dashboard/assignments"
          className="product-action secondary"
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
            className="product-action secondary"
            style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <span>Classroom post</span>
            <Icon name="externalLink" size={13}/>
          </a>
        )}
      </div>

      {/* Main Page Header */}
      <header className="product-heading" style={{ alignItems: 'flex-start' }}>
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
      <section className="overview-stats" aria-label="Assignment metrics" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
        <article className="overview-stat">
          <span className="stat-icon stat-lilac"><Icon name="book" size={18}/></span>
          <div className="stat-text">
            <span>Course & work type</span>
            <strong style={{ fontSize: 16 }}>{assignment.course_name || 'Coursework'}</strong>
            <small className="capitalize">{assignment.work_type ? assignment.work_type.replace('_', ' ') : 'Graded Assignment'}</small>
          </div>
        </article>

        <article className="overview-stat">
          <span className="stat-icon stat-peach"><Icon name="clock" size={18}/></span>
          <div className="stat-text">
            <span>Submission deadline</span>
            <strong style={{ fontSize: 15, color: isOverdue ? '#b15252' : '#2c2f3c' }}>
              {hasValidDue ? format(due, 'MMM d, yyyy') : 'No deadline'}
            </strong>
            <small style={{ color: isOverdue ? '#b15252' : '#6657d9', fontWeight: 600 }}>
              {relativeStr || 'Open submission'}
            </small>
          </div>
        </article>

        <article className="overview-stat">
          <span className={`stat-icon ${isSubmitted ? 'stat-mint' : isOverdue ? '' : 'stat-blue'}`} style={isOverdue && !isSubmitted ? { background: '#fff0f0', color: '#b15252' } : {}}>
            <Icon name={isSubmitted ? 'checkCircle' : isOverdue ? 'alert' : 'clipboard'} size={18}/>
          </span>
          <div className="stat-text">
            <span>Current state</span>
            <strong style={{ fontSize: 16, color: isSubmitted ? '#47a887' : isOverdue ? '#b15252' : '#2c2f3c' }}>
              {isSubmitted ? 'Turned in' : isOverdue ? 'Overdue' : 'Pending'}
            </strong>
            <small>{assignment.max_points ? `${assignment.max_points} Maximum Points` : 'Coursework Deliverable'}</small>
          </div>
        </article>
      </section>

      {/* Main Tab Bar Strip */}
      <div className="surface-card" style={{ padding: 0, overflow: 'hidden' }}>
        <nav className="product-tabs" style={{ borderBottom: '1px solid #f0f0f3', background: '#fff' }} aria-label="Assignment workspace tabs">
          {TABS.map((t) => {
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                aria-pressed={isActive}
                className={`product-tab ${isActive ? 'active' : ''}`}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '9px 14px' }}
              >
                <Icon name={t.icon} size={14}/>
                <span>{t.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab Panel Body */}
        <div style={{ padding: '20px 22px', background: '#fdfdfe' }}>
          {tab === 'overview' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Instructions Box */}
              <section className="product-card" style={{ padding: '18px 20px', borderRadius: 10 }}>
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
              <section className="product-card" style={{ padding: '18px 20px', borderRadius: 10 }}>
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
                        className="quick-link"
                        style={{ minHeight: 56, padding: '10px 12px' }}
                      >
                        <span className="quick-icon quick-blue" style={{ fontSize: 14 }}>
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
                    className="product-action secondary"
                    style={{ cursor: 'pointer' }}
                  >
                    <span><Icon name="lightbulb" size={14}/> Ask AI Tutor</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab('solver')}
                    className="product-action secondary"
                    style={{ cursor: 'pointer' }}
                  >
                    <span><Icon name="code" size={14}/> AI Solver</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setTab('turnin')}
                    className="product-action"
                    style={{ cursor: 'pointer' }}
                  >
                    <span><Icon name="upload" size={14}/> Turn In</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {tab === 'tutor' && <TutorPanel assignment={assignment} />}
          {tab === 'solver' && <SolutionPanel assignment={assignment} />}
          {tab === 'review' && <ReviewPanel assignment={assignment} />}
          {tab === 'turnin' && <TurnInPanel assignment={assignment} onTurnIn={handleTurnIn} />}
        </div>
      </div>
    </main>
  );
}
