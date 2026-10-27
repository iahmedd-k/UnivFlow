'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export default function TimetablePage() {
  const { getToken } = useAuth();
  const [classes, setClasses] = useState([]);
  const [portalSettings, setPortalSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // 0 = Monday, 1 = Tuesday, ..., 6 = Sunday
  const currentDayOfWeek = useMemo(() => {
    const d = new Date().getDay();
    return d === 0 ? 6 : d - 1;
  }, []);

  const [selectedDay, setSelectedDay] = useState(currentDayOfWeek);
  const [viewMode, setViewMode] = useState('rows'); // 'rows' (default) | 'day' | 'table'
  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [form, setForm] = useState({
    subject: '',
    weekdays: [currentDayOfWeek],
    start_time: '09:00',
    end_time: '09:50',
    teacher: '',
    room: '',
  });
  const [file, setFile] = useState(null);

  const loadData = useCallback(async () => {
    try {
      const token = getToken ? await getToken() : null;
      const [allClasses, portalData] = await Promise.all([
        api.getTimetableClasses(token),
        api.getPortalSettings(token).catch(() => null),
      ]);
      setClasses(allClasses || []);
      setPortalSettings(portalData || null);
    } catch (err) {
      setError(err.message || 'Could not load timetable schedule.');
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
      if (res?.status === 'session_expired') {
        setError('University portal session expired. Reconnect via Portal tab.');
      } else {
        setNotice('Timetable and course schedule refreshed from University Portal.');
      }
    } catch (err) {
      setError(err.message || 'Could not sync timetable from university portal.');
    } finally {
      setSyncing(false);
    }
  };

  const byDay = useMemo(() => {
    return WEEKDAYS.map((name, weekday) => {
      const dayClasses = classes.filter((entry) => Number(entry.weekday) === weekday);
      dayClasses.sort((a, b) => (a.start_time || '').localeCompare(b.start_time || ''));
      return {
        name,
        weekday,
        classes: dayClasses,
      };
    });
  }, [classes]);

  const activeDayClasses = useMemo(() => {
    return byDay[selectedDay]?.classes || [];
  }, [byDay, selectedDay]);

  const nextScheduledDay = useMemo(() => {
    for (let offset = 1; offset < WEEKDAYS.length; offset += 1) {
      const weekday = (selectedDay + offset) % WEEKDAYS.length;
      if (byDay[weekday]?.classes.length) return byDay[weekday];
    }
    return null;
  }, [byDay, selectedDay]);

  const todaysSchedule = useMemo(() => {
    return byDay[currentDayOfWeek]?.classes || [];
  }, [byDay, currentDayOfWeek]);

  // Official university matrix table grouping courses to weekday time-slots
  const matrixRows = useMemo(() => {
    const courseMap = new Map();
    classes.forEach((c) => {
      const key = (c.subject || '').trim();
      if (!key) return;
      if (!courseMap.has(key)) {
        const isLab = key.toLowerCase().includes('lab');
        courseMap.set(key, {
          subject: key,
          teacher: c.teacher || '',
          room: c.room || '',
          isLab,
          days: { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [] },
        });
      }
      const item = courseMap.get(key);
      if (c.teacher && !item.teacher) {
        item.teacher = c.teacher;
      }
      if (c.room && !item.room) {
        item.room = c.room;
      }
      const slotTime = `${c.start_time} – ${c.end_time}`;
      const dayNum = Number(c.weekday);
      if (item.days[dayNum]) {
        const exists = item.days[dayNum].some(
          (s) => (typeof s === 'string' ? s : s.time) === slotTime
        );
        if (!exists) {
          item.days[dayNum].push({
            time: slotTime,
            room: c.room ? c.room.trim() : '',
          });
        }
      }
    });
    return Array.from(courseMap.values());
  }, [classes]);

  const nextClassToday = useMemo(() => {
    if (!todaysSchedule.length) return null;
    const now = new Date();
    const currentMinutes = now.getHours() * 60 + now.getMinutes();
    return todaysSchedule.find((item) => {
      if (!item.start_time) return false;
      const [hours, minutes] = item.start_time.split(':').map(Number);
      const startMinutes = hours * 60 + minutes;
      return Number.isFinite(startMinutes) && startMinutes >= currentMinutes;
    }) || null;
  }, [todaysSchedule]);

  const updateField = (key, value) => setForm((curr) => ({ ...curr, [key]: value }));

  const handleAddClass = async (e) => {
    e.preventDefault();
    if (!form.subject.trim()) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      await api.saveTimetableClasses(
        form.weekdays.map((w) => ({
          subject: form.subject.trim(),
          weekday: w,
          start_time: form.start_time,
          end_time: form.end_time,
          teacher: form.teacher.trim() || null,
          room: form.room.trim() || null,
        })),
        token
      );
      await loadData();
      setForm({
        subject: '',
        weekdays: [selectedDay],
        start_time: '09:00',
        end_time: '09:50',
        teacher: '',
        room: '',
      });
      setShowAddModal(false);
      setNotice('Lecture successfully added to your weekly routine.');
    } catch (err) {
      setError(err.message || 'Could not save the lecture.');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveClass = async (id, subject) => {
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      await api.deleteTimetableClass(id, token);
      await loadData();
      setNotice(`Removed ${subject || 'lecture'} from routine.`);
    } catch (err) {
      setError(err.message || 'Could not remove lecture.');
    }
  };

  const handleParseFile = async () => {
    if (!file) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      const res = await api.parseTimetableImage(file, token);
      await loadData();
      setNotice(res.message || `Imported ${res.saved_count || 0} classes from timetable image.`);
      setFile(null);
      setShowImportModal(false);
    } catch (err) {
      setError(err.message || 'Could not extract timetable from image.');
    } finally {
      setSaving(false);
    }
  };

  const handleClearTimetable = async () => {
    setClearing(true);
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      await api.clearAllTimetableClasses(token);
      await loadData();
      setShowClearConfirm(false);
      setNotice('Weekly timetable cleared successfully.');
    } catch (err) {
      setError(err.message || 'Could not clear timetable.');
    } finally {
      setClearing(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-heading">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">YOUR SEMESTER</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">Timetable</h1>
          <p className="text-sm font-normal text-muted leading-relaxed">See your classes by day or get a full week overview.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-border bg-surface p-1" role="group" aria-label="Timetable view">
            <button type="button" onClick={() => setViewMode('rows')} className={`rounded-md px-3 py-1.5 text-sm font-medium transition cursor-pointer ${viewMode === 'rows' ? 'bg-ink text-white font-semibold shadow-xs' : 'text-nav hover:bg-surface-secondary'}`} aria-pressed={viewMode === 'rows'}>Schedule (Rows)</button>
            <button type="button" onClick={() => setViewMode('day')} className={`rounded-md px-3 py-1.5 text-sm font-medium transition cursor-pointer ${viewMode === 'day' ? 'bg-ink text-white font-semibold shadow-xs' : 'text-nav hover:bg-surface-secondary'}`} aria-pressed={viewMode === 'day'}>Day View</button>
            <button type="button" onClick={() => setViewMode('table')} className={`rounded-md px-3 py-1.5 text-sm font-medium transition cursor-pointer ${viewMode === 'table' ? 'bg-ink text-white font-semibold shadow-xs' : 'text-nav hover:bg-surface-secondary'}`} aria-pressed={viewMode === 'table'}>Matrix</button>
          </div>
          <button type="button" onClick={() => setShowImportModal(true)} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-border-input bg-surface px-3 text-sm font-medium text-nav hover:bg-surface-secondary"><Icon name="upload" size={15} />Import</button>
          <button type="button" onClick={() => setShowAddModal(true)} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-violet px-3 text-sm font-medium text-white hover:bg-violet-dark"><Icon name="fileAdd" size={15} />Add class</button>
          <button type="button" disabled={syncing || loading} onClick={handleSyncPortal} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-border-input bg-surface px-3 text-sm font-medium text-nav hover:bg-surface-secondary disabled:opacity-50">
            <Icon name="refresh" size={15} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync'}
          </button>
          <button
            type="button"
            disabled={classes.length === 0 || loading || clearing}
            onClick={() => setShowClearConfirm(true)}
            className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-rose-border bg-surface px-3 text-sm font-medium text-rose hover:bg-rose-bg disabled:opacity-50"
            title="Clear all classes from timetable"
          >
            <Icon name="trash" size={14} />
            {clearing ? 'Clearing…' : 'Clear Timetable'}
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

      {portalSettings?.url && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-muted">
          <span className={`h-2 w-2 rounded-full ${portalSettings.session_status === 'ACTIVE' ? 'bg-success' : 'bg-muted'}`} />
          <span><strong className="font-semibold text-heading">University portal</strong> · {portalSettings.session_status?.replaceAll('_', ' ').toLowerCase() || 'status unavailable'}</span>
          {portalSettings.last_synced_at && <span className="text-subtle tabular-nums">Synced {new Date(portalSettings.last_synced_at).toLocaleString()}</span>}
          <Link className="ml-auto font-medium text-violet hover:underline text-sm" href="/dashboard/portal">Portal settings <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      )}

      <section className="flex flex-wrap gap-x-8 gap-y-2 rounded-xl border border-border bg-surface px-4 py-3 text-sm text-muted" aria-label="Weekly schedule summary">
        <span><strong className="font-semibold text-heading tabular-nums">{loading ? '—' : classes.length}</strong> scheduled {classes.length === 1 ? 'class' : 'classes'} this week</span>
        <span><strong className="font-semibold text-heading tabular-nums">{loading ? '—' : byDay.filter((day) => day.classes.length > 0).length}</strong> of 7 days have classes</span>
      </section>

      {nextClassToday && (
        <section className="flex flex-wrap items-center gap-3 rounded-xl border border-violet-light bg-violet-light/50 p-4">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-violet shadow-xs"><Icon name="clock" size={18} /></span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <small className="text-xs font-medium text-violet uppercase tracking-wider">Up next today · <span className="tabular-nums">{nextClassToday.start_time}–{nextClassToday.end_time}</span></small>
            <strong className="text-base font-semibold text-heading">{nextClassToday.subject}</strong>
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-dark bg-white px-2.5 py-1 rounded-md border border-violet-light">
            <Icon name="school" size={14} />
            Room: {nextClassToday.room && nextClassToday.room.trim() ? nextClassToday.room : '-'}
          </span>
          {nextClassToday.teacher && <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted"><Icon name="graduation" size={14} />{nextClassToday.teacher}</span>}
        </section>
      )}

      {/* Day Selector Pill Navigation (Day View) */}
      {viewMode === 'day' && (
        <div className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-6 border-b border-border-light">
          {WEEKDAYS.map((dayName, idx) => {
            const isToday = idx === currentDayOfWeek;
            const isSelected = idx === selectedDay;
            const count = byDay[idx]?.classes.length || 0;
            return (
              <button
                key={dayName}
                type="button"
                onClick={() => setSelectedDay(idx)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition whitespace-nowrap ${
                  isSelected
                    ? 'bg-ink text-white font-semibold shadow-xs'
                    : 'bg-surface text-nav hover:bg-surface-secondary border border-border'
                }`}
              >
                <span>{dayName}</span>
                {isToday && (
                  <span className={`text-xs px-2 py-0.5 rounded-full font-semibold uppercase ${
                    isSelected ? 'bg-surface-secondary text-ink' : 'bg-violet-light text-violet'
                  }`}>
                    Today
                  </span>
                )}
                <span className={`text-xs px-2 py-0.5 rounded-full tabular-nums ${
                  isSelected ? 'bg-surface/20 text-white' : 'bg-surface-secondary text-muted'
                }`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Main View Area */}
      {loading ? (
        <div className="p-12 text-center text-sm font-normal text-muted bg-surface rounded-xl border border-border">
          Loading timetable routine…
        </div>
      ) : viewMode === 'table' ? (
        /* Official University Portal Matrix Table */
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm border-collapse">
              <thead>
                <tr className="bg-surface-secondary border-b border-border text-muted font-medium text-xs uppercase tracking-wider">
                  <th className="py-3 px-4">Course</th>
                  <th className="py-3 px-4">Instructor</th>
                  {WEEKDAYS.map((day) => <th key={day} className="py-3 px-3 text-center">{day}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-border-light">
                {matrixRows.length === 0 ? (
                  <tr>
                    <td colSpan={WEEKDAYS.length + 2} className="py-12 text-center text-sm font-normal text-muted">
                      No timetable records found.
                    </td>
                  </tr>
                ) : (
                  matrixRows.map((row) => (
                    <tr key={row.subject} className="hover:bg-surface-secondary/70 transition">
                      <td className="py-3.5 px-4 font-semibold text-sm text-heading">
                        <div className="leading-snug">{row.subject}</div>
                        <span className={`inline-block mt-1 px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wider ${row.isLab ? 'bg-violet-light text-violet' : 'bg-surface-secondary text-muted'}`}>
                          {row.isLab ? 'Lab' : 'Course'}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-muted text-sm font-normal">{row.teacher || 'Not provided'}</td>
                      {WEEKDAYS.map((_, d) => {
                        const slots = row.days[d] || [];
                        return (
                          <td key={d} className="py-3.5 px-3 text-center align-middle">
                            {slots.length > 0 ? (
                              <div className="flex flex-col items-center gap-1">
                                {slots.map((s, i) => {
                                  const timeStr = typeof s === 'string' ? s : s.time;
                                  const roomStr = typeof s === 'object' && s.room ? s.room : '';
                                  return (
                                    <div
                                      key={i}
                                      className="inline-flex flex-col items-center px-2.5 py-1 rounded-md bg-surface-secondary text-xs font-medium tabular-nums text-heading border border-border-input"
                                    >
                                      <span>{timeStr}</span>
                                      <span className="text-[11px] font-normal text-muted mt-0.5">
                                        Room: {roomStr && roomStr.trim() ? roomStr : '-'}
                                      </span>
                                    </div>
                                  );
                                })}
                              </div>
                            ) : (
                              <span className="text-subtle font-normal tabular-nums">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : viewMode === 'day' ? (
        /* Single Day Timeline View */
        <div className="space-y-3">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-lg font-semibold text-heading">
              {WEEKDAYS[selectedDay]} Classes
            </h2>
            <span className="text-xs font-normal text-muted tabular-nums">
              {activeDayClasses.length} {activeDayClasses.length === 1 ? 'lecture' : 'lectures'} scheduled
            </span>
          </div>

          {activeDayClasses.length > 0 ? (
            <div className="space-y-2.5">
              {activeDayClasses.map((item) => (
                <div
                  key={item.id}
                  className="group flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-xs transition hover:border-border-hover max-sm:items-start"
                >
                  <div className="flex min-w-0 items-center gap-3.5">
                    {/* Time Slot Badge */}
                    <div className="px-3 py-2 rounded-lg bg-surface-secondary text-heading text-xs font-medium tabular-nums shrink-0 text-center border border-border-input">
                      <div>{item.start_time}</div>
                      <div className="text-xs text-muted font-normal">to {item.end_time}</div>
                    </div>

                    {/* Course Details */}
                    <div className="min-w-0">
                      <h3 className="font-semibold text-base text-heading leading-snug">
                        {item.subject}
                      </h3>
                      <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-muted">
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-surface-secondary border border-border-input font-medium text-heading">
                          <Icon name="school" size={12} />
                          Room: {item.room && item.room.trim() ? item.room : '-'}
                        </span>
                        {item.teacher && (
                          <span className="inline-flex items-center gap-1 text-muted">
                            <Icon name="graduation" size={12} />
                            {item.teacher}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Right Actions */}
                  <div className="ml-auto flex shrink-0 items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => handleRemoveClass(item.id, item.subject)}
                      className="opacity-0 group-hover:opacity-100 transition p-1.5 text-muted hover:text-rose rounded-md hover:bg-rose-bg"
                      title="Remove from routine"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-xl border border-border bg-surface p-5 max-sm:flex-wrap max-sm:items-start">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-surface-secondary text-muted">
                <Icon name="calendar" size={18} />
              </div>
              <div>
                <p className="m-0 text-base font-semibold text-heading">No classes on {WEEKDAYS[selectedDay]}</p>
                <p className="mt-1 text-sm font-normal text-muted leading-relaxed">
                  Add a class for this day or check your next scheduled day.
                </p>
              </div>
              {nextScheduledDay && (
                <button
                  type="button"
                  className="ml-auto inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-lg border border-border-input px-3 py-2 text-sm font-medium text-violet hover:bg-violet-light max-sm:ml-[51px]"
                  onClick={() => setSelectedDay(nextScheduledDay.weekday)}
                >
                  View {nextScheduledDay.name} <span className="font-normal text-muted tabular-nums">{nextScheduledDay.classes.length} {nextScheduledDay.classes.length === 1 ? 'class' : 'classes'}</span>
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Row-Level Week Routine View (Monday with all schedule along it, Tuesday below, Wednesday below, etc.) */
        <div className="flex flex-col gap-3.5">
          {byDay.map((day) => {
            const isToday = day.weekday === currentDayOfWeek;
            const hasClasses = day.classes.length > 0;

            return (
              <section
                key={day.name}
                className={`overflow-hidden rounded-2xl border transition-all ${
                  isToday
                    ? 'border-violet/40 bg-gradient-to-r from-violet-light/30 via-surface to-surface shadow-xs ring-1 ring-violet/20'
                    : 'border-border bg-surface hover:border-border-hover shadow-2xs'
                } p-4 sm:p-5`}
              >
                <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                  {/* Day Anchor Column (Left side of the row) */}
                  <div className="lg:w-44 shrink-0 flex lg:flex-col items-center lg:items-start justify-between lg:justify-center gap-1 pb-2 lg:pb-0 lg:pr-4 lg:border-r border-border-light">
                    <div className="flex items-center gap-2">
                      <h3 className={`m-0 text-base sm:text-lg font-bold tracking-tight ${isToday ? 'text-violet' : 'text-heading'}`}>
                        {day.name}
                      </h3>
                      {isToday && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-violet px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white shadow-2xs">
                          <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
                          Today
                        </span>
                      )}
                    </div>
                    <span className="text-xs font-normal text-muted tabular-nums">
                      {hasClasses ? `${day.classes.length} ${day.classes.length === 1 ? 'session' : 'sessions'}` : 'Free Day'}
                    </span>
                  </div>

                  {/* Along the day: Schedule Track / Cards along the row */}
                  <div className="flex-1 min-w-0">
                    {hasClasses ? (
                      <div className="flex items-stretch gap-3 overflow-x-auto pb-1.5 pt-0.5 scrollbar-thin">
                        {day.classes.map((c) => {
                          const isLab = c.subject?.toLowerCase().includes('lab') || (c.room && c.room.toLowerCase().includes('lab'));
                          const roomDisplay = c.room && c.room.trim() ? c.room : 'To be announced';

                          return (
                            <div
                              key={c.id}
                              className={`group relative flex flex-col justify-between rounded-xl border p-3.5 transition-all min-w-[240px] max-w-[290px] sm:min-w-[260px] shrink-0 ${
                                isLab
                                  ? 'border-emerald-200/70 bg-emerald-50/40 hover:border-emerald-400'
                                  : 'border-border-input bg-surface-secondary/60 hover:border-violet/40 hover:bg-surface-secondary'
                              } shadow-2xs hover:shadow-xs`}
                            >
                              {/* Top Bar: Time slot + Badge */}
                              <div className="flex items-center justify-between gap-2 text-xs mb-2">
                                <span className="inline-flex items-center gap-1 font-semibold text-heading tabular-nums bg-surface px-2 py-0.5 rounded-md border border-border-light shadow-2xs">
                                  <Icon name="clock" size={12} className={isLab ? 'text-emerald-600' : 'text-violet'} />
                                  <span>{c.start_time} – {c.end_time}</span>
                                </span>
                                <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded ${
                                  isLab ? 'bg-emerald-100 text-emerald-800' : 'bg-violet-light text-violet'
                                }`}>
                                  {isLab ? 'Lab' : 'Lecture'}
                                </span>
                              </div>

                              {/* Subject Title */}
                              <h4 className="text-sm font-bold text-heading leading-snug line-clamp-2 mb-2.5" title={c.subject}>
                                {c.subject}
                              </h4>

                              {/* Prominent Classroom / Room & Instructor Info */}
                              <div className="pt-2 border-t border-border-light/70 flex flex-col gap-1.5 text-xs">
                                <div className="inline-flex items-center gap-1.5 font-semibold text-heading bg-surface px-2 py-1 rounded-md border border-border-light">
                                  <span className="grid size-5 place-items-center rounded bg-violet-light text-violet shrink-0">
                                    <Icon name="school" size={11} />
                                  </span>
                                  <span className="text-xs">
                                    Room: <span className="text-violet-dark font-bold">{roomDisplay}</span>
                                  </span>
                                </div>
                                {c.teacher && (
                                  <div className="inline-flex items-center gap-1.5 text-muted text-[11px] truncate px-0.5">
                                    <Icon name="graduation" size={11} />
                                    <span className="truncate">{c.teacher}</span>
                                  </div>
                                )}
                              </div>

                              {/* Delete action button on hover */}
                              <button
                                type="button"
                                onClick={() => handleRemoveClass(c.id, c.subject)}
                                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition p-1 text-muted hover:text-rose rounded-md hover:bg-rose-bg bg-surface shadow-2xs border border-border-light cursor-pointer"
                                title="Remove from routine"
                              >
                                <Icon name="close" size={12} />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 py-2.5 px-3.5 rounded-xl border border-dashed border-border-input bg-surface-secondary/30 text-xs text-muted font-normal">
                        <Icon name="calendar" size={13} className="text-subtle" />
                        <span>No classes scheduled for {day.name} · Free day</span>
                      </div>
                    )}
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Add Lecture Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-surface rounded-2xl max-w-md w-full p-6 shadow-xl border border-border animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-border-light mb-4">
              <h3 className="font-semibold text-heading text-base">Add Lecture to Routine</h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-muted hover:text-heading"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <form onSubmit={handleAddClass} className="space-y-3">
              <div>
                <label className="text-sm font-medium text-heading block mb-1">Course Title *</label>
                <input
                  required
                  value={form.subject}
                  onChange={(e) => updateField('subject', e.target.value)}
                  placeholder="e.g. Distributed Database Systems"
                  className="w-full px-3 py-2 text-sm font-normal rounded-lg border border-border-input focus:outline-none focus:ring-2 focus:ring-violet/20"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-sm font-medium text-heading block mb-1">Start Time *</label>
                  <input
                    type="time"
                    required
                    value={form.start_time}
                    onChange={(e) => updateField('start_time', e.target.value)}
                    className="w-full px-3 py-2 text-sm font-normal rounded-lg border border-border-input tabular-nums"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-heading block mb-1">End Time *</label>
                  <input
                    type="time"
                    required
                    value={form.end_time}
                    onChange={(e) => updateField('end_time', e.target.value)}
                    className="w-full px-3 py-2 text-sm font-normal rounded-lg border border-border-input tabular-nums"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-sm font-medium text-heading block mb-1">Instructor</label>
                  <input
                    value={form.teacher}
                    onChange={(e) => updateField('teacher', e.target.value)}
                    placeholder="e.g. Dr. Ali Arshad"
                    className="w-full px-3 py-2 text-sm font-normal rounded-lg border border-border-input"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium text-heading block mb-1">Venue / Room</label>
                  <input
                    value={form.room}
                    onChange={(e) => updateField('room', e.target.value)}
                    placeholder="e.g. Lab 3"
                    className="w-full px-3 py-2 text-sm font-normal rounded-lg border border-border-input"
                  />
                </div>
              </div>
              <div>
                <label className="text-sm font-medium text-heading block mb-1.5">Lecture Days *</label>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((day, idx) => (
                    <label
                      key={day}
                      className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium border cursor-pointer select-none transition ${
                        form.weekdays.includes(idx)
                          ? 'bg-ink border-ink text-white'
                          : 'bg-surface border-border-input text-nav hover:bg-surface-secondary'
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={form.weekdays.includes(idx)}
                        onChange={(e) =>
                          updateField(
                            'weekdays',
                            e.target.checked
                              ? [...form.weekdays, idx].sort()
                              : form.weekdays.filter((v) => v !== idx)
                          )
                        }
                      />
                      <span>{day.slice(0, 3)}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-3 border-t border-border-light">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3 py-2 text-sm font-medium text-muted hover:text-heading"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !form.weekdays.length}
                  className="px-4 py-2 text-sm font-medium rounded-lg bg-ink text-white hover:bg-neutral-800 disabled:opacity-50 transition"
                >
                  {saving ? 'Saving…' : 'Save Lecture'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Import Image Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-neutral-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-neutral-100 mb-4">
              <h3 className="font-bold text-neutral-900 text-sm">Import Timetable Image</h3>
              <button
                type="button"
                onClick={() => setShowImportModal(false)}
                className="text-neutral-400 hover:text-neutral-700"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <div className="space-y-4">
              <p className="text-xs text-neutral-600 leading-relaxed">
                Upload a timetable image or PDF. Uniflow validates subject names, weekdays, and time slots with 100% precision. Validated classes will cleanly override and replace your current routine.
              </p>
              <label className="block">
                <span className="text-xs font-medium text-neutral-700 block mb-1">Select File</span>
                <input
                  type="file"
                  accept="image/*,.pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="block w-full text-xs text-neutral-500 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-neutral-100 file:text-neutral-700 hover:file:bg-neutral-200 transition"
                />
              </label>
              {file && (
                <div className="text-xs text-neutral-600 flex items-center gap-1.5 font-mono">
                  <Icon name="file" size={13} />
                  <span>{file.name}</span>
                </div>
              )}
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-neutral-100">
                <button
                  type="button"
                  onClick={() => setShowImportModal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-neutral-600 hover:text-neutral-900"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={saving || !file}
                  onClick={handleParseFile}
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-neutral-900 text-white hover:bg-neutral-800 disabled:opacity-50 transition"
                >
                  {saving ? 'Processing Image…' : 'Extract & Override'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Clear Timetable Confirmation Modal */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-sm w-full p-6 shadow-xl border border-neutral-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center gap-3 text-rose-600 mb-3">
              <span className="grid size-9 place-items-center rounded-xl bg-rose-50 text-rose-600"><Icon name="alert" size={18} /></span>
              <h3 className="font-bold text-neutral-900 text-sm">Clear Weekly Timetable?</h3>
            </div>
            <p className="text-xs text-neutral-600 leading-relaxed mb-5">
              This will permanently remove all {classes.length} scheduled lectures from your weekly routine. You can import an updated timetable or sync from your portal again whenever you like.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowClearConfirm(false)}
                className="px-3.5 py-2 text-xs font-medium text-neutral-600 hover:text-neutral-900"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={clearing}
                onClick={handleClearTimetable}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50 transition"
              >
                {clearing ? 'Clearing…' : 'Yes, Clear Timetable'}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
