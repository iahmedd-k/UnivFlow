'use client';

import { useMemo } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

const cardClass = 'rounded-xl border border-line bg-surface p-5 shadow-2xs';
const EMPTY_ASSIGNMENTS = [];

function MetricCard({ label, value, detail, icon, href, tone = 'violet' }) {
  const tones = {
    violet: 'bg-violet-light text-violet',
    amber: 'bg-amber-bg text-amber',
    blue: 'bg-info-bg text-info',
    green: 'bg-success-bg text-success',
  };

  return (
    <article className={`${cardClass} transition-colors hover:border-violet/30`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-muted">{label}</span>
        <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${tones[tone]}`}>
          <Icon name={icon} size={17} />
        </span>
      </div>
      <div className="mt-4 flex items-baseline gap-2">
        <strong className="text-3xl font-semibold leading-none tracking-tight text-heading tabular-nums">{value}</strong>
        {detail && <span className="text-sm text-muted">{detail}</span>}
      </div>
      <Link href={href} className="mt-4 inline-flex text-sm font-medium text-violet no-underline hover:text-violet-dark">
        View details <span aria-hidden="true" className="ml-1">→</span>
      </Link>
    </article>
  );
}

function formatDate(value, options) {
  if (!value) return 'Date not set';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date not set';
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

export default function DashboardOverview() {
  const { getToken, userId } = useAuth();
  const { user } = useUser();
  const dataOwnerId = getQueryOwnerKey(userId);
  const { data: overview, isPending, isError } = useQuery({
    queryKey: ['dashboard', 'overview', dataOwnerId],
    queryFn: async ({ signal }) => api.getOverview(await api.getRequestToken(getToken), false, { signal, direct: true }),
  });

  const assignments = overview?.upcoming_assignments || EMPTY_ASSIGNMENTS;
  const todayClasses = overview?.today_classes;
  const classes = todayClasses || [];
  const attendance = overview?.average_attendance;
  const academicSummary = overview?.academic_summary;
  const dueToday = useMemo(() => assignments.filter((item) => {
    if (!item.due_at) return false;
    const due = new Date(item.due_at);
    const now = new Date();
    return due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate();
  }).length, [assignments]);
  const name = user?.firstName || user?.username;

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 pb-10 font-sans">
      <header className="flex flex-col justify-between gap-4 border-b border-border-light pb-5 sm:flex-row sm:items-end">
        <div>
          <p suppressHydrationWarning className="text-sm font-medium text-muted">{formatDate(new Date(), { weekday: 'long', month: 'long', day: 'numeric' })}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-heading sm:text-3xl">
            Welcome back{name ? `, ${name}` : ''}
          </h1>
          <p className="mt-1.5 text-sm leading-6 text-muted">Your academic work, upcoming deadlines, and today&apos;s schedule.</p>
        </div>
        <nav aria-label="Overview shortcuts" className="flex flex-wrap gap-2">
          <Link href="/dashboard/classroom" className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-surface px-3.5 text-sm font-medium text-body no-underline hover:bg-surface-secondary">
            <Icon name="school" size={16} /> Google Classroom
          </Link>
          <Link href="/dashboard/assignments" className="inline-flex h-10 items-center gap-2 rounded-lg bg-violet px-3.5 text-sm font-medium text-white no-underline hover:bg-violet-dark">
            <Icon name="listChecks" size={16} /> Assignments
          </Link>
        </nav>
      </header>

      {isError && <div role="alert" className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose">Dashboard data could not be loaded. Check your connection and try again.</div>}

      <section aria-label="Academic summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Active courses" value={overview ? (overview.courses_count ?? 0) : '—'} detail="in your workspace" icon="school" href="/dashboard/classroom" tone="blue" />
        <MetricCard label="Pending assignments" value={overview ? (overview.assignments?.pending ?? 0) : '—'} detail={overview?.assignments?.overdue ? `${overview.assignments.overdue} overdue` : 'to review'} icon="listChecks" href="/dashboard/assignments" tone="amber" />
        <MetricCard label="Classes today" value={todayClasses ? classes.length : '—'} detail="on your timetable" icon="calendar" href="/dashboard/timetable" />
        <MetricCard label="Average attendance" value={attendance != null ? `${Number(attendance).toFixed(1)}%` : '—'} detail={attendance != null ? 'recorded so far' : 'no records yet'} icon="clipboardCheck" href="/dashboard/attendance" tone="green" />
      </section>

      <section className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(300px,0.85fr)]">
        <article className={cardClass}>
          <header className="flex items-start justify-between gap-3 border-b border-border-light pb-4">
            <div>
              <p className="text-sm font-medium text-muted">Deadlines and unfinished work</p>
              <h2 className="mt-0.5 text-lg font-semibold tracking-tight text-heading">Assignments to review</h2>
            </div>
            <Link href="/dashboard/assignments" className="shrink-0 text-sm font-medium text-violet no-underline hover:text-violet-dark">All assignments →</Link>
          </header>
          {isPending ? (
            <p className="py-8 text-center text-sm text-muted">Loading assignments…</p>
          ) : assignments.length === 0 ? (
            <div className="py-9 text-center">
              <span className="mx-auto grid size-10 place-items-center rounded-full bg-success-bg text-success"><Icon name="checkCircle" size={19} /></span>
              <p className="mt-3 text-sm font-medium text-heading">No upcoming assignments</p>
                <p className="mt-1 text-sm text-muted">Assignments due soon or still awaiting completion will appear here.</p>
            </div>
          ) : (
            <ul className="divide-y divide-border-light">
              {assignments.slice(0, 6).map((item) => {
                const dueDate = item.due_at ? new Date(item.due_at) : null;
                const isOverdue = dueDate && dueDate < new Date();
                const isToday = dueDate && dueDate.toDateString() === new Date().toDateString();
                return (
                  <li key={item.id} className="flex items-center justify-between gap-4 py-4 first:pt-4 last:pb-1">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-heading">{item.title || 'Untitled assignment'}</p>
                      <p className="mt-1 text-sm text-muted">Due {formatDate(item.due_at, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</p>
                    </div>
                    <span className={`shrink-0 rounded-md px-2 py-1 text-xs font-medium ${isOverdue ? 'bg-rose-bg text-rose' : isToday ? 'bg-amber-bg text-amber' : 'bg-surface-secondary text-muted'}`}>
                      {isOverdue ? 'Overdue' : isToday ? 'Due today' : 'Upcoming'}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          {overview && assignments.length > 0 && <p className="mt-4 border-t border-border-light pt-3 text-sm text-muted">{dueToday} due today · {assignments.length} items to review</p>}
        </article>

        <article className={cardClass}>
          <header className="flex items-start justify-between gap-3 border-b border-border-light pb-4">
            <div>
              <p className="text-sm font-medium text-muted">Your timetable</p>
              <h2 className="mt-0.5 text-lg font-semibold tracking-tight text-heading">Today&apos;s classes</h2>
            </div>
            <Link href="/dashboard/timetable" className="shrink-0 text-sm font-medium text-violet no-underline hover:text-violet-dark">Timetable →</Link>
          </header>
          {isPending ? (
            <p className="py-8 text-center text-sm text-muted">Loading schedule…</p>
          ) : classes.length === 0 ? (
            <div className="py-9 text-center">
              <span className="mx-auto grid size-10 place-items-center rounded-full bg-surface-secondary text-muted"><Icon name="calendar" size={19} /></span>
              <p className="mt-3 text-sm font-medium text-heading">No classes scheduled today</p>
              <p className="mt-1 text-sm text-muted">Your synced or added classes will show up here.</p>
            </div>
          ) : (
            <ul className="divide-y divide-border-light">
              {classes.map((item, index) => (
                <li key={item.id || `${item.subject}-${index}`} className="flex gap-3 py-4 first:pt-4 last:pb-1">
                  <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="calendar" size={15} /></span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-heading">{item.subject || 'Class'}</p>
                    <p className="mt-1 text-sm text-muted tabular-nums">{item.start_time || 'Time not set'}{item.end_time ? ` – ${item.end_time}` : ''}</p>
                    {(item.room || item.teacher) && <p className="mt-1 truncate text-xs text-muted">{[item.room, item.teacher].filter(Boolean).join(' · ')}</p>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <section aria-label="Academic tools" className="grid gap-4 sm:grid-cols-2">
        <Link href="/dashboard/rag-assistant" className={`${cardClass} group flex gap-4 no-underline transition-colors hover:border-violet/30`}>
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="brain" size={19} /></span>
          <span><strong className="block text-sm font-semibold text-heading">Study Assistant</strong><span className="mt-1 block text-sm leading-5 text-muted">Ask questions about your course materials and notes.</span><span className="mt-3 block text-sm font-medium text-violet group-hover:text-violet-dark">Open Study Assistant →</span></span>
        </Link>
        <Link href="/dashboard/portal" className={`${cardClass} group flex gap-4 no-underline transition-colors hover:border-violet/30`}>
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-info-bg text-info"><Icon name="globe" size={19} /></span>
          <span><strong className="block text-sm font-semibold text-heading">Academic record</strong><span className="mt-1 block text-sm leading-5 text-muted">{academicSummary?.cgpa != null ? `CGPA ${Number(academicSummary.cgpa).toFixed(2)}${academicSummary.sgpa != null ? ` · SGPA ${Number(academicSummary.sgpa).toFixed(2)}` : ''}` : 'View grades and information synced from your university portal.'}</span><span className="mt-3 block text-sm font-medium text-violet group-hover:text-violet-dark">Open university portal →</span></span>
        </Link>
      </section>
    </main>
  );
}
