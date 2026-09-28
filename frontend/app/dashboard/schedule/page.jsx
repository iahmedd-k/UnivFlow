'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

export default function SchedulePage() {
  const { getToken } = useAuth();
  const [classes, setClasses] = useState([]);
  const [upcomingClasses, setUpcomingClasses] = useState([]);
  const [attendance, setAttendance] = useState(null);
  const [activeTab, setActiveTab] = useState('timetable');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [form, setForm] = useState({ subject: '', weekdays: [0], start_time: '09:00', end_time: '10:00', teacher: '', room: '' });
  const [file, setFile] = useState(null);

  const load = useCallback(async () => {
    const token = await getToken();
    const [allClasses, attendanceData, upcomingData] = await Promise.all([api.getTimetableClasses(token), api.getAttendanceSummary(token), api.getUpcoming(7, token)]);
    setClasses(allClasses || []); setAttendance(attendanceData || null); setUpcomingClasses(upcomingData?.classes || []);
  }, [getToken]);

  useEffect(() => { load().catch((err) => setError(err.message || 'Could not load schedule.')).finally(() => setLoading(false)); }, [load]);

  const byDay = useMemo(() => weekdays.map((name, weekday) => ({ name, classes: classes.filter((entry) => Number(entry.weekday) === weekday) })), [classes]);
  const updateField = (key, value) => setForm((current) => ({ ...current, [key]: value }));

  const addClass = async (event) => {
    event.preventDefault(); setSaving(true); setError(''); setNotice('');
    try {
      const token = await getToken();
      await api.saveTimetableClasses([{ ...form, subject: form.subject.trim(), teacher: form.teacher.trim() || null, room: form.room.trim() || null }], token);
      await load(); setForm((current) => ({ ...current, subject: '', teacher: '', room: '' })); setNotice('Class added to your weekly timetable.');
    } catch (err) { setError(err.message || 'Could not save that class.'); }
    finally { setSaving(false); }
  };

  const removeClass = async (id) => {
    setError(''); setNotice('');
    try { const token = await getToken(); await api.deleteTimetableClass(id, token); await load(); }
    catch (err) { setError(err.message || 'Could not remove that class.'); }
  };

  const parseFile = async () => {
    if (!file) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const token = await getToken(); const result = await api.parseTimetableImage(file, token); await load();
      setNotice(result.message || `Imported ${result.saved_count || 0} classes from the timetable image.`); setFile(null);
    } catch (err) { setError(err.message || 'Could not read that timetable image.'); }
    finally { setSaving(false); }
  };

  return <main className="product-page pb-10">
    <header className="product-heading"><div><p className="eyebrow">ACADEMIC PLANNER</p><h1>Timetable & attendance</h1><p>Organize your weekly classes and keep track of course attendance.</p></div></header>
    {error && <div className="product-alert" role="alert">{error}</div>}{notice && <div className="product-alert ok" role="status">{notice}</div>}
    <section className="product-grid three">
      <article className="product-stat"><span>Weekly classes</span><strong>{loading ? '—' : classes.length}</strong></article>
      <article className="product-stat"><span>Attendance average</span><strong>{loading ? '—' : `${Number(attendance?.overall_attendance || 0).toFixed(0)}%`}</strong></article>
      <article className="product-stat"><span>Courses with records</span><strong>{loading ? '—' : attendance?.per_course?.length || 0}</strong></article>
    </section>

    <nav className="product-tabs rounded-lg border border-[#efeff3] bg-white" aria-label="Schedule sections">
      <button type="button" className={`product-tab ${activeTab === 'timetable' ? 'active' : ''}`} aria-pressed={activeTab === 'timetable'} onClick={() => setActiveTab('timetable')}>Timetable</button>
      <button type="button" className={`product-tab ${activeTab === 'attendance' ? 'active' : ''}`} aria-pressed={activeTab === 'attendance'} onClick={() => setActiveTab('attendance')}>Attendance</button>
    </nav>

    {activeTab === 'timetable' && <>
    <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">RECURRING TIMETABLE</p><h2>Your week</h2></div></header>
      {loading ? <div className="product-empty">Loading timetable…</div> : classes.length ? <div className="week-grid">{byDay.filter((day) => day.classes.length).map((day) => <section className="week-day" key={day.name}><h3>{day.name}</h3>{day.classes.map((entry) => <article className="week-class" key={entry.id}><div><strong>{entry.subject}</strong><small>{entry.start_time}–{entry.end_time}{entry.room ? ` · ${entry.room}` : ''}</small>{entry.teacher && <small>{entry.teacher}</small>}</div><button type="button" className="remove-class" aria-label={`Remove ${entry.subject}`} onClick={() => removeClass(entry.id)}>×</button></article>)}</section>)}</div> : <div className="product-empty"><strong>Your timetable is empty</strong>Add classes below or upload a timetable image to get started.</div>}
    </section>

    <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">GOOGLE CLASSROOM</p><h2>Scheduled classes this week</h2></div><span className="product-pill">{upcomingClasses.length}</span></header>{loading ? <div className="product-empty">Loading classes…</div> : upcomingClasses.length ? <div className="product-list">{upcomingClasses.map((item) => <article className="product-row" key={item.id}><span className="product-icon"><Icon name="clock" size={15}/></span><span className="product-row-main"><strong>{item.subject}</strong><small>{item.teacher || 'Class'}{item.room ? ` · ${item.room}` : ''}</small></span><span className="product-row-meta">{item.date ? new Date(item.date).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : ''}{item.start_time ? ` · ${item.start_time}` : ''}</span></article>)}</div> : <div className="product-empty">No dated Classroom sessions are scheduled for the next seven days.</div>}</section>

    <div className="product-grid">
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">ADD A CLASS</p><h2>Build your timetable</h2></div></header><form className="product-card-body" onSubmit={addClass}>
        <div className="product-form-grid"><label className="product-field wide"><span>Class or course name</span><input required value={form.subject} onChange={(e) => updateField('subject', e.target.value)} placeholder="e.g. Interaction Design" /></label>
          <label className="product-field"><span>Starts</span><input required type="time" value={form.start_time} onChange={(e) => updateField('start_time', e.target.value)} /></label><label className="product-field"><span>Ends</span><input required type="time" value={form.end_time} onChange={(e) => updateField('end_time', e.target.value)} /></label>
          <label className="product-field"><span>Instructor</span><input value={form.teacher} onChange={(e) => updateField('teacher', e.target.value)} /></label><label className="product-field"><span>Room</span><input value={form.room} onChange={(e) => updateField('room', e.target.value)} /></label>
          <div className="product-field wide"><span>Days</span><div className="product-day-picker">{weekdays.map((day, index) => <label key={day}><input type="checkbox" checked={form.weekdays.includes(index)} onChange={(e) => updateField('weekdays', e.target.checked ? [...form.weekdays, index].sort() : form.weekdays.filter((value) => value !== index))} />{day.slice(0, 3)}</label>)}</div></div>
        </div><button className="product-action schedule-add" type="submit" disabled={saving || !form.weekdays.length}>{saving ? 'Saving…' : <><Icon name="calendar" size={14}/> Add to timetable</>}</button>
      </form></section>
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">IMPORT A TIMETABLE</p><h2>Read a timetable image</h2></div></header><div className="product-card-body"><p className="import-description">Upload a clear timetable image. Uniflow extracts class times and adds them to your weekly schedule.</p><label className="product-field"><span>Image file</span><input type="file" accept="image/*" onChange={(e) => setFile(e.target.files?.[0] || null)} /></label>{file && <p className="last-synced mt-2">Selected: {file.name}</p>}<button className="product-action schedule-add" type="button" disabled={saving || !file} onClick={parseFile}>{saving ? 'Reading image…' : 'Extract classes'}</button><p className="product-note">Review extracted class details after import; image recognition can miss small text.</p></div></section>
    </div>
    </>}

    {activeTab === 'attendance' && <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">COURSE RECORDS</p><h2>Attendance by course</h2><p className="last-synced mt-1">Percentages are based on records synced from your university portal.</p></div></header>{loading ? <div className="product-empty" role="status">Loading attendance…</div> : attendance?.per_course?.length ? <div className="product-card-body">{attendance.per_course.map((row, index) => <div className="attendance-row" key={`${row.course_id}-${index}`}><span>{row.course_name || row.subject || 'Course'}</span><div className="attendance-track" role="meter" aria-label={`${row.course_name || row.subject || 'Course'} attendance`} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.max(0, Math.min(100, Number(row.percentage) || 0))}><span style={{ width: `${Math.max(0, Math.min(100, Number(row.percentage) || 0))}%` }} /></div><strong>{Number(row.percentage || 0).toFixed(0)}%</strong></div>)}</div> : <div className="product-empty"><strong>No attendance records yet</strong><span>Records appear here when attendance data is synced from your university portal.</span></div>}</section>}
  </main>;
}
