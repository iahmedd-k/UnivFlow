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

  const handleTurnIn = async (assignmentId, templateId, fileNames, token) => {
    await api.turnInAssignment(assignmentId, { template_id: templateId, templateId, fileNames }, token);
    await loadAssignments(true);
  };

  const openModalWithTab = (assignment, tab = 'overview') => {
    setInitialModalTab(tab);
    setActiveAssignment(assignment);
  };

  return (
    <main className="product-page pb-12" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <header className="product-heading">
        <div>
          <p className="eyebrow">COURSEWORK & DEADLINES</p>
          <h1 style={{ margin: '4px 0', fontSize: 24, fontWeight: 600, color: '#252837', letterSpacing: '-0.6px' }}>
            Assignments
          </h1>
          <p style={{ color: '#858998', fontSize: 12 }}>
            Review deadlines, query your AI academic tutor, test solutions, and turn in to Google Classroom.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Link href="/dashboard/templates" className="product-action secondary" style={{ textDecoration: 'none' }}>
            <Icon name="files" size={15}/>
            <span>Cover Templates</span>
          </Link>
          <button
            type="button"
            onClick={() => loadAssignments(true)}
            disabled={refreshing || loading}
            className="product-action"
            style={{ cursor: 'pointer' }}
            aria-label="Refresh assignments"
          >
            {refreshing ? 'Syncing…' : <><Icon name="refresh" size={14}/> Sync Classroom</>}
          </button>
        </div>
      </header>

      {/* 4 Summary Stat Cards matching Uniflow Overview Design */}
      <section className="overview-stats" aria-label="Coursework summary">
        <article className="overview-stat">
          <span className="stat-icon stat-lilac"><Icon name="clipboard" size={18}/></span>
          <div className="stat-text">
            <span>Total coursework</span>
            <strong>{loading ? '—' : stats.total}</strong>
            <small>{stats.quizzes} quizzes included</small>
          </div>
        </article>

        <article className="overview-stat">
          <span className="stat-icon stat-peach"><Icon name="clock" size={18}/></span>
          <div className="stat-text">
            <span>Upcoming & open</span>
            <strong style={{ color: '#d88752' }}>{loading ? '—' : stats.upcoming}</strong>
            <small>Pending submissions</small>
          </div>
        </article>

        <article className="overview-stat">
          <span className="stat-icon" style={{ background: '#fff0f0', color: '#b15252' }}><Icon name="alert" size={18}/></span>
          <div className="stat-text">
            <span>Past deadline</span>
            <strong style={{ color: '#b15252' }}>{loading ? '—' : stats.overdue}</strong>
            <small>{stats.overdue > 0 ? 'Requires attention' : 'All clear!'}</small>
          </div>
        </article>

        <article className="overview-stat">
          <span className="stat-icon stat-mint"><Icon name="checkCircle" size={18}/></span>
          <div className="stat-text">
            <span>Submitted & done</span>
            <strong style={{ color: '#47a887' }}>{loading ? '—' : stats.submitted}</strong>
            <small>{stats.completionRate}% completion rate</small>
          </div>
        </article>
      </section>

      {/* Filter and Search Bar Container */}
      <div className="surface-card" style={{ padding: 0, overflow: 'hidden' }}>
        {/* Top Search Controls Bar */}
        <div
          style={{
            padding: '14px 18px',
            borderBottom: '1px solid #f0f0f3',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          {/* Search Input */}
          <div style={{ position: 'relative', flex: 1, minWidth: 220 }}>
            <span
              style={{
                position: 'absolute',
                left: 11,
                top: '50%',
                transform: 'translateY(-50%)',
                color: '#9a9dab',
                fontSize: 13,
                pointerEvents: 'none',
              }}
            >
              <Icon name="search" size={15}/>
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search assignments or courses…"
              style={{
                width: '100%',
                height: 36,
                padding: '0 30px 0 32px',
                border: '1px solid #e4e4eb',
                borderRadius: 8,
                background: '#fafafd',
                color: '#2c2f3b',
                fontSize: 12,
                outline: 'none',
                fontFamily: 'inherit',
              }}
              aria-label="Search assignments"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  color: '#9a9cab',
                  cursor: 'pointer',
                  fontSize: 12,
                  padding: 4,
                }}
              >
                <Icon name="close" size={14}/>
              </button>
            )}
          </div>

          {/* Selectors and View Mode Switcher */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {availableCourses.length > 0 && (
              <select
                value={selectedCourse}
                onChange={(e) => setSelectedCourse(e.target.value)}
                style={{
                  height: 36,
                  padding: '0 10px',
                  border: '1px solid #e4e4eb',
                  borderRadius: 8,
                  background: '#fff',
                  color: '#475569',
                  fontSize: 11,
                  fontWeight: 500,
                  outline: 'none',
                  cursor: 'pointer',
                }}
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
              style={{
                height: 36,
                padding: '0 10px',
                border: '1px solid #e4e4eb',
                borderRadius: 8,
                background: '#fff',
                color: '#475569',
                fontSize: 11,
                fontWeight: 500,
                outline: 'none',
                cursor: 'pointer',
              }}
              aria-label="Sort assignments"
            >
              <option value="due_asc">Deadline: Earliest first</option>
              <option value="due_desc">Deadline: Latest first</option>
              <option value="title">Alphabetical (A-Z)</option>
              <option value="course">Course Name</option>
            </select>

            {/* View Mode Toggle */}
            <div style={{ display: 'inline-flex', borderRadius: 8, border: '1px solid #e4e4eb', padding: 2, background: '#f8f8fb' }}>
              <button
                type="button"
                onClick={() => setViewMode('grid')}
                style={{
                  padding: '4px 8px',
                  border: 'none',
                  borderRadius: 6,
                  background: viewMode === 'grid' ? '#fff' : 'transparent',
                  color: viewMode === 'grid' ? '#6657d9' : '#858998',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  boxShadow: viewMode === 'grid' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
                }}
                title="Grid View"
              >
                <Icon name="dashboard" size={13}/> Grid
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                style={{
                  padding: '4px 8px',
                  border: 'none',
                  borderRadius: 6,
                  background: viewMode === 'list' ? '#fff' : 'transparent',
                  color: viewMode === 'list' ? '#6657d9' : '#858998',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  boxShadow: viewMode === 'list' ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
                }}
                title="List View"
              >
                <Icon name="listChecks" size={13}/> List
              </button>
            </div>
          </div>
        </div>

        {/* Status Tabs Strip */}
        <nav className="product-tabs" style={{ borderBottom: 'none', background: '#fff' }} aria-label="Filter assignments">
          {statusFilters.map((item) => {
            const isActive = filter === item.id;
            return (
              <button
                type="button"
                key={item.id}
                onClick={() => setFilter(item.id)}
                aria-pressed={isActive}
                className={`product-tab ${isActive ? 'active' : ''}`}
              >
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Error Callout */}
      {error && (
        <div className="product-alert" role="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <div>
            <strong style={{ display: 'block' }}>Assignments could not be loaded</strong>
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => loadAssignments(true)} className="product-action secondary" style={{ flexShrink: 0 }}>
            Try again
          </button>
        </div>
      )}

      {/* Assignments Content */}
      {loading ? (
        <div className="product-card" style={{ padding: 24, textAlign: 'center', color: '#858998' }}>
          <span className="loading-dot" style={{ display: 'inline-block', marginBottom: 8 }} />
          <p style={{ fontSize: 12, margin: 0 }}>Loading your coursework…</p>
        </div>
      ) : visibleAssignments.length === 0 ? (
        <div className="product-card">
          <div className="product-empty">
            <span className="empty-calendar" style={{ margin: '0 auto 10px' }}><Icon name="checkCircle" size={19}/></span>
            <strong>{query ? 'No matching coursework' : filter === 'all' ? 'No assignments yet' : 'Nothing in this view'}</strong>
            <p>
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
                className="product-action secondary"
                style={{ marginTop: 10, cursor: 'pointer' }}
              >
                Clear Search
              </button>
            )}
          </div>
        </div>
      ) : viewMode === 'grid' ? (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 14,
          }}
        >
          {visibleAssignments.map((assignment) => (
            <AssignmentCard
              key={assignment.id}
              assignment={assignment}
              viewMode="grid"
            />
          ))}
        </div>
      ) : (
        <div className="product-card overflow-hidden">
          <div className="product-list">
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
