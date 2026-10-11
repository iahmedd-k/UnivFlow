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
  const { getToken } = useAuth();
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
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
    else setLoading(true);
    try {
      const token = getToken ? await getToken() : null;
      const data = await api.getAssignments(filter === 'all' ? null : filter, token, null, {
        noCache: isManualRefresh,
      });
      setAssignments(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      setError(e.message || 'Unable to connect to the assignment service.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [getToken, filter]);

  useEffect(() => {
    loadAssignments();
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
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-12 text-[#292d3a]">
      {/* Header */}
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.11em] text-[#9195a3]">COURSEWORK & DEADLINES</p>
          <h1 className="my-1 text-2xl font-semibold tracking-[-0.6px] text-[#252837]">
            Assignments
          </h1>
          <p className="text-xs text-[#858998]">
            Review deadlines, query your AI academic tutor, test solutions, and turn in to Google Classroom.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/dashboard/templates" className="inline-flex min-h-9 items-center justify-center gap-[7px] rounded-[7px] border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] no-underline hover:bg-[#f8f8fb]">
            <Icon name="files" size={15}/>
            <span>Cover Templates</span>
          </Link>
          <button
            type="button"
            onClick={() => loadAssignments(true)}
            disabled={refreshing || loading}
            className="inline-flex min-h-9 items-center justify-center gap-[7px] rounded-[7px] border border-violet bg-violet px-3 text-xs font-semibold text-white hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-55"
            aria-label="Refresh assignments"
          >
            {refreshing ? 'Syncing…' : <><Icon name="refresh" size={14}/> Sync Classroom</>}
          </button>
        </div>
      </header>

      {/* 4 Summary Stat Cards matching Uniflow Overview Design */}
      <section className="mb-5 grid grid-cols-1 gap-[13px] sm:grid-cols-2 xl:grid-cols-4" aria-label="Coursework summary">
        <article className="flex min-h-[102px] items-start gap-3 rounded-[11px] border border-[#ebebf0] bg-white p-[17px_15px]">
          <span className="grid size-[30px] shrink-0 place-items-center rounded-[9px] bg-[#f0edff] text-violet"><Icon name="clipboard" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-[#858998]">Total coursework</span>
            <strong className="text-[22px] font-semibold leading-none tracking-[-0.7px] text-[#2c2f3c]">{loading ? '—' : stats.total}</strong>
            <small className="text-xs text-[#aaacb7]">{stats.quizzes} quizzes included</small>
          </div>
        </article>

        <article className="flex min-h-[102px] items-start gap-3 rounded-[11px] border border-[#ebebf0] bg-white p-[17px_15px]">
          <span className="grid size-[30px] shrink-0 place-items-center rounded-[9px] bg-[#fff1e9] text-[#d88752]"><Icon name="clock" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-[#858998]">Upcoming & open</span>
            <strong className="text-[22px] font-semibold leading-none tracking-[-0.7px] text-[#d88752]">{loading ? '—' : stats.upcoming}</strong>
            <small className="text-xs text-[#aaacb7]">Pending submissions</small>
          </div>
        </article>

        <article className="flex min-h-[102px] items-start gap-3 rounded-[11px] border border-[#ebebf0] bg-white p-[17px_15px]">
          <span className="grid size-[30px] shrink-0 place-items-center rounded-[9px] bg-[#fff0f0] text-[#b15252]"><Icon name="alert" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-[#858998]">Past deadline</span>
            <strong className="text-[22px] font-semibold leading-none tracking-[-0.7px] text-[#b15252]">{loading ? '—' : stats.overdue}</strong>
            <small className="text-xs text-[#aaacb7]">{stats.overdue > 0 ? 'Requires attention' : 'All clear!'}</small>
          </div>
        </article>

        <article className="flex min-h-[102px] items-start gap-3 rounded-[11px] border border-[#ebebf0] bg-white p-[17px_15px]">
          <span className="grid size-[30px] shrink-0 place-items-center rounded-[9px] bg-[#e8f7f1] text-[#47a887]"><Icon name="checkCircle" size={18}/></span>
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs text-[#858998]">Submitted & done</span>
            <strong className="text-[22px] font-semibold leading-none tracking-[-0.7px] text-[#47a887]">{loading ? '—' : stats.submitted}</strong>
            <small className="text-xs text-[#aaacb7]">{stats.completionRate}% completion rate</small>
          </div>
        </article>
      </section>

      {/* Filter and Search Bar Container */}
      <div className="overflow-hidden rounded-[11px] border border-[#ebebf0] bg-white">
        {/* Top Search Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#f0f0f3] px-[18px] py-3.5">
          {/* Search Input */}
          <div className="relative min-w-[220px] flex-1">
            <span className="pointer-events-none absolute left-[11px] top-1/2 -translate-y-1/2 text-[13px] text-[#9a9dab]">
              <Icon name="search" size={15}/>
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search assignments or courses…"
              className="h-9 w-full rounded-lg border border-[#e4e4eb] bg-[#fafafd] pl-8 pr-[30px] text-xs text-[#2c2f3b] outline-none focus-visible:ring-2 focus-visible:ring-violet/20"
              aria-label="Search assignments"
            />
            {query && (
              <button type="button" onClick={() => setQuery('')} className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer border-0 bg-transparent p-1 text-xs text-[#9a9cab]">
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
                className="h-9 cursor-pointer rounded-lg border border-[#e4e4eb] bg-white px-2.5 text-xs font-medium text-slate-600 outline-none"
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
              className="h-9 cursor-pointer rounded-lg border border-[#e4e4eb] bg-white px-2.5 text-xs font-medium text-slate-600 outline-none"
              aria-label="Sort assignments"
            >
              <option value="due_asc">Deadline: Earliest first</option>
              <option value="due_desc">Deadline: Latest first</option>
              <option value="title">Alphabetical (A-Z)</option>
              <option value="course">Course Name</option>
            </select>

            {/* View Mode Toggle */}
            <div className="inline-flex rounded-lg border border-[#e4e4eb] bg-[#f8f8fb] p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('grid')}
                className={`cursor-pointer rounded-md border-0 px-2 py-1 text-xs font-semibold ${viewMode === 'grid' ? 'bg-white text-violet shadow-sm' : 'bg-transparent text-[#858998]'}`}
                title="Grid View"
              >
                <Icon name="dashboard" size={13}/> Grid
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={`cursor-pointer rounded-md border-0 px-2 py-1 text-xs font-semibold ${viewMode === 'list' ? 'bg-white text-violet shadow-sm' : 'bg-transparent text-[#858998]'}`}
                title="List View"
              >
                <Icon name="listChecks" size={13}/> List
              </button>
            </div>
          </div>
        </div>

        {/* Status Tabs Strip */}
        <nav className="flex gap-1.5 overflow-x-auto bg-white px-[17px] py-3" aria-label="Filter assignments">
          {statusFilters.map((item) => {
            const isActive = filter === item.id;
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => setFilter(item.id)}
                aria-pressed={isActive}
                className={`shrink-0 cursor-pointer whitespace-nowrap rounded-[7px] border px-2.5 py-[7px] text-xs ${isActive ? 'border-[#e9e5ff] bg-[#f2efff] font-semibold text-[#5e4fc5]' : 'border-transparent bg-transparent text-[#777b89]'}`}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Error Callout */}
      {error && (
        <div className="flex items-center justify-between gap-2.5 rounded-lg border border-[#f1dede] bg-[#fff8f8] px-[13px] py-[11px] text-xs text-[#a04a4a]" role="alert">
          <div>
            <strong className="block font-semibold">Assignments could not be loaded</strong>
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => loadAssignments(true)} className="inline-flex min-h-9 shrink-0 items-center justify-center gap-[7px] rounded-[7px] border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]">
            Try again
          </button>
        </div>
      )}

      {/* Assignments Content */}
      {loading ? (
        <div className="rounded-[11px] border border-[#ebebf0] bg-white p-6 text-center text-[#858998]">
          <span className="mb-2 inline-block size-[9px] animate-spin rounded-full border-2 border-[#e2e0f2] border-t-[#6555d7]" />
          <p className="m-0 text-xs">Loading your coursework…</p>
        </div>
      ) : visibleAssignments.length === 0 ? (
        <div className="rounded-[11px] border border-[#ebebf0] bg-white">
          <div className="px-5 py-[34px] text-center text-xs leading-relaxed text-[#9396a3]">
            <span className="mx-auto mb-2.5 grid size-[35px] place-items-center rounded-[11px] bg-[#edf8f3] text-[#53aa87]"><Icon name="checkCircle" size={19}/></span>
            <strong className="mb-[5px] block text-xs text-[#515563]">{query ? 'No matching coursework' : filter === 'all' ? 'No assignments yet' : 'Nothing in this view'}</strong>
            <p className="mx-auto max-w-[360px]">
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
                className="mt-2.5 inline-flex min-h-9 cursor-pointer items-center justify-center gap-[7px] rounded-[7px] border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]"
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
        <div className="overflow-hidden rounded-[11px] border border-[#ebebf0] bg-white">
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
