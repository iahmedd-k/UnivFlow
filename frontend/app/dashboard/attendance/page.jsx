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
      const token = getToken ? await getToken() : null;
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
    loadData();
  }, []);

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
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-heading">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">SEMESTER TRACKING</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">Attendance</h1>
          <p className="text-sm font-normal text-muted leading-relaxed">Compare verified portal attendance with each course’s weekly timetable frequency.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-border bg-surface p-1" role="group" aria-label="Attendance layout">
            <button type="button" onClick={() => setViewMode('table')} className={`rounded-md px-3 py-1.5 text-sm font-medium ${viewMode === 'table' ? 'bg-ink text-white' : 'text-nav hover:bg-surface-secondary'}`} aria-pressed={viewMode === 'table'}>Table</button>
            <button type="button" onClick={() => setViewMode('cards')} className={`rounded-md px-3 py-1.5 text-sm font-medium ${viewMode === 'cards' ? 'bg-ink text-white' : 'text-nav hover:bg-surface-secondary'}`} aria-pressed={viewMode === 'cards'}>Cards</button>
          </div>
          <button type="button" disabled={syncing || loading} onClick={handleSyncPortal} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-violet px-3 text-sm font-medium text-white hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">
            <Icon name="refresh" size={15} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync portal'}
          </button>
        </div>
      </header>

      {error && (
        <div className="mb-4 bg-rose-bg border border-rose-border text-rose px-4 py-3 rounded-xl text-sm font-normal flex items-center gap-2" role="alert">
          <Icon name="alert" size={15} />
          <span>{error}</span>
        </div>
      )}
      {notice && (
        <div className="mb-4 bg-success-bg border border-success/30 text-success px-4 py-3 rounded-xl text-sm font-normal flex items-center gap-2" role="status">
          <Icon name="check" size={15} />
          <span>{notice}</span>
        </div>
      )}

      <div className="mb-4 rounded-xl border border-info-bg bg-info-light px-4 py-3 text-sm leading-relaxed text-ink">
        Attendance uses the portal’s Attendance Report: Total is classes held, ATTS is attended, and ABS is absent. Hour columns are excluded; timetable frequency is informational and does not change the portal totals.
      </div>

      {portalSettings?.url ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-muted">
          <span className={`h-2 w-2 rounded-full ${portalSettings.session_status === 'ACTIVE' ? 'bg-success' : 'bg-muted'}`} />
          <span><strong className="font-semibold text-heading">University portal</strong> · {portalSettings.session_status?.replaceAll('_', ' ').toLowerCase() || 'status unavailable'}</span>
          {portalSettings.last_synced_at && <span className="text-subtle tabular-nums">Synced {new Date(portalSettings.last_synced_at).toLocaleString()}</span>}
          <Link className="ml-auto font-medium text-violet hover:underline text-sm" href="/dashboard/portal">Portal settings <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning-bg bg-warning-bg/40 px-3.5 py-2.5 text-sm text-warning">
          <span>Attendance data may be out of date until you connect your university portal.</span>
          <Link className="font-medium hover:underline text-sm" href="/dashboard/portal">Connect portal <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      )}

      {portalSettings?.session_status === 'REAUTH_REQUIRED' && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-warning-bg bg-warning-bg/40 px-4 py-3 text-sm leading-relaxed text-warning" role="alert">
          <span>The saved university portal session has expired. Attendance is showing the last stored snapshot and may not include recent classes.</span>
          <Link className="shrink-0 font-medium text-warning underline underline-offset-2" href="/dashboard/portal">Reconnect portal</Link>
        </div>
      )}

      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3" aria-label="Attendance summary">
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Overall attendance</span>
          <strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{loading || totals.overallPct == null ? '—' : `${totals.overallPct}%`}</strong>
          <small className="mt-1 block text-xs font-normal text-subtle">{totals.coursesWithCounts} courses with exact counts · 75% required</small>
        </article>
        <article className={`rounded-xl border bg-surface p-4 shadow-xs ${totals.deficitCount ? 'border-rose-border' : 'border-border'}`}>
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Needs attention</span>
          <strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{loading ? '—' : totals.deficitCount}</strong>
          <small className="mt-1 block text-xs font-normal text-subtle">{loading ? 'Courses below 75%' : `${totals.borderlineCount} near threshold · based on portal percentages`}</small>
        </article>
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Verified classes attended</span>
          <strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{loading ? '—' : totals.coursesWithCounts ? `${totals.totalAttended} / ${totals.totalHeld}` : '—'}</strong>
          <small className="mt-1 block text-xs font-normal text-subtle">{loading ? 'Across tracked courses' : totals.coursesWithCounts ? `${totals.totalAbsent} absences · ${totals.coursesWithCounts} courses with counts` : 'Exact class counts are unavailable'}</small>
        </article>
      </section>

      {!loading && totals.deficitCount > 0 && (
        <button type="button" className="flex w-full flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-border bg-rose-bg px-4 py-3 text-left text-sm font-normal text-rose hover:bg-rose-bg/80" onClick={() => setFilter('deficit')}>
          <span><strong className="font-semibold">{totals.deficitCount} {totals.deficitCount === 1 ? 'course is' : 'courses are'} below the 75% requirement.</strong> Review the recovery plan for each course.</span>
          <span className="font-medium inline-flex items-center gap-1">Show courses <Icon name="arrowUpRight" size={14} /></span>
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
            className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium ${filter === item.id ? 'border-violet-light bg-violet-light text-violet' : 'border-border bg-surface text-nav hover:bg-surface-secondary'}`}
            aria-pressed={filter === item.id}
          >
            <span>{item.label}</span><span className="text-xs font-medium tabular-nums">{item.count}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-12 text-center text-sm font-normal text-muted bg-surface rounded-xl border border-border">
          Loading official attendance records…
        </div>
      ) : filteredCourses.length === 0 ? (
        <div className="p-12 text-center text-sm font-normal text-muted bg-surface rounded-xl border border-border">
          {courses.length === 0 ? 'No attendance records yet. Connect your university portal or sync to load course records.' : 'No courses match this filter.'}
        </div>
      ) : viewMode === 'table' ? (
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-secondary text-xs uppercase tracking-wider text-muted font-medium"><th className="px-4 py-3">Course</th><th className="px-4 py-3">Classes</th><th className="px-4 py-3">Attendance</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">What to do</th></tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {filteredCourses.map((c) => (
                  <tr className="hover:bg-surface-secondary/70 transition" key={c.course_id || c.subject}>
                    <td className="px-4 py-3.5"><strong className="block font-semibold text-heading">{c.cleanTitle}</strong><small className="mt-0.5 block text-xs font-normal text-muted">{c.isLab ? 'Lab' : 'Course'}{c.subject && c.subject !== c.cleanTitle ? ` · ${c.subject}` : ''}</small></td>
                    <td className="px-4 py-3.5">
                      <strong className="block font-medium text-heading tabular-nums">{c.hasCounts ? `${c.attended} / ${c.held}` : 'Counts unavailable'}</strong>
                      <small className="mt-0.5 block text-xs font-normal text-muted tabular-nums">
                        {c.hasCounts ? `${c.absent} absent` : 'Portal count data unavailable'}
                        {c.weekly_schedule_available ? ` · ${c.classesPerWeek}/week scheduled` : ' · no timetable match'}
                      </small>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex min-w-28 items-center gap-2">
                        <strong className={`shrink-0 font-semibold tabular-nums ${!c.hasAttendance ? 'text-muted' : c.isDeficit ? 'text-danger' : c.isBorderline ? 'text-warning' : 'text-success'}`}>{c.hasAttendance ? `${c.pct}%` : '—'}</strong>
                        <span className="h-1.5 min-w-12 flex-1 overflow-hidden rounded-full bg-border-input"><i className={`block h-full rounded-full ${!c.hasAttendance ? 'bg-muted' : c.isDeficit ? 'bg-rose-500' : c.isBorderline ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${c.hasAttendance ? Math.min(100, Math.max(0, c.pct)) : 0}%` }} /></span>
                      </div>
                    </td>
                    <td className="px-4 py-3.5"><span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${!c.hasAttendance ? 'bg-surface-secondary text-muted' : c.isDeficit ? 'bg-rose-bg text-rose' : c.isBorderline ? 'bg-warning-bg text-warning' : 'bg-success-bg text-success'}`}>{!c.hasAttendance ? 'No portal percentage' : c.isDeficit ? 'Below requirement' : c.isBorderline ? 'Near threshold' : 'On track'}</span></td>
                    <td className={`px-4 py-3.5 text-muted leading-relaxed ${c.isDeficit ? 'bg-rose-bg/30' : ''}`}>
                      {!c.hasCounts ? (
                        <span>{c.hasAttendance ? 'Exact attendance counts are needed for recovery estimates.' : 'Sync the portal to load attendance.'}</span>
                      ) : c.isDeficit ? (
                        <span>Attend the next <strong className="font-semibold text-heading tabular-nums">{c.neededToPass} {c.neededToPass === 1 ? 'class' : 'classes'}</strong> to recover.</span>
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
              className={`flex flex-col justify-between rounded-xl border bg-surface p-4 shadow-xs transition ${
                c.isDeficit
                  ? 'border-rose-border ring-1 ring-rose-bg'
                  : c.isBorderline
                  ? 'border-warning-bg ring-1 ring-warning-bg/50'
                  : 'border-border'
              }`}
            >
              <div>
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <h3 className="font-semibold text-base text-heading leading-snug">{c.cleanTitle}</h3>
                    <span className="text-xs text-muted block mt-0.5">{c.subject}</span>
                  </div>
                  <span
                    className={`shrink-0 text-xs font-semibold px-2.5 py-0.5 rounded-full tabular-nums ${
                      !c.hasAttendance
                        ? 'bg-surface-secondary text-muted border border-border'
                        : c.isDeficit
                        ? 'bg-rose-bg text-rose border border-rose-border'
                        : c.isBorderline
                        ? 'bg-warning-bg text-warning border border-warning'
                        : 'bg-success-bg text-success border border-success/30'
                    }`}
                  >
                    {c.hasAttendance ? `${c.pct}%` : 'No data'}
                  </span>
                </div>

                <div className="grid grid-cols-4 gap-1 py-2 border-y border-border-light text-center my-3">
                  <div>
                    <span className="text-xs text-muted block uppercase tracking-wider font-medium">Held</span>
                    <strong className="text-xs font-semibold text-heading tabular-nums">{c.hasCounts ? c.held : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-muted block uppercase tracking-wider font-medium">Present</span>
                    <strong className="text-xs font-semibold text-success tabular-nums">{c.hasCounts ? c.attended : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-muted block uppercase tracking-wider font-medium">Absent</span>
                    <strong className="text-xs font-semibold text-danger tabular-nums">{c.hasCounts ? c.absent : '—'}</strong>
                  </div>
                  <div>
                    <span className="text-xs text-muted block uppercase tracking-wider font-medium">Per week</span>
                    <strong className="text-xs font-medium text-muted tabular-nums">{c.weekly_schedule_available ? c.classesPerWeek : '—'}</strong>
                  </div>
                </div>

                <div className="w-full bg-border-input h-1.5 rounded-full overflow-hidden mb-3">
                  <div
                    className={`h-full rounded-full ${!c.hasAttendance ? 'bg-muted' : c.isDeficit ? 'bg-rose-500' : c.isBorderline ? 'bg-amber-500' : 'bg-emerald-500'}`}
                    style={{ width: `${c.hasAttendance ? Math.min(100, Math.max(0, c.pct)) : 0}%` }}
                  />
                </div>
              </div>

              <div
                className={`p-3 rounded-lg text-xs leading-relaxed border font-normal ${
                  !c.hasCounts
                  ? 'bg-surface-secondary border-border text-muted'
                  : c.isDeficit
                    ? 'bg-rose-bg border-rose-border text-rose'
                    : c.isBorderline
                    ? 'bg-warning-bg/40 border-warning-bg text-warning'
                    : 'bg-success-bg/40 border-success/20 text-success'
                }`}
              >
                {!c.hasCounts ? (
                  <span>{c.hasAttendance ? 'Exact class counts are needed for a recovery estimate.' : 'No attendance data is available.'}</span>
                ) : c.isDeficit ? (
                  <span>
                    <strong className="font-semibold">Action Required:</strong> Must attend next{' '}
                    <span className="font-semibold underline decoration-rose-300 tabular-nums">{c.neededToPass} classes</span> consecutively to clear examination threshold.
                  </span>
                ) : (
                  <span>
                    <strong className="font-semibold">Good Standing:</strong> Can afford to miss up to{' '}
                    <strong className="font-semibold tabular-nums">{c.canAffordToMiss} {c.canAffordToMiss === 1 ? 'class' : 'classes'}</strong> before dropping below 75%.
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
