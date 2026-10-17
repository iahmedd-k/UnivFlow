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
  const [viewMode, setViewMode] = useState('day'); // 'table' | 'day' | 'week'
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
      const token = await getToken();
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
          isLab,
          days: { 0: [], 1: [], 2: [], 3: [], 4: [], 5: [], 6: [] },
        });
      }
      const item = courseMap.get(key);
      if (c.teacher && !item.teacher) {
        item.teacher = c.teacher;
      }
      const slot = `${c.start_time} – ${c.end_time}`;
      const dayNum = Number(c.weekday);
      if (item.days[dayNum] && !item.days[dayNum].includes(slot)) {
        item.days[dayNum].push(slot);
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
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">YOUR SEMESTER</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Timetable</h1>
          <p className="mt-1 text-xs text-[#858998]">See your classes by day or get a full week overview.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-neutral-200 bg-white p-1" role="group" aria-label="Timetable view">
            <button type="button" onClick={() => setViewMode('table')} className={`rounded-md px-3 py-1.5 text-xs font-medium ${viewMode === 'table' ? 'bg-neutral-900 text-white' : 'text-neutral-600 hover:bg-neutral-100'}`} aria-pressed={viewMode === 'table'}>Matrix</button>
            <button type="button" onClick={() => setViewMode('day')} className={`rounded-md px-3 py-1.5 text-xs font-medium ${viewMode === 'day' ? 'bg-neutral-900 text-white' : 'text-neutral-600 hover:bg-neutral-100'}`} aria-pressed={viewMode === 'day'}>Day</button>
            <button type="button" onClick={() => setViewMode('week')} className={`rounded-md px-3 py-1.5 text-xs font-medium ${viewMode === 'week' ? 'bg-neutral-900 text-white' : 'text-neutral-600 hover:bg-neutral-100'}`} aria-pressed={viewMode === 'week'}>Week</button>
          </div>
          <button type="button" onClick={() => setShowImportModal(true)} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 hover:bg-neutral-50"><Icon name="upload" size={15} />Import</button>
          <button type="button" onClick={() => setShowAddModal(true)} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 text-xs font-semibold text-white hover:bg-indigo-700"><Icon name="fileAdd" size={15} />Add class</button>
          <button type="button" disabled={syncing || loading} onClick={handleSyncPortal} className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 text-xs font-semibold text-neutral-700 hover:bg-neutral-50 disabled:opacity-50">
            <Icon name="refresh" size={15} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync'}
          </button>
          <button
            type="button"
            disabled={classes.length === 0 || loading || clearing}
            onClick={() => setShowClearConfirm(true)}
            className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
            title="Clear all classes from timetable"
          >
            <Icon name="trash" size={14} />
            {clearing ? 'Clearing…' : 'Clear Timetable'}
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

      {portalSettings?.url && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-600">
          <span className={`h-2 w-2 rounded-full ${portalSettings.session_status === 'ACTIVE' ? 'bg-emerald-500' : 'bg-neutral-300'}`} />
          <span><strong>University portal</strong> · {portalSettings.session_status?.replaceAll('_', ' ').toLowerCase() || 'status unavailable'}</span>
          {portalSettings.last_synced_at && <span className="text-neutral-400">Synced {new Date(portalSettings.last_synced_at).toLocaleString()}</span>}
          <Link className="ml-auto font-medium text-indigo-600 hover:underline" href="/dashboard/portal">Portal settings <Icon name="arrowUpRight" size={13} /></Link>
        </div>
      )}

      <section className="flex flex-wrap gap-x-8 gap-y-2 rounded-xl border border-neutral-200 bg-white px-4 py-3 text-xs text-neutral-600" aria-label="Weekly schedule summary">
        <span><strong className="font-semibold text-neutral-900">{loading ? '—' : classes.length}</strong> scheduled {classes.length === 1 ? 'class' : 'classes'} this week</span>
        <span><strong className="font-semibold text-neutral-900">{loading ? '—' : byDay.filter((day) => day.classes.length > 0).length}</strong> of 7 days have classes</span>
      </section>

      {nextClassToday && (
        <section className="flex flex-wrap items-center gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-indigo-600 shadow-sm"><Icon name="clock" size={18} /></span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <small className="text-xs text-indigo-700">Up next today · {nextClassToday.start_time}–{nextClassToday.end_time}</small>
            <strong className="text-sm font-semibold text-indigo-950">{nextClassToday.subject}</strong>
          </div>
          {nextClassToday.room && <span className="inline-flex items-center gap-1.5 text-xs text-indigo-800"><Icon name="school" size={14} />{nextClassToday.room}</span>}
          {nextClassToday.teacher && <span className="inline-flex items-center gap-1.5 text-xs text-indigo-800"><Icon name="graduation" size={14} />{nextClassToday.teacher}</span>}
        </section>
      )}

      {/* Day Selector Pill Navigation (Day View) */}
      {viewMode === 'day' && (
        <div className="flex items-center gap-1.5 overflow-x-auto pb-2 mb-6 border-b border-neutral-100">
          {WEEKDAYS.map((dayName, idx) => {
            const isToday = idx === currentDayOfWeek;
            const isSelected = idx === selectedDay;
            const count = byDay[idx]?.classes.length || 0;
            return (
              <button
                key={dayName}
                type="button"
                onClick={() => setSelectedDay(idx)}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium transition whitespace-nowrap ${
                  isSelected
                    ? 'bg-neutral-900 text-white font-semibold shadow-xs'
                    : 'bg-white text-neutral-600 hover:bg-neutral-100 border border-neutral-200/60'
                }`}
              >
                <span>{dayName}</span>
                {isToday && (
                  <span className={`text-xs px-1.5 py-0.2 rounded-full font-bold uppercase ${
                    isSelected ? 'bg-neutral-700 text-neutral-100' : 'bg-neutral-100 text-neutral-600'
                  }`}>
                    Today
                  </span>
                )}
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                  isSelected ? 'bg-neutral-800 text-neutral-200' : 'bg-neutral-100 text-neutral-500'
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
        <div className="p-12 text-center text-xs text-neutral-400 bg-white rounded-xl border border-neutral-200">
          Loading timetable routine…
        </div>
      ) : viewMode === 'table' ? (
        /* Official University Portal Matrix Table */
        <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-neutral-50/80 border-b border-neutral-200 text-neutral-600 font-semibold text-xs uppercase tracking-wider">
                  <th className="py-3 px-4">Course</th>
                  <th className="py-3 px-4">Instructor</th>
                  {WEEKDAYS.map((day) => <th key={day} className="py-3 px-3 text-center">{day}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {matrixRows.length === 0 ? (
                  <tr>
                    <td colSpan={WEEKDAYS.length + 2} className="py-12 text-center text-xs text-neutral-400">
                      No timetable records found.
                    </td>
                  </tr>
                ) : (
                  matrixRows.map((row) => (
                    <tr key={row.subject} className="hover:bg-neutral-50/60 transition">
                      <td className="py-3.5 px-4 font-semibold text-neutral-900">
                        <div className="leading-snug">{row.subject}</div>
                        <span className={`inline-block mt-0.5 px-1.5 py-0.2 rounded text-xs font-semibold uppercase ${row.isLab ? 'bg-indigo-50 text-indigo-700' : 'bg-neutral-100 text-neutral-600'}`}>
                          {row.isLab ? 'Lab' : 'Course'}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-neutral-700 font-medium">{row.teacher || 'Not provided'}</td>
                      {WEEKDAYS.map((_, d) => {
                        const slots = row.days[d] || [];
                        return (
                          <td key={d} className="py-3.5 px-3 text-center">
                            {slots.length > 0 ? (
                              slots.map((s, i) => (
                                <span key={i} className="inline-block px-2 py-1 rounded bg-neutral-100 font-mono text-xs font-semibold text-neutral-800 my-0.5 whitespace-nowrap shadow-2xs">
                                  {s}
                                </span>
                              ))
                            ) : (
                              <span className="text-neutral-300 font-mono">—</span>
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
            <h2 className="text-sm font-bold text-neutral-900">
              {WEEKDAYS[selectedDay]} Classes
            </h2>
            <span className="text-xs text-neutral-500 font-mono">
              {activeDayClasses.length} {activeDayClasses.length === 1 ? 'lecture' : 'lectures'} scheduled
            </span>
          </div>

          {activeDayClasses.length > 0 ? (
            <div className="space-y-2.5">
              {activeDayClasses.map((item) => (
                <div
                  key={item.id}
                  className="group flex items-center gap-3 rounded-xl border border-neutral-200/90 bg-white p-4 shadow-2xs transition hover:border-neutral-300 max-sm:items-start"
                >
                  <div className="flex min-w-0 items-center gap-3.5">
                    {/* Time Slot Badge */}
                    <div className="px-3 py-2 rounded-lg bg-neutral-100 text-neutral-900 font-mono text-xs font-semibold shrink-0 text-center">
                      <div>{item.start_time}</div>
                      <div className="text-xs text-neutral-500 font-normal">to {item.end_time}</div>
                    </div>

                    {/* Course Details */}
                    <div className="min-w-0">
                      <h3 className="font-bold text-sm text-neutral-900 leading-snug">
                        {item.subject}
                      </h3>
                      <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-neutral-500">
                        {item.room && (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-neutral-50 border border-neutral-200/60 font-medium text-neutral-700">
                            <Icon name="school" size={11} />
                            {item.room}
                          </span>
                        )}
                        {item.teacher && (
                          <span className="inline-flex items-center gap-1 text-neutral-600">
                            <Icon name="graduation" size={11} />
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
                      className="opacity-0 group-hover:opacity-100 transition p-1.5 text-neutral-400 hover:text-rose-600 rounded-md hover:bg-rose-50"
                      title="Remove from routine"
                    >
                      <Icon name="close" size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-3 rounded-xl border border-neutral-200 bg-white p-4 max-sm:flex-wrap max-sm:items-start">
              <div className="grid h-[38px] w-[38px] shrink-0 place-items-center rounded-[10px] bg-neutral-100 text-neutral-500">
                <Icon name="calendar" size={18} />
              </div>
              <div>
                <p className="m-0 text-[13px] font-semibold text-neutral-800">No classes on {WEEKDAYS[selectedDay]}</p>
                <p className="mt-[3px] text-xs leading-normal text-neutral-500">
                  Add a class for this day or check your next scheduled day.
                </p>
              </div>
              {nextScheduledDay && (
                <button
                  type="button"
                  className="ml-auto inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-lg border border-neutral-200 px-2.5 py-2 text-xs font-semibold text-violet-700 hover:bg-violet-50 max-sm:ml-[51px]"
                  onClick={() => setSelectedDay(nextScheduledDay.weekday)}
                >
                  View {nextScheduledDay.name} <span className="font-medium text-neutral-500">{nextScheduledDay.classes.length} {nextScheduledDay.classes.length === 1 ? 'class' : 'classes'}</span>
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Full week agenda */
        <div className="flex flex-col gap-2.5">
          {byDay.map((day) => (
            <section
              key={day.name}
              className={`overflow-hidden rounded-xl border bg-white ${
                day.weekday === currentDayOfWeek
                  ? 'border-violet-300 shadow-sm'
                  : 'border-neutral-200'
              }`}
            >
              <header className="flex items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3">
                <h3 className="m-0 text-[13px] font-semibold text-neutral-800">{day.name}</h3>
                <div className="flex items-center gap-2">
                  {day.weekday === currentDayOfWeek && (
                    <span className="rounded-full bg-violet-50 px-2 py-0.5 text-xs font-semibold text-violet-700">Today</span>
                  )}
                  <span className="text-xs text-neutral-500">{day.classes.length} {day.classes.length === 1 ? 'class' : 'classes'}</span>
                </div>
              </header>

              {day.classes.length > 0 ? (
                <div className="flex flex-col">
                  {day.classes.map((c) => (
                    <div key={c.id} className="grid grid-cols-[105px_minmax(0,1fr)] items-center gap-3.5 border-b border-neutral-100 px-4 py-3 last:border-b-0 max-sm:grid-cols-[78px_minmax(0,1fr)] max-sm:gap-2.5 max-sm:px-3 max-sm:py-2.5">
                      <time className="flex flex-col gap-0.5 text-xs tabular-nums text-neutral-600">
                        <span>{c.start_time}</span>
                        <span>{c.end_time}</span>
                      </time>
                      <div className="flex min-w-0 flex-col gap-1">
                        <strong className="text-[13px] font-semibold leading-snug text-neutral-800 max-sm:text-xs">{c.subject}</strong>
                        {(c.room || c.teacher) && (
                          <span className="truncate text-xs text-neutral-500">
                            {[c.room, c.teacher].filter(Boolean).join(' · ')}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="m-0 px-4 py-3 text-xs text-neutral-500">No classes scheduled</p>
              )}
            </section>
          ))}
        </div>
      )}

      {/* Add Lecture Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-neutral-100 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-neutral-100 mb-4">
              <h3 className="font-bold text-neutral-900 text-sm">Add Lecture to Routine</h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-neutral-400 hover:text-neutral-700"
              >
                <Icon name="close" size={16} />
              </button>
            </div>
            <form onSubmit={handleAddClass} className="space-y-3">
              <div>
                <label className="text-xs font-medium text-neutral-700 block mb-1">Course Title *</label>
                <input
                  required
                  value={form.subject}
                  onChange={(e) => updateField('subject', e.target.value)}
                  placeholder="e.g. Distributed Database Systems"
                  className="w-full px-3 py-2 text-xs rounded-lg border border-neutral-200 focus:outline-none focus:ring-1 focus:ring-neutral-900"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">Start Time *</label>
                  <input
                    type="time"
                    required
                    value={form.start_time}
                    onChange={(e) => updateField('start_time', e.target.value)}
                    className="w-full px-3 py-1.5 text-xs rounded-lg border border-neutral-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">End Time *</label>
                  <input
                    type="time"
                    required
                    value={form.end_time}
                    onChange={(e) => updateField('end_time', e.target.value)}
                    className="w-full px-3 py-1.5 text-xs rounded-lg border border-neutral-200"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">Instructor</label>
                  <input
                    value={form.teacher}
                    onChange={(e) => updateField('teacher', e.target.value)}
                    placeholder="e.g. Dr. Ali Arshad"
                    className="w-full px-3 py-1.5 text-xs rounded-lg border border-neutral-200"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">Venue / Room</label>
                  <input
                    value={form.room}
                    onChange={(e) => updateField('room', e.target.value)}
                    placeholder="e.g. Lab 3"
                    className="w-full px-3 py-1.5 text-xs rounded-lg border border-neutral-200"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-neutral-700 block mb-1.5">Lecture Days *</label>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((day, idx) => (
                    <label
                      key={day}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border cursor-pointer select-none transition ${
                        form.weekdays.includes(idx)
                          ? 'bg-neutral-900 border-neutral-900 text-white'
                          : 'bg-white border-neutral-200 text-neutral-600 hover:bg-neutral-50'
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
              <div className="flex items-center justify-end gap-2 pt-3 border-t border-neutral-100">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-3 py-1.5 text-xs font-medium text-neutral-600 hover:text-neutral-900"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !form.weekdays.length}
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-neutral-900 text-white hover:bg-neutral-800 disabled:opacity-50 transition"
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
