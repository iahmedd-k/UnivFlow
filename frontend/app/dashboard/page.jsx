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
  return <article className="overview-stat"><span className={`stat-icon ${tone}`}><Icon name={icon} size={19}/></span><div className="stat-text"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>;
}

export default function DashboardOverview() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [overview, setOverview] = useState(null);
  const [upcoming, setUpcoming] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const token = await getToken();
        const results = await Promise.allSettled([api.getOverview(token), api.getUpcoming(7, token)]);
        if (cancelled) return;
        if (results[0].status === 'fulfilled') setOverview(results[0].value);
        else setError(results[0].reason?.message || 'Your overview could not be loaded.');
        if (results[1].status === 'fulfilled') setUpcoming(results[1].value);
      } catch (err) {
        if (!cancelled) setError(err.message || 'Your overview could not be loaded.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [getToken]);

  const events = useMemo(() => {
    const rows = [
      ...(upcoming?.assignments || []).map((item) => ({ ...item, kind: 'Assignment', href: '/dashboard/assignments', date: item.due_at, tone: 'event-blue' })),
      ...(upcoming?.exams || []).map((item) => ({ ...item, kind: 'Exam', href: '/dashboard/exams', date: item.date, tone: 'event-violet' })),
      ...(upcoming?.quizzes || []).map((item) => ({ ...item, kind: 'Quiz', href: '/dashboard/quizzes', date: item.date, tone: 'event-amber' })),
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

  return <div className="overview-page">
    <section className="overview-heading">
      <div><p className="eyebrow">{today}</p><h1>Good to see you, {firstName}.</h1><p className="overview-subtitle">Here’s what’s happening across your semester.</p></div>
      <Link className="primary-action" href="/dashboard/assignments"><Icon name="listChecks" size={15}/> Review assignments</Link>
    </section>

    {error && <div className="dashboard-alert" role="alert"><Icon name="alert" size={17}/><div><strong>We couldn’t load your latest overview.</strong><p>{error}</p></div></div>}

    <section className="overview-stats" aria-label="Academic overview">
      <StatCard label="Active courses" value={loading ? '—' : overview?.courses_count ?? 0} detail="Across your semester" tone="stat-lilac" icon="book" />
      <StatCard label="Open assignments" value={loading ? '—' : assignmentCount} detail="Still in your coursework queue" tone="stat-peach" icon="clock" />
      <StatCard label="Classes this week" value={loading ? '—' : upcoming?.classes?.length ?? overview?.upcoming_classes ?? 0} detail="On your academic calendar" tone="stat-mint" icon="calendar" />
      <StatCard label="Attendance" value={loading ? '—' : `${Number(overview?.average_attendance || 0).toFixed(0)}%`} detail="Average across courses" tone="stat-blue" icon="chart" />
    </section>

    <section className="overview-grid">
      <article className="surface-card upcoming-card">
        <header className="card-heading"><div><p className="eyebrow">The next 7 days</p><h2>Coming up</h2></div><Link className="text-link" href="/dashboard/assignments">View assignments <Icon name="arrowUpRight" size={14}/></Link></header>
        {loading ? <div className="list-placeholder"><span className="loading-dot"/> Gathering your deadlines…</div> : events.length ? <div className="event-list">{events.map((event, index) => <Link className="event-row" href={event.href} key={`${event.kind}-${event.id || event.title}-${index}`}>
          <span className={`event-marker ${event.tone}`}><span/></span><span className="event-info"><span className="event-title">{event.title || 'Untitled item'}</span><span className="event-meta">{event.kind}{event.room ? ` · ${event.room}` : ''}</span></span><span className="event-date">{formatDate(event.date)}</span><Icon name="arrowUpRight" size={14} className="event-chevron" />
        </Link>)}</div> : <div className="empty-upcoming"><span className="empty-calendar"><Icon name="checkCircle" size={21}/></span><strong>You’re all caught up</strong><p>No deadlines or assessments due in the next 7 days.</p><Link className="text-link" href="/dashboard/assignments">Open assignments <Icon name="arrowUpRight" size={14}/></Link></div>}
        {!loading && events.length > 0 && <footer className="upcoming-footer"><span className="status-dot"/> Updated from your academic workspace</footer>}
      </article>

      <aside className="overview-aside">
        <article className="surface-card academic-card">
          <header className="card-heading"><div><p className="eyebrow">Your progress</p><h2>Academic standing</h2></div><span className="standing-icon"><Icon name="graduation" size={18}/></span></header>
          {summary && (summary.cgpa || summary.sgpa) ? <div className="gpa-content">
            <div className="gpa-primary"><span>Cumulative GPA</span><strong>{summary.cgpa ? Number(summary.cgpa).toFixed(2) : '—'}<small> / 4.00</small></strong></div>
            <div className="gpa-divider"/><div className="gpa-secondary"><span>Latest term</span><strong>{summary.sgpa ? Number(summary.sgpa).toFixed(2) : '—'}</strong></div>
            {summary.semester_name && <p className="semester-label">{summary.semester_name}</p>}
          </div> : <div className="academic-empty"><strong>Make progress visible</strong><p>Connect your university portal to see GPA and semester results here.</p><span className="academic-empty-icon"><Icon name="globe" size={17}/></span></div>}
        </article>
        <article className="focus-card"><div className="focus-orbit orbit-one"/><div className="focus-orbit orbit-two"/><span className="focus-kicker">A little momentum</span><h3>Small steps add up.</h3><p>Pick one task and make a start. Your semester is easier when it’s all in one place.</p><Link href="/dashboard/assignments">Go to assignments <Icon name="arrowUpRight" size={14}/></Link></article>
      </aside>
    </section>

    <section className="quick-links-section"><div className="quick-links-heading"><div><p className="eyebrow">Jump back in</p><h2>Your workspace</h2></div></div><div className="quick-links">
      <Link href="/dashboard/assignments" className="quick-link"><span className="quick-icon quick-blue"><Icon name="listChecks" size={18}/></span><span><strong>Assignments</strong><small>Manage your coursework</small></span><Icon name="arrowUpRight" size={15}/></Link>
      <Link href="/dashboard/exams" className="quick-link"><span className="quick-icon quick-lilac"><Icon name="calendarCheck" size={18}/></span><span><strong>Exams & quizzes</strong><small>See what’s coming up</small></span><Icon name="arrowUpRight" size={15}/></Link>
      <Link href="/dashboard/courses" className="quick-link"><span className="quick-icon quick-mint"><Icon name="sparkles" size={18}/></span><span><strong>Study assistant</strong><small>Ask your course documents</small></span><Icon name="arrowUpRight" size={15}/></Link>
    </div></section>
  </div>;
}
