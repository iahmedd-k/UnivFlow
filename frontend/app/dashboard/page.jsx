'use client';

import { useEffect, useMemo, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

function formatDate(value, options = { month: 'short', day: 'numeric' }) {
  if (!value) return 'Date TBC';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Date TBC' : new Intl.DateTimeFormat('en', options).format(date);
}

function StatCard({ label, value, detail, tone, icon }) {
  return <article className="flex min-h-24 items-start gap-3 rounded-xl border border-border bg-surface p-4">
    <span className={`grid size-7 shrink-0 place-items-center rounded-lg ${tone}`}><Icon name={icon} size={19}/></span>
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <strong className="text-2xl font-semibold leading-none tracking-tight text-heading">{value}</strong>
      <small className="text-xs text-subtle">{detail}</small>
    </div>
  </article>;
}

export default function DashboardOverview() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [overview, setOverview] = useState(null);
  const [upcoming, setUpcoming] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [solvingId, setSolvingId] = useState(null);

  const loadData = async (cancelled = false) => {
    try {
      const token = await getToken();
      const results = await Promise.allSettled([api.getOverview(token, true), api.getUpcoming(7, token)]);
      if (cancelled) return;
      if (results[0].status === 'fulfilled') setOverview(results[0].value);
      else if (!overview) setError(results[0].reason?.message || 'Your overview could not be loaded.');
      if (results[1].status === 'fulfilled') setUpcoming(results[1].value);
    } catch (err) {
      if (!cancelled && !overview) setError(err.message || 'Your overview could not be loaded.');
    } finally {
      if (!cancelled) setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    setError('');
    loadData(cancelled);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getToken]);

  // Real-time polling if any 4-Agent crew solver run is currently active
  const activeRuns = overview?.ai_agent_hub?.active_crew_runs || [];
  useEffect(() => {
    if (!activeRuns.length) return undefined;
    const interval = setInterval(() => {
      loadData(false);
    }, 3500);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRuns.length]);

  const [turningInId, setTurningInId] = useState(null);
  const [turnInNotice, setTurnInNotice] = useState('');
  const [dismissingId, setDismissingId] = useState(null);
  const [showClearTimetable, setShowClearTimetable] = useState(false);
  const [clearingTimetable, setClearingTimetable] = useState(false);
  const [timetableNotice, setTimetableNotice] = useState('');

  const handleDashboardClearTimetable = async () => {
    setClearingTimetable(true);
    setError('');
    setTimetableNotice('');
    try {
      const token = await getToken();
      await api.clearDashboardTimetable(token);
      setTimetableNotice('Timetable schedule cleared successfully.');
      setShowClearTimetable(false);
      await loadData(false);
    } catch (err) {
      setError(err.message || 'Could not clear timetable.');
    } finally {
      setClearingTimetable(false);
    }
  };

  const handleDismissRun = async (assignmentId) => {
    if (dismissingId) return;
    setDismissingId(assignmentId);
    try {
      const token = await getToken();
      await api.dismissActiveCrewRun(assignmentId, token);
      await loadData(false);
    } catch (err) {
      console.warn('Failed to dismiss run:', err);
    } finally {
      setDismissingId(null);
    }
  };

  const handleDashboardQuickTurnIn = async (assignmentId) => {
    if (turningInId) return;
    setTurningInId(assignmentId);
    setError('');
    setTurnInNotice('');
    try {
      const token = await getToken();
      const res = await api.quickTurnInAssignment(assignmentId, token);
      setTurnInNotice(res.message || 'Successfully turned in Google Doc and ZIP deliverables to Google Classroom!');
      await loadData(false);
    } catch (err) {
      setError(err.message || 'Quick turn-in failed. Please try again.');
    } finally {
      setTurningInId(null);
    }
  };

  const handleQuickSolve = async (assignmentId) => {
    if (solvingId) return;
    setSolvingId(assignmentId);
    try {
      const token = await getToken();
      await api.generateAssignmentSolution(assignmentId, { create_google_doc: true }, token);
      await loadData(false);
    } catch (err) {
      setError(err.message || 'Could not start the 4-agent solver.');
    } finally {
      setSolvingId(null);
    }
  };

  const events = useMemo(() => {
    const rows = [
      ...(upcoming?.assignments || []).map((item) => ({ ...item, kind: 'Assignment', href: '/dashboard/assignments', date: item.due_at, tone: 'bg-info-bg text-info' })),
      ...(upcoming?.classes || []).map((item) => ({ ...item, kind: 'Class', title: item.subject, href: '/dashboard/timetable', date: item.date, tone: 'bg-violet-light text-violet' })),
      ...(upcoming?.exams || []).map((item) => ({ ...item, kind: 'Exam', href: '/dashboard/timetable', date: item.date, tone: 'bg-violet-light text-violet' })),

    ];
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    return rows
      .filter((item) => {
        const date = new Date(item.date);
        return !Number.isNaN(date.getTime()) && date >= start && date < end;
      })
      .sort((a, b) => new Date(a.date) - new Date(b.date))
      .slice(0, 5);
  }, [upcoming]);

  const summary = overview?.academic_summary;
  const firstName = user?.firstName || user?.username || 'there';
  const today = new Intl.DateTimeFormat('en', { weekday: 'long', month: 'long', day: 'numeric' }).format(new Date());
  const assignmentCount = overview?.assignments?.pending ?? 0;
  const agentHub = overview?.ai_agent_hub || { active_crew_runs: [], ready_for_review: [], total_solved: 0, active_count: 0 };
  const readySolutions = agentHub.ready_for_review || [];

  return <div className="mx-auto max-w-6xl">
    <section className="mb-7 flex flex-col items-start justify-between gap-6 sm:flex-row sm:items-end">
      <div>
        <p className="text-xs font-semibold uppercase leading-snug tracking-wider text-label">{today}</p>
        <h1 className="mt-2 text-3xl font-semibold leading-tight tracking-tight text-ink">Good to see you, {firstName}.</h1>
        <p className="mt-2 text-xs text-muted">Here’s what’s happening across your semester.</p>
      </div>
      <Link className="inline-flex min-h-9 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-violet bg-violet px-3.5 text-xs font-semibold text-white shadow-card transition hover:-translate-y-px hover:bg-violet-dark" href="/dashboard/assignments">
        <Icon name="listChecks" size={15}/> Review assignments
      </Link>
    </section>

    {error && <div className="mb-5 flex items-start gap-2.5 rounded-lg border border-rose-border bg-rose-bg p-3 text-xs text-rose" role="alert">
      <Icon name="alert" size={17}/>
      <div><strong className="font-semibold">We couldn’t load your latest overview.</strong><p className="mt-0.5 text-rose/80">{error}</p></div>
    </div>}

    {timetableNotice && (
      <div className="mb-5 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs font-semibold text-emerald-800">
        <div className="flex items-center gap-2">
          <Icon name="checkCircle" size={14} />
          <span>{timetableNotice}</span>
        </div>
        <button type="button" onClick={() => setTimetableNotice('')} className="text-emerald-700 hover:text-emerald-900">
          <Icon name="close" size={12} />
        </button>
      </div>
    )}

    <section className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Academic overview">
      <StatCard label="Active courses" value={loading ? '—' : overview?.courses_count ?? 0} detail="Across your semester" tone="bg-violet-light text-violet" icon="book" />
      <StatCard label="Open assignments" value={loading ? '—' : assignmentCount} detail="Still in your coursework queue" tone="bg-warning-bg text-warning" icon="clock" />
      <StatCard label="AI Solved Solutions" value={loading ? '—' : agentHub.total_solved} detail={agentHub.active_count > 0 ? `${agentHub.active_count} generating now` : "Verified deliverables ready"} tone="bg-success-bg text-success" icon="sparkles" />
      <StatCard label="Attendance" value={loading ? '—' : `${Number(overview?.average_attendance || 0).toFixed(0)}%`} detail="Average across courses" tone="bg-info-bg text-info" icon="chart" />
    </section>

    {/* 4-Agent CrewAI Live Hub Section */}
    {(activeRuns.length > 0 || readySolutions.length > 0) && (
      <section
        className="rounded-xl border border-violet/20 bg-gradient-to-br from-surface to-violet-light/40 p-5 sm:p-6"
      >
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="mb-1.5 inline-flex items-center gap-1.5 rounded-full bg-violet-light px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-dark">
              <Icon name="sparkles" size={13} />
              <span>4-Agent Autonomous Solver Hub</span>
            </div>
            <h2 className="text-base font-semibold text-ink">Live Assignment Solving Pipeline</h2>
          </div>
          <Link href="/dashboard/assignments" className="inline-flex items-center gap-1 text-xs font-semibold text-violet-muted hover:text-violet-dark">
            Open Studio <Icon name="arrowUpRight" size={13} />
          </Link>
        </header>

        <div className="flex flex-col gap-3">
          {activeRuns.map((run) => {
            const hasAgents = Array.isArray(run.crew_progress?.agents) && run.crew_progress.agents.length > 0;
            const hasSteps = run.crew_progress && typeof run.crew_progress.current_step === 'number' && typeof run.crew_progress.total_steps === 'number';
            const roleTitles = {
              planner: '1. Planner',
              theory_research: '2. Theory & Research',
              coder_diagram: '3. Coder & Diagram',
              reporter_fixer: '4. Reporter & Fixer',
            };

            return (
              <div key={run.assignment_id} className="rounded-lg border border-line bg-surface p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <strong className="block text-sm font-semibold text-ink">{run.title}</strong>
                    <small className="text-xs text-muted">{run.course_name} · Due {formatDate(run.due_at)}</small>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-bg px-2.5 py-1 text-xs font-semibold text-warning">
                      <span className="size-1.5 animate-spin rounded-full border-2 border-line border-t-violet" />
                      <span>{hasSteps ? (run.crew_progress.step_title || 'Solving in Progress') : 'Solving in Progress'}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDismissRun(run.assignment_id)}
                      disabled={dismissingId === run.assignment_id}
                      className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-muted hover:bg-surface-secondary hover:text-ink disabled:opacity-50"
                      title="Dismiss run from dashboard"
                    >
                      {dismissingId === run.assignment_id ? (
                        <span className="size-2.5 animate-spin rounded-full border-2 border-line border-t-ink" />
                      ) : (
                        <Icon name="close" size={12} />
                      )}
                      <span>Dismiss</span>
                    </button>
                  </div>
                </div>

                {hasAgents ? (
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    {run.crew_progress.agents.map((ag) => {
                      const isDone = ag.status === 'completed';
                      const isRunning = ag.status === 'running';
                      return (
                        <div
                          key={ag.id}
                          className={`rounded-lg border px-3 py-2 ${isDone ? 'border-brand-border bg-brand-bg' : isRunning ? 'border-violet/30 bg-violet-light/50' : 'border-line bg-paper'}`}
                        >
                          <div className={`flex items-center gap-1.5 text-xs font-semibold ${isDone ? 'text-brand-hover' : isRunning ? 'text-violet-dark' : 'text-muted'}`}>
                            {isDone ? <Icon name="checkCircle" size={12} /> : isRunning ? <span className="size-1.5 animate-spin rounded-full border-2 border-line border-t-violet" /> : <span className="size-1.5 rounded-full bg-subtle" />}
                            <span>{roleTitles[ag.id] || ag.id}</span>
                          </div>
                          <small className="mt-1 block text-xs capitalize text-muted">
                            {isDone ? 'Completed' : isRunning ? 'Working…' : 'Queued'}
                          </small>
                        </div>
                      );
                    })}
                  </div>
                ) : hasSteps ? (
                  <div className="flex flex-col gap-2 rounded-lg border border-line bg-paper p-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-ink">Step {run.crew_progress.current_step} of {run.crew_progress.total_steps}: {run.crew_progress.step_title}</span>
                      <span className="text-muted">{Math.round((run.crew_progress.current_step / run.crew_progress.total_steps) * 100)}%</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full border border-line bg-surface">
                      <div
                        className="h-full rounded-full bg-violet transition-all duration-500"
                        style={{ width: `${Math.min(100, (run.crew_progress.current_step / run.crew_progress.total_steps) * 100)}%` }}
                      />
                    </div>
                    {run.crew_progress.detail && (
                      <p className="text-xs text-muted truncate">{run.crew_progress.detail}</p>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-lg border border-line bg-paper p-3 text-xs text-muted">
                    <span className="size-2 animate-spin rounded-full border-2 border-line border-t-violet" />
                    <span>Autonomous solver pipeline active. Initializing context and tools...</span>
                  </div>
                )}
              </div>
            );
          })}

          {turnInNotice && (
            <div className="mb-2 flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs font-semibold text-emerald-800">
              <div className="flex items-center gap-2">
                <Icon name="checkCircle" size={14} />
                <span>{turnInNotice}</span>
              </div>
              <button type="button" onClick={() => setTurnInNotice('')} className="text-emerald-700 hover:text-emerald-900">
                <Icon name="close" size={12} />
              </button>
            </div>
          )}

          {readySolutions.length > 0 && activeRuns.length === 0 && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {readySolutions.slice(0, 3).map((sol) => (
                <div key={sol.assignment_id} className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-brand-border bg-surface p-3">
                  <div className="min-w-0">
                    <strong className="block truncate text-sm font-semibold text-ink">{sol.title}</strong>
                    <small className="text-xs font-semibold text-brand-hover">✓ Verified solution ready</small>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {sol.google_doc_url && (
                      <a href={sol.google_doc_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-7 items-center rounded-md border border-border-input bg-surface px-2 text-xs font-semibold text-nav hover:bg-surface-secondary">
                        Doc
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDashboardQuickTurnIn(sol.assignment_id)}
                      disabled={turningInId === sol.assignment_id}
                      className="inline-flex min-h-7 items-center gap-1 rounded-md bg-emerald-600 px-2 text-xs font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-50"
                      title="Quick Turn In (Doc + ZIP) to Google Classroom"
                    >
                      <Icon name="upload" size={11} />
                      <span>{turningInId === sol.assignment_id ? 'Turning in…' : '⚡ Turn In'}</span>
                    </button>
                    <Link href={`/dashboard/assignments/${sol.assignment_id}`} className="inline-flex min-h-7 items-center rounded-md border border-violet bg-violet px-2 text-xs font-semibold text-white hover:bg-violet-dark">
                      Review
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    )}

    <section className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(265px,.9fr)]">
      <article className="flex min-h-80 flex-col rounded-xl border border-border bg-surface">
        <header className="flex items-center justify-between gap-3 border-b border-border-light px-5 pb-4 pt-5">
          <div>
            <p className="text-xs font-semibold uppercase leading-snug tracking-wider text-label">The next 7 days</p>
            <h2 className="mt-1 text-sm font-semibold tracking-tight text-heading">Coming up</h2>
          </div>
          <Link className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-violet-muted hover:text-violet-dark" href="/dashboard/assignments">View assignments <Icon name="arrowUpRight" size={14}/></Link>
        </header>
        {loading ? <div className="flex flex-1 items-center justify-center gap-2 text-xs text-muted"><span className="size-2 animate-spin rounded-full border-2 border-line border-t-violet"/> Gathering your deadlines…</div> : events.length ? <div className="px-5 pt-px">{events.map((event, index) => {
          const isPendingAssignment = event.kind === 'Assignment' && event.status !== 'ready_for_review' && event.status !== 'completed';
          return (
            <div className="flex min-h-14 items-center justify-between gap-3 border-b border-border-light text-inherit last:border-0" key={`${event.kind}-${event.id || event.title}-${index}`}>
              <Link href={event.href} className="flex flex-1 items-center gap-2.5 text-inherit no-underline">
                <span className={`grid size-6 shrink-0 place-items-center rounded-lg ${event.tone}`}><span className="size-1.5 rounded-full bg-current"/></span>
                <span className="flex min-w-0 flex-1 flex-col gap-1"><span className="truncate text-xs font-semibold text-body transition-colors hover:text-violet">{event.title || 'Untitled item'}</span><span className="text-xs text-subtle">{event.kind}{event.room ? ` · ${event.room}` : ''}</span></span>
              </Link>
              <div className="flex items-center gap-2.5">
                <span className="whitespace-nowrap text-xs text-muted">{formatDate(event.date)}</span>
                {isPendingAssignment && event.id && (
                  <button
                    type="button"
                    onClick={() => handleQuickSolve(event.id)}
                    disabled={solvingId === event.id}
                    className="inline-flex min-h-6 items-center gap-1 rounded-md border border-violet bg-violet px-2 text-xs font-semibold text-white hover:bg-violet-dark disabled:opacity-50"
                    title="Solve with 4-Agent Crew"
                  >
                    {solvingId === event.id ? 'Starting…' : <><Icon name="sparkles" size={11}/> Solve</>}
                  </button>
                )}
                <Link href={event.href}><Icon name="arrowUpRight" size={14} className="text-subtle" /></Link>
              </div>
            </div>
          );
        })}</div> : <div className="flex flex-1 flex-col items-center justify-center p-6 text-center"><span className="mb-2.5 grid size-9 place-items-center rounded-lg bg-success-light text-success"><Icon name="checkCircle" size={21}/></span><strong className="text-xs font-semibold text-body">You’re all caught up</strong><p className="my-1 max-w-60 text-xs leading-relaxed text-subtle">No deadlines or assessments due in the next 7 days.</p><Link className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-violet-muted hover:text-violet-dark" href="/dashboard/assignments">Open assignments <Icon name="arrowUpRight" size={14}/></Link></div>}
        {!loading && events.length > 0 && <footer className="mt-auto flex items-center gap-1.5 border-t border-border-light px-5 py-3 text-xs text-subtle"><span className="size-1.5 rounded-full bg-success"/> Updated from your academic workspace</footer>}
      </article>

      <aside className="flex flex-col gap-3.5">
        <article className="min-h-44 flex flex-col rounded-xl border border-border bg-surface">
          <header className="flex items-center justify-between gap-3 border-b border-border-light px-4 pb-3 pt-4">
            <div><p className="text-xs font-semibold uppercase leading-snug tracking-wider text-label">Your progress</p><h2 className="mt-1 text-sm font-semibold tracking-tight text-heading">Academic standing</h2></div>
            <span className="grid size-6 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="graduation" size={18}/></span>
          </header>
          {summary && (summary.cgpa || summary.sgpa) ? <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-4 pb-3 pt-4">
            <div className="flex flex-col gap-1.5"><span className="text-xs text-muted">Cumulative GPA</span><strong className="text-2xl font-semibold tracking-tight text-violet">{summary.cgpa ? Number(summary.cgpa).toFixed(2) : '—'}<small className="text-xs font-medium tracking-normal text-violet/60"> / 4.00</small></strong></div>
            <div className="h-9 w-px bg-border"/><div className="flex flex-col gap-1.5"><span className="text-xs text-muted">Latest term</span><strong className="text-lg font-semibold text-body">{summary.sgpa ? Number(summary.sgpa).toFixed(2) : '—'}</strong></div>
            {summary.semester_name && <p className="col-span-full border-t border-border-light pt-2.5 text-xs text-subtle">{summary.semester_name}</p>}
          </div> : <div className="relative p-4"><strong className="text-xs font-semibold text-body">Make progress visible</strong><p className="mt-1.5 max-w-[210px] text-xs leading-relaxed text-muted">Connect your university portal to see GPA and semester results here.</p><span className="absolute bottom-4 right-4 text-violet/40"><Icon name="globe" size={17}/></span></div>}
        </article>
        <article className="relative min-h-[134px] overflow-hidden rounded-xl bg-violet-light p-4 before:absolute before:right-[-45px] before:top-[-73px] before:size-[150px] before:rounded-full before:border before:border-violet/20 after:absolute after:right-[-12px] after:top-[-100px] after:size-[150px] after:rounded-full after:border after:border-violet/20">
          <span className="relative text-xs font-semibold uppercase tracking-wider text-violet-muted">4-Agent Autonomous Workflow</span>
          <h3 className="relative mt-1.5 text-[15px] font-semibold tracking-tight text-ink">Planner · Theory · Coder · Fixer</h3>
          <p className="relative mt-1 max-w-[220px] text-xs leading-relaxed text-muted">Every assignment is verified with code execution, diagrams, and editable Google Docs.</p>
          <Link className="relative mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-violet" href="/dashboard/assignments">Open assignments studio <Icon name="arrowUpRight" size={14}/></Link>
        </article>
      </aside>
    </section>

    <section className="mt-6">
      <div className="mb-3"><p className="text-xs font-semibold uppercase leading-snug tracking-wider text-label">Jump back in</p><h2 className="mt-1 text-sm font-semibold tracking-tight text-heading">Your workspace</h2></div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="flex min-h-16 items-center justify-between gap-2.5 rounded-lg border border-border bg-surface p-3 transition hover:border-violet-light">
          <Link href="/dashboard/timetable" className="flex min-w-0 flex-1 items-center gap-2.5 text-inherit no-underline">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="calendar" size={18}/></span>
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <strong className="text-xs font-semibold text-body">Weekly Timetable</strong>
              <small className="truncate text-xs text-subtle">Routine, venues & timings</small>
            </span>
          </Link>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setShowClearTimetable(true)}
              disabled={clearingTimetable}
              className="inline-flex min-h-7 items-center gap-1 rounded-md border border-rose-200 bg-rose-50/60 px-2 text-xs font-semibold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
              title="Clear all classes from timetable"
            >
              <Icon name="trash" size={12} />
              <span>Clear</span>
            </button>
            <Link href="/dashboard/timetable" className="text-subtle hover:text-body">
              <Icon name="arrowUpRight" size={15}/>
            </Link>
          </div>
        </div>
        <Link href="/dashboard/attendance" className="flex min-h-16 items-center gap-2.5 rounded-lg border border-border bg-surface p-3 text-inherit transition hover:-translate-y-px hover:border-violet-light"><span className="grid size-7 shrink-0 place-items-center rounded-lg bg-success-bg text-success"><Icon name="clipboardCheck" size={18}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="text-xs font-semibold text-body">Attendance Tracker</strong><small className="truncate text-xs text-subtle">75% policy eligibility & recovery math</small></span><Icon name="arrowUpRight" size={15}/></Link>
        <Link href="/dashboard/assignments" className="flex min-h-16 items-center gap-2.5 rounded-lg border border-border bg-surface p-3 text-inherit transition hover:-translate-y-px hover:border-violet-light"><span className="grid size-7 shrink-0 place-items-center rounded-lg bg-info-bg text-info"><Icon name="listChecks" size={18}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="text-xs font-semibold text-body">Assignments Studio</strong><small className="truncate text-xs text-subtle">AI solving, code execution & turn-in</small></span><Icon name="arrowUpRight" size={15}/></Link>
      </div>
    </section>

    {/* Clear Timetable Confirmation Modal on Dashboard */}
    {showClearTimetable && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
        <div className="bg-surface rounded-2xl max-w-sm w-full p-6 shadow-xl border border-border animate-in fade-in zoom-in-95 duration-150">
          <div className="flex items-center gap-3 text-rose mb-3">
            <span className="grid size-9 place-items-center rounded-xl bg-rose-bg text-rose"><Icon name="alert" size={18} /></span>
            <h3 className="font-bold text-heading text-sm">Clear Weekly Timetable?</h3>
          </div>
          <p className="text-xs text-muted leading-relaxed mb-5">
            This will wipe your timetable routine and upcoming class schedules. You can import an updated timetable or sync from your portal anytime.
          </p>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowClearTimetable(false)}
              className="px-3.5 py-2 text-xs font-medium text-muted hover:text-body"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={clearingTimetable}
              onClick={handleDashboardClearTimetable}
              className="px-4 py-2 text-xs font-semibold rounded-lg bg-rose text-white hover:bg-rose-dark disabled:opacity-50 transition"
            >
              {clearingTimetable ? 'Clearing…' : 'Yes, Clear Timetable'}
            </button>
          </div>
        </div>
      </div>
    )}
  </div>;
}
