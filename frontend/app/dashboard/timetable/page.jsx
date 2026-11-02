'use client';

import { useCallback, useMemo, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const EMPTY_CLASSES = [];

export default function TimetablePage() {
  const { getToken, userId } = useAuth();
  const ownerKey = getQueryOwnerKey(userId);
  const classesKey = ['timetable', 'classes', ownerKey];
  const portalSettingsKey = ['portal', 'settings', ownerKey];
  const classesQuery = useQuery({
    queryKey: classesKey,
    queryFn: async ({ signal }) => api.getTimetableClasses(await api.getRequestToken(getToken), { signal, direct: true }),
  });
  const portalSettingsQuery = useQuery({
    queryKey: portalSettingsKey,
    queryFn: async ({ signal }) => api.getPortalSettings(await api.getRequestToken(getToken), { signal, direct: true }),
  });
  const { refetch: refetchClasses } = classesQuery;
  const { refetch: refetchPortalSettings } = portalSettingsQuery;
  const classes = classesQuery.data || EMPTY_CLASSES;
  const portalSettings = portalSettingsQuery.data || null;
  const loading = classesQuery.isPending;
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState(null);
  const [updating, setUpdating] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  // 0 = Monday, 1 = Tuesday, ..., 6 = Sunday
  const currentDayOfWeek = useMemo(() => {
    const d = new Date().getDay();
    return d === 0 ? 6 : d - 1;
  }, []);

  const [showAddModal, setShowAddModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [clearing, setClearing] = useState(false);
  const [deleting, setDeleting] = useState(false);
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
    await Promise.allSettled([refetchClasses(), refetchPortalSettings()]);
  }, [refetchClasses, refetchPortalSettings]);
  const visibleError = error || (classesQuery.isError ? classesQuery.error?.message || 'Could not load timetable schedule.' : '');

  const handleSyncPortal = async () => {
    setSyncing(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      const res = await api.syncPortalHeadless(token, true);
      api.clearCache('timetable');
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

  const updateField = (key, value) => setForm((curr) => ({ ...curr, [key]: value }));

  const handleAddClass = async (e) => {
    e.preventDefault();
    if (!form.subject.trim()) {
      setError('Enter a class or lab name before saving.');
      return;
    }
    if (form.end_time <= form.start_time) {
      setError('End time must be later than start time.');
      return;
    }
    if (!form.weekdays.length) {
      setError('Choose at least one day for this class.');
      return;
    }
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      await api.saveTimetableClasses(
        [{
          subject: form.subject.trim(),
          weekdays: form.weekdays,
          start_time: form.start_time,
          end_time: form.end_time,
          teacher: form.teacher.trim() || null,
          room: form.room.trim() || null,
        }],
        token,
        false
      );
      await loadData();
      setForm({
        subject: '',
        weekdays: [currentDayOfWeek],
        start_time: '09:00',
        end_time: '09:50',
        teacher: '',
        room: '',
      });
      setShowAddModal(false);
      setNotice('Class added to your timetable.');
    } catch (err) {
      setError(err.message || 'Could not save the lecture.');
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveClass = (item) => {
    setError('');
    setNotice('');
    setDeleteTarget(item);
  };

  const confirmDeleteClass = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      await api.deleteTimetableClass(deleteTarget.id, token);
      await loadData();
      setNotice(`Deleted ${deleteTarget.subject || 'class'} from your timetable.`);
      setDeleteTarget(null);
    } catch (err) {
      setError(err.message || 'Could not remove lecture.');
    } finally {
      setDeleting(false);
    }
  };

  const startEditing = (item) => {
    setError('');
    setNotice('');
    setEditingId(item.id);
    setEditForm({
      subject: item.subject || '',
      weekday: Number(item.weekday),
      start_time: item.start_time || '09:00',
      end_time: item.end_time || '09:50',
      teacher: item.teacher || '',
      room: item.room || '',
      semester_name: item.semester_name || '',
      semester_start: item.semester_start || null,
      semester_end: item.semester_end || null,
    });
  };

  const updateEditField = (key, value) => setEditForm((current) => ({ ...current, [key]: value }));

  const handleUpdateClass = async (id) => {
    if (!editForm?.subject.trim()) {
      setError('Enter a class or lab name before saving.');
      return;
    }
    if (editForm.end_time <= editForm.start_time) {
      setError('End time must be later than start time.');
      return;
    }

    setUpdating(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      await api.updateTimetableClass(id, {
        subject: editForm.subject.trim(),
        weekdays: [Number(editForm.weekday)],
        start_time: editForm.start_time,
        end_time: editForm.end_time,
        teacher: editForm.teacher.trim(),
        room: editForm.room.trim(),
        semester_name: editForm.semester_name,
        semester_start: editForm.semester_start,
        semester_end: editForm.semester_end,
      }, token);
      await loadData();
      setEditingId(null);
      setEditForm(null);
      setNotice('Class updated.');
    } catch (err) {
      setError(err.message || 'Could not update this class.');
    } finally {
      setUpdating(false);
    }
  };

  const handleParseFile = async () => {
    if (!file) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
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
      const token = await api.getRequestToken(getToken);
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
    <main className="mx-auto w-full max-w-6xl space-y-6 pb-10 font-sans text-heading">
      <header className="flex flex-col justify-between gap-4 border-b border-border-light pb-5 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-muted">Your weekly schedule</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-heading sm:text-3xl">Timetable</h1>
          <p className="mt-1.5 text-sm leading-6 text-muted">See when and where each class meets throughout the week. Portal updates only run when you start them here.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => setShowImportModal(true)} className="inline-flex h-10 items-center gap-2 rounded-lg border border-border-input bg-surface px-3.5 text-sm font-medium text-nav hover:bg-surface-secondary">
            <Icon name="upload" size={15} /> Import schedule
          </button>
          <button type="button" onClick={() => setShowAddModal(true)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-violet px-3.5 text-sm font-medium text-white hover:bg-violet-dark">
            <Icon name="fileAdd" size={15} /> Add class
          </button>
          <button type="button" disabled={syncing || loading} onClick={handleSyncPortal} className="inline-flex h-10 items-center gap-2 rounded-lg border border-border-input bg-surface px-3.5 text-sm font-medium text-nav hover:bg-surface-secondary disabled:opacity-50">
            <Icon name="refresh" size={15} className={syncing ? 'animate-spin' : ''} />
            {syncing ? 'Syncing…' : 'Sync portal'}
          </button>
        </div>
      </header>

      {visibleError && <div role="alert" className="flex items-center gap-2 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose"><Icon name="alert" size={15} />{visibleError}</div>}
      {notice && <div role="status" className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-bg px-4 py-3 text-sm text-success"><Icon name="check" size={15} />{notice}</div>}

      {portalSettings?.url && (
        <section aria-label="University portal sync status" className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface px-4 py-3 text-sm">
          <span className={`size-2 rounded-full ${portalSettings.session_status === 'ACTIVE' ? 'bg-success' : 'bg-muted'}`} />
          <span className="font-medium text-heading">University portal</span>
          <span className="text-muted">{portalSettings.session_status?.replaceAll('_', ' ').toLowerCase() || 'status unavailable'}</span>
          {portalSettings.last_synced_at && <span className="text-muted">Last synced {new Date(portalSettings.last_synced_at).toLocaleString()}</span>}
          <Link className="ml-auto font-medium text-violet no-underline hover:text-violet-dark" href="/dashboard/portal">Portal settings →</Link>
        </section>
      )}

      <section aria-label="Weekly schedule summary" className="flex flex-wrap items-center gap-x-8 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3.5 text-sm text-muted">
        <span><strong className="font-semibold text-heading tabular-nums">{loading ? '—' : classes.length}</strong> {classes.length === 1 ? 'class' : 'classes'} this week</span>
        <span><strong className="font-semibold text-heading tabular-nums">{loading ? '—' : byDay.filter((day) => day.classes.length > 0).length}</strong> days with classes</span>
        {classes.length > 0 && <button type="button" disabled={clearing} onClick={() => setShowClearConfirm(true)} className="ml-auto inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-rose disabled:opacity-50"><Icon name="trash" size={14} />Clear timetable</button>}
      </section>

      <section aria-labelledby="weekly-schedule-heading" className="overflow-hidden rounded-xl border border-line bg-surface">
        <header className="flex items-center justify-between gap-3 border-b border-border-light px-5 py-4">
          <div>
            <h2 id="weekly-schedule-heading" className="text-base font-semibold text-heading">Weekly schedule</h2>
            <p className="mt-0.5 text-sm text-muted">Classes are listed by day and start time.</p>
          </div>
          {!loading && <span className="rounded-md bg-surface-secondary px-2.5 py-1 text-xs font-medium text-muted tabular-nums">{classes.length} total</span>}
        </header>
        {loading ? (
          <div className="px-5 py-12 text-center text-sm text-muted">Loading weekly schedule…</div>
        ) : classes.length === 0 ? (
          <div className="px-5 py-14 text-center">
            <span className="mx-auto grid size-11 place-items-center rounded-full bg-surface-secondary text-muted"><Icon name="calendar" size={20} /></span>
            <h3 className="mt-3 text-sm font-semibold text-heading">No classes in your timetable</h3>
            <p className="mx-auto mt-1 max-w-md text-sm leading-5 text-muted">Add classes manually, import your schedule, or sync it from your university portal.</p>
            <button type="button" onClick={() => setShowAddModal(true)} className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg bg-violet px-3.5 text-sm font-medium text-white hover:bg-violet-dark"><Icon name="fileAdd" size={14} />Add a class</button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-left text-sm">
              <thead className="bg-surface-secondary text-xs font-medium uppercase tracking-wide text-muted">
                <tr>
                  <th scope="col" className="w-40 px-5 py-3">Time</th>
                  <th scope="col" className="px-5 py-3">Class</th>
                  <th scope="col" className="w-56 px-5 py-3">Instructor</th>
                  <th scope="col" className="w-40 px-5 py-3">Room</th>
                  <th scope="col" className="w-36 px-5 py-3 text-right">Actions</th>
                </tr>
              </thead>
              {byDay.map((day) => (
                <tbody key={day.name} className="divide-y divide-border-light">
                  <tr className="border-y border-border-light bg-surface-secondary/70">
                    <th scope="rowgroup" colSpan={5} className="px-5 py-2.5 text-left">
                      <span className="font-semibold text-heading">{day.name}</span>
                      <span className="ml-2 font-normal text-muted">{day.classes.length} {day.classes.length === 1 ? 'class' : 'classes'}</span>
                    </th>
                  </tr>
                  {day.classes.length ? day.classes.map((item) => {
                    const isEditing = editingId === item.id;
                    return (
                      <tr key={item.id} className="group hover:bg-surface-secondary/40">
                        <td className="px-5 py-3.5">
                          {isEditing ? (
                            <div className="space-y-2">
                              <select aria-label="Class day" value={editForm.weekday} onChange={(event) => updateEditField('weekday', event.target.value)} className="h-9 w-full rounded-md border border-border-input bg-surface px-2 text-sm text-heading focus:border-violet focus:outline-none">
                                {WEEKDAYS.map((name, weekday) => <option key={name} value={weekday}>{name}</option>)}
                              </select>
                              <input aria-label="Start time" type="time" value={editForm.start_time} onChange={(event) => updateEditField('start_time', event.target.value)} className="h-9 w-full rounded-md border border-border-input bg-surface px-2 text-sm tabular-nums text-heading focus:border-violet focus:outline-none" />
                              <input aria-label="End time" type="time" value={editForm.end_time} onChange={(event) => updateEditField('end_time', event.target.value)} className="h-9 w-full rounded-md border border-border-input bg-surface px-2 text-sm tabular-nums text-heading focus:border-violet focus:outline-none" />
                            </div>
                          ) : <span className="whitespace-nowrap font-medium text-body tabular-nums">{item.start_time || '—'}{item.end_time ? ` – ${item.end_time}` : ''}</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          {isEditing ? <input aria-label="Class or lab name" autoFocus value={editForm.subject} onChange={(event) => updateEditField('subject', event.target.value)} className="h-9 w-full min-w-48 rounded-md border border-border-input bg-surface px-2.5 text-sm font-medium text-heading focus:border-violet focus:outline-none" /> : <span className="font-medium text-heading">{item.subject || 'Untitled class'}</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          {isEditing ? <input aria-label="Instructor" value={editForm.teacher} onChange={(event) => updateEditField('teacher', event.target.value)} className="h-9 w-full min-w-36 rounded-md border border-border-input bg-surface px-2.5 text-sm text-heading focus:border-violet focus:outline-none" /> : <span className="text-muted">{item.teacher || '—'}</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          {isEditing ? <input aria-label="Room" value={editForm.room} onChange={(event) => updateEditField('room', event.target.value)} className="h-9 w-full min-w-24 rounded-md border border-border-input bg-surface px-2.5 text-sm text-heading focus:border-violet focus:outline-none" /> : <span className="text-muted">{item.room || '—'}</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          {isEditing ? (
                            <div className="flex items-center justify-end gap-2">
                              <button type="button" disabled={updating} onClick={() => handleUpdateClass(item.id)} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-violet px-2.5 text-xs font-medium text-white hover:bg-violet-dark disabled:opacity-50"><Icon name="check" size={13} />{updating ? 'Saving…' : 'Save'}</button>
                              <button type="button" disabled={updating} onClick={() => { setEditingId(null); setEditForm(null); setError(''); }} className="h-8 rounded-md border border-border-input px-2.5 text-xs font-medium text-nav hover:bg-surface-secondary disabled:opacity-50">Cancel</button>
                            </div>
                          ) : (
                            <div className="flex items-center justify-end gap-1">
                              <button type="button" onClick={() => startEditing(item)} aria-label={`Edit ${item.subject || 'class'} on ${day.name}`} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-input bg-surface px-2.5 text-xs font-medium text-nav hover:border-violet/40 hover:bg-violet-light hover:text-violet"><Icon name="edit" size={13} />Edit</button>
                              <button type="button" onClick={() => handleRemoveClass(item)} aria-label={`Delete ${item.subject || 'class'} from ${day.name}`} title="Delete class" className="grid size-8 place-items-center rounded-md border border-border-input bg-surface text-muted hover:border-rose-border hover:bg-rose-bg hover:text-rose"><Icon name="trash" size={14} /></button>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  }) : (
                    <tr><td colSpan={5} className="px-5 py-3 text-sm text-muted">No classes scheduled</td></tr>
                  )}
                </tbody>
              ))}
            </table>
          </div>
        )}
      </section>
      {/* Add Lecture Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-surface rounded-2xl max-w-md w-full p-6 shadow-xl border border-border animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-border-light mb-4">
              <h3 className="font-semibold text-heading text-base">Add class</h3>
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
                {saving ? 'Saving…' : 'Save class'}
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
              <p className="text-sm text-muted leading-relaxed">
                Upload a timetable image or PDF to extract class days, times, instructors, and rooms. Imported classes replace your current timetable.
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

      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs">
          <section role="dialog" aria-modal="true" aria-labelledby="delete-class-heading" className="w-full max-w-sm rounded-xl border border-line bg-surface p-5 shadow-xl">
            <h2 id="delete-class-heading" className="text-base font-semibold text-heading">Delete this class?</h2>
            <p className="mt-2 text-sm leading-5 text-muted">This removes <strong className="font-medium text-heading">{deleteTarget.subject}</strong> from your timetable. This action cannot be undone.</p>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" disabled={deleting} onClick={() => setDeleteTarget(null)} className="h-9 rounded-lg border border-border-input px-3 text-sm font-medium text-nav hover:bg-surface-secondary disabled:opacity-50">Cancel</button>
              <button type="button" disabled={deleting} onClick={confirmDeleteClass} className="h-9 rounded-lg bg-rose px-3 text-sm font-medium text-white hover:bg-rose/90 disabled:opacity-50">{deleting ? 'Deleting…' : 'Delete class'}</button>
            </div>
          </section>
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
