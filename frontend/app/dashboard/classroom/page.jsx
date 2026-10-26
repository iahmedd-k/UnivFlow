'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const courseColors = ['#526c78', '#259b70', '#3478e5', '#873e98', '#426f9a', '#b5673d'];

function dueLabel(value) {
  if (!value) return 'No deadline';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Due date unavailable';
  const today = new Date();
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startDue = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((startDue - startToday) / 86400000);
  if (days === 0) return 'Due today';
  if (days === 1) return 'Due tomorrow';
  if (days < 0) return `Overdue · ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
  return `Due ${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
}

export default function ClassroomPage() {
  const { getToken } = useAuth();
  const [courses, setCourses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [sync, setSync] = useState(null);
  const [semesterDate, setSemesterDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadData = useCallback(async (forceRefresh = false) => {
    try {
      const token = getToken ? await getToken() : null;
      const results = await Promise.allSettled([
        api.getCourses(token),
        api.getSyncStatus(token),
        api.getClassroomSettings(token),
        api.getAssignments(null, token, null, forceRefresh ? { noCache: true } : {}),
      ]);

      if (results[0].status === 'fulfilled') setCourses(results[0].value || []);
      if (results[1].status === 'fulfilled') {
        const syncData = results[1].value;
        setSync(syncData);
        if (syncData?.sync_run?.status === 'failed' && (!results[0].value || results[0].value.length === 0)) {
          const syncErr = syncData.sync_run.error || syncData.sync_run.result?.errors?.[0];
          if (syncErr) setError(syncErr);
        }
      }
      if (results[2].status === 'fulfilled') setSemesterDate(results[2].value?.semester_start_date || '');
      if (results[3].status === 'fulfilled') setAssignments(results[3].value || []);

      const failed = results.find((r) => r.status === 'rejected');
      if (failed) throw failed.reason;
    } catch (err) {
      setError(err.message || 'Could not load local Classroom data.');
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    void loadData();
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.get('google_connected') === 'true') {
        setMessage('Google Classroom connected successfully!');
      } else if (params.get('google_error')) {
          const errType = params.get('google_error');
          setError(
            errType === 'token_exchange_failed'
              ? 'Google sign-in token exchange failed. Please try again.'
              : errType === 'invalid_oauth_state'
              ? 'Google sign-in expired or invalid. Please try connecting again.'
              : `Google sign-in was not completed: ${errType}`
          );
        }
      }
  }, []);

  useEffect(() => {
    if (sync?.sync_run?.status !== 'running') return undefined;

    let cancelled = false;
    let timer;
    const checkSyncStatus = async () => {
      try {
        const token = await getToken();
        const latest = await api.getSyncStatus(token);
        if (cancelled) return;
        setSync(latest);

        if (latest.sync_run?.status === 'running') {
          timer = setTimeout(checkSyncStatus, 5000);
          return;
        }

        await loadData();
        if (latest.sync_run?.status === 'completed') {
          const result = latest.sync_run.result || {};
          setMessage(`Sync complete: ${result.courses || 0} courses and ${result.assignments || 0} assignments updated.`);
        } else if (latest.sync_run?.status === 'failed') {
          const syncErr = latest.sync_run.error || latest.sync_run.result?.errors?.[0] || 'Google Classroom sync failed.';
          setError(syncErr);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Could not check Google Classroom sync progress. Retrying…');
          timer = setTimeout(checkSyncStatus, 10000);
        }
      }
    };

    timer = setTimeout(checkSyncStatus, 5000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sync?.sync_run?.status, getToken, loadData]);

  const handleSync = async () => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const token = await getToken();
      await api.saveClassroomSettings({ semester_start_date: semesterDate || null }, token);
      const result = await api.triggerSync(semesterDate || null, token);
      setMessage(result.message || 'Google Classroom sync started. Tracking progress…');
      setSync((current) => ({
        ...current,
        sync_run: {
          ...current?.sync_run,
          status: 'running',
          started_at: new Date().toISOString(),
        },
      }));
    } catch (err) {
      setError(err.message || 'Could not start Classroom sync.');
    } finally {
      setBusy(false);
    }
  };

  const handleConnect = async () => {
    setBusy(true);
    setError('');
    try {
      const token = await getToken();
      const result = await api.getGoogleAuthUrl(token, '/dashboard/classroom');
      if (result.auth_url) window.location.assign(result.auth_url);
      else throw new Error('Google did not return an authorization URL.');
    } catch (err) {
      setError(err.message || 'Could not initiate Google connection.');
      setBusy(false);
    }
  };

  const isConnected = Boolean(sync?.google_connected);
  const syncRun = sync?.sync_run;
  const isSyncRunning = syncRun?.status === 'running' || busy;

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-heading">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">COURSE CONNECTION</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">Google Classroom</h1>
          <p className="text-sm font-normal text-muted leading-relaxed">Connect your account, sync course work, and review the courses available in Uniflow.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${isConnected ? 'bg-success-bg text-success' : 'bg-warning-bg text-warning'}`}>
            <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-success' : 'bg-warning'}`} />
            {isConnected ? 'Connected' : 'Not connected'}
          </span>
          {!isConnected && (
            <button type="button" onClick={handleConnect} disabled={busy} className="inline-flex min-h-9 items-center justify-center rounded-md border border-violet bg-violet px-3 text-sm font-medium text-white hover:bg-violet-dark disabled:opacity-55">
              {busy ? 'Connecting…' : 'Connect Google'}
            </button>
          )}
        </div>
      </header>

      {error && <div className="flex items-center justify-between gap-4 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert"><span>{error}</span><button type="button" className="inline-flex min-h-8 shrink-0 items-center justify-center rounded-md border border-border-input bg-surface px-3 text-sm font-medium text-nav hover:bg-surface-secondary" onClick={loadData}>Try again</button></div>}
      {message && <div className="rounded-lg border border-success/30 bg-success-bg px-4 py-3 text-sm text-success" role="status">{message}</div>}

      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3" aria-label="Classroom sync summary">
        {[
          ['Courses synced', loading ? '—' : courses.length],
          ['Assignments synced', loading ? '—' : sync?.assignments_in_db ?? 0],
        ].map(([label, value]) => <article className="rounded-xl border border-border bg-surface p-4 shadow-xs" key={label}><span className="block text-xs font-medium uppercase tracking-wider text-muted">{label}</span><strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{value}</strong></article>)}
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs"><span className="block text-xs font-medium uppercase tracking-wider text-muted">Last successful sync</span><strong className="mt-2 block text-base font-semibold capitalize text-heading">{sync?.last_sync ? new Date(sync.last_sync).toLocaleDateString() : 'Not synced'}</strong><small className="mt-1 block text-xs font-normal text-subtle tabular-nums">{sync?.last_sync ? new Date(sync.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Connect and sync to get started'}</small></article>
      </section>

      <section className="min-w-0 rounded-xl border border-border bg-surface shadow-xs">
        <header className="flex items-center justify-between gap-3.5 border-b border-border-light px-5 py-4"><div><p className="text-xs font-medium uppercase tracking-wider text-label">SYNC SETTINGS</p><h2 className="text-lg font-semibold text-heading">Coursework sync</h2></div></header>
        <div className="p-5">
          <p className="mb-4 text-sm leading-relaxed text-muted font-normal">Sync runs in the background. You can leave this page while courses and assignments are updated.</p>
          {syncRun?.status === 'running' && <p className="mb-4 rounded-lg bg-violet-light px-3 py-2.5 text-sm leading-relaxed text-violet" role="status">Sync in progress. This page will update when it finishes.</p>}
          <div className="flex flex-col gap-3 border-t border-border-light pt-4 sm:flex-row sm:items-end">
            <label className="flex w-full max-w-xs flex-col gap-1.5 text-sm font-medium text-heading"><span>Semester start date</span><input className="rounded-md border border-border-input px-3 py-2 text-sm font-normal outline-none focus:border-violet focus:ring-2 focus:ring-violet/20" type="date" value={semesterDate} onChange={(e) => setSemesterDate(e.target.value)} /></label>
            <p className="pb-2 text-xs font-normal text-subtle">Older courses can be excluded from this semester’s sync.</p>
            {isConnected && <button type="button" onClick={handleSync} disabled={isSyncRunning} className="ml-auto inline-flex min-h-9 items-center justify-center rounded-md border border-violet bg-violet px-3 text-sm font-medium text-white hover:bg-violet-dark disabled:opacity-55">{syncRun?.status === 'running' ? 'Syncing…' : busy ? 'Starting…' : 'Sync now'}</button>}
          </div>
        </div>
      </section>

      <section aria-labelledby="classroom-courses-heading">
        <header className="mb-3 flex items-end justify-between gap-3">
          <div><p className="text-xs font-medium uppercase tracking-wider text-label">YOUR CLASSROOM</p><h2 id="classroom-courses-heading" className="mt-1 text-lg font-semibold text-heading">Your courses</h2></div>
          <span className="inline-flex items-center rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-nav tabular-nums">{loading ? '…' : courses.length}</span>
        </header>
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading courses">
            {[1, 2, 3].map((item) => <div key={item} className="h-[290px] animate-pulse overflow-hidden rounded-xl border border-border bg-surface"><div className="h-28 bg-surface-secondary"/><div className="space-y-3 p-4"><div className="h-4 w-3/4 rounded bg-surface-secondary"/><div className="h-3 w-1/2 rounded bg-surface-secondary"/><div className="h-16 rounded bg-surface-secondary/50"/></div></div>)}
          </div>
        ) : courses.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-surface px-5 py-10 text-center leading-relaxed"><strong className="mb-1 text-base font-semibold text-heading">{isConnected ? 'No courses synced yet' : 'Connect Google Classroom to get started'}</strong><span className="text-sm font-normal text-muted">{isConnected ? 'Run a sync to bring your enrolled courses and assignments into Uniflow.' : 'Once connected, your enrolled courses and coursework will appear here.'}</span></div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {courses.map((course, index) => {
              const courseAssignments = assignments
                .filter((item) => String(item.course_id) === String(course.id) && item.submission_state !== 'TURNED_IN' && item.submission_state !== 'RETURNED')
                .slice(0, 2);
              const color = courseColors[index % courseColors.length];
              const initials = (course.teacher_name || course.name || 'C').trim().charAt(0).toUpperCase();
              return (
                <article key={course.id} className="flex min-h-[300px] flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-xs transition-shadow hover:shadow-md">
                  <header className="relative min-h-[118px] overflow-hidden px-4 pb-4 pt-4 text-white" style={{ backgroundColor: color }}>
                    <span className="pointer-events-none absolute -right-5 -top-8 h-28 w-28 rotate-12 rounded-2xl border border-white/15 bg-white/10" aria-hidden="true" />
                    <h3 className="relative z-10 truncate pr-8 text-lg font-semibold leading-6" title={course.name}>{course.name || 'Untitled course'}</h3>
                    {course.section && <p className="relative z-10 mt-1 truncate text-xs font-medium text-white/90">{course.section}</p>}
                    <p className="relative z-10 mt-1 truncate text-xs font-normal text-white/90">{course.teacher_name || 'Google Classroom course'}</p>
                    <span className="absolute -bottom-5 right-4 grid h-14 w-14 place-items-center rounded-full border-2 border-white bg-[#465d68] text-xl font-semibold text-white shadow-xs" aria-label={`Instructor ${course.teacher_name || ''}`}>
                      {initials}
                    </span>
                  </header>
                  <div className="flex flex-1 flex-col px-4 pb-4 pt-8">
                    {courseAssignments.length ? (
                      <div className="space-y-2">
                        {courseAssignments.map((item) => (
                          <Link key={item.id} href={`/dashboard/assignments/${item.id}`} className="block rounded-lg border border-border-light px-3 py-2.5 transition-colors hover:border-violet-light hover:bg-surface-secondary">
                            <span className="block text-xs font-normal text-muted tabular-nums">{dueLabel(item.due_at || item.due_date)}</span>
                            <span className="mt-0.5 block truncate text-sm font-semibold text-heading">{item.title || 'Untitled assignment'}</span>
                          </Link>
                        ))}
                      </div>
                    ) : (
                      <p className="flex-1 py-2 text-xs font-normal text-subtle">No upcoming assignments</p>
                    )}
                  </div>
                  <footer className="flex min-h-14 items-center justify-end border-t border-border-light px-4">
                    {course.alternate_link ? <a href={course.alternate_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs font-medium text-violet hover:underline">Open Classroom <Icon name="externalLink" size={13}/></a> : <span className="text-xs font-normal text-subtle">Synced course</span>}
                  </footer>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
