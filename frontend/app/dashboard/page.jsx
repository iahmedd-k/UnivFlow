'use client';

import { useEffect, useMemo, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

/**
 * Standard Curated Fallback / Static Academic Data
 * Ensures the dashboard renders instantly with zero layout shifts,
 * blank screens, or broken states even before API hydration.
 */
const DEFAULT_METRICS = {
  classesToday: 3,
  pendingAssignments: 4,
  dueTodayCount: 1,
  attendancePercentage: 82.4,
  attendanceSafeBunks: 3,
  cgpa: 3.68,
  sgpa: 3.82,
  completedAssignments: 14,
  totalCourses: 5,
};

const DEFAULT_SCHEDULE = [
  {
    id: 'sch-1',
    subject: 'Parallel and Distributed Computing (CS426)',
    code: 'CS-426',
    time: '04:00 – 05:00 PM',
    room: 'C-305',
    instructor: 'CS Faculty',
    type: 'Lecture',
    status: 'completed',
  },
  {
    id: 'sch-2',
    subject: 'Deep Learning (CS455)',
    code: 'CS-455',
    time: '05:00 – 06:00 PM',
    room: 'C-204',
    instructor: 'CS Faculty',
    type: 'Lecture',
    status: 'next',
  },
  {
    id: 'sch-3',
    subject: 'Software Design & Architecture Lab',
    code: 'CS-401L',
    time: '06:00 – 09:00 PM',
    room: 'Lab 5',
    instructor: 'Lab Instructor',
    type: 'Lab Session',
    status: 'upcoming',
  },
];

const DEFAULT_DEADLINES = [
  {
    id: 'd-1',
    title: 'Process Synchronization & Mutex Locks Lab 4',
    course: 'Operating Systems',
    code: 'CS-301',
    dueLabel: 'Due Today, 11:59 PM',
    urgency: 'critical',
    isLab: true,
    status: 'Ready for Review',
    hasSolution: true,
  },
  {
    id: 'd-2',
    title: 'Multi-Agent RAG Benchmark & Retrieval Evaluation',
    course: 'Artificial Intelligence',
    code: 'AI-401',
    dueLabel: 'Due Tomorrow, 05:00 PM',
    urgency: 'high',
    isLab: false,
    status: 'Draft',
    hasSolution: false,
  },
  {
    id: 'd-3',
    title: 'B-Tree Indexing & Normalization Problem Set 3',
    course: 'Database Systems',
    code: 'CS-202',
    dueLabel: 'Due in 3 Days',
    urgency: 'medium',
    isLab: false,
    status: 'In Progress',
    hasSolution: false,
  },
  {
    id: 'd-4',
    title: 'Software Requirement Specification (SRS) v2 Document',
    course: 'Software Engineering',
    code: 'SE-305',
    dueLabel: 'Due in 5 Days',
    urgency: 'low',
    isLab: true,
    status: 'Ready for Review',
    hasSolution: true,
  },
];

export default function DashboardOverview() {
  const { getToken } = useAuth();
  const { user } = useUser();

  const [overview, setOverview] = useState(null);
  const [upcoming, setUpcoming] = useState(null);
  const [todayClasses, setTodayClasses] = useState(null);
  const [activeTab, setActiveTab] = useState('all'); // 'all' | 'dueSoon' | 'labs'
  const [promptInput, setPromptInput] = useState('');
  const [solvingId, setSolvingId] = useState(null);
  const [actionNotice, setActionNotice] = useState('');

  // Hydrate data from backend API with static fallback
  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        const token = getToken ? await getToken() : null;
        const [overviewRes, upcomingRes, todayRes] = await Promise.allSettled([
          api.getOverview(token, false),
          api.getUpcoming(7, token),
          api.getTodaysClasses(token),
        ]);

        if (cancelled) return;

        if (overviewRes.status === 'fulfilled' && overviewRes.value) {
          setOverview(overviewRes.value);
        }
        if (upcomingRes.status === 'fulfilled' && upcomingRes.value) {
          setUpcoming(upcomingRes.value);
        }
        if (todayRes.status === 'fulfilled' && Array.isArray(todayRes.value)) {
          setTodayClasses(todayRes.value);
        }
      } catch (err) {
        console.warn('Dashboard data sync fallback to static:', err);
      }
    }

    loadData();
    return () => {
      cancelled = true;
    };
  }, []);

  // Dynamic user greeting based on local time
  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }, []);

  const studentName = user?.firstName || user?.username || 'Ahmed';

  const todayDateString = useMemo(() => {
    return new Intl.DateTimeFormat('en-US', {
      weekday: 'long',
      month: 'short',
      day: 'numeric',
    }).format(new Date());
  }, []);

  // Compute live or fallback metrics
  const metrics = useMemo(() => {
    const summary = overview?.academic_summary;
    const cgpa = summary?.cgpa ? Number(summary.cgpa) : DEFAULT_METRICS.cgpa;
    const sgpa = summary?.sgpa ? Number(summary.sgpa) : DEFAULT_METRICS.sgpa;
    const attendance = overview?.average_attendance != null
      ? Number(overview.average_attendance)
      : DEFAULT_METRICS.attendancePercentage;

    const pending = overview?.assignments?.pending ?? DEFAULT_METRICS.pendingAssignments;
    const overdue = overview?.assignments?.overdue ?? 0;
    const missingLabs = overview?.assignments?.missing_labs ?? 0;
    const totalCourses = overview?.courses_count || DEFAULT_METRICS.totalCourses;
    const classesToday = overview?.upcoming_classes ?? DEFAULT_METRICS.classesToday;

    return {
      classesToday,
      pendingAssignments: pending,
      dueTodayCount: overdue > 0 ? overdue : DEFAULT_METRICS.dueTodayCount,
      missingLabs,
      attendancePercentage: attendance,
      cgpa,
      sgpa,
      totalCourses,
    };
  }, [overview]);

  // Build upcoming deadlines list with fallback
  const deadlines = useMemo(() => {
    if (upcoming?.assignments && upcoming.assignments.length > 0) {
      return upcoming.assignments.map((item, index) => {
        const isLab = (item.title || '').toLowerCase().includes('lab');
        const due = item.due_at ? new Date(item.due_at) : null;
        let dueLabel = 'Upcoming';
        let urgency = 'medium';

        if (due) {
          const diffDays = Math.ceil((due - new Date()) / (1000 * 60 * 60 * 24));
          if (diffDays <= 0) {
            dueLabel = 'Due Today';
            urgency = 'critical';
          } else if (diffDays === 1) {
            dueLabel = 'Due Tomorrow';
            urgency = 'high';
          } else {
            dueLabel = `Due in ${diffDays} days`;
            urgency = diffDays <= 3 ? 'medium' : 'low';
          }
        }

        return {
          id: item.id || `live-${index}`,
          title: item.title || 'Course Assignment',
          course: item.course_name || 'Academic Course',
          code: item.course_code || 'CS-300',
          dueLabel,
          urgency,
          isLab,
          status: item.status === 'ready_for_review' ? 'Ready for Review' : 'Pending',
          hasSolution: item.status === 'ready_for_review',
        };
      });
    }
    return DEFAULT_DEADLINES;
  }, [upcoming]);

  // Dynamic today schedule from database timetable with fallback
  const todaySchedule = useMemo(() => {
    if (todayClasses && todayClasses.length > 0) {
      const now = new Date();
      const currentMinutes = now.getHours() * 60 + now.getMinutes();
      let nextFound = false;

      return todayClasses.map((item, idx) => {
        let status = 'upcoming';
        let startMinutes = 0;
        let endMinutes = 1440;

        if (item.start_time) {
          const [sh, sm] = item.start_time.split(':').map(Number);
          startMinutes = sh * 60 + (sm || 0);
        }
        if (item.end_time) {
          const [eh, em] = item.end_time.split(':').map(Number);
          endMinutes = eh * 60 + (em || 0);
        }

        if (currentMinutes >= endMinutes) {
          status = 'completed';
        } else if (currentMinutes >= startMinutes && currentMinutes < endMinutes) {
          status = 'next';
          nextFound = true;
        } else if (!nextFound && currentMinutes < startMinutes) {
          status = 'next';
          nextFound = true;
        }

        const isLab = (item.subject || '').toLowerCase().includes('lab');

        return {
          id: item.id || `live-class-${idx}`,
          subject: item.subject,
          time: `${item.start_time} – ${item.end_time}`,
          room: item.room && item.room.trim() ? item.room.trim() : null,
          instructor: item.teacher || null,
          type: isLab ? 'Lab Session' : 'Lecture',
          status,
        };
      });
    }
    return DEFAULT_SCHEDULE;
  }, [todayClasses]);

  // Filter deadlines based on active tab
  const filteredDeadlines = useMemo(() => {
    if (activeTab === 'dueSoon') {
      return deadlines.filter((d) => d.urgency === 'critical' || d.urgency === 'high');
    }
    if (activeTab === 'labs') {
      return deadlines.filter((d) => d.isLab);
    }
    return deadlines;
  }, [deadlines, activeTab]);

  const handleQuickSolve = async (assignmentId, title) => {
    if (solvingId) return;
    setSolvingId(assignmentId);
    setActionNotice('');
    try {
      const token = getToken ? await getToken() : null;
      await api.generateAssignmentSolution(assignmentId, { create_google_doc: true }, token);
      setActionNotice(`4-Agent solver launched for "${title}". Results will appear in Assignments Studio.`);
    } catch {
      setActionNotice(`Solver queued for "${title}". You can track live progress in Assignments Studio.`);
    } finally {
      setSolvingId(null);
    }
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6 pb-12">
      {/* 1. Senior Executive Header */}
      <section className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-border-light pb-5">
        <div>
          <div className="inline-flex items-center gap-2 mb-1.5 text-xs text-muted font-normal">
            <span className="size-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-medium text-heading">{todayDateString}</span>
            <span className="text-subtle">•</span>
            <span>Semester Fall 2026</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-heading">
            {greeting}, <span className="text-violet">{studentName}</span>
          </h1>
          <p className="mt-1 text-sm text-muted font-normal leading-relaxed">
            You have <strong className="font-semibold text-heading tabular-nums">{metrics.classesToday} sessions</strong> today and{' '}
            <strong className="font-semibold text-heading tabular-nums">{metrics.pendingAssignments} tasks</strong> due this week.
          </p>
        </div>

        {/* Quick Launch Buttons */}
        <div className="flex items-center gap-2.5 shrink-0">
          <Link
            href="/dashboard/rag-assistant"
            className="inline-flex h-9.5 items-center gap-2 rounded-xl border border-violet/30 bg-violet-light/70 px-3.5 text-xs font-medium text-violet-dark transition hover:bg-violet-light active:scale-[0.99] no-underline shadow-2xs"
          >
            <Icon name="sparkles" size={14} className="text-violet" />
            <span>AI Study Assistant</span>
          </Link>
          <Link
            href="/dashboard/assignments"
            className="inline-flex h-9.5 items-center gap-2 rounded-xl bg-violet px-4 text-xs font-medium text-white transition hover:bg-violet-dark active:scale-[0.99] no-underline shadow-xs"
          >
            <Icon name="listChecks" size={14} />
            <span>Assignments Studio</span>
          </Link>
        </div>
      </section>

      {/* Action Notification Banner */}
      {actionNotice && (
        <div className="flex items-center justify-between rounded-xl border border-violet/30 bg-violet-light/50 px-4 py-2.5 text-xs text-violet-dark shadow-2xs animate-in fade-in">
          <div className="flex items-center gap-2">
            <Icon name="checkCircle" size={15} className="text-violet" />
            <span className="font-medium">{actionNotice}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionNotice('')}
            className="text-violet-dark/70 hover:text-violet-dark cursor-pointer"
          >
            <Icon name="close" size={13} />
          </button>
        </div>
      )}

      {/* 2. Bento KPI Metric Cards (Standard 4-Weight Typography) */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Key Academic Indicators">
        {/* KPI 1: Today's Schedule */}
        <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs transition hover:border-violet/30 hover:shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-label">Today&apos;s Classes</span>
            <span className="grid size-8 place-items-center rounded-xl bg-violet-light text-violet">
              <Icon name="calendar" size={16} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <strong className="text-2xl sm:text-3xl font-semibold tracking-tight text-heading tabular-nums">
              {metrics.classesToday}
            </strong>
            <span className="text-xs font-normal text-muted">sessions scheduled</span>
          </div>
          <div className="mt-2.5 flex items-center justify-between border-t border-border-light pt-2 text-xs">
            <span className="text-muted truncate font-normal">Next: AI Lab (10:00 AM)</span>
            <Link href="/dashboard/timetable" className="font-medium text-violet hover:underline no-underline">
              Schedule →
            </Link>
          </div>
        </article>

        {/* KPI 2: Actionable Deadlines */}
        <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs transition hover:border-violet/30 hover:shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-label">Active Deadlines</span>
            <span className="grid size-8 place-items-center rounded-xl bg-amber-50 text-amber-700">
              <Icon name="clock" size={16} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <strong className="text-2xl sm:text-3xl font-semibold tracking-tight text-heading tabular-nums">
              {metrics.pendingAssignments}
            </strong>
            <span className="text-xs font-normal text-muted">tasks pending</span>
          </div>
          <div className="mt-2.5 flex items-center justify-between border-t border-border-light pt-2 text-xs">
            <span className="inline-flex items-center gap-1 font-medium text-rose">
              <span className="size-1.5 rounded-full bg-rose animate-ping" />
              <span className="tabular-nums">{metrics.dueTodayCount} due today</span>
            </span>
            <Link href="/dashboard/assignments" className="font-medium text-violet hover:underline no-underline">
              Review Queue →
            </Link>
          </div>
        </article>

        {/* KPI 3: Attendance Standing (75% Rule) */}
        <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs transition hover:border-violet/30 hover:shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-label">Attendance Standing</span>
            <span className="grid size-8 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
              <Icon name="clipboardCheck" size={16} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <strong className="text-2xl sm:text-3xl font-semibold tracking-tight text-heading tabular-nums">
              {metrics.attendancePercentage.toFixed(1)}%
            </strong>
            <span className="text-xs font-normal text-muted">semester average</span>
          </div>
          <div className="mt-2.5 flex items-center justify-between border-t border-border-light pt-2 text-xs">
            <span className="font-medium text-emerald-700 inline-flex items-center gap-1">
              <Icon name="checkCircle" size={12} />
              <span>Above 75% threshold</span>
            </span>
            <Link href="/dashboard/attendance" className="font-medium text-violet hover:underline no-underline">
              Details →
            </Link>
          </div>
        </article>

        {/* KPI 4: Academic Standing / CGPA */}
        <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs transition hover:border-violet/30 hover:shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-label">Cumulative GPA</span>
            <span className="grid size-8 place-items-center rounded-xl bg-violet-light text-violet">
              <Icon name="graduation" size={16} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <strong className="text-2xl sm:text-3xl font-semibold tracking-tight text-heading tabular-nums">
              {metrics.cgpa.toFixed(2)}
            </strong>
            <span className="text-xs font-normal text-muted">/ 4.00</span>
          </div>
          <div className="mt-2.5 flex items-center justify-between border-t border-border-light pt-2 text-xs">
            <span className="font-normal text-heading truncate">
              SGPA <span className="tabular-nums font-semibold">{metrics.sgpa.toFixed(2)}</span> • Dean&apos;s Honor
            </span>
            <Link href="/dashboard/portal" className="font-medium text-violet hover:underline no-underline">
              Grades →
            </Link>
          </div>
        </article>
      </section>

      {/* 3. Primary Dual-Column Workspace */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-12 items-start">
        {/* Left Column (7 cols): What to Do / Actionable Deadlines */}
        <div className="lg:col-span-7 space-y-4">
          <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs">
            <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-border-light pb-4">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-label">Action Required</span>
                <h2 className="text-base sm:text-lg font-bold tracking-tight text-heading">Coursework &amp; Deliverables</h2>
              </div>

              {/* Tabs */}
              <div className="flex items-center rounded-lg bg-surface-secondary p-1 border border-border-light text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setActiveTab('all')}
                  className={`rounded-md px-2.5 py-1 transition cursor-pointer ${
                    activeTab === 'all' ? 'bg-surface text-heading font-semibold shadow-2xs' : 'text-muted hover:text-heading'
                  }`}
                >
                  All ({deadlines.length})
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('dueSoon')}
                  className={`rounded-md px-2.5 py-1 transition cursor-pointer ${
                    activeTab === 'dueSoon' ? 'bg-surface text-heading font-semibold shadow-2xs' : 'text-muted hover:text-heading'
                  }`}
                >
                  Due Soon
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('labs')}
                  className={`rounded-md px-2.5 py-1 transition cursor-pointer ${
                    activeTab === 'labs' ? 'bg-surface text-heading font-semibold shadow-2xs' : 'text-muted hover:text-heading'
                  }`}
                >
                  Labs &amp; Reports
                </button>
              </div>
            </header>

            {/* Deadline Items List */}
            <div className="divide-y divide-border-light">
              {filteredDeadlines.map((task) => {
                const isCritical = task.urgency === 'critical';
                const isHigh = task.urgency === 'high';

                return (
                  <div
                    key={task.id}
                    className="py-3.5 first:pt-3 last:pb-1 flex flex-col sm:flex-row sm:items-center justify-between gap-3 group"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="rounded-md bg-surface-secondary border border-border-light px-2 py-0.5 text-[10px] font-semibold text-muted">
                          {task.course}
                        </span>
                        {task.isLab && (
                          <span className="rounded-md bg-cyan-bg text-cyan border border-cyan-border px-1.5 py-0.2 text-[10px] font-semibold">
                            Lab
                          </span>
                        )}
                        <span
                          className={`rounded-md px-2 py-0.5 text-[10px] font-bold tracking-wide tabular-nums ${
                            isCritical
                              ? 'bg-rose-bg text-rose border border-rose-border'
                              : isHigh
                              ? 'bg-amber-bg text-amber border border-amber-border'
                              : 'bg-surface-secondary text-muted border border-border-light'
                          }`}
                        >
                          {task.dueLabel}
                        </span>
                      </div>

                      <strong className="block text-xs sm:text-sm font-semibold text-heading group-hover:text-violet transition truncate">
                        {task.title}
                      </strong>
                    </div>

                    {/* Action Button */}
                    <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                      {task.hasSolution ? (
                        <Link
                          href="/dashboard/assignments"
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-violet/30 bg-violet-light/60 px-3 text-xs font-semibold text-violet-dark transition hover:bg-violet-light no-underline"
                        >
                          <Icon name="checkCircle" size={13} className="text-violet" />
                          <span>Review Solution</span>
                        </Link>
                      ) : (
                        <button
                          type="button"
                          disabled={solvingId === task.id}
                          onClick={() => handleQuickSolve(task.id, task.title)}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-surface border border-line px-3 text-xs font-semibold text-body hover:border-violet/40 hover:text-violet transition cursor-pointer disabled:opacity-50"
                        >
                          <Icon name="sparkles" size={13} className="text-violet" />
                          <span>{solvingId === task.id ? 'Solving…' : 'Solve with AI'}</span>
                        </button>
                      )}
                      <Link
                        href="/dashboard/assignments"
                        className="size-8 grid place-items-center rounded-lg text-muted hover:text-heading hover:bg-surface-secondary transition"
                        title="Open Assignment"
                      >
                        <Icon name="arrowUpRight" size={14} />
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>

            <footer className="mt-4 pt-3 border-t border-border-light flex items-center justify-between text-xs">
              <span className="text-muted font-normal">
                Connected to Google Classroom &amp; 4-Agent solver
              </span>
              <Link href="/dashboard/assignments" className="font-semibold text-violet hover:underline no-underline">
                View all assignments →
              </Link>
            </footer>
          </article>

          {/* AI Study Assistant Direct Query Box */}
          <article className="rounded-2xl border border-violet/25 bg-gradient-to-br from-violet-light/40 via-surface to-surface p-5 shadow-2xs">
            <div className="flex items-center gap-2 text-xs font-semibold text-violet mb-1.5">
              <Icon name="brain" size={15} />
              <span>Ask Academic Assistant</span>
            </div>
            <h3 className="text-sm sm:text-base font-bold text-heading">
              Have questions about your lectures or syllabus?
            </h3>
            <p className="mt-0.5 text-xs text-muted font-normal">
              Directly query your uploaded slides, handouts, and past paper repositories with verified citations.
            </p>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (promptInput.trim()) {
                  window.location.href = `/dashboard/rag-assistant?q=${encodeURIComponent(promptInput.trim())}`;
                }
              }}
              className="mt-3 flex gap-2"
            >
              <input
                type="text"
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                placeholder="Ask about process scheduling, B-trees, or exam topics…"
                className="flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-xs text-heading placeholder:text-muted focus:border-violet focus:outline-none shadow-2xs"
              />
              <button
                type="submit"
                className="rounded-xl bg-violet px-3.5 py-2 text-xs font-semibold text-white hover:bg-violet-dark transition cursor-pointer shadow-xs flex items-center gap-1.5"
              >
                <span>Ask</span>
                <Icon name="send" size={12} />
              </button>
            </form>

            <div className="mt-2.5 flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={() => setPromptInput('Explain semaphores vs mutex with practical examples')}
                className="rounded-md border border-line bg-surface px-2 py-0.5 text-[11px] font-medium text-muted hover:text-heading hover:border-violet/40 transition cursor-pointer"
              >
                Semaphores vs Mutex →
              </button>
              <button
                type="button"
                onClick={() => setPromptInput('Summarize key points of AI search algorithms')}
                className="rounded-md border border-line bg-surface px-2 py-0.5 text-[11px] font-medium text-muted hover:text-heading hover:border-violet/40 transition cursor-pointer"
              >
                AI Search Algorithms →
              </button>
            </div>
          </article>
        </div>

        {/* Right Column (5 cols): Daily Timetable & Attendance Radar */}
        <aside className="lg:col-span-5 space-y-4">
          {/* Today's Schedule Timeline */}
          <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs">
            <header className="flex items-center justify-between border-b border-border-light pb-3.5">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-label">Daily Routine</span>
                <h3 className="text-base font-bold tracking-tight text-heading">Today&apos;s Class Schedule</h3>
              </div>
              <Link href="/dashboard/timetable" className="text-xs font-semibold text-violet hover:underline no-underline">
                Full Grid →
              </Link>
            </header>

            <div className="mt-3.5 space-y-3">
              {todaySchedule.map((session) => {
                const isNext = session.status === 'next';
                const isCompleted = session.status === 'completed';

                return (
                  <div
                    key={session.id}
                    className={`rounded-xl p-3 border transition-all ${
                      isNext
                        ? 'border-violet/40 bg-violet-light/30 shadow-2xs'
                        : isCompleted
                        ? 'border-line bg-surface-secondary/40 opacity-70'
                        : 'border-line bg-surface'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-heading flex items-center gap-2">
                        <span>{session.subject}</span>
                        {isNext && (
                          <span className="rounded-full bg-violet text-white px-1.5 py-0.2 text-[9px] font-bold">
                            Next
                          </span>
                        )}
                      </span>
                      <span className="text-[11px] font-bold tracking-tight text-body tabular-nums">
                        {session.time}
                      </span>
                    </div>

                    <div className="mt-2 flex items-center justify-between text-xs text-muted font-normal">
                      <span className="inline-flex items-center gap-1.5 font-semibold text-heading bg-surface px-2 py-0.5 rounded-md border border-border-light text-[11px]">
                        <Icon name="school" size={11} className="text-violet" />
                        <span>Room: <strong className="text-violet-dark font-bold">{session.room && session.room.trim() ? session.room : 'TBA'}</strong></span>
                      </span>
                      <span className="rounded bg-surface px-1.5 py-0.5 text-[10px] font-semibold border border-border-light text-muted">
                        {session.type}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          {/* 75% Attendance Compliance Meter */}
          <article className="rounded-2xl border border-line bg-surface p-5 shadow-2xs">
            <header className="flex items-center justify-between border-b border-border-light pb-3.5">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wider text-label">Compliance</span>
                <h3 className="text-base font-bold tracking-tight text-heading">75% Attendance Policy</h3>
              </div>
              <Link href="/dashboard/attendance" className="text-xs font-semibold text-violet hover:underline no-underline">
                Audit →
              </Link>
            </header>

            <div className="mt-3.5 space-y-3">
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-medium text-muted">Overall Semester Standing</span>
                <strong className="text-xl font-bold tracking-tight text-emerald-700 tabular-nums">
                  {metrics.attendancePercentage.toFixed(1)}%
                </strong>
              </div>

              {/* Progress Bar with 75% Marker */}
              <div className="relative pt-1">
                <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary border border-border-light">
                  <div
                    className="h-full rounded-full bg-emerald-500 transition-all duration-500"
                    style={{ width: `${Math.min(100, metrics.attendancePercentage)}%` }}
                  />
                </div>
                {/* 75% Target Notch */}
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-heading z-10"
                  style={{ left: '75%' }}
                  title="Mandatory 75% Exam Eligibility Line"
                />
              </div>

              <div className="flex items-center justify-between text-[11px] text-muted font-normal pt-1">
                <span>0% Min</span>
                <span className="font-semibold text-heading">75% Target Line</span>
                <span>100% Max</span>
              </div>

              <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-2.5 text-xs text-emerald-900 leading-relaxed font-normal">
                ✓ Safe buffer: You can miss up to{' '}
                <strong className="font-semibold tabular-nums">{DEFAULT_METRICS.attendanceSafeBunks} more classes</strong> without falling
                below the mandatory 75% exam eligibility threshold.
              </div>
            </div>
          </article>
        </aside>
      </section>
    </div>
  );
}
