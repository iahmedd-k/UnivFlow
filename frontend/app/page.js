'use client';

import { useState, useEffect, useCallback } from 'react';
import { useUser, useAuth, SignInButton, SignUpButton, UserButton } from '@clerk/nextjs';
import { api } from './lib/api';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function formatClassTime(value) {
  if (!value) return 'TBA';
  if (/^\d{2}:\d{2}$/.test(value)) {
    const [hour, minute] = value.split(':').map(Number);
    const suffix = hour >= 12 ? 'PM' : 'AM';
    return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${suffix}`;
  }
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function classTimeStatus(entry, now = new Date()) {
  if (!entry?.start_time || !/^\d{2}:\d{2}$/.test(entry.start_time)) return 'Time to be confirmed';
  const [hour, minute] = entry.start_time.split(':').map(Number);
  const start = new Date(now);
  start.setHours(hour, minute, 0, 0);
  const minutes = Math.round((start.getTime() - now.getTime()) / 60000);
  if (minutes > 0) return `Starts in ${minutes} min`;
  if (minutes >= -60) return 'In progress';
  return 'Finished';
}

export default function Home() {
  const { isSignedIn, user, isLoaded: isUserLoaded } = useUser();
  const { getToken } = useAuth();

  // Tab State
  const [activeTab, setActiveTab] = useState('overview');

  // Data States
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [backendHealth, setBackendHealth] = useState(null);
  const [authStatus, setAuthStatus] = useState(null);
  const [overview, setOverview] = useState(null);
  const [courses, setCourses] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [schedules, setSchedules] = useState([]);
  const [attendance, setAttendance] = useState(null);
  const [exams, setExams] = useState([]);
  const [quizzes, setQuizzes] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [classroomAnnouncements, setClassroomAnnouncements] = useState([]);
  const [recentEmails, setRecentEmails] = useState([]);
  const [driveFiles, setDriveFiles] = useState([]);
  const [workspaceError, setWorkspaceError] = useState('');
  const [courseRosters, setCourseRosters] = useState({});
  const [rosterLoading, setRosterLoading] = useState(null);
  const [timetableEntries, setTimetableEntries] = useState([]);
  const [timetableToday, setTimetableToday] = useState([]);
  const [timetableDrafts, setTimetableDrafts] = useState([]);
  const [timetableRawText, setTimetableRawText] = useState('');
  const [timetableIssues, setTimetableIssues] = useState([]);
  const [timetableFileName, setTimetableFileName] = useState('');
  const [timetableBusy, setTimetableBusy] = useState(false);
  const [timetableViewMode, setTimetableViewMode] = useState('matrix');
  const [showManualAddRow, setShowManualAddRow] = useState(false);
  const [newClassSubject, setNewClassSubject] = useState('');
  const [newClassWeekdays, setNewClassWeekdays] = useState([0]);
  const [newClassStartTime, setNewClassStartTime] = useState('09:00');
  const [newClassEndTime, setNewClassEndTime] = useState('10:30');
  const [newClassTeacher, setNewClassTeacher] = useState('');
  const [newClassRoom, setNewClassRoom] = useState('');
  const [semesterName, setSemesterName] = useState('');
  const [semesterStart, setSemesterStart] = useState('');
  const [semesterEnd, setSemesterEnd] = useState('');
  const [reminderMinutes, setReminderMinutes] = useState(30);
  const [classAlertsEnabled, setClassAlertsEnabled] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [clock, setClock] = useState(() => new Date());
  const [portalUrl, setPortalUrl] = useState('');
  const [portalAttendanceUrl, setPortalAttendanceUrl] = useState('');
  const [portalLoginEmail, setPortalLoginEmail] = useState('');
  const [portalAuthMethod, setPortalAuthMethod] = useState('google');
  const [portalBrowserInfo, setPortalBrowserInfo] = useState(null);
  const [portalReport, setPortalReport] = useState(null);
  const [portalSessionStatus, setPortalSessionStatus] = useState('NOT_CONFIGURED');
  const [portalLastSyncedAt, setPortalLastSyncedAt] = useState(null);
  const [portalHeadlessSyncing, setPortalHeadlessSyncing] = useState(false);
  const [portalBusy, setPortalBusy] = useState(false);
  const [notificationMsg, setNotificationMsg] = useState('');
  const [assignmentFilter, setAssignmentFilter] = useState('all');
  const [classroomCourseFilter, setClassroomCourseFilter] = useState('all');
  const [classroomSearch, setClassroomSearch] = useState('');

  // Semester Start Date & Sync Modal
  const [semesterStartDate, setSemesterStartDate] = useState('');
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [syncModalDate, setSyncModalDate] = useState('');

  // Load all dashboard data
  const loadDashboardData = useCallback(async () => {
    setLoading(true);
    try {
      const token = isSignedIn ? await getToken() : null;

      // Parallel data fetching
      const [
        healthRes,
        statusRes,
        overviewRes,
        coursesRes,
        assignmentsRes,
        schedulesRes,
        attendanceRes,
        examsRes,
        quizzesRes,
        announcementsRes,
        classroomAnnouncementsRes,
        timetableRes,
        timetableTodayRes,
        classroomSettingsRes,
      ] = await Promise.allSettled([
        api.checkHealth(),
        api.getAuthStatus(token),
        api.getOverview(token),
        api.getCourses(token, semesterStartDate),
        api.getAssignments(null, token, semesterStartDate),
        api.getTodaySchedules(token),
        api.getAttendanceSummary(token),
        api.getExams(token, semesterStartDate),
        api.getQuizzes(token, semesterStartDate),
        api.getAnnouncements(token, semesterStartDate),
        api.getClassroomAnnouncements(token, semesterStartDate),
        api.getTimetableClasses(token),
        api.getTodaysClasses(token),
        api.getClassroomSettings(token),
      ]);

      if (healthRes.status === 'fulfilled') setBackendHealth(healthRes.value);
      if (statusRes.status === 'fulfilled') setAuthStatus(statusRes.value);
      if (overviewRes.status === 'fulfilled') setOverview(overviewRes.value);
      if (coursesRes.status === 'fulfilled') setCourses(coursesRes.value || []);
      if (assignmentsRes.status === 'fulfilled') setAssignments(assignmentsRes.value || []);
      if (schedulesRes.status === 'fulfilled') setSchedules(schedulesRes.value || []);
      if (attendanceRes.status === 'fulfilled') setAttendance(attendanceRes.value || null);
      if (examsRes.status === 'fulfilled') setExams(examsRes.value || []);
      if (quizzesRes.status === 'fulfilled') setQuizzes(quizzesRes.value || []);
      if (announcementsRes.status === 'fulfilled') setAnnouncements(announcementsRes.value || []);
      if (classroomAnnouncementsRes.status === 'fulfilled') setClassroomAnnouncements(classroomAnnouncementsRes.value || []);
      if (timetableRes.status === 'fulfilled') setTimetableEntries(timetableRes.value || []);
      if (timetableTodayRes.status === 'fulfilled') setTimetableToday(timetableTodayRes.value || []);

      if (classroomSettingsRes.status === 'fulfilled' && classroomSettingsRes.value?.semester_start_date) {
        setSemesterStartDate(classroomSettingsRes.value.semester_start_date);
        setSyncModalDate(classroomSettingsRes.value.semester_start_date);
      }

      if (statusRes.status === 'fulfilled' && statusRes.value?.google_connected) {
        const [emailsRes, driveRes] = await Promise.allSettled([
          api.getRecentEmails(token, semesterStartDate),
          api.getRecentDriveFiles(token, semesterStartDate),
        ]);
        setRecentEmails(emailsRes.status === 'fulfilled' ? emailsRes.value || [] : []);
        setDriveFiles(driveRes.status === 'fulfilled' ? driveRes.value || [] : []);
        const integrationFailure = [emailsRes, driveRes].find((item) => item.status === 'rejected');
        setWorkspaceError(integrationFailure?.reason?.message || '');
      } else {
        setRecentEmails([]);
        setDriveFiles([]);
        setWorkspaceError('');
      }
      try {
        const portal = await api.getPortalSettings(token);
        setPortalUrl(portal.url || '');
        setPortalAttendanceUrl(portal.attendance_url || '');
        setPortalLoginEmail(portal.login_email || user?.primaryEmailAddress?.emailAddress || '');
        setPortalAuthMethod(portal.auth_method || 'google');
        setPortalBrowserInfo(portal.browser_open ? { opened: true } : null);
        setPortalReport(portal.report || null);
        setPortalSessionStatus(portal.session_status || 'NOT_CONFIGURED');
        setPortalLastSyncedAt(portal.last_synced_at || null);
      } catch (portalError) {
        console.warn('Portal settings unavailable:', portalError.message);
      }
    } catch (err) {
      console.error('Error fetching dashboard data:', err);
    } finally {
      setLoading(false);
    }
  }, [isSignedIn, getToken, user, semesterStartDate]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadDashboardData();
  }, [loadDashboardData]);

  // Open Sync Modal or trigger Sync
  const handleOpenSyncModal = () => {
    setSyncModalDate(semesterStartDate || new Date(new Date().getFullYear(), new Date().getMonth() - 2, 1).toISOString().slice(0, 10));
    setShowSyncModal(true);
  };

  // Perform Sync with Semester Start Date
  const handlePerformSync = async (dateToUse) => {
    setSyncing(true);
    setShowSyncModal(false);
    setNotificationMsg('');
    try {
      const token = await getToken();
      const targetDate = dateToUse || semesterStartDate || null;
      if (targetDate) {
        setSemesterStartDate(targetDate);
        await api.saveClassroomSettings({ semester_start_date: targetDate }, token);
      }
      await api.triggerSync(targetDate, token);
      setNotificationMsg(`Sync started${targetDate ? ` from semester start (${targetDate})` : ''}. Refreshing live data...`);
      await loadDashboardData();
    } catch (err) {
      setNotificationMsg(`Sync failed: ${err.message}`);
    } finally {
      setSyncing(false);
    }
  };

  const handleSaveSemesterStartDate = async (dateVal) => {
    setSemesterStartDate(dateVal);
    try {
      const token = await getToken();
      await api.saveClassroomSettings({ semester_start_date: dateVal || null }, token);
      setNotificationMsg(dateVal ? `Semester start date set to ${dateVal}.` : 'Semester filter cleared.');
      await loadDashboardData();
    } catch (err) {
      setNotificationMsg(`Could not update semester start date: ${err.message}`);
    }
  };

  // Google OAuth Handlers
  const handleConnectGoogle = async () => {
    try {
      const token = await getToken();
      const res = await api.getGoogleAuthUrl(token);
      if (res?.auth_url) {
        window.location.href = res.auth_url;
      }
    } catch (err) {
      setNotificationMsg(`Could not start Google connection: ${err.message}`);
    }
  };

  const handleDisconnectGoogle = async () => {
    try {
      const token = await getToken();
      await api.disconnectGoogle(token);
      setNotificationMsg('Google account disconnected.');
      await loadDashboardData();
    } catch (err) {
      setNotificationMsg(`Disconnect failed: ${err.message}`);
    }
  };

  const handleLoadRoster = async (courseId) => {
    if (courseRosters[courseId]) {
      setCourseRosters((current) => {
        const next = { ...current };
        delete next[courseId];
        return next;
      });
      return;
    }
    setRosterLoading(courseId);
    try {
      const token = await getToken();
      const students = await api.getCourseStudents(courseId, token);
      setCourseRosters((current) => ({ ...current, [courseId]: students || [] }));
    } catch (error) {
      setNotificationMsg(error.message || 'Could not load student roster.');
    } finally {
      setRosterLoading(null);
    }
  };

  const handleTimetableImage = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setTimetableBusy(true);
    setTimetableFileName(file.name);
    setNotificationMsg('Extracting tabular classes with AI and updating schedule...');
    try {
      const token = await getToken();
      const result = await api.parseTimetableImage(file, token);
      if (result.semester_name) {
        setSemesterName(result.semester_name);
      }
      const [all, today] = await Promise.all([api.getTimetableClasses(token), api.getTodaysClasses(token)]);
      setTimetableEntries(all || []);
      setTimetableToday(today || []);
      setTimetableRawText(result.raw_text || '');
      setTimetableIssues(Array.isArray(result.issues) ? result.issues : []);

      const count = (result.candidates || []).length || (all || []).length;
      setNotificationMsg(result.message || `Successfully extracted and updated ${count} timetable classes!`);
    } catch (error) {
      console.warn('Timetable extraction error:', error);
      setNotificationMsg(error.message || 'Could not parse the timetable file.');
    } finally {
      setTimetableBusy(false);
    }
  };

  const handleManualAddClass = async (e) => {
    if (e) e.preventDefault();
    if (!newClassSubject.trim()) {
      setNotificationMsg('Please enter a class name.');
      return;
    }
    if (newClassEndTime <= newClassStartTime) {
      setNotificationMsg('End time must be after start time.');
      return;
    }
    setTimetableBusy(true);
    try {
      const token = await getToken();
      await api.saveTimetableClasses([{
        subject: newClassSubject.trim(),
        weekdays: newClassWeekdays,
        start_time: newClassStartTime,
        end_time: newClassEndTime,
        teacher: newClassTeacher.trim() || null,
        room: newClassRoom.trim() || null,
        semester_name: semesterName || null,
        semester_start: semesterStart || null,
        semester_end: semesterEnd || null,
      }], token);

      const [all, today] = await Promise.all([api.getTimetableClasses(token), api.getTodaysClasses(token)]);
      setTimetableEntries(all || []);
      setTimetableToday(today || []);
      setNewClassSubject('');
      setNewClassTeacher('');
      setNewClassRoom('');
      setShowManualAddRow(false);
      setNotificationMsg(`Added ${newClassSubject} to schedule.`);
    } catch (error) {
      setNotificationMsg(error.message || 'Could not add class.');
    } finally {
      setTimetableBusy(false);
    }
  };

  const handleClearAllTimetable = async () => {
    if (!confirm('Are you sure you want to clear all weekly timetable classes?')) return;
    setTimetableBusy(true);
    try {
      const token = await getToken();
      await api.clearAllTimetableClasses(token);
      setTimetableEntries([]);
      setTimetableToday([]);
      setTimetableDrafts([]);
      setNotificationMsg('Weekly timetable cleared.');
    } catch (error) {
      setNotificationMsg(error.message || 'Could not clear timetable.');
    } finally {
      setTimetableBusy(false);
    }
  };

  const handleDeleteTimetableClass = async (entryId) => {
    try {
      const token = await getToken();
      await api.deleteTimetableClass(entryId, token);
      const [all, today] = await Promise.all([api.getTimetableClasses(token), api.getTodaysClasses(token)]);
      setTimetableEntries(all || []);
      setTimetableToday(today || []);
    } catch (error) {
      setNotificationMsg(error.message || 'Could not remove this class.');
    }
  };

  const handleEnableClassAlerts = async () => {
    if (!('Notification' in window)) {
      setNotificationMsg('This browser does not support desktop notifications.');
      return;
    }
    const permission = await Notification.requestPermission();
    setClassAlertsEnabled(permission === 'granted');
    if (permission !== 'granted') setNotificationMsg('Allow notifications in your browser settings to receive class alerts.');
  };

  const handleSavePortalUrl = async () => {
    setPortalBusy(true);
    try {
      const token = await getToken();
      const result = await api.savePortalUrl(portalUrl, token, { login_email: portalLoginEmail.trim() || null, auth_method: portalAuthMethod });
      setPortalUrl(result.url);
      setNotificationMsg('University portal URL saved.');
    } catch (error) {
      setNotificationMsg(error.message || 'Could not save the portal URL.');
    } finally {
      setPortalBusy(false);
    }
  };

  const handleOpenPortal = async () => {
    setPortalBusy(true);
    try {
      const token = await getToken();
      const enteredUrl = portalUrl.trim();
      if (!enteredUrl) {
        throw new Error('Enter your university portal URL first.');
      }
      const saved = await api.savePortalUrl(enteredUrl, token, { login_email: portalLoginEmail.trim() || null, auth_method: portalAuthMethod });
      setPortalUrl(saved.url);
      const result = await api.openPortalBrowser(token);
      setPortalBrowserInfo(result);
      setNotificationMsg(result.message || 'Portal browser opened. Complete sign-in in that window.');
    } catch (error) {
      setNotificationMsg(error.message || 'Could not open the portal browser.');
    } finally {
      setPortalBusy(false);
    }
  };

  const handleCapturePortalReport = async () => {
    setPortalBusy(true);
    try {
      const token = isSignedIn ? await getToken() : null;
      const result = await api.capturePortalReport(token);
      setPortalReport(result.summary || null);
      setPortalSessionStatus('ACTIVE');
      setPortalLastSyncedAt(new Date().toISOString());
      if (result.destination_url_saved) setPortalAttendanceUrl(result.destination_url_saved);

      await loadDashboardData();

      const details = [];
      if (result.attendance?.length) details.push(`${result.attendance.length} attendance records`);
      if (result.timetable?.length) details.push(`${result.timetable.length} timetable classes`);
      if (result.summary?.cgpa) details.push(`CGPA ${result.summary.cgpa}`);
      const msg = details.length
        ? `Captured: Saved ${details.join(', ')}. Auto-sync destination memorized!`
        : 'Captured current portal view. Destination path memorized for auto-sync.';
      setNotificationMsg(msg);
    } catch (error) {
      setNotificationMsg(error.message || 'Could not capture the portal report.');
    } finally {
      setPortalBusy(false);
    }
  };

  const handleHeadlessPortalSync = async () => {
    setPortalHeadlessSyncing(true);
    try {
      const token = isSignedIn ? await getToken() : null;
      const result = await api.syncPortalHeadless(token);
      if (result.status === 'session_expired') {
        setPortalSessionStatus('EXPIRED');
        setNotificationMsg('University portal session has expired. Click "Open secure sign-in browser" to re-authenticate.');
      } else if (result.status === 'success') {
        setPortalSessionStatus('ACTIVE');
        setPortalLastSyncedAt(result.last_synced_at || new Date().toISOString());
        if (result.summary) setPortalReport(result.summary);

        await loadDashboardData();

        const details = [];
        if (result.attendance?.length) details.push(`${result.attendance.length} attendance rows`);
        if (result.timetable?.length) details.push(`${result.timetable.length} timetable classes`);
        if (result.summary?.cgpa) details.push(`CGPA ${result.summary.cgpa}`);
        const msg = details.length
          ? `Auto-sync success: Refreshed ${details.join(', ')} across all saved portal destinations.`
          : 'Auto-sync success: Refreshed portal records.';
        setNotificationMsg(msg);
      } else {
        setNotificationMsg(result.message || 'Auto-sync completed.');
      }
    } catch (error) {
      setNotificationMsg(error.message || 'Could not run background auto-sync.');
    } finally {
      setPortalHeadlessSyncing(false);
    }
  };

  const handleClosePortal = async () => {
    try {
      const token = isSignedIn ? await getToken() : null;
      await api.closePortalBrowser(token);
      setPortalBrowserInfo(null);
    } catch (error) {
      setNotificationMsg(error.message || 'Could not close the portal browser.');
    }
  };

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!classAlertsEnabled || Notification.permission !== 'granted') return undefined;
    const checkForClass = () => {
      const now = new Date();
      const today = now.getDay() === 0 ? 6 : now.getDay() - 1;
      const todayString = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
      timetableEntries.filter((entry) => entry.weekday === today).forEach((entry) => {
        if ((entry.semester_start && todayString < entry.semester_start) || (entry.semester_end && todayString > entry.semester_end)) return;
        const [hour, minute] = entry.start_time.split(':').map(Number);
        const begins = new Date(now);
        begins.setHours(hour, minute, 0, 0);
        const minutesUntil = (begins.getTime() - now.getTime()) / 60000;
        const alertKey = `uniflow-class-alert-${entry.id}-${now.toDateString()}`;
        if (minutesUntil >= 0 && minutesUntil <= reminderMinutes && !sessionStorage.getItem(alertKey)) {
          new Notification(`${entry.subject} starts in ${Math.ceil(minutesUntil)} min`, { body: `Room ${entry.room || 'TBA'} · ${entry.teacher || 'Teacher not listed'}` });
          sessionStorage.setItem(alertKey, 'sent');
        }
      });
    };
    checkForClass();
    const interval = window.setInterval(checkForClass, 30000);
    return () => window.clearInterval(interval);
  }, [classAlertsEnabled, reminderMinutes, timetableEntries]);

  // The semester boundary applies to every Classroom surface. Keep records with
  // no timestamp because older Classroom rows can legitimately omit one.
  const semesterBoundary = semesterStartDate ? new Date(`${semesterStartDate}T00:00:00`).getTime() : null;
  const isAfterSemester = (item, fields) => {
    if (!semesterBoundary) return true;
    const dates = fields.map((field) => item?.[field] ? new Date(item[field]).getTime() : NaN).filter(Number.isFinite);
    return !dates.length || dates.some((value) => value >= semesterBoundary);
  };
  const semesterAssignments = assignments.filter((item) => isAfterSemester(item, ['created_at', 'updated_at', 'due_at', 'due_date']));
  const semesterCourses = courses.filter((item) => isAfterSemester(item, ['created_at', 'updated_at']) || semesterAssignments.some((assignment) => assignment.course_id === item.id));
  const semesterClassroomAnnouncements = classroomAnnouncements.filter((item) => isAfterSemester(item, ['published_at', 'created_at']));
  const semesterUniversityAnnouncements = announcements.filter((item) => isAfterSemester(item, ['published_at', 'created_at']));
  const semesterExams = exams.filter((item) => isAfterSemester(item, ['date', 'created_at']));
  const semesterQuizzes = quizzes.filter((item) => isAfterSemester(item, ['date', 'created_at']));

  // Filtered assignments
  const filteredAssignments = semesterAssignments.filter((a) => {
    const type = (a.work_type || 'ASSIGNMENT').toUpperCase();
    const isSubmitted = ['TURNED_IN', 'RETURNED'].includes(a.submission_state);
    if (assignmentFilter === 'announcements') return false;
    if (assignmentFilter === 'missing' && !a.is_missing) return false;
    if (assignmentFilter === 'assignments' && type !== 'ASSIGNMENT') return false;
    if (assignmentFilter === 'quizzes' && !a.is_quiz && !['MULTIPLE_CHOICE_QUESTION', 'SHORT_ANSWER_QUESTION'].includes(type)) return false;
    if (assignmentFilter === 'submitted' && !isSubmitted) return false;
    if (assignmentFilter === 'open' && isSubmitted) return false;
    if (classroomCourseFilter !== 'all' && String(a.course_id) !== classroomCourseFilter) return false;
    const query = classroomSearch.trim().toLowerCase();
    return !query || `${a.title} ${a.description || ''} ${a.course_name || ''}`.toLowerCase().includes(query);
  });

  const filteredClassroomAnnouncements = semesterClassroomAnnouncements.filter((item) => {
    if (classroomCourseFilter !== 'all' && String(item.course_id) !== classroomCourseFilter) return false;
    const query = classroomSearch.trim().toLowerCase();
    return !query || `${item.title} ${item.content || ''} ${item.course_name || ''}`.toLowerCase().includes(query);
  });

  const todayClasses = [...timetableToday, ...schedules].sort((first, second) => {
    const firstTime = first.start_time?.length === 5 ? first.start_time : new Date(first.start_time || 0).toTimeString().slice(0, 5);
    const secondTime = second.start_time?.length === 5 ? second.start_time : new Date(second.start_time || 0).toTimeString().slice(0, 5);
    return firstTime.localeCompare(secondTime);
  });

  // Render Signed Out Landing Page
  if (isUserLoaded && !isSignedIn) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
        {/* Navigation */}
        <header
          style={{
            maxWidth: '1200px',
            width: '100%',
            margin: '0 auto',
            padding: '1.25rem 2rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '8px',
                background: '#0f172a',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 700,
                color: '#ffffff',
                fontSize: '0.9375rem',
              }}
            >
              U
            </div>
            <span style={{ fontSize: '1.125rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-main)' }}>
              Uniflow
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <SignInButton mode="modal">
              <button className="btn-secondary">Sign In</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button className="btn-primary">Get Started</button>
            </SignUpButton>
          </div>
        </header>

        {/* Hero Section */}
        <main
          style={{
            flex: 1,
            maxWidth: '1200px',
            width: '100%',
            margin: '0 auto',
            padding: '4rem 2rem 5rem 2rem',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '4px 12px',
              borderRadius: '9999px',
              background: '#f0fdf4',
              border: '1px solid #bbf7d0',
              color: '#15803d',
              fontSize: '0.8125rem',
              fontWeight: 500,
              marginBottom: '1.5rem',
            }}
          >
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: '#16a34a',
              }}
            />
            Academic Intelligence & Automation
          </div>

          <h1
            style={{
              fontSize: 'clamp(2.25rem, 4.5vw, 3.5rem)',
              fontWeight: 700,
              lineHeight: 1.15,
              maxWidth: '800px',
              letterSpacing: '-0.03em',
              marginBottom: '1.25rem',
              color: 'var(--text-main)',
            }}
          >
            Unified Academic Command Center
          </h1>

          <p
            style={{
              fontSize: '1.0625rem',
              color: 'var(--text-muted)',
              maxWidth: '640px',
              lineHeight: 1.6,
              marginBottom: '2.5rem',
            }}
          >
            Seamlessly bridge Google Classroom, assignments, attendance thresholds, and university exam radar into one structured, minimal dashboard.
          </p>

          <div style={{ display: 'flex', gap: '0.875rem', flexWrap: 'wrap', justifyContent: 'center', marginBottom: '4rem' }}>
            <SignInButton mode="modal">
              <button
                className="btn-primary"
                style={{ fontSize: '0.9375rem', padding: '10px 22px' }}
              >
                Launch Dashboard
              </button>
            </SignInButton>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noreferrer"
              className="btn-secondary"
              style={{ fontSize: '0.9375rem', padding: '10px 20px' }}
            >
              API Documentation
            </a>
          </div>

          {/* Feature Highlights Grid */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
              gap: '1.25rem',
              width: '100%',
              textAlign: 'left',
            }}
          >
            <div className="glass-panel" style={{ padding: '1.5rem' }}>
              <div className="eyebrow" style={{ marginBottom: '0.5rem' }}>Integration</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-main)' }}>
                Google Classroom Sync
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.5 }}>
                Direct OAuth integration to synchronize registered courses, coursework, attachments, and student rosters automatically.
              </p>
            </div>

            <div className="glass-panel" style={{ padding: '1.5rem' }}>
              <div className="eyebrow" style={{ marginBottom: '0.5rem' }}>Workflow</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-main)' }}>
                Assignment Pipeline
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.5 }}>
                Track deadlines with countdown indicators, review AI-generated drafts, and manage coursework submissions in one clean view.
              </p>
            </div>

            <div className="glass-panel" style={{ padding: '1.5rem' }}>
              <div className="eyebrow" style={{ marginBottom: '0.5rem' }}>Monitoring</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-main)' }}>
                Attendance Guardian
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.5 }}>
                Real-time lecture attendance tracking with 75% threshold indicators to prevent disqualifications.
              </p>
            </div>

            <div className="glass-panel" style={{ padding: '1.5rem' }}>
              <div className="eyebrow" style={{ marginBottom: '0.5rem' }}>Schedule</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-main)' }}>
                Exam & Timetable Radar
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.5 }}>
                Live exam schedules, upcoming quizzes, weekly timetable automation, and campus notices.
              </p>
            </div>
          </div>
        </main>
      </div>
    );
  }

  // Render Signed In Uniflow Portal
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
      {/* Top App Header */}
      <header
        style={{
          borderBottom: '1px solid var(--border-subtle)',
          background: '#ffffff',
          position: 'sticky',
          top: 0,
          zIndex: 50,
        }}
      >
        <div
          style={{
            maxWidth: '1400px',
            margin: '0 auto',
            padding: '0.75rem 2rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          {/* Logo & Status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  width: '30px',
                  height: '30px',
                  borderRadius: '6px',
                  background: '#0f172a',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  color: '#ffffff',
                  fontSize: '0.875rem',
                }}
              >
                U
              </div>
              <span style={{ fontSize: '1.0625rem', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-main)' }}>
                Uniflow
              </span>
            </div>

            {/* Backend connection pill */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '3px 9px',
                borderRadius: '9999px',
                background: backendHealth?.status === 'healthy' ? '#f0fdf4' : '#fef2f2',
                border: `1px solid ${backendHealth?.status === 'healthy' ? '#bbf7d0' : '#fecaca'}`,
                fontSize: '0.6875rem',
                fontWeight: 600,
                color: backendHealth?.status === 'healthy' ? '#15803d' : '#b91c1c',
              }}
            >
              <span
                style={{
                  width: '5px',
                  height: '5px',
                  borderRadius: '50%',
                  background: backendHealth?.status === 'healthy' ? '#16a34a' : '#dc2626',
                }}
              />
              {backendHealth?.status === 'healthy' ? 'API Online' : 'API Connecting'}
            </div>
          </div>

          {/* Actions & Profile */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {/* Semester Start Date Pill */}
            <button
              onClick={handleOpenSyncModal}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 10px',
                borderRadius: 'var(--radius-sm)',
                background: '#f8fafc',
                border: '1px solid var(--border-subtle)',
                fontSize: '0.75rem',
                color: '#334155',
                cursor: 'pointer',
              }}
              title="Click to change semester start date filter"
            >
              <span className="eyebrow" style={{ fontSize: '0.625rem' }}>SEMESTER:</span>
              <span style={{ fontWeight: 600 }}>{semesterStartDate || 'All time'}</span>
            </button>

            {/* Google Classroom Status */}
            {authStatus?.google_connected ? (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '5px 10px',
                  borderRadius: 'var(--radius-sm)',
                  background: '#f8fafc',
                  border: '1px solid var(--border-subtle)',
                  fontSize: '0.75rem',
                  color: '#334155',
                }}
              >
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#16a34a' }} />
                <span>Classroom Connected</span>
                {authStatus?.google_email && (
                  <span style={{ color: 'var(--text-muted)' }}>
                    ({authStatus.google_email})
                  </span>
                )}
                <button
                  onClick={handleDisconnectGoogle}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '0.75rem',
                    textDecoration: 'underline',
                    marginLeft: '2px',
                  }}
                >
                  disconnect
                </button>
              </div>
            ) : (
              <button
                onClick={handleConnectGoogle}
                className="btn-google"
                style={{ padding: '6px 12px', fontSize: '0.8125rem' }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                  />
                </svg>
                Connect Classroom
              </button>
            )}

            {/* Sync Button */}
            <button
              onClick={handleOpenSyncModal}
              disabled={syncing}
              className="btn-secondary"
              style={{ padding: '6px 12px', fontSize: '0.8125rem' }}
            >
              {syncing ? 'Syncing...' : 'Sync'}
            </button>

            {/* Clerk User Button */}
            <UserButton afterSignOutUrl="/" />
          </div>
        </div>
      </header>

      {/* Sync / Semester Start Date Modal */}
      {showSyncModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(15, 23, 42, 0.4)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            padding: '1rem',
          }}
        >
          <div
            className="glass-panel animate-fade-in"
            style={{
              maxWidth: '480px',
              width: '100%',
              padding: '1.75rem',
              background: '#ffffff',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.5rem' }}>
              Sync Semester Data
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.5, marginBottom: '1.25rem' }}>
              Specify your semester start date so Uniflow only imports coursework, announcements, and emails from this semester onwards, filtering out past semesters.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '1.5rem' }}>
              <label className="eyebrow" htmlFor="sync-start-date">Semester Start Date</label>
              <input
                id="sync-start-date"
                type="date"
                value={syncModalDate}
                onChange={(e) => setSyncModalDate(e.target.value)}
                style={{
                  color: 'var(--text-main)',
                  background: '#ffffff',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)',
                  padding: '9px 12px',
                  font: 'inherit',
                  fontSize: '0.875rem',
                  outline: 'none',
                }}
              />
              <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>
                Items dated before this date will be excluded from the sync.
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                className="btn-secondary"
                onClick={() => setShowSyncModal(false)}
                disabled={syncing}
              >
                Cancel
              </button>
              <button
                className="btn-primary"
                onClick={() => handlePerformSync(syncModalDate)}
                disabled={syncing}
              >
                {syncing ? 'Syncing...' : 'Start Sync'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main Dashboard Body */}
      <main style={{ flex: 1, maxWidth: '1400px', width: '100%', margin: '0 auto', padding: '1.75rem 2rem' }}>
        {/* Notification Alert */}
        {notificationMsg && (
          <div
            className="animate-fade-in"
            style={{
              padding: '10px 14px',
              borderRadius: 'var(--radius-md)',
              background: '#f0fdf4',
              border: '1px solid #bbf7d0',
              color: '#166534',
              fontSize: '0.8125rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '1.25rem',
            }}
          >
            <span>{notificationMsg}</span>
            <button
              onClick={() => setNotificationMsg('')}
              style={{
                background: 'none',
                border: 'none',
                color: '#15803d',
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: 600,
              }}
            >
              ✕
            </button>
          </div>
        )}

        {/* Welcome Section */}
        <div style={{ marginBottom: '1.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ fontSize: '1.375rem', fontWeight: 600, letterSpacing: '-0.02em', color: 'var(--text-main)', marginBottom: '0.2rem' }}>
              Welcome back, {user?.firstName || 'Student'}
            </h2>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
              Live academic overview, coursework pipeline, and weekly timetable sync.
            </p>
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: '0.75rem', fontWeight: 500 }} suppressHydrationWarning>
            {mounted ? clock.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' }) : null}
          </div>
        </div>

        {/* Google Classroom Connection Callout if not connected */}
        {!authStatus?.google_connected && (
          <div
            className="animate-fade-in glass-panel"
            style={{
              padding: '1.125rem 1.25rem',
              marginBottom: '1.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '1rem',
              background: '#ffffff',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-main)', marginBottom: '2px' }}>
                Connect your Google Classroom account
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                Authorize Google Classroom to synchronize your courses, assignments, and schedule into Uniflow.
              </div>
            </div>
            <button onClick={handleConnectGoogle} className="btn-google" style={{ padding: '7px 14px', fontSize: '0.8125rem' }}>
              <svg width="14" height="14" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
              </svg>
              Connect Google Classroom
            </button>
          </div>
        )}

        {/* Top Metric Cards */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '1rem',
            marginBottom: '1.5rem',
          }}
        >
          {/* Card 1: Courses */}
          <div className="glass-panel" style={{ padding: '1.125rem 1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
              <span className="eyebrow">COURSES</span>
              <span className="badge badge-info">{semesterCourses.length} active</span>
            </div>
            <div style={{ fontSize: '1.625rem', fontWeight: 700, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
              {semesterCourses.length}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
              Classroom courses synced
            </div>
          </div>

          {/* Card 2: Assignments Pending */}
          <div className="glass-panel" style={{ padding: '1.125rem 1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
              <span className="eyebrow">ASSIGNMENTS</span>
              <span className="badge badge-warning">
                {semesterAssignments.length} pending
              </span>
            </div>
            <div style={{ fontSize: '1.625rem', fontWeight: 700, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
                {semesterAssignments.length}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
              {overview?.assignments?.overdue ?? 0} overdue · {overview?.assignments?.completed ?? 0} completed
            </div>
          </div>

          {/* Card 3: Attendance Average */}
          <div className="glass-panel" style={{ padding: '1.125rem 1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
              <span className="eyebrow">AVG ATTENDANCE</span>
              <span className={`badge ${attendance?.overall_attendance != null && attendance.overall_attendance >= 75 ? 'badge-success' : 'badge-danger'}`}>
                75% Target
              </span>
            </div>
            <div
              style={{
                fontSize: '1.625rem',
                fontWeight: 700,
                letterSpacing: '-0.02em',
                color: attendance?.overall_attendance == null
                  ? 'var(--text-muted)'
                  : attendance.overall_attendance < 75 ? '#b91c1c' : '#15803d',
              }}
            >
              {attendance?.overall_attendance != null ? `${attendance.overall_attendance}%` : '—'}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
              Lecture attendance threshold
            </div>
          </div>

          {/* Card 4: Upcoming Exams */}
          <div className="glass-panel" style={{ padding: '1.125rem 1.25rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
              <span className="eyebrow">EXAMS & QUIZZES</span>
              <span className="badge badge-purple">Schedule</span>
            </div>
            <div style={{ fontSize: '1.625rem', fontWeight: 700, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
              {semesterExams.length + semesterQuizzes.length}
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
              {semesterExams.length} exams · {semesterQuizzes.length} quizzes scheduled
            </div>
          </div>
        </div>

        {/* Tab Navigation */}
        <div
          style={{
            display: 'flex',
            gap: '4px',
            borderBottom: '1px solid var(--border-subtle)',
            marginBottom: '1.5rem',
            overflowX: 'auto',
          }}
        >
          {[
            { id: 'overview', label: 'Overview' },
            { id: 'classroom', label: 'Classroom & Courses' },
            { id: 'assignments', label: 'Assignments Hub' },
            { id: 'schedule', label: 'Schedule & Attendance' },
            { id: 'university', label: 'Exams & Notices' },
            { id: 'workspace', label: 'Mail & Drive' },
            { id: 'settings', label: 'System & Integrations' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '8px 14px',
                background: 'none',
                border: 'none',
                borderBottom: activeTab === tab.id ? '2px solid #0f172a' : '2px solid transparent',
                color: activeTab === tab.id ? '#0f172a' : 'var(--text-muted)',
                fontWeight: activeTab === tab.id ? 600 : 500,
                fontSize: '0.8125rem',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                whiteSpace: 'nowrap',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab 1: Overview */}
        {activeTab === 'overview' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '1.25rem' }}>
            {/* Today's Schedule Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>Today&apos;s Classes</h3>
                <span className="count-pill">{todayClasses.length} classes</span>
              </div>
              {todayClasses.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                  <p>No classes scheduled for today.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {todayClasses.map((s) => (
                    <div
                      key={s.id}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 'var(--radius-md)',
                        background: '#f8fafc',
                        border: '1px solid var(--border-subtle)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 600, fontSize: '0.8125rem', color: 'var(--text-main)' }}>{s.subject || 'Class'}</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
                          Room: {s.room || 'TBA'} · Teacher: {s.teacher || 'Instructor'}
                        </div>
                      </div>
                      <div className="badge badge-purple">
                        {formatClassTime(s.start_time)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pending Assignments Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>Urgent Assignments</h3>
                <button
                  onClick={() => setActiveTab('assignments')}
                  style={{ background: 'none', border: 'none', color: '#0f172a', fontSize: '0.75rem', fontWeight: 500, cursor: 'pointer', textDecoration: 'underline' }}
                >
                  View all
                </button>
              </div>
              {semesterAssignments.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '2rem 1rem', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                  <p>No assignments found. Connect Google Classroom and click Sync.</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {semesterAssignments.slice(0, 5).map((a) => (
                    <div
                      key={a.id}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 'var(--radius-md)',
                        background: '#f8fafc',
                        border: '1px solid var(--border-subtle)',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <div style={{ maxWidth: '70%' }}>
                        <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {a.title}
                        </div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '2px' }}>
                          Due: {a.due_at ? new Date(a.due_at).toLocaleDateString() : 'No deadline'}
                        </div>
                      </div>
                      <span className={`badge ${a.status === 'submitted' ? 'badge-success' : a.status === 'overdue' ? 'badge-danger' : 'badge-warning'}`}>
                        {a.status || 'Pending'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 2: Classroom & Courses */}
        {activeTab === 'classroom' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-main)' }}>Google Classroom Courses</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                  Active courses and coursework synced from semester start date: <strong>{semesterStartDate || 'All time'}</strong>.
                </p>
              </div>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button onClick={handleOpenSyncModal} className="btn-secondary">
                  Change Semester Date
                </button>
                <button onClick={handleOpenSyncModal} disabled={syncing} className="btn-primary">
                  {syncing ? 'Syncing...' : 'Sync Classroom'}
                </button>
              </div>
            </div>

            {/* Semester Filter Banner */}
            <div
              className="glass-panel"
              style={{
                padding: '10px 14px',
                marginBottom: '1.25rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '8px',
                background: '#f8fafc',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8125rem', color: '#334155' }}>
                <span className="eyebrow">ACTIVE FILTER:</span>
                <span>
                  {semesterStartDate
                    ? `Only fetching data from ${semesterStartDate} onwards (past semesters ignored)`
                    : 'No semester start date configured. All historical coursework will be included.'}
                </span>
              </div>
              <button
                onClick={handleOpenSyncModal}
                style={{
                  background: 'none',
                  border: 'none',
                  color: '#0f172a',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  textDecoration: 'underline',
                  cursor: 'pointer',
                }}
              >
                {semesterStartDate ? 'Change Date' : 'Set Semester Start Date'}
              </button>
            </div>

            {semesterCourses.length === 0 ? (
              <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center' }}>
                <p style={{ fontSize: '0.9375rem', marginBottom: '1rem', color: 'var(--text-muted)' }}>
                  No courses synced yet. Connect your Google account to import your Classroom data.
                </p>
                <button onClick={handleConnectGoogle} className="btn-google">
                  Connect Google Classroom
                </button>
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '1.25rem' }}>
                {semesterCourses.map((course) => (
                  <div key={course.id} className="glass-panel-interactive" style={{ padding: '1.25rem', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                        <h4 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>{course.name}</h4>
                        <span className="badge badge-info">{course.section || 'Active'}</span>
                      </div>
                      <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', marginBottom: '1rem', lineHeight: 1.4 }}>
                        {course.description || 'No description provided.'}
                      </p>
                    </div>
                    <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                      <span>Teacher: {course.teacher_name || 'Instructor'}</span>
                      {course.alternate_link && (
                        <a
                          href={course.alternate_link}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#0f172a', textDecoration: 'underline', fontWeight: 500 }}
                        >
                          Open Classroom
                        </a>
                      )}
                    </div>
                    <button onClick={() => handleLoadRoster(course.id)} className="roster-toggle">
                      {rosterLoading === course.id ? 'Loading roster…' : courseRosters[course.id] ? 'Hide class roster' : 'View class roster'}
                    </button>
                    {Array.isArray(courseRosters[course.id]) && (
                      <div className="roster-list">
                        {courseRosters[course.id].length ? courseRosters[course.id].map((student) => (
                          <div className="roster-student" key={student.id || student.name}>
                            <span>{student.name}</span><small>{student.email || 'Student'}</small>
                          </div>
                        )) : <span className="roster-empty">No students were returned for this course.</span>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Assignments Hub */}
        {activeTab === 'assignments' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-main)' }}>Assignments Tracker</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                  Manage, review, and track course deliverables from semester start: <strong>{semesterStartDate || 'All time'}</strong>.
                </p>
              </div>

              {/* Filter Pills */}
              <div style={{ display: 'flex', gap: '4px', background: '#f1f5f9', padding: '3px', borderRadius: 'var(--radius-md)' }}>
                {['all', 'missing', 'assignments', 'quizzes', 'open', 'submitted', 'announcements'].map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setAssignmentFilter(filter)}
                    style={{
                      padding: '4px 10px',
                      borderRadius: 'var(--radius-sm)',
                      background: assignmentFilter === filter ? '#ffffff' : 'transparent',
                      color: assignmentFilter === filter ? '#0f172a' : 'var(--text-muted)',
                      border: assignmentFilter === filter ? '1px solid #cbd5e1' : '1px solid transparent',
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      textTransform: 'capitalize',
                      cursor: 'pointer',
                      boxShadow: assignmentFilter === filter ? 'var(--shadow-sm)' : 'none',
                    }}
                  >
                    {filter}
                  </button>
                ))}
              </div>
            </div>

            <div className="classroom-filters">
              <input aria-label="Search Classroom work and announcements" value={classroomSearch} onChange={(event) => setClassroomSearch(event.target.value)} placeholder="Search titles, courses, or announcements" />
              <select aria-label="Filter by course" value={classroomCourseFilter} onChange={(event) => setClassroomCourseFilter(event.target.value)}>
                <option value="all">All courses</option>
                {semesterCourses.map((course) => <option key={course.id} value={String(course.id)}>{course.name}</option>)}
              </select>
              <span>{assignmentFilter === 'announcements' ? filteredClassroomAnnouncements.length : filteredAssignments.length} items</span>
            </div>

            {assignmentFilter === 'announcements' ? (
              filteredClassroomAnnouncements.length ? (
                <div className="classroom-announcement-list">
                  {filteredClassroomAnnouncements.map((item) => (
                    <article className="classroom-announcement glass-panel" key={item.external_id}>
                      <div className="announcement-meta"><span>{item.course_name}</span><time>{item.published_at ? new Date(item.published_at).toLocaleString() : 'Date unavailable'}</time></div>
                      <h4>{item.title}</h4>
                      <p>{item.content}</p>
                      {item.url && <a href={item.url} target="_blank" rel="noreferrer">Open in Google Classroom</a>}
                    </article>
                  ))}
                </div>
              ) : <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>No Classroom announcements match the active filters.</div>
            ) : filteredAssignments.length === 0 ? (
              <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                <p>No Classroom coursework matches the active semester filter. Click Sync to fetch the latest assignments.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {filteredAssignments.map((a) => (
                  <div
                    key={a.id}
                    className="glass-panel-interactive"
                    style={{
                      padding: '1.125rem 1.25rem',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      flexWrap: 'wrap',
                      gap: '1rem',
                    }}
                  >
                    <div style={{ maxWidth: '600px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <h4 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-main)' }}>{a.title}</h4>
                        <span className={`badge ${a.is_missing ? 'badge-danger' : ['TURNED_IN', 'RETURNED'].includes(a.submission_state) ? 'badge-success' : 'badge-warning'}`}>
                          {a.is_missing ? 'Missing' : ['TURNED_IN', 'RETURNED'].includes(a.submission_state) ? 'Submitted' : a.status || 'Open'}
                        </span>
                        <span className="work-type-tag">{a.is_quiz ? 'Quiz' : (a.work_type || 'Assignment').replaceAll('_', ' ').toLowerCase()}</span>
                      </div>
                      {a.description && (
                        <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem', lineHeight: 1.4, marginBottom: '6px' }}>
                          {a.description}
                        </p>
                      )}
                      <div style={{ display: 'flex', gap: '15px', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                        <span>{a.course_name}</span>
                        <span>Due: {a.due_at ? new Date(a.due_at).toLocaleString() : 'No deadline'}</span>
                        {a.submission_state && <span>Classroom: {a.submission_state.replaceAll('_', ' ').toLowerCase()}</span>}
                        {a.state && <span>State: {a.state}</span>}
                      </div>
                      {a.materials?.length > 0 && <div className="assignment-materials">{a.materials.map((material) => material.url ? <a key={material.id} href={material.url} target="_blank" rel="noreferrer">{material.title || material.type}</a> : <span key={material.id}>{material.title || material.type}</span>)}</div>}
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      {a.url && (
                        <a href={a.url} target="_blank" rel="noreferrer" className="btn-secondary" style={{ padding: '6px 12px', fontSize: '0.75rem' }}>
                          Classroom Link
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Schedule & Attendance */}
        {activeTab === 'schedule' && (
          <div className="schedule-page">
            {/* Top Timetable Toolbar */}
            <section className="timetable-import glass-panel">
              <div className="schedule-section-heading">
                <div>
                  <div className="eyebrow">ACADEMIC SCHEDULE</div>
                  <h3>Weekly Class Timetable</h3>
                  <p>Upload your timetable image (PNG, JPG) or PDF — AI extracts tabular data automatically and populates your weekly matrix.</p>
                </div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <label className="btn-primary upload-timetable-button" style={{ cursor: 'pointer', margin: 0 }}>
                    {timetableBusy ? 'Extracting with AI…' : 'Upload Timetable Image / PDF'}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/bmp,application/pdf,.pdf"
                      onChange={handleTimetableImage}
                      disabled={timetableBusy}
                      style={{ display: 'none' }}
                    />
                  </label>
                  <button className="btn-secondary" onClick={() => setShowManualAddRow(!showManualAddRow)}>
                    {showManualAddRow ? 'Close Form' : '+ Add Class'}
                  </button>
                  {timetableEntries.length > 0 && (
                    <button className="btn-secondary" style={{ color: '#dc2626' }} onClick={handleClearAllTimetable} disabled={timetableBusy}>
                      Clear Schedule
                    </button>
                  )}
                </div>
              </div>

              {timetableFileName && (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>Source: <strong>{timetableFileName}</strong></span>
                  {semesterName && <span className="badge badge-neutral">{semesterName}</span>}
                  <span className="count-pill">{timetableEntries.length} weekly classes</span>
                </div>
              )}

              {/* Inline Manual Add Class Form */}
              {showManualAddRow && (
                <div style={{ marginTop: '1rem', padding: '1rem', background: '#f8fafc', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}>
                  <div style={{ fontSize: '0.8125rem', fontWeight: 600, marginBottom: '0.75rem', color: 'var(--text-main)' }}>Add Class Manually</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px', marginBottom: '10px' }}>
                    <div>
                      <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Course Title *</label>
                      <input
                        style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                        value={newClassSubject}
                        onChange={(e) => setNewClassSubject(e.target.value)}
                        placeholder="e.g. CS-301 Data Structures"
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Start Time *</label>
                      <input
                        type="time"
                        style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                        value={newClassStartTime}
                        onChange={(e) => setNewClassStartTime(e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>End Time *</label>
                      <input
                        type="time"
                        style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                        value={newClassEndTime}
                        onChange={(e) => setNewClassEndTime(e.target.value)}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Teacher</label>
                      <input
                        style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                        value={newClassTeacher}
                        onChange={(e) => setNewClassTeacher(e.target.value)}
                        placeholder="e.g. Dr. Ali"
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Room / Venue</label>
                      <input
                        style={{ width: '100%', padding: '6px 8px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}
                        value={newClassRoom}
                        onChange={(e) => setNewClassRoom(e.target.value)}
                        placeholder="e.g. Room C-101"
                      />
                    </div>
                  </div>
                  <div style={{ marginBottom: '10px' }}>
                    <label style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Class Days *</label>
                    <div className="weekday-picker" style={{ margin: 0 }}>
                      {WEEKDAYS.map((day, dayIndex) => (
                        <label key={day}>
                          <input
                            type="checkbox"
                            checked={newClassWeekdays.includes(dayIndex)}
                            onChange={(event) => setNewClassWeekdays(event.target.checked ? [...newClassWeekdays, dayIndex].sort() : newClassWeekdays.filter((v) => v !== dayIndex))}
                          />
                          {day.slice(0, 3)}
                        </label>
                      ))}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button className="btn-primary" onClick={handleManualAddClass} disabled={timetableBusy}>Save Class</button>
                    <button className="btn-secondary" onClick={() => setShowManualAddRow(false)}>Cancel</button>
                  </div>
                </div>
              )}

              {/* View Mode Switcher Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-main)' }}>
                  Weekly Schedule Matrix
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    className={`btn-secondary ${timetableViewMode === 'matrix' ? 'btn-active' : ''}`}
                    style={{ padding: '4px 10px', fontSize: '0.75rem', background: timetableViewMode === 'matrix' ? '#0f172a' : '#ffffff', color: timetableViewMode === 'matrix' ? '#ffffff' : '#334155' }}
                    onClick={() => setTimetableViewMode('matrix')}
                  >
                    Matrix Grid
                  </button>
                  <button
                    className={`btn-secondary ${timetableViewMode === 'list' ? 'btn-active' : ''}`}
                    style={{ padding: '4px 10px', fontSize: '0.75rem', background: timetableViewMode === 'list' ? '#0f172a' : '#ffffff', color: timetableViewMode === 'list' ? '#ffffff' : '#334155' }}
                    onClick={() => setTimetableViewMode('list')}
                  >
                    List View
                  </button>
                </div>
              </div>

              {/* TABULAR WEEKLY TIMETABLE MATRIX */}
              {timetableViewMode === 'matrix' ? (
                <div className="timetable-matrix-container">
                  <div className="timetable-matrix-grid">
                    {WEEKDAYS.map((dayName, dayIndex) => {
                      const dayClasses = timetableEntries
                        .filter((entry) => entry.weekday === dayIndex)
                        .sort((a, b) => a.start_time.localeCompare(b.start_time));
                      const isToday = mounted && ((new Date().getDay() + 6) % 7) === dayIndex;

                      return (
                        <div className={`matrix-day-col ${isToday ? 'is-today' : ''}`} key={dayName}>
                          <div className="matrix-day-header">
                            <span>{dayName}</span>
                            {isToday ? <span className="today-badge">Today</span> : <span className="count-pill">{dayClasses.length}</span>}
                          </div>
                          <div className="matrix-day-body">
                            {dayClasses.length === 0 ? (
                              <div className="matrix-empty-day">No classes</div>
                            ) : (
                              dayClasses.map((item) => (
                                <div className="matrix-class-card" key={item.id}>
                                  <button
                                    className="delete-btn"
                                    title="Delete class"
                                    onClick={() => handleDeleteTimetableClass(item.id)}
                                  >
                                    ✕
                                  </button>
                                  <span className="card-time">{formatClassTime(item.start_time)} – {formatClassTime(item.end_time)}</span>
                                  <div className="card-subject">{item.subject}</div>
                                  <div className="card-meta">
                                    {item.room && <span>Room {item.room}</span>}
                                    {item.teacher && <span>{item.teacher}</span>}
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                /* List View */
                <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {timetableEntries.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)', fontSize: '0.8125rem' }}>
                      No classes scheduled. Upload a timetable image above to build your weekly view.
                    </div>
                  ) : (
                    timetableEntries.map((entry) => (
                      <article className="weekly-class-row" key={entry.id} style={{ padding: '8px 12px', background: '#ffffff', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <span className="weekday-pill">{entry.weekday_name}</span>
                          <strong>{entry.subject}</strong>
                          <small style={{ color: 'var(--text-muted)' }}>
                            {formatClassTime(entry.start_time)} – {formatClassTime(entry.end_time)} · {entry.teacher || 'Teacher not listed'} · Room {entry.room || 'TBA'}
                          </small>
                        </div>
                        <button className="remove-draft-button" onClick={() => handleDeleteTimetableClass(entry.id)}>Remove</button>
                      </article>
                    ))
                  )}
                </div>
              )}
            </section>

            {/* Today's Classes & Alerts */}
            <div className="timetable-tools-row" style={{ marginTop: '1.25rem' }}>
              <section className="glass-panel timetable-list-card">
                <div className="schedule-section-heading compact">
                  <div>
                    <div className="eyebrow">TODAY</div>
                    <h3>Today’s Classes</h3>
                  </div>
                  <span className="count-pill">{todayClasses.length}</span>
                </div>
                {todayClasses.length ? (
                  todayClasses.map((entry, index) => (
                    <article className="today-class-row" key={`today-${entry.id}-${index}`}>
                      <div>
                        <strong>{entry.subject}</strong>
                        <span>{formatClassTime(entry.start_time)} – {formatClassTime(entry.end_time)}</span>
                        <small>{entry.teacher || 'Teacher not listed'} · Room {entry.room || 'TBA'}</small>
                      </div>
                      <b className={`class-status ${classTimeStatus(entry, clock).toLowerCase().replaceAll(' ', '-')}`}>{classTimeStatus(entry, clock)}</b>
                    </article>
                  ))
                ) : (
                  <p className="timetable-empty">No classes scheduled for today. Upload your timetable above to build today’s view.</p>
                )}
                <div className="class-alert-controls">
                  <label>
                    Alert before
                    <select value={reminderMinutes} onChange={(event) => setReminderMinutes(Number(event.target.value))}>
                      <option value={5}>5 minutes</option>
                      <option value={10}>10 minutes</option>
                      <option value={15}>15 minutes</option>
                      <option value={30}>30 minutes</option>
                      <option value={60}>1 hour</option>
                    </select>
                  </label>
                  <button className="btn-secondary" onClick={handleEnableClassAlerts}>
                    {classAlertsEnabled ? 'Class alerts enabled' : 'Enable class alerts'}
                  </button>
                </div>
                <p className="ocr-setup-note">Browser alerts appear while Uniflow is open.</p>
              </section>

              <section className="glass-panel timetable-list-card">
                <div className="schedule-section-heading compact">
                  <div>
                    <div className="eyebrow">SUMMARY</div>
                    <h3>Schedule Statistics</h3>
                  </div>
                  <span className="count-pill">{timetableEntries.length} Total</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#f8fafc', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Weekly Classes</span>
                    <strong style={{ color: 'var(--text-main)' }}>{timetableEntries.length} sessions</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#f8fafc', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Today&apos;s Classes</span>
                    <strong style={{ color: 'var(--text-main)' }}>{todayClasses.length} sessions</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#f8fafc', borderRadius: 'var(--radius-sm)', fontSize: '0.8125rem' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Semester</span>
                    <strong style={{ color: 'var(--text-main)' }}>{semesterName || 'Active Semester'}</strong>
                  </div>
                </div>
              </section>
            </div>

            <section className="glass-panel portal-setup-card">
              <div className="schedule-section-heading">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <span className="eyebrow">UNIVERSITY PORTAL & AUTO-SYNC</span>
                    {portalSessionStatus === 'ACTIVE' && (
                      <span className="badge badge-success" style={{ fontSize: '0.6875rem' }}>🟢 Auto-Sync Session Active</span>
                    )}
                    {portalSessionStatus === 'EXPIRED' && (
                      <span className="badge badge-danger" style={{ fontSize: '0.6875rem' }}>🔴 Session Expired — Re-authenticate</span>
                    )}
                    {portalSessionStatus === 'NOT_CONFIGURED' && (
                      <span className="badge" style={{ fontSize: '0.6875rem', background: '#e2e8f0', color: '#475569' }}>⚪ Initial Sign-In Needed</span>
                    )}
                  </div>
                  <h3>Attendance & academic radar</h3>
                  <p>Log in once in the secure browser and capture your report. Uniflow memorizes your destination path and session cookies to fetch updates headlessly in the background.</p>
                </div>
                {portalReport?.cgpa != null && <div className="portal-gpa"><span>CGPA</span><strong>{portalReport.cgpa}</strong></div>}
              </div>

              <div className="portal-url-row">
                <label>University portal URL
                  <input
                    type="url"
                    value={portalUrl}
                    onChange={(event) => setPortalUrl(event.target.value)}
                    placeholder="https://portals.au.edu.pk/students/"
                  />
                </label>
                <label>Student login email
                  <input
                    type="email"
                    value={portalLoginEmail}
                    onChange={(event) => setPortalLoginEmail(event.target.value)}
                    placeholder="student@au.edu.pk"
                  />
                </label>
                <label>Portal sign-in
                  <select value={portalAuthMethod} onChange={(event) => setPortalAuthMethod(event.target.value)}>
                    <option value="google">Google SSO</option>
                    <option value="password">Email and password</option>
                    <option value="either">Detect either</option>
                  </select>
                </label>
                <button className="btn-secondary" onClick={handleSavePortalUrl} disabled={portalBusy || !portalUrl.trim()}>
                  Save requirements
                </button>
              </div>

              <div className="portal-actions">
                <button className="btn-primary" onClick={handleOpenPortal} disabled={portalBusy || !portalUrl.trim()}>
                  {portalBusy ? 'Working…' : portalBrowserInfo?.opened ? 'Browser is open' : 'Open secure sign-in browser'}
                </button>
                <button className="btn-secondary" onClick={handleCapturePortalReport} disabled={portalBusy || !portalBrowserInfo?.opened}>
                  Capture & memorise flow
                </button>
                <button
                  className="btn-secondary"
                  onClick={handleHeadlessPortalSync}
                  disabled={portalHeadlessSyncing || portalBusy || portalSessionStatus === 'NOT_CONFIGURED'}
                  title={portalSessionStatus === 'NOT_CONFIGURED' ? 'Complete initial login & capture first' : 'Trigger background headless fetch using saved session'}
                >
                  {portalHeadlessSyncing ? 'Auto-syncing…' : '⚡ Sync now (background)'}
                </button>
                {portalBrowserInfo?.opened && (
                  <button className="portal-link-button" onClick={handleClosePortal}>
                    Close browser
                  </button>
                )}
              </div>

              {portalBrowserInfo?.opened && (
                <div className="portal-browser-instructions">
                  <strong>{portalBrowserInfo.title || 'Portal browser is open'}</strong>
                  <span>{portalBrowserInfo.message || (portalBrowserInfo.google_sign_in_available ? 'Sign in with your Google account in the opened browser window.' : portalBrowserInfo.password_form_available ? 'Enter your portal credentials in the opened browser window.' : 'Sign in in the opened browser window.')}</span>
                  <span style={{ fontSize: '0.75rem', opacity: 0.85 }}>Uniflow never collects or stores your passwords. After logging in, navigate to your attendance report and click &apos;Capture &amp; memorise flow&apos;.</span>
                </div>
              )}

              <div className="portal-summary-line" style={{ flexWrap: 'wrap', gap: '1rem' }}>
                <span>Semester: <strong>{portalReport?.semester_name || 'Not detected yet'}</strong></span>
                <span>Last auto-synced: <strong>{portalLastSyncedAt ? new Date(portalLastSyncedAt).toLocaleString() : 'Not synced yet'}</strong></span>
                {portalAttendanceUrl && (
                  <span style={{ maxWidth: '100%', wordBreak: 'break-all', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Saved Destination: <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: '4px' }}>{portalAttendanceUrl}</code>
                  </span>
                )}
              </div>
              <p className="ocr-setup-note">Session cookies and destination URLs are securely kept locally in your backend environment. Background sync runs headlessly without disturbing your workflow.</p>
            </section>

            {/* Attendance Breakdown */}
            <div className="glass-panel attendance-breakdown" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>Attendance Breakdown</h3>
                <span className="badge badge-success">Target: 75%+</span>
              </div>
              {attendance?.per_course?.length ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {attendance.per_course.map((item, idx) => (
                    <div key={idx}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem', marginBottom: '4px' }}>
                        <span style={{ fontWeight: 500, color: 'var(--text-main)' }}>{item.course_name || item.subject}</span>
                        <span style={{ color: item.percentage < 75 ? '#b91c1c' : '#15803d', fontWeight: 600 }}>
                          {item.percentage}% ({item.attended}/{item.total})
                        </span>
                      </div>
                      <div style={{ width: '100%', height: '6px', background: '#f1f5f9', borderRadius: '3px', overflow: 'hidden' }}>
                        <div
                          style={{
                            width: `${Math.min(item.percentage, 100)}%`,
                            height: '100%',
                            background: item.percentage < 75 ? '#ef4444' : '#10b981',
                            borderRadius: '3px',
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>No attendance records found.</p>
              )}
            </div>
          </div>
        )}

        {/* Tab 5: Exams & Notices */}
        {activeTab === 'university' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: '1.25rem' }}>
            {/* Exams Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>University Exams</h3>
                <span className="count-pill">{semesterExams.length} scheduled</span>
              </div>
              {semesterExams.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>No upcoming exams scheduled.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {semesterExams.map((exam) => (
                    <div
                      key={exam.id}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 'var(--radius-md)',
                        background: '#f8fafc',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: '0.8125rem', color: 'var(--text-main)' }}>{exam.title}</div>
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '3px' }}>
                        Date: {exam.date ? new Date(exam.date).toLocaleDateString() : 'TBA'} · Time: {exam.time || 'TBA'} · Room: {exam.room || 'TBA'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Announcements Card */}
            <div className="glass-panel" style={{ padding: '1.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--text-main)' }}>Campus Announcements</h3>
                <span className="count-pill">{semesterUniversityAnnouncements.length} notices</span>
              </div>
              {semesterUniversityAnnouncements.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '0.8125rem' }}>No recent announcements.</p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {semesterUniversityAnnouncements.map((ann) => (
                    <div
                      key={ann.id}
                      style={{
                        padding: '10px 14px',
                        borderRadius: 'var(--radius-md)',
                        background: '#f8fafc',
                        border: '1px solid var(--border-subtle)',
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: '0.8125rem', color: 'var(--text-main)' }}>{ann.title}</div>
                      {ann.content && (
                        <p style={{ color: 'var(--text-muted)', fontSize: '0.75rem', marginTop: '3px', lineHeight: 1.4 }}>
                          {ann.content}
                        </p>
                      )}
                      <div style={{ color: 'var(--text-dim)', fontSize: '0.6875rem', marginTop: '4px' }}>
                        Source: {ann.source || 'University Portal'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 6: Integrations & Settings */}
        {activeTab === 'workspace' && (
          <section className="workspace-page">
            <div className="workspace-heading">
              <div>
                <div className="eyebrow">GOOGLE WORKSPACE</div>
                <h2>Mail & files</h2>
                <p>Latest inbox messages and recently updated Drive files from semester start ({semesterStartDate || 'All time'}).</p>
              </div>
              {authStatus?.google_connected && <span className="connection-label"><span /> Google connected</span>}
            </div>
            {!authStatus?.google_connected ? (
              <div className="workspace-empty glass-panel">
                <div className="workspace-icon">G</div>
                <h3>Connect your Google account</h3>
                <p>One secure connection powers Classroom, Gmail, Docs, and Drive.</p>
                <button onClick={handleConnectGoogle} className="btn-google">Connect Google</button>
              </div>
            ) : workspaceError ? (
              <div className="workspace-notice"><strong>Google needs permission to read mail and files.</strong><span>{workspaceError}</span><button onClick={handleConnectGoogle} className="btn-secondary">Reconnect Google</button></div>
            ) : (
              <div className="workspace-grid">
                <article className="workspace-card glass-panel">
                  <div className="workspace-card-heading"><div><div className="eyebrow">INBOX</div><h3>Latest emails</h3></div><span className="count-pill">{recentEmails.length}</span></div>
                  {recentEmails.length ? recentEmails.map((email) => (
                    <a className="email-row" key={email.id} href={`https://mail.google.com/mail/u/0/#all/${email.id}`} target="_blank" rel="noreferrer">
                      <span className={`mail-dot ${email.unread ? 'is-unread' : ''}`} />
                      <div className="email-copy"><strong>{email.subject}</strong><span>{email.from}</span><small>{email.snippet}</small></div>
                      <time>{email.date ? new Date(email.date).toLocaleDateString() : ''}</time>
                    </a>
                  )) : <div className="workspace-blank">No recent inbox messages for this semester.</div>}
                </article>
                <article className="workspace-card glass-panel">
                  <div className="workspace-card-heading"><div><div className="eyebrow">GOOGLE DRIVE</div><h3>Recent files</h3></div><span className="count-pill">{driveFiles.length}</span></div>
                  {driveFiles.length ? driveFiles.map((file) => {
                    const isDoc = file.mimeType === 'application/vnd.google-apps.document';
                    return <a className="file-row" key={file.id} href={file.webViewLink || `https://drive.google.com/open?id=${file.id}`} target="_blank" rel="noreferrer"><span className={`file-type ${isDoc ? 'doc-type' : ''}`}>{isDoc ? 'DOC' : 'FILE'}</span><div className="file-copy"><strong>{file.name}</strong><span>{isDoc ? 'Google Doc' : file.mimeType?.split('.').pop() || 'Drive file'}</span></div><time>{file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}</time></a>;
                  }) : <div className="workspace-blank">No files found in Google Drive for this semester.</div>}
                </article>
              </div>
            )}
            <div className="workspace-footnote">Email content is limited to sender, subject, date, and preview. Your messages are never changed.</div>
          </section>
        )}

        {activeTab === 'settings' && (
          <div className="glass-panel" style={{ padding: '1.5rem', maxWidth: '800px' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '1.25rem' }}>System & Integration Status</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
              {/* Semester Start Date Config */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)', flexWrap: 'wrap', gap: '10px' }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Semester Start Date Filter</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    Ignores all past semester coursework, announcements, and emails before this date.
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input
                    type="date"
                    value={semesterStartDate}
                    onChange={(e) => handleSaveSemesterStartDate(e.target.value)}
                    style={{
                      padding: '4px 8px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-subtle)',
                      fontSize: '0.75rem',
                      color: 'var(--text-main)',
                      background: '#ffffff',
                    }}
                  />
                  {semesterStartDate && (
                    <button
                      onClick={() => handleSaveSemesterStartDate('')}
                      className="btn-secondary"
                      style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>

              {/* Integration 1: Clerk Auth */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Clerk Authentication</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    Logged in as {user?.primaryEmailAddress?.emailAddress}
                  </div>
                </div>
                <span className="badge badge-success">Active</span>
              </div>

              {/* Integration 2: Google Classroom */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Google Classroom OAuth</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    {authStatus?.google_connected
                      ? `Connected (${authStatus.google_email || 'Active'})`
                      : 'Not connected'}
                  </div>
                </div>
                {authStatus?.google_connected ? (
                  <button onClick={handleDisconnectGoogle} className="btn-secondary" style={{ fontSize: '0.75rem', padding: '5px 10px' }}>
                    Disconnect
                  </button>
                ) : (
                  <button onClick={handleConnectGoogle} className="btn-google" style={{ fontSize: '0.75rem', padding: '5px 10px' }}>
                    Connect
                  </button>
                )}
              </div>

              {/* Integration 3: FastAPI Backend */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Uniflow FastAPI Backend</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    API health is checked live from the dashboard.
                  </div>
                </div>
                <span className={`badge ${backendHealth?.status === 'healthy' ? 'badge-success' : 'badge-danger'}`}>
                  {backendHealth?.status === 'healthy' ? 'Online' : 'Offline'}
                </span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div><div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Gmail, Google Docs & Drive</div><div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{authStatus?.google_connected ? 'Uses the connected Google account' : 'Available after Google connection'}</div></div>
                <span className={`badge ${authStatus?.google_connected ? 'badge-success' : 'badge-warning'}`}>{authStatus?.google_connected ? 'Connected' : 'Not connected'}</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div><div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>University portal & attendance</div><div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Portal URL and sign-in flow are configured via schedule tab.</div></div>
                <span className="badge badge-warning">Configurable</span>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0' }}>
                <div>
                  <div style={{ fontWeight: 500, fontSize: '0.8125rem', color: 'var(--text-main)' }}>Database Storage</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                    PostgreSQL storage backend configured server-side.
                  </div>
                </div>
                <span className="badge badge-info">Managed</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
