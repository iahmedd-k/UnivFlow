'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function AttendancePage() {
  const { getToken } = useAuth();
  const [attendance, setAttendance] = useState(null);
  const [portalSettings, setPortalSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [viewMode, setViewMode] = useState('table'); // 'table' | 'cards'
  const [filter, setFilter] = useState('all'); // 'all' | 'deficit' | 'borderline' | 'safe'
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const loadData = useCallback(async () => {
    try {
      const token = await getToken();
      const [attData, portalData] = await Promise.all([
        api.getAttendanceSummary(token),
        api.getPortalSettings(token).catch(() => null),
      ]);
      setAttendance(attData || null);
      setPortalSettings(portalData || null);
    } catch (err) {
      setError(err.message || 'Could not load attendance records.');
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    const timer = setTimeout(() => loadData(), 0);
    return () => clearTimeout(timer);
  }, [loadData]);

  const handleSyncPortal = async () => {
    setSyncing(true);
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      const res = await api.syncPortalHeadless(token);
      await loadData();
      if (res?.session_expired || ['session_expired', 'reconnect_required'].includes(res?.status)) {
        setError('University portal session expired. Attendance still shows the last saved snapshot. Reconnect in Portal settings, then sync again.');
      } else if (res?.status === 'already_running') {
        setNotice('A university portal sync is already running. Wait for it to finish, then refresh attendance.');
      } else if (res?.status === 'partial') {
        setNotice('Portal sync finished with some pages unavailable. Attendance was refreshed only if its report was read successfully.');
      } else if (res?.status === 'success') {
        setNotice('Attendance table successfully refreshed from University Portal.');
      } else {
        setError('The portal did not confirm that attendance was refreshed. Check Portal settings and try again.');
      }
    } catch (err) {
      setError(err.message || 'Could not synchronize attendance with university portal.');
    } finally {
      setSyncing(false);
    }
  };

  const courses = useMemo(() => {
    const list = attendance?.per_course || [];
    return list.map((item) => {
      const isLab = (item.subject || '').toLowerCase().includes('lab') || (item.course_name || '').toLowerCase().includes('lab');
      const heldValue = item.held ?? item.total;
      const attendedValue = item.attended;
      const held = heldValue != null && Number.isFinite(Number(heldValue)) ? Number(heldValue) : null;
      const attended = attendedValue != null && Number.isFinite(Number(attendedValue)) ? Number(attendedValue) : null;
      const hasCounts = held > 0 && attended != null && attended >= 0 && attended <= held;
      const portalPct = item.percentage != null && Number.isFinite(Number(item.percentage))
        ? Number(item.percentage)
        : null;
      const pct = hasCounts ? (attended * 100) / held : portalPct;
      const formattedPct = pct == null ? null : Number(pct.toFixed(1));
      const absent = hasCounts ? Number(item.absent ?? Math.max(0, held - attended)) : null;
      const classesPerWeek = Number(item.classes_per_week) || 0;

      let neededToPass = item.recovery_needed ?? 0;
      let canAffordToMiss = item.safe_bunks ?? 0;
      if (hasCounts && item.recovery_needed === undefined && item.safe_bunks === undefined) {
        if (pct < 75) {
          neededToPass = Math.max(1, Math.ceil((0.75 * held - attended) / 0.25));
        } else {
          canAffordToMiss = Math.max(0, Math.floor((attended - 0.75 * held) / 0.75));
        }
      }

      let cleanTitle = item.course_name || item.subject || 'Course';
      cleanTitle = cleanTitle.replace(/^F-26-/, '').replace(/-\d+$/, '').trim();

      return {
        ...item,
        cleanTitle,
        isLab,
        hasAttendance: formattedPct != null && formattedPct >= 0 && formattedPct <= 100,
        hasCounts,
        held,
        attended,
        absent,
        pct: formattedPct,
        classesPerWeek,
        neededToPass,
        canAffordToMiss,
        isDeficit: formattedPct != null && formattedPct < 75,
        isBorderline: formattedPct != null && formattedPct >= 75 && formattedPct < 80,
        isSafe: formattedPct != null && formattedPct >= 80,
      };
    });
  }, [attendance]);

  const filteredCourses = useMemo(() => {
    if (filter === 'deficit') return courses.filter((c) => c.isDeficit);
    if (filter === 'borderline') return courses.filter((c) => c.isBorderline);
    if (filter === 'safe') return courses.filter((c) => c.isSafe);
    return courses;
  }, [courses, filter]);

  // Aggregate stats
  const totals = useMemo(() => {
    const coursesWithCounts = courses.filter((course) => course.hasCounts);
    const totalHeld = coursesWithCounts.reduce((acc, c) => acc + c.held, 0);
    const totalAttended = coursesWithCounts.reduce((acc, c) => acc + c.attended, 0);
    const totalAbsent = coursesWithCounts.reduce((acc, c) => acc + c.absent, 0);
    const overallPct = totalHeld > 0
      ? ((totalAttended * 100) / totalHeld).toFixed(1)
      : attendance?.overall_attendance != null
        ? Number(attendance.overall_attendance).toFixed(1)
        : null;
    const deficitCount = courses.filter((c) => c.isDeficit).length;
    const safeCount = courses.filter((c) => c.isSafe).length;
    const borderlineCount = courses.filter((c) => c.isBorderline).length;

    return {
      totalHeld,
      totalAttended,
      totalAbsent,
      coursesWithCounts: coursesWithCounts.length,
      overallPct,
      deficitCount,
      safeCount,
      borderlineCount,
    };
  }, [courses, attendance]);

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">SEMESTER TRACKING</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Attendance</h1>
          <p className="mt-1 text-xs text-[#858998]">Compare verified portal attendance with each course’s weekly timetable frequency.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-neutral-200 bg-white p-1" role="group" aria-label="Attendance layout">
            <button type="button" onClick={() => setViewMode('table')} className={`rounded-md px-3 py-1.5 text-xs font-medium ${viewMode === 'table' ? 'bg-neutral-900 text-white' : 'text-neutral-600 hover:bg-neutral-100'}`} aria-pressed={viewMode === 'table'}>Table</button>
            <button type="button" onClick={() => setViewMode('cards')} className={`rounded-md px-3 py-1.5 text-xs font-medium ${viewMode === 'cards' ? 'bg-neutral-900 text-white' : 'text-neutral-600 hover:bg-neutral-100'}`} aria-pressed={viewMode === 'cards'}>Cards</button>
          </div>
          <button type="button" disabled={syncing || loading} onClick={handleSyncPortal} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50">
            <Icon name="refresh" size={15} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync portal'}
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-4 bg-rose-50 border border-rose-200 text-rose-800 px-4 py-3 rounded-xl text-xs flex items-center gap-2" role="alert">
          <Icon name="alert" size={15} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="mb-4 bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-3 rounded-xl text-xs flex items-center gap-2" role="status">
          <Icon name="check" size={15} />
          <span>{notice}</span>
        </div>
      )}

      <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-xs leading-relaxed text-blue-900">
        Attendance uses the portal’s Attendance Report: Total is classes held, ATTS is attended, and ABS is absent. Hour columns are excluded; timetable frequency is informational and does not change the portal totals.
      </div>

      {portalSettings?.url ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-600">
          <span className={`h-2 w-2 rounded-full ${portalSettings.session_status === 'ACTIVE' ? 'bg-emerald-500' : 'bg-neutral-300'}`} />
          <span><strong>University portal</strong> · {portalSettings.session_status?.replaceAll('_', ' ').toLowerCase() || 'status unavailable'}</span>
          {portalSettings.last_synced_at && <span className="text-neutral-400">Synced {new Date(portalSettings.last_synced_at).toLocaleString()}</span>}
          <Link className="ml-auto font-medium text-indigo-600 hover:underline" href="/dashboard/portal">Portal settings <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <span>Attendance data may be out of date until you connect your university portal.</span>
          <Link className="font-medium hover:underline" href="/dashboard/portal">Connect portal <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      )}

      {portalSettings?.session_status === 'REAUTH_REQUIRED' && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900" role="alert">
          <span>The saved university portal session has expired. Attendance is showing the last stored snapshot and may not include recent classes.</span>
          <Link className="shrink-0 font-semibold text-amber-800 underline underline-offset-2" href="/dashboard/portal">Reconnect portal</Link>
        </div>
      )}

      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3" aria-label="Attendance summary">
        <article className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
          <span className="block text-xs text-neutral-500">Overall attendance</span>
          <strong className="mt-2 block text-2xl font-semibold text-neutral-900">{loading || totals.overallPct == null ? '—' : `${totals.overallPct}%`}</strong>
          <small className="mt-1 block text-xs text-neutral-500">{totals.coursesWithCounts} courses with exact counts · 75% required</small>
        </article>
        <article className={`rounded-xl border bg-white p-4 shadow-sm ${totals.deficitCount ? 'border-rose-200' : 'border-neutral-200'}`}>
          <span className="block text-xs text-neutral-500">Needs attention</span>
          <strong className="mt-2 block text-2xl font-semibold text-neutral-900">{loading ? '—' : totals.deficitCount}</strong>
          <small className="mt-1 block text-xs text-neutral-500">{loading ? 'Courses below 75%' : `${totals.borderlineCount} near threshold · based on portal percentages`}</small>
        </article>
        <article className="rounded-xl border border-neutral-200 bg-white p-4 shadow-sm">
          <span className="block text-xs text-neutral-500">Verified classes attended</span>
          <strong className="mt-2 block text-2xl font-semibold text-neutral-900">{loading ? '—' : totals.coursesWithCounts ? `${totals.totalAttended} / ${totals.totalHeld}` : '—'}</strong>
          <small className="mt-1 block text-xs text-neutral-500">{loading ? 'Across tracked courses' : totals.coursesWithCounts ? `${totals.totalAbsent} absences · ${totals.coursesWithCounts} courses with counts` : 'Exact class counts are unavailable'}</small>
        </article>
      </section>

      {!loading && totals.deficitCount > 0 && (
        <button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-left text-xs text-rose-800 hover:bg-rose-100" onClick={() => setFilter('deficit')}>
          <span><strong>{totals.deficitCount} {totals.deficitCount === 1 ? 'course is' : 'courses are'} below the 75% requirement.</strong> Review the recovery plan for each course.</span>
          <span>Show courses <Icon name="arrowUpRight" size={14} /></span>
        </button>
      )}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter courses by attendance status">
        {[
          { id: 'all', label: 'All courses', count: courses.length },
          { id: 'deficit', label: 'Below 75%', count: totals.deficitCount },
          { id: 'borderline', label: 'Near threshold', count: totals.borderlineCount },
          { id: 'safe', label: 'On track', count: totals.safeCount },
        ].map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setFilter(item.id)}
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${filter === item.id ? 'border-indigo-200 bg-indigo-50 text-indigo-700' : 'border-neutral-200 bg-white text-neutral-600 hover:bg-neutral-50'}`}
            aria-pressed={filter === item.id}
          >
            {item.label}<span>{item.count}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-12 text-center text-xs text-neutral-400 bg-white rounded-xl border border-neutral-200">
          Loading official attendance records…
        </div>
      ) : filteredCourses.length === 0 ? (
        <div className="p-12 text-center text-xs text-neutral-400 bg-white rounded-xl border border-neutral-200">
          {courses.length === 0 ? 'No attendance records yet. Connect your university portal or sync to load course records.' : 'No courses match this filter.'}
        </div>
      ) : viewMode === 'table' ? (
        <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50 text-xs uppercase tracking-wide text-neutral-600"><th className="px-4 py-3">Course</th><th className="px-4 py-3">Classes</th><th className="px-4 py-3">Attendance</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">What to do</th></tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {filteredCourses.map((c) => (
                  <tr className="hover:bg-neutral-50" key={c.course_id || c.subject}>
                    <td className="px-4 py-3"><strong className="block font-semibold text-neutral-900">{c.cleanTitle}</strong><small className="mt-1 block text-neutral-500">{c.isLab ? 'Lab' : 'Course'}{c.subject && c.subject !== c.cleanTitle ? ` · ${c.subject}` : ''}</small></td>
                    <td>
                      <strong className="block font-medium text-neutral-800">{c.hasCounts ? `${c.attended} / ${c.held}` : 'Counts unavailable'}</strong>
                      <small className="mt-1 block text-neutral-500">
                        {c.hasCounts ? `${c.absent} absent` : 'Portal count data unavailable'}
                        {c.weekly_schedule_available ? ` · ${c.classesPerWeek}/week scheduled` : ' · no timetable match'}
                      </small>
                    </td>
                    <td>
                      <div className="flex min-w-28 items-center gap-2">
                        <strong className={`shrink-0 font-mono ${!c.hasAttendance ? 'text-neutral-400' : c.isDeficit ? 'text-rose-700' : c.isBorderline ? 'text-amber-700' : 'text-emerald-700'}`}>{c.hasAttendance ? `${c.pct}%` : '—'}</strong>
                        <span className="h-1.5 min-w-12 flex-1 overflow-hidden rounded-full bg-neutral-100"><i className={`block h-full rounded-full ${!c.hasAttendance ? 'bg-neutral-300' : c.isDeficit ? 'bg-rose-500' : c.isBorderline ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${c.hasAttendance ? Math.min(100, Math.max(0, c.pct)) : 0}%` }} /></span>
                      </div>
                    </td>
                    <td className="px-4 py-3"><span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${!c.hasAttendance ? 'bg-neutral-100 text-neutral-600' : c.isDeficit ? 'bg-rose-50 text-rose-700' : c.isBorderline ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>{!c.hasAttendance ? 'No portal percentage' : c.isDeficit ? 'Below requirement' : c.isBorderline ? 'Near threshold' : 'On track'}</span></td>
                    <td className={`px-4 py-3 text-neutral-600 ${c.isDeficit ? 'bg-rose-50/60' : ''}`}>
                      {!c.hasCounts ? (
                        <span>{c.hasAttendance ? 'Exact attendance counts are needed for recovery estimates.' : 'Sync the portal to load attendance.'}</span>
                      ) : c.isDeficit ? (
                        <span>Attend the next <strong>{c.neededToPass} {c.neededToPass === 1 ? 'class' : 'classes'}</strong> to recover.</span>
                      ) : (
                        <span>{c.canAffordToMiss > 0 ? `Can miss up to ${c.canAffordToMiss} ${c.canAffordToMiss === 1 ? 'class' : 'classes'} and stay above 75%.` : 'Attend upcoming classes to maintain your standing.'}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredCourses.map((c) => (
            <article
              key={c.course_id || c.subject}
              className={`flex flex-col justify-between rounded-xl border bg-white p-4 shadow-sm transition ${
                c.isDeficit
                  ? 'border-rose-200/80 ring-1 ring-rose-100'
                  : c.isBorderline
                  ? 'border-amber-200/80 ring-1 ring-amber-100'
                  : 'border-neutral-200/80'
              }`}
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <h3 className="font-bold text-sm text-neutral-900 leading-snug">{c.cleanTitle}</h3>
                    <span className="text-xs text-neutral-400 font-mono block mt-0.5">{c.subject}</span>
                  </div>
                  <span
                    className={`shrink-0 text-xs font-bold px-2 py-0.5 rounded-lg font-mono ${
                      !c.hasAttendance
                        ? 'bg-neutral-100 text-neutral-500 border border-neutral-200'
                        : c.isDeficit
                        ? 'bg-rose-50 text-rose-700 border border-rose-200'
                        : c.isBorderline
                        ? 'bg-amber-50 text-amber-700 border border-amber-200'
                        : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                    }`}
                  >
                    {c.hasAttendance ? `${c.pct}%` : 'No data'}
                  </span>
                </div>

                <div className="grid grid-cols-4 gap-1 py-2 border-y border-neutral-100 text-center my-3">
                  <div>
                    <span className="text-xs text-neutral-400 block uppercase">Held</span>
                    <strong className="text-xs text-neutral-800">{c.hasCounts ? c.held : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-400 block uppercase">Present</span>
                    <strong className="text-xs text-emerald-700">{c.hasCounts ? c.attended : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-400 block uppercase">Absent</span>
                    <strong className="text-xs text-rose-700">{c.hasCounts ? c.absent : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-neutral-400 block uppercase">Per week</span>
                    <strong className="text-xs text-neutral-500 font-mono">{c.weekly_schedule_available ? c.classesPerWeek : '—'}</strong>
                  </div>
                </div>

                <div className="w-full bg-neutral-100 h-1.5 rounded-full overflow-hidden mb-3">
                  <div
                    className={`h-full rounded-full ${!c.hasAttendance ? 'bg-neutral-300' : c.isDeficit ? 'bg-rose-500' : c.isBorderline ? 'bg-amber-500' : 'bg-emerald-500'}`}
                    style={{ width: `${c.hasAttendance ? Math.min(100, Math.max(0, c.pct)) : 0}%` }}
                  />
                </div>
              </div>

              <div
                className={`p-2.5 rounded-lg text-xs leading-relaxed border ${
                  !c.hasCounts
                  ? 'bg-neutral-50 border-neutral-200 text-neutral-600'
                  : c.isDeficit
                    ? 'bg-rose-50/70 border-rose-100 text-rose-800'
                    : c.isBorderline
                    ? 'bg-amber-50/70 border-amber-100 text-amber-800'
                    : 'bg-emerald-50/70 border-emerald-100 text-emerald-800'
                }`}
              >
                {!c.hasCounts ? (
                  <span>{c.hasAttendance ? 'Exact class counts are needed for a recovery estimate.' : 'No attendance data is available.'}</span>
                ) : c.isDeficit ? (
                  <span>
                    <strong>Action Required:</strong> Must attend next{' '}
                    <span className="font-bold underline decoration-rose-300">{c.neededToPass} classes</span> consecutively to clear examination threshold.
                  </span>
                ) : (
                  <span>
                    <strong>Good Standing:</strong> Can afford to miss up to{' '}
                    <strong>{c.canAffordToMiss} {c.canAffordToMiss === 1 ? 'class' : 'classes'}</strong> before dropping below 75%.
                  </span>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  );
}
