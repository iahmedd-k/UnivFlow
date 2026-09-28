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

  const loadData = useCallback(async () => {
    try {
      const token = await getToken();
      const results = await Promise.allSettled([
        api.getCourses(token),
        api.getSyncStatus(token),
        api.getClassroomSettings(token),
        api.getAssignments(null, token, null, { noCache: true }),
      ]);

      if (results[0].status === 'fulfilled') setCourses(results[0].value || []);
      if (results[1].status === 'fulfilled') setSync(results[1].value);
      if (results[2].status === 'fulfilled') setSemesterDate(results[2].value?.semester_start_date || '');
      if (results[3].status === 'fulfilled') setAssignments(results[3].value || []);

      const failed = results.find((r) => r.status === 'rejected');
      if (failed) throw failed.reason;
      setError('');
    } catch (err) {
      setError(err.message || 'Could not load local Classroom data.');
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadData();
  }, [loadData]);

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
          setError(latest.sync_run.error || 'Google Classroom sync failed.');
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
      const result = await api.getGoogleAuthUrl(token);
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
    <main className="product-page pb-10">
      <header className="product-heading">
        <div>
          <p className="eyebrow">COURSE CONNECTION</p>
          <h1>Google Classroom</h1>
          <p>Connect your account, sync course work, and review the courses available in Uniflow.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`product-pill ${isConnected ? 'success' : 'warning'}`}>
            <span className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-amber-500'}`} />
            {isConnected ? 'Connected' : 'Not connected'}
          </span>
          {!isConnected && (
            <button type="button" onClick={handleConnect} disabled={busy} className="product-action">
              {busy ? 'Connecting…' : 'Connect Google'}
            </button>
          )}
        </div>
      </header>

      {error && <div className="product-alert flex items-center justify-between gap-4" role="alert"><span>{error}</span><button type="button" className="product-action secondary shrink-0" onClick={loadData}>Try again</button></div>}
      {message && <div className="product-alert ok" role="status">{message}</div>}

      <section className="product-grid three" aria-label="Classroom sync summary">
        <article className="product-stat"><span>Courses synced</span><strong>{loading ? '—' : courses.length}</strong></article>
        <article className="product-stat"><span>Assignments synced</span><strong>{loading ? '—' : sync?.assignments_in_db ?? 0}</strong></article>
        <article className="product-stat"><span>Last successful sync</span><strong className="sync-status-value">{sync?.last_sync ? new Date(sync.last_sync).toLocaleDateString() : 'Not synced'}</strong><small className="last-synced">{sync?.last_sync ? new Date(sync.last_sync).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Connect and sync to get started'}</small></article>
      </section>

      <section className="product-card">
        <header className="product-card-head"><div><p className="eyebrow">SYNC SETTINGS</p><h2>Coursework sync</h2></div></header>
        <div className="product-card-body">
          <p className="import-description">Sync runs in the background. You can leave this page while courses and assignments are updated.</p>
          {syncRun?.status === 'running' && <p className="product-note mb-4" role="status">Sync in progress. This page will update when it finishes.</p>}
          <div className="flex flex-col gap-3 border-t border-[#f0f0f3] pt-4 sm:flex-row sm:items-end">
            <label className="product-field w-full sm:max-w-xs"><span>Semester start date</span><input type="date" value={semesterDate} onChange={(e) => setSemesterDate(e.target.value)} /></label>
            <p className="last-synced sm:pb-2">Older courses can be excluded from this semester’s sync.</p>
            {isConnected && <button type="button" onClick={handleSync} disabled={isSyncRunning} className="product-action sm:ml-auto">{syncRun?.status === 'running' ? 'Syncing…' : busy ? 'Starting…' : 'Sync now'}</button>}
          </div>
        </div>
      </section>

      <section aria-labelledby="classroom-courses-heading">
        <header className="mb-3 flex items-end justify-between gap-3">
          <div><p className="eyebrow">YOUR CLASSROOM</p><h2 id="classroom-courses-heading" className="mt-1 text-base font-semibold text-[#343746]">Your courses</h2></div>
          <span className="product-pill">{loading ? '…' : courses.length}</span>
        </header>
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading courses">
            {[1, 2, 3].map((item) => <div key={item} className="h-[290px] animate-pulse overflow-hidden rounded-xl border border-[#ebebf0] bg-white"><div className="h-28 bg-gray-100"/><div className="space-y-3 p-4"><div className="h-4 w-3/4 rounded bg-gray-100"/><div className="h-3 w-1/2 rounded bg-gray-100"/><div className="h-16 rounded bg-gray-50"/></div></div>)}
          </div>
        ) : courses.length === 0 ? (
          <div className="product-card product-empty"><strong>{isConnected ? 'No courses synced yet' : 'Connect Google Classroom to get started'}</strong><span>{isConnected ? 'Run a sync to bring your enrolled courses and assignments into Uniflow.' : 'Once connected, your enrolled courses and coursework will appear here.'}</span></div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {courses.map((course, index) => {
              const courseAssignments = assignments
                .filter((item) => String(item.course_id) === String(course.id) && item.submission_state !== 'TURNED_IN' && item.submission_state !== 'RETURNED')
                .slice(0, 2);
              const color = courseColors[index % courseColors.length];
              const initials = (course.teacher_name || course.name || 'C').trim().charAt(0).toUpperCase();
              return (
                <article key={course.id} className="flex min-h-[300px] flex-col overflow-hidden rounded-xl border border-[#e4e5e8] bg-white shadow-[0_1px_3px_rgba(25,30,45,0.06)] transition-shadow hover:shadow-md">
                  <header className="relative min-h-[118px] overflow-hidden px-4 pb-4 pt-4 text-white" style={{ backgroundColor: color }}>
                    <span className="pointer-events-none absolute -right-5 -top-8 h-28 w-28 rotate-12 rounded-2xl border border-white/15 bg-white/10" aria-hidden="true" />
                    <h3 className="relative z-10 truncate pr-8 text-lg font-medium leading-6" title={course.name}>{course.name || 'Untitled course'}</h3>
                    {course.section && <p className="relative z-10 mt-1 truncate text-xs font-semibold">{course.section}</p>}
                    <p className="relative z-10 mt-1 truncate text-xs text-white/90">{course.teacher_name || 'Google Classroom course'}</p>
                    <span className="absolute -bottom-5 right-4 grid h-14 w-14 place-items-center rounded-full border-2 border-white bg-[#465d68] text-xl font-medium text-white shadow-sm" aria-label={`Instructor ${course.teacher_name || ''}`}>
                      {initials}
                    </span>
                  </header>
                  <div className="flex flex-1 flex-col px-4 pb-4 pt-8">
                    {courseAssignments.length ? (
                      <div className="space-y-2">
                        {courseAssignments.map((item) => (
                          <Link key={item.id} href={`/dashboard/assignments/${item.id}`} className="block rounded-lg border border-[#ececf1] px-3 py-2.5 transition-colors hover:border-[#d8d3f7] hover:bg-[#faf9ff]">
                            <span className="block text-[10px] font-medium text-[#7b7e8b]">{dueLabel(item.due_at || item.due_date)}</span>
                            <span className="mt-0.5 block truncate text-xs font-semibold text-[#3f4350]">{item.title || 'Untitled assignment'}</span>
                          </Link>
                        ))}
                      </div>
                    ) : (
                      <p className="flex-1 py-2 text-xs text-[#9295a2]">No upcoming assignments</p>
                    )}
                  </div>
                  <footer className="flex min-h-14 items-center justify-end border-t border-[#ededf2] px-4">
                    {course.alternate_link ? <a href={course.alternate_link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#5e52c7] hover:text-[#493eae]">Open Classroom <Icon name="externalLink" size={13}/></a> : <span className="text-[10px] text-[#a0a2ad]">Synced course</span>}
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
