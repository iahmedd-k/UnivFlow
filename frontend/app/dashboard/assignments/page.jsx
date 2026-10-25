'use client';

import { useEffect, useMemo, useState, useCallback } from 'react';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import AssignmentCard from './AssignmentCard';

const statusFilters = [
  { id: 'all', label: 'All Work' },
  { id: 'open', label: 'Upcoming' },
  { id: 'missing', label: 'Overdue' },
  { id: 'assignments', label: 'Assignments & Labs' },
  { id: 'quizzes', label: 'Quizzes' },
  { id: 'submitted', label: 'Submitted' },
];

export default function AssignmentsPage() {
  const { getToken, userId } = useAuth();
  const cacheKey = `uniflow_cached_assignments_${userId || 'default'}`;

  const [assignments, setAssignments] = useState(() => {
    if (typeof window !== 'undefined') {
      try {
        const cached = localStorage.getItem('uniflow_cached_assignments');
        if (cached) return JSON.parse(cached);
      } catch (_) {}
    }
    return [];
  });
  const [loading, setLoading] = useState(() => {
    if (typeof window !== 'undefined') {
      try {
        const cached = localStorage.getItem('uniflow_cached_assignments');
        if (cached && JSON.parse(cached).length > 0) return false;
      } catch (_) {}
    }
    return true;
  });
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [selectedCourse, setSelectedCourse] = useState('all');
  const [sortBy, setSortBy] = useState('due_asc');
  const [query, setQuery] = useState('');
  const [error, setError] = useState(null);
  const [activeAssignment, setActiveAssignment] = useState(null);
  const [initialModalTab, setInitialModalTab] = useState('overview');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'

  const loadAssignments = useCallback(async (isManualRefresh = false) => {
    if (isManualRefresh) setRefreshing(true);
    else if (!assignments.length) setLoading(true);
    try {
      const token = getToken ? await getToken() : null;
      const data = await api.getAssignments(filter === 'all' ? null : filter, token, null, {
        noCache: isManualRefresh,
      });
      const list = Array.isArray(data) ? data : [];
      setAssignments(list);
      if (filter === 'all' && list.length > 0 && typeof window !== 'undefined') {
        try {
          localStorage.setItem(cacheKey, JSON.stringify(list));
        } catch (_) {}
      }
      setError(null);
    } catch (e) {
      setError(e.message || 'Unable to connect to the assignment service.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [getToken, filter, assignments.length, cacheKey]);

  const handleSyncClassroom = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const token = await getToken();
      // Directly sync from Google Classroom API - returns latest live data immediately
      const result = await api.triggerSync(null, token);
      api.clearCache();
      
      if (result?.assignments && Array.isArray(result.assignments)) {
        // Instantly display the fresh GCR data on the frontend
        setAssignments(result.assignments);
        if (typeof window !== 'undefined') {
          try {
            localStorage.setItem(cacheKey, JSON.stringify(result.assignments));
          } catch (_) {}
        }
      } else {
        await loadAssignments(true);
      }

      if (result?.status === 'reconnect_required') {
        setError(result.message || 'Google Classroom needs to be reconnected to sync coursework.');
      }
    } catch (err) {
      const msg = err.message || '';
      if (msg.includes('invalid_grant') || msg.includes('expired or revoked')) {
        setError('Your Google Classroom token has expired. Please reconnect your Google account.');
      } else {
        setError(msg || 'Could not sync from Google Classroom.');
      }
    } finally {
      setRefreshing(false);
    }
  };

  const handleConnectGoogle = async () => {
    try {
      const token = await getToken();
      const res = await api.getGoogleAuthUrl(token, '/dashboard/assignments');
      if (res?.auth_url) window.location.assign(res.auth_url);
    } catch (e) {
      setError(e.message || 'Could not initiate Google connection.');
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => loadAssignments(), 0);
    return () => clearTimeout(timer);
  }, [loadAssignments]);

  const availableCourses = useMemo(() => {
    const courses = new Set();
    assignments.forEach((a) => {
      if (a.course_name) courses.add(a.course_name);
    });
    return Array.from(courses).sort();
  }, [assignments]);

  const stats = useMemo(() => {
    const total = assignments.length;
    const now = new Date();
    let overdue = 0;
    let submitted = 0;
    let upcoming = 0;
    let quizzes = 0;

    assignments.forEach((a) => {
      const isSub = a.submission_state === 'TURNED_IN' || a.submission_state === 'RETURNED' || a.status === 'APPROVED';
      const isDue = a.due_at ? new Date(a.due_at) : null;
      if (a.is_quiz) quizzes++;
      if (isSub) {
        submitted++;
      } else if (isDue && isDue < now) {
        overdue++;
      } else {
        upcoming++;
      }
    });

    const completionRate = total > 0 ? Math.round((submitted / total) * 100) : 0;
    return { total, overdue, submitted, upcoming, quizzes, completionRate };
  }, [assignments]);

  const visibleAssignments = useMemo(() => {
    let list = [...assignments];

    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (a) =>
          a.title?.toLowerCase().includes(q) ||
          a.course_name?.toLowerCase().includes(q) ||
          a.description?.toLowerCase().includes(q)
      );
    }

    if (selectedCourse !== 'all') {
      list = list.filter((a) => a.course_name === selectedCourse);
    }

    list.sort((a, b) => {
      if (sortBy === 'due_asc') {
        if (!a.due_at) return 1;
        if (!b.due_at) return -1;
        return new Date(a.due_at) - new Date(b.due_at);
      }
      if (sortBy === 'due_desc') {
        if (!a.due_at) return 1;
        if (!b.due_at) return -1;
        return new Date(b.due_at) - new Date(a.due_at);
      }
      if (sortBy === 'title') {
        return (a.title || '').localeCompare(b.title || '');
      }
      if (sortBy === 'course') {
        return (a.course_name || '').localeCompare(b.course_name || '');
      }
      return 0;
    });

    return list;
  }, [assignments, query, selectedCourse, sortBy]);

  const handleTurnIn = async (assignmentId, templateId, files, token) => {
    await api.turnInAssignment(assignmentId, { template_id: templateId, files }, token);
    await loadAssignments(true);
  };

  const openModalWithTab = (assignment, tab = 'overview') => {
    setInitialModalTab(tab);
    setActiveAssignment(assignment);
  };

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-5 pb-12 text-ink">
      {/* Header */}
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-label">COURSEWORK & DEADLINES</p>
          <h1 className="my-1 text-2xl font-semibold tracking-tight text-ink">
            Assignments
          </h1>
          <p className="text-xs text-muted">
            Review deadlines, query your AI academic tutor, test solutions, and turn in to Google Classroom.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/dashboard/templates" className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-semibold text-nav no-underline hover:bg-surface-secondary">
            <Icon name="files" size={15}/>
            <span>Cover Templates</span>
          </Link>
          <button
            type="button"
            onClick={handleSyncClassroom}
            disabled={refreshing || loading}
            className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border border-violet bg-violet px-3 text-xs font-semibold text-white hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-55"
            aria-label="Refresh assignments"
          >
            {refreshing ? 'Syncing…' : <><Icon name="refresh" size={14}/> Sync Classroom</>}
          </button>
        </div>
      </header>

      {/* 4 Summary Stat Cards matching Uniflow Overview Design */}
      <section className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Coursework summary">
        <article className="flex min-h-24 items-start gap-3 rounded-xl border border-border bg-surface p-4">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="clipboard" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted">Total coursework</span>
            <strong className="text-2xl font-semibold leading-none tracking-tight text-heading">{loading ? '—' : stats.total}</strong>
            <small className="text-xs text-subtle">{stats.quizzes} quizzes included</small>
          </div>
        </article>

        <article className="flex min-h-24 items-start gap-3 rounded-xl border border-border bg-surface p-4">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-warning-bg text-warning"><Icon name="clock" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted">Upcoming & open</span>
            <strong className="text-2xl font-semibold leading-none tracking-tight text-warning">{loading ? '—' : stats.upcoming}</strong>
            <small className="text-xs text-subtle">Pending submissions</small>
          </div>
        </article>

        <article className="flex min-h-24 items-start gap-3 rounded-xl border border-border bg-surface p-4">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-danger-bg text-danger"><Icon name="alert" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted">Past deadline</span>
            <strong className="text-2xl font-semibold leading-none tracking-tight text-danger">{loading ? '—' : stats.overdue}</strong>
            <small className="text-xs text-subtle">{stats.overdue > 0 ? 'Requires attention' : 'All clear!'}</small>
          </div>
        </article>

        <article className="flex min-h-24 items-start gap-3 rounded-xl border border-border bg-surface p-4">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-success-bg text-success"><Icon name="checkCircle" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-muted">Submitted & done</span>
            <strong className="text-2xl font-semibold leading-none tracking-tight text-success">{loading ? '—' : stats.submitted}</strong>
            <small className="text-xs text-subtle">{stats.completionRate}% completion rate</small>
          </div>
        </article>
      </section>

      {/* Filter and Search Bar Container */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {/* Top Search Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light px-4 py-3.5">
          {/* Search Input */}
          <div className="relative min-w-[220px] flex-1">
            <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-subtle">
              <Icon name="search" size={15}/>
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search assignments or courses…"
              className="h-9 w-full rounded-lg border border-border-input bg-surface-tertiary pl-8 pr-7 text-xs text-heading outline-none focus-visible:ring-2 focus-visible:ring-violet/20"
              aria-label="Search assignments"
            />
            {query && (
              <button type="button" onClick={() => setQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer border-0 bg-transparent p-1 text-xs text-subtle">
                <Icon name="close" size={14}/>
              </button>
            )}
          </div>

          {/* Selectors and View Mode Switcher */}
          <div className="flex flex-wrap items-center gap-2">
            {availableCourses.length > 0 && (
              <select
                value={selectedCourse}
                onChange={(e) => setSelectedCourse(e.target.value)}
                className="h-9 cursor-pointer rounded-lg border border-border-input bg-surface px-2.5 text-xs font-medium text-nav outline-none"
                aria-label="Filter by course"
              >
                <option value="all">All Courses ({availableCourses.length})</option>
                {availableCourses.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            )}

            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="h-9 cursor-pointer rounded-lg border border-border-input bg-surface px-2.5 text-xs font-medium text-nav outline-none"
              aria-label="Sort assignments"
            >
              <option value="due_asc">Deadline: Earliest first</option>
              <option value="due_desc">Deadline: Latest first</option>
              <option value="title">Alphabetical (A-Z)</option>
              <option value="course">Course Name</option>
            </select>

            {/* View Mode Toggle */}
            <div className="inline-flex rounded-lg border border-border-input bg-surface-secondary p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('grid')}
                className={`cursor-pointer rounded-md border-0 px-2 py-1 text-xs font-semibold ${viewMode === 'grid' ? 'bg-surface text-violet shadow-sm' : 'bg-transparent text-muted'}`}
                title="Grid View"
              >
                <Icon name="dashboard" size={13}/> Grid
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={`cursor-pointer rounded-md border-0 px-2 py-1 text-xs font-semibold ${viewMode === 'list' ? 'bg-surface text-violet shadow-sm' : 'bg-transparent text-muted'}`}
                title="List View"
              >
                <Icon name="listChecks" size={13}/> List
              </button>
            </div>
          </div>
        </div>

        {/* Status Tabs Strip */}
        <nav className="flex gap-1.5 overflow-x-auto bg-surface px-4 py-3" aria-label="Filter assignments">
          {statusFilters.map((item) => {
            const isActive = filter === item.id;
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => setFilter(item.id)}
                aria-pressed={isActive}
                className={`shrink-0 cursor-pointer whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs ${isActive ? 'border-violet-light bg-violet-light font-semibold text-violet' : 'border-transparent bg-transparent text-nav'}`}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Error Callout */}
      {error && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-xs text-rose" role="alert">
          <div>
            <strong className="block font-semibold">
              {error.toLowerCase().includes('reconnect') || error.toLowerCase().includes('expired')
                ? 'Google Classroom session expired'
                : 'Assignments could not be loaded'}
            </strong>
            <span className="mt-0.5 block">{error}</span>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto">
            {(error.toLowerCase().includes('reconnect') || error.toLowerCase().includes('expired') || error.toLowerCase().includes('revoked')) && (
              <button
                type="button"
                onClick={handleConnectGoogle}
                className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-md bg-rose px-3 text-xs font-semibold text-white hover:opacity-90"
              >
                Reconnect Google
              </button>
            )}
            <button
              type="button"
              onClick={() => loadAssignments(true)}
              className="inline-flex min-h-8 shrink-0 items-center justify-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-semibold text-nav hover:bg-surface-secondary"
            >
              Try again
            </button>
          </div>
        </div>
      )}

      {/* Assignments Content */}
      {loading ? (
        <div className="rounded-xl border border-border bg-surface p-6 text-center text-muted">
          <span className="mb-2 inline-block size-2 animate-spin rounded-full border-2 border-line border-t-violet" />
          <p className="m-0 text-xs">Loading your coursework…</p>
        </div>
      ) : visibleAssignments.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface">
          <div className="px-5 py-8 text-center text-xs leading-relaxed text-subtle">
            <span className="mx-auto mb-2.5 grid size-9 place-items-center rounded-lg bg-success-light text-success"><Icon name="checkCircle" size={19}/></span>
            <strong className="mb-1 block text-xs text-body">{query ? 'No matching coursework' : filter === 'all' ? 'No assignments yet' : 'Nothing in this view'}</strong>
            <p className="mx-auto max-w-sm">
              {query
                ? 'Try a different search term or clear the filter.'
                : filter === 'all'
                ? 'Coursework synced from your connected Classroom will appear here.'
                : 'There are no assignments matching this filter right now.'}
            </p>
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                className="mt-2.5 inline-flex min-h-9 cursor-pointer items-center justify-center gap-1.5 rounded-md border border-border-input bg-surface px-3 text-xs font-semibold text-nav hover:bg-surface-secondary"
              >
                Clear Search
              </button>
            )}
          </div>
        </div>
      ) : viewMode === 'grid' ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3.5">
          {visibleAssignments.map((assignment) => (
            <AssignmentCard
              key={assignment.id}
              assignment={assignment}
              viewMode="grid"
            />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <div className="flex flex-col">
            {visibleAssignments.map((assignment) => (
              <AssignmentCard
                key={assignment.id}
                assignment={assignment}
                viewMode="list"
              />
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
