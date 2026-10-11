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
  return <article className="flex min-h-[102px] items-start gap-3 rounded-[11px] border border-[#ebebf0] bg-white p-[17px_15px]">
    <span className={`grid size-[30px] shrink-0 place-items-center rounded-[9px] ${tone}`}><Icon name={icon} size={19}/></span>
    <div className="flex min-w-0 flex-col gap-1">
      <span className="text-xs text-[#858998]">{label}</span>
      <strong className="text-[22px] font-semibold leading-none tracking-[-0.7px] text-[#2c2f3c]">{value}</strong>
      <small className="text-xs text-[#aaacb7]">{detail}</small>
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
      const results = await Promise.allSettled([api.getOverview(token), api.getUpcoming(7, token)]);
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
    setLoading(true);
    setError('');
    loadData(cancelled);
    return () => { cancelled = true; };
  }, [getToken]);

  // Real-time polling if any 4-Agent crew solver run is currently active
  const activeRuns = overview?.ai_agent_hub?.active_crew_runs || [];
  useEffect(() => {
    if (!activeRuns.length) return undefined;
    const interval = setInterval(() => {
      loadData(false);
    }, 3500);
    return () => clearInterval(interval);
  }, [activeRuns.length]);

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
      ...(upcoming?.assignments || []).map((item) => ({ ...item, kind: 'Assignment', href: '/dashboard/assignments', date: item.due_at, tone: 'bg-[#ecf2ff] text-[#6685cf]' })),
      ...(upcoming?.classes || []).map((item) => ({ ...item, kind: 'Class', title: item.subject, href: '/dashboard/timetable', date: item.date, tone: 'bg-[#f1edff] text-[#7867d8]' })),
      ...(upcoming?.exams || []).map((item) => ({ ...item, kind: 'Exam', href: '/dashboard/timetable', date: item.date, tone: 'bg-[#f1edff] text-[#7867d8]' })),
      ...(upcoming?.quizzes || []).map((item) => ({ ...item, kind: 'Quiz', href: '/dashboard/timetable', date: item.date, tone: 'bg-[#fff4e7] text-[#d8944f]' })),
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

  return <div className="mx-auto max-w-[1080px]">
    <section className="mb-[27px] flex flex-col items-start justify-between gap-[22px] sm:flex-row sm:items-end">
      <div>
        <p className="text-xs font-semibold uppercase leading-[1.4] tracking-[0.11em] text-[#9195a3]" suppressHydrationWarning>{today}</p>
        <h1 className="mt-2 text-[clamp(25px,3vw,32px)] font-semibold leading-[1.2] tracking-[-1.15px] text-[#252837]">Good to see you, {firstName}.</h1>
        <p className="mt-2 text-xs text-[#858998]">Here’s what’s happening across your semester.</p>
      </div>
      <Link className="inline-flex min-h-[38px] items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-[#6555d2] bg-violet px-3.5 text-xs font-semibold text-white shadow-[0_3px_8px_#6555d921] transition hover:-translate-y-px hover:bg-[#5445c7]" href="/dashboard/assignments">
        <Icon name="listChecks" size={15}/> Review assignments
      </Link>
    </section>

    {error && <div className="mb-[19px] flex items-start gap-2.5 rounded-[9px] border border-[#f2dddd] bg-[#fff8f8] p-3 text-xs text-[#974b4b]" role="alert">
      <Icon name="alert" size={17}/>
      <div><strong className="font-semibold">We couldn’t load your latest overview.</strong><p className="mt-[3px] text-[#ad7373]">{error}</p></div>
    </div>}

    <section className="mb-5 grid grid-cols-1 gap-[13px] sm:grid-cols-2 xl:grid-cols-4" aria-label="Academic overview">
      <StatCard label="Active courses" value={loading ? '—' : overview?.courses_count ?? 0} detail="Across your semester" tone="bg-[#f0edff] text-violet" icon="book" />
      <StatCard label="Open assignments" value={loading ? '—' : assignmentCount} detail="Still in your coursework queue" tone="bg-[#fff1e9] text-[#d88752]" icon="clock" />
      <StatCard label="AI Solved Solutions" value={loading ? '—' : agentHub.total_solved} detail={agentHub.active_count > 0 ? `${agentHub.active_count} generating now` : "Verified deliverables ready"} tone="bg-[#e8f7f1] text-[#47a887]" icon="sparkles" />
      <StatCard label="Attendance" value={loading ? '—' : `${Number(overview?.average_attendance || 0).toFixed(0)}%`} detail="Average across courses" tone="bg-[#eaf2ff] text-[#5b83cf]" icon="chart" />
    </section>

    {/* 4-Agent CrewAI Live Hub Section */}
    {(activeRuns.length > 0 || readySolutions.length > 0) && (
      <section
        className="rounded-xl border border-violet/20 bg-gradient-to-br from-white to-violet-light/40 p-5 sm:p-6"
      >
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="mb-1.5 inline-flex items-center gap-1.5 rounded-full bg-violet-light px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-dark">
              <Icon name="sparkles" size={13} />
              <span>4-Agent Autonomous Solver Hub</span>
            </div>
            <h2 className="text-base font-semibold text-ink">Live Assignment Solving Pipeline</h2>
          </div>
          <Link href="/dashboard/assignments" className="inline-flex items-center gap-1 text-xs font-semibold text-[#6253cd] hover:text-[#4134a8]">
            Open Studio <Icon name="arrowUpRight" size={13} />
          </Link>
        </header>

        <div className="flex flex-col gap-3">
          {activeRuns.map((run) => {
            const agents = run.crew_progress?.agents || [
              { id: 'planner', status: 'running', summary: '' },
              { id: 'theory_research', status: 'queued', summary: '' },
              { id: 'coder_diagram', status: 'queued', summary: '' },
              { id: 'reporter_fixer', status: 'queued', summary: '' },
            ];
            const roleTitles = {
              planner: '1. Planner',
              theory_research: '2. Theory & Research',
              coder_diagram: '3. Coder & Diagram',
              reporter_fixer: '4. Reporter & Fixer',
            };

            return (
              <div key={run.assignment_id} className="rounded-lg border border-line bg-white p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <strong className="block text-sm font-semibold text-ink">{run.title}</strong>
                    <small className="text-xs text-muted">{run.course_name} · Due {formatDate(run.due_at)}</small>
                  </div>
                  <span className="inline-flex items-center gap-[5px] rounded-full bg-[#fff4e4] px-2 py-1 text-xs font-semibold text-[#a87936]">
                    <span className="size-1.5 animate-spin rounded-full border-2 border-[#e2e0f2] border-t-[#6555d7]" />
                    <span>CrewAI Solving in Progress</span>
                  </span>
                </div>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  {agents.map((ag) => {
                    const isDone = ag.status === 'completed';
                    const isRunning = ag.status === 'running';
                    return (
                      <div
                        key={ag.id}
                        className={`rounded-lg border px-3 py-2 ${isDone ? 'border-brand-border bg-brand-bg' : isRunning ? 'border-violet/30 bg-violet-light/50' : 'border-line bg-paper'}`}
                      >
                        <div className={`flex items-center gap-1.5 text-xs font-semibold ${isDone ? 'text-brand-hover' : isRunning ? 'text-violet-dark' : 'text-muted'}`}>
                          {isDone ? <Icon name="checkCircle" size={12} /> : isRunning ? <span className="size-1.5 animate-spin rounded-full border-2 border-[#e2e0f2] border-t-[#6555d7]" /> : <span className="size-1.5 rounded-full bg-[#d3d5de]" />}
                          <span>{roleTitles[ag.id] || ag.id}</span>
                        </div>
                        <small className="mt-1 block text-xs capitalize text-muted">
                          {isDone ? 'Completed' : isRunning ? 'Working…' : 'Queued'}
                        </small>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}

          {readySolutions.length > 0 && activeRuns.length === 0 && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {readySolutions.slice(0, 3).map((sol) => (
                <div key={sol.assignment_id} className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-brand-border bg-white p-3">
                  <div className="min-w-0">
                    <strong className="block truncate text-sm font-semibold text-ink">{sol.title}</strong>
                    <small className="text-xs font-semibold text-brand-hover">✓ Verified solution ready</small>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    {sol.google_doc_url && (
                      <a href={sol.google_doc_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-7 items-center rounded-md border border-[#e5e5ec] bg-white px-2 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]">
                        Doc
                      </a>
                    )}
                    <Link href="/dashboard/assignments" className="inline-flex min-h-7 items-center rounded-md border border-violet bg-violet px-[9px] text-xs font-semibold text-white hover:bg-violet-dark">
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

    <section className="grid grid-cols-1 items-stretch gap-[15px] lg:grid-cols-[minmax(0,1.55fr)_minmax(265px,.9fr)]">
      <article className="flex min-h-[317px] flex-col rounded-[11px] border border-[#ebebf0] bg-white">
        <header className="flex items-center justify-between gap-3 border-b border-[#f0f0f3] px-[19px] pb-[15px] pt-[19px]">
          <div>
            <p className="text-xs font-semibold uppercase leading-[1.4] tracking-[0.11em] text-[#9195a3]">The next 7 days</p>
            <h2 className="mt-[5px] text-sm font-semibold tracking-[-0.2px] text-[#2c2f3b]">Coming up</h2>
          </div>
          <Link className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-[#6253cd] hover:text-[#4134a8]" href="/dashboard/assignments">View assignments <Icon name="arrowUpRight" size={14}/></Link>
        </header>
        {loading ? <div className="flex flex-1 items-center justify-center gap-2 text-xs text-[#9699a6]"><span className="size-[9px] animate-spin rounded-full border-2 border-[#e2e0f2] border-t-[#6555d7]"/> Gathering your deadlines…</div> : events.length ? <div className="px-[19px] pt-px">{events.map((event, index) => {
          const isPendingAssignment = event.kind === 'Assignment' && event.status !== 'ready_for_review' && event.status !== 'completed';
          return (
            <div className="flex min-h-[53px] items-center justify-between gap-[11px] border-b border-[#f2f2f5] text-inherit last:border-0" key={`${event.kind}-${event.id || event.title}-${index}`}>
              <Link href={event.href} className="flex flex-1 items-center gap-2.5 text-inherit no-underline">
                <span className={`grid size-[26px] shrink-0 place-items-center rounded-lg ${event.tone}`}><span className="size-1.5 rounded-full bg-current"/></span>
                <span className="flex min-w-0 flex-1 flex-col gap-1"><span className="truncate text-xs font-semibold text-[#454856] transition-colors hover:text-[#5d4dcc]">{event.title || 'Untitled item'}</span><span className="text-xs text-[#9b9eaa]">{event.kind}{event.room ? ` · ${event.room}` : ''}</span></span>
              </Link>
              <div className="flex items-center gap-2.5">
                <span className="whitespace-nowrap text-xs text-[#797d8c]">{formatDate(event.date)}</span>
                {isPendingAssignment && event.id && (
                  <button
                    type="button"
                    onClick={() => handleQuickSolve(event.id)}
                    disabled={solvingId === event.id}
                    className="inline-flex min-h-[26px] items-center gap-1 rounded-[5px] border border-violet bg-violet px-2 text-xs font-semibold text-white hover:bg-violet-dark disabled:opacity-50"
                    title="Solve with 4-Agent Crew"
                  >
                    {solvingId === event.id ? 'Starting…' : <><Icon name="sparkles" size={11}/> Solve</>}
                  </button>
                )}
                <Link href={event.href}><Icon name="arrowUpRight" size={14} className="text-[#b7b9c3]" /></Link>
              </div>
            </div>
          );
        })}</div> : <div className="flex flex-1 flex-col items-center justify-center p-6 text-center"><span className="mb-2.5 grid size-[35px] place-items-center rounded-[11px] bg-[#edf8f3] text-[#53aa87]"><Icon name="checkCircle" size={21}/></span><strong className="text-xs font-semibold text-[#454856]">You’re all caught up</strong><p className="my-[5px] max-w-[230px] text-xs leading-[1.55] text-[#999ca8]">No deadlines or assessments due in the next 7 days.</p><Link className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-[#6253cd] hover:text-[#4134a8]" href="/dashboard/assignments">Open assignments <Icon name="arrowUpRight" size={14}/></Link></div>}
        {!loading && events.length > 0 && <footer className="mt-auto flex items-center gap-[7px] border-t border-[#f1f1f4] px-[19px] py-3 text-xs text-[#9b9eaa]"><span className="size-1.5 rounded-full bg-[#6ac5a4]"/> Updated from your academic workspace</footer>}
      </article>

      <aside className="flex flex-col gap-3.5">
        <article className="min-h-[169px] rounded-[11px] border border-[#ebebf0] bg-white">
          <header className="flex items-center justify-between gap-3 border-b border-[#f0f0f3] px-[17px] pb-[13px] pt-4">
            <div><p className="text-xs font-semibold uppercase leading-[1.4] tracking-[0.11em] text-[#9195a3]">Your progress</p><h2 className="mt-[5px] text-sm font-semibold tracking-[-0.2px] text-[#2c2f3b]">Academic standing</h2></div>
            <span className="grid size-[25px] place-items-center rounded-lg bg-[#f2efff] text-violet"><Icon name="graduation" size={18}/></span>
          </header>
          {summary && (summary.cgpa || summary.sgpa) ? <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-[17px] pb-[13px] pt-4">
            <div className="flex flex-col gap-[7px]"><span className="text-xs text-[#9598a5]">Cumulative GPA</span><strong className="text-[25px] font-semibold tracking-[-1px] text-[#4f43b9]">{summary.cgpa ? Number(summary.cgpa).toFixed(2) : '—'}<small className="text-xs font-medium tracking-normal text-[#aaa6cf]"> / 4.00</small></strong></div>
            <div className="h-[37px] w-px bg-[#ecebf1]"/><div className="flex flex-col gap-[7px]"><span className="text-xs text-[#9598a5]">Latest term</span><strong className="text-[17px] font-semibold text-[#535665]">{summary.sgpa ? Number(summary.sgpa).toFixed(2) : '—'}</strong></div>
            {summary.semester_name && <p className="col-span-full border-t border-[#f2f2f5] pt-2.5 text-xs text-[#999ca9]">{summary.semester_name}</p>}
          </div> : <div className="relative p-4"><strong className="text-xs font-semibold text-[#555866]">Make progress visible</strong><p className="mt-1.5 max-w-[210px] text-xs leading-[1.5] text-[#9295a2]">Connect your university portal to see GPA and semester results here.</p><span className="absolute bottom-4 right-[17px] text-[#b7b0eb]"><Icon name="globe" size={17}/></span></div>}
        </article>
        <article className="relative min-h-[134px] overflow-hidden rounded-[11px] bg-[#eeecff] p-[17px] before:absolute before:right-[-45px] before:top-[-73px] before:size-[150px] before:rounded-full before:border before:border-[#d7d2f5] after:absolute after:right-[-12px] after:top-[-100px] after:size-[150px] after:rounded-full after:border after:border-[#d7d2f5]">
          <span className="relative text-xs font-semibold uppercase tracking-[0.1em] text-[#7469c6]">4-Agent Autonomous Workflow</span>
          <h3 className="relative mt-[7px] text-[15px] font-semibold tracking-[-0.3px] text-[#3d3968]">Planner · Theory · Coder · Fixer</h3>
          <p className="relative mt-[5px] max-w-[220px] text-xs leading-[1.5] text-[#7f7aab]">Every assignment is verified with code execution, diagrams, and editable Google Docs.</p>
          <Link className="relative mt-[9px] inline-flex items-center gap-1.5 text-xs font-semibold text-[#594bc0]" href="/dashboard/assignments">Open assignments studio <Icon name="arrowUpRight" size={14}/></Link>
        </article>
      </aside>
    </section>

    <section className="mt-[23px]">
      <div className="mb-3"><p className="text-xs font-semibold uppercase leading-[1.4] tracking-[0.11em] text-[#9195a3]">Jump back in</p><h2 className="mt-[5px] text-[13px] font-semibold tracking-[-0.2px] text-[#2c2f3b]">Your workspace</h2></div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <Link href="/dashboard/timetable" className="flex min-h-[66px] items-center gap-2.5 rounded-[10px] border border-[#ebebf0] bg-white p-3 text-inherit transition hover:-translate-y-px hover:border-[#d6d0fb]"><span className="grid size-[29px] shrink-0 place-items-center rounded-lg bg-[#f1edff] text-[#7463d2]"><Icon name="calendar" size={18}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="text-xs font-semibold text-[#484b59]">Weekly Timetable</strong><small className="truncate text-xs text-[#9a9daa]">Routine, classroom venues & timings</small></span><Icon name="arrowUpRight" size={15}/></Link>
      <Link href="/dashboard/attendance" className="flex min-h-[66px] items-center gap-2.5 rounded-[10px] border border-[#ebebf0] bg-white p-3 text-inherit transition hover:-translate-y-px hover:border-[#d6d0fb]"><span className="grid size-[29px] shrink-0 place-items-center rounded-lg bg-[#eaf7f1] text-[#4ca887]"><Icon name="clipboardCheck" size={18}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="text-xs font-semibold text-[#484b59]">Attendance Tracker</strong><small className="truncate text-xs text-[#9a9daa]">75% policy eligibility & recovery math</small></span><Icon name="arrowUpRight" size={15}/></Link>
      <Link href="/dashboard/assignments" className="flex min-h-[66px] items-center gap-2.5 rounded-[10px] border border-[#ebebf0] bg-white p-3 text-inherit transition hover:-translate-y-px hover:border-[#d6d0fb]"><span className="grid size-[29px] shrink-0 place-items-center rounded-lg bg-[#edf2ff] text-[#6381cf]"><Icon name="listChecks" size={18}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="text-xs font-semibold text-[#484b59]">Assignments Studio</strong><small className="truncate text-xs text-[#9a9daa]">AI solving, code execution & turn-in</small></span><Icon name="arrowUpRight" size={15}/></Link>
      </div>
    </section>
  </div>;
}
