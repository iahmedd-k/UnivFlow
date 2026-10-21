'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import { isExtensionInstalled, syncGcrViaExtension, autoVisitAndSyncGcr, syncSelectedViaExtension, EXTENSION_VERSION } from '@/app/lib/extensionBridge';

export default function SettingsPage() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [notificationEmail, setNotificationEmail] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [browserStatus, setBrowserStatus] = useState(null);
  const [browserBusy, setBrowserBusy] = useState(false);
  const [browserError, setBrowserError] = useState('');
  const [browserNotice, setBrowserNotice] = useState('');

  // Student Academic Profile state
  const [studentName, setStudentName] = useState('');
  const [rollNo, setRollNo] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState('');
  const [profileError, setProfileError] = useState('');

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const token = await getToken();
        const p = await api.getStudentProfile(token);
        if (active && p) {
          setStudentName(p.student_name || '');
          setRollNo(p.roll_no || '');
        }
      } catch (err) {
        console.error('Failed to load student profile:', err);
      }
    })();
    return () => { active = false; };
  }, [getToken]);

  const handleSaveProfile = async (e) => {
    e.preventDefault();
    setSavingProfile(true);
    setProfileSuccess('');
    setProfileError('');
    try {
      const token = await getToken();
      await api.updateStudentProfile({
        student_name: studentName.trim(),
        roll_no: rollNo.trim(),
      }, token);
      setProfileSuccess('Academic identity saved! Google Docs and terminal outputs will use this name and Reg ID.');
    } catch (err) {
      setProfileError(err.message || 'Could not save student profile.');
    } finally {
      setSavingProfile(false);
    }
  };

  const loadEmail = useCallback(async () => {
    try {
      const token = await getToken();
      const result = await api.getNotificationEmail(token);
      setNotificationEmail(result?.email || '');
    } catch (err) {
      console.error('Failed to load notification email:', err);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    let active = true;
    const fetchEmail = async () => {
      try {
        const token = await getToken();
        const result = await api.getNotificationEmail(token);
        if (active) setNotificationEmail(result?.email || '');
      } catch (err) {
        console.error('Failed to load notification email:', err);
      } finally {
        if (active) setLoading(false);
      }
    };
    fetchEmail();
    return () => { active = false; };
  }, [getToken]);

  const loadBrowserStatus = useCallback(async () => {
    try {
      const token = await getToken();
      const result = await api.getClaudeBrowserStatus(token);
      setBrowserStatus(result);
      setBrowserError('');
    } catch (err) {
      setBrowserError(err.message || 'Could not load your private Claude browser status.');
    }
  }, [getToken]);

  useEffect(() => {
    let active = true;
    const fetchBrowser = async () => {
      try {
        const token = await getToken();
        const result = await api.getClaudeBrowserStatus(token);
        if (active) {
          setBrowserStatus(result);
          setBrowserError('');
        }
      } catch (err) {
        if (active) setBrowserError(err.message || 'Could not load your private Claude browser status.');
      }
    };
    fetchBrowser();
    return () => { active = false; };
  }, [getToken]);

  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleEmail, setGoogleEmail] = useState('');
  const [googleBusy, setGoogleBusy] = useState(false);
  const [gcrBrowserStatus, setGcrBrowserStatus] = useState(null);
  const [gcrBusy, setGcrBusy] = useState(false);

  const loadGoogleAuth = useCallback(async () => {
    try {
      const token = await getToken();
      const status = await api.getAuthStatus(token);
      setGoogleConnected(Boolean(status?.google_connected));
      setGoogleEmail(status?.google_email || '');
    } catch (err) {
      console.error('Failed to load Google auth status:', err);
    }
  }, [getToken]);

  const loadGcrStatus = useCallback(async () => {
    try {
      const token = await getToken();
      const status = await api.getClassroomBrowserStatus(token);
      setGcrBrowserStatus(status);
    } catch (err) {
      console.error('Failed to load Google Classroom browser status:', err);
    }
  }, [getToken]);

  useEffect(() => {
    let active = true;
    const fetchGoogle = async () => {
      try {
        const token = await getToken();
        const [status, gcr] = await Promise.all([
          api.getAuthStatus(token).catch(() => null),
          api.getClassroomBrowserStatus(token).catch(() => null),
        ]);
        if (active) {
          if (status) {
            setGoogleConnected(Boolean(status?.google_connected));
            setGoogleEmail(status?.google_email || '');
          }
          if (gcr) {
            setGcrBrowserStatus(gcr);
          }
        }
      } catch (err) {
        console.error('Failed to load Google auth status:', err);
      }
    };
    fetchGoogle();
    return () => { active = false; };
  }, [getToken]);

  const handleDisconnectGcrSession = async () => {
    if (!window.confirm('Disconnect your synced Google Classroom background session? Automatic background turn-in will need to be re-synced.')) return;
    setGcrBusy(true);
    setError('');
    setSuccess('');
    try {
      const token = await getToken();
      await api.disconnectClassroomSession(token);
      setSuccess('Google Classroom background session disconnected.');
      await loadGcrStatus();
    } catch (err) {
      setError(err.message || 'Could not disconnect Google Classroom background session.');
    } finally {
      setGcrBusy(false);
    }
  };

  const [extensionDetected, setExtensionDetected] = useState(false);
  const [syncOptionGcr, setSyncOptionGcr] = useState(true);
  const [syncOptionClaude, setSyncOptionClaude] = useState(false);
  const [syncOptionPortal, setSyncOptionPortal] = useState(false);
  const [forceClaude, setForceClaude] = useState(false);
  const [forcePortal, setForcePortal] = useState(false);
  const [extensionSyncBusy, setExtensionSyncBusy] = useState(false);
  const [showExtensionHelp, setShowExtensionHelp] = useState(false);

  useEffect(() => {
    setExtensionDetected(isExtensionInstalled());
    const onReady = () => setExtensionDetected(true);
    window.addEventListener('uniflow-companion-ready', onReady);
    const interval = setInterval(() => {
      if (isExtensionInstalled()) {
        setExtensionDetected(true);
        clearInterval(interval);
      }
    }, 1000);
    return () => {
      window.removeEventListener('uniflow-companion-ready', onReady);
      clearInterval(interval);
    };
  }, []);

  const handleExtensionSyncGcr = async () => {
    setExtensionSyncBusy(true);
    setError('');
    setSuccess('');
    try {
      const token = await getToken();
      const res = await syncGcrViaExtension({ token });
      setSuccess(res?.message || 'Google Classroom session synced from your Chrome profile!');
      await loadGcrStatus();
    } catch (err) {
      setError(err.message || 'Extension sync failed. Ensure you are signed into classroom.google.com in this Chrome profile.');
    } finally {
      setExtensionSyncBusy(false);
    }
  };

  const handleExtensionAutoVisitGcr = async () => {
    setExtensionSyncBusy(true);
    setError('');
    setSuccess('Opening Google Classroom in a tab to capture session cookies…');
    try {
      const token = await getToken();
      const res = await autoVisitAndSyncGcr({ token });
      setSuccess('✅ ' + (res?.message || 'Google Classroom session captured and synced!'));
      await loadGcrStatus();
    } catch (err) {
      setError(err.message || 'Could not auto-capture Classroom session.');
    } finally {
      setExtensionSyncBusy(false);
    }
  };

  const handleExtensionSyncSelected = async (autoVisit = false) => {
    if (!syncOptionGcr && !syncOptionClaude && !syncOptionPortal) {
      setError('Please select at least one session to sync.');
      return;
    }
    setExtensionSyncBusy(true);
    setError('');
    setSuccess(autoVisit ? 'Visiting required URLs and capturing sessions…' : 'Syncing selected sessions from this Chrome profile…');
    try {
      const token = await getToken();
      const claudeConnected = Boolean(browserStatus?.has_session_key);
      const portalConnected = Boolean(portalStatus?.has_session_cookies || portalStatus?.session_status === 'ACTIVE');

      const res = await syncSelectedViaExtension({
        token,
        syncGcr: syncOptionGcr,
        syncClaude: syncOptionClaude,
        syncPortal: syncOptionPortal,
        claudeAlreadyConnected: claudeConnected,
        portalAlreadyConnected: portalConnected,
        forceClaude,
        forcePortal,
        autoVisit,
      });

      const msgs = [];
      if (res?.results?.gcr && !res.results.gcr.skipped) msgs.push('Google Classroom ✓');
      if (res?.results?.claude && !res.results.claude.skipped) msgs.push('Claude.ai ✓');
      if (res?.results?.portal && !res.results.portal.skipped) msgs.push('Portal ✓');

      setSuccess(`✅ Synced: ${msgs.length > 0 ? msgs.join(', ') : 'Selected sessions updated'}`);
      await Promise.all([loadGcrStatus(), loadBrowserStatus(), loadPortalStatus()]);
    } catch (err) {
      setError(err.message || 'Session sync failed. Check your browser sessions.');
    } finally {
      setExtensionSyncBusy(false);
    }
  };

  const [tokenCopied, setTokenCopied] = useState(false);
  const handleCopyAuthToken = async () => {
    try {
      const token = await getToken();
      if (!token) throw new Error('Could not retrieve active session token. Please re-login.');
      await navigator.clipboard.writeText(token);
      setTokenCopied(true);
      setSuccess('📋 Fresh Uniflow Auth Token copied to clipboard! (You can paste it directly into the extension popup)');
      setTimeout(() => setTokenCopied(false), 3500);
    } catch (err) {
      setError('Could not copy token: ' + (err.message || 'Unknown error'));
    }
  };

  const handleConnectGoogle = async () => {
    setGoogleBusy(true);
    setError('');
    setSuccess('');
    try {
      const token = await getToken();
      const res = await api.getGoogleAuthUrl(token, '/dashboard/settings');
      if (res?.auth_url) {
        window.location.assign(res.auth_url);
      } else {
        throw new Error('Google did not return an authorization link.');
      }
    } catch (err) {
      setError(err.message || 'Could not initiate Google connection.');
      setGoogleBusy(false);
    }
  };

  const handleDisconnectGoogle = async () => {
    if (!window.confirm('Disconnect Google Classroom? Automatic sync and turn-in will be paused until reconnected.')) {
      return;
    }
    setGoogleBusy(true);
    setError('');
    setSuccess('');
    try {
      const token = await getToken();
      await api.disconnectGoogle(token);
      setGoogleConnected(false);
      setGoogleEmail('');
      setSuccess('Google Classroom disconnected successfully.');
      await loadGoogleAuth();
    } catch (err) {
      setError(err.message || 'Could not disconnect Google Classroom.');
    } finally {
      setGoogleBusy(false);
    }
  };

  const [portalStatus, setPortalStatus] = useState(null);
  const [portalCookieInput, setPortalCookieInput] = useState('');
  const [syncingPortalCookie, setSyncingPortalCookie] = useState(false);

  const loadPortalStatus = useCallback(async () => {
    try {
      const token = await getToken();
      const res = await api.getPortalSettings(token);
      setPortalStatus(res);
    } catch (err) {
      console.error('Failed to load portal status:', err);
    }
  }, [getToken]);

  useEffect(() => {
    let active = true;
    const fetchPortal = async () => {
      try {
        const token = await getToken();
        const res = await api.getPortalSettings(token);
        if (active) setPortalStatus(res);
      } catch (err) {
        console.error('Failed to load portal status:', err);
      }
    };
    fetchPortal();
    return () => { active = false; };
  }, [getToken]);

  const handleSyncPortalCookie = async (e) => {
    if (e) e.preventDefault();
    if (!portalCookieInput.trim()) {
      setBrowserError('Please enter your portal session cookie.');
      return;
    }
    setSyncingPortalCookie(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      const res = await api.syncPortalCookies(portalCookieInput.trim(), null, token);
      setBrowserNotice(res?.message || 'Portal session cookie connected successfully!');
      setPortalCookieInput('');
      await loadPortalStatus();
    } catch (err) {
      setBrowserError(err.message || 'Could not sync portal session cookie.');
    } finally {
      setSyncingPortalCookie(false);
    }
  };

  const handleDisconnectPortalCookie = async () => {
    if (!window.confirm('Disconnect your university portal session cookie?')) return;
    setSyncingPortalCookie(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      await api.disconnectPortalCookies(token);
      setBrowserNotice('Portal session cookies disconnected.');
      await loadPortalStatus();
    } catch (err) {
      setBrowserError(err.message || 'Could not disconnect portal session cookies.');
    } finally {
      setSyncingPortalCookie(false);
    }
  };

  const startClaudeBrowser = async () => {
    setBrowserBusy(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      const result = await api.openClaudeBrowser(token);
      setBrowserStatus((current) => ({ ...current, ...result, is_open: result.active }));
      setBrowserNotice(result.message || 'Your private Claude browser is ready.');
    } catch (err) {
      setBrowserError(err.message || 'Could not start your private Claude browser.');
    } finally {
      setBrowserBusy(false);
    }
  };

  const setAutomaticSolving = async (enabled) => {
    setBrowserBusy(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      await api.setAutomaticClaudeSolving(enabled, token);
      setBrowserStatus((current) => ({
        ...current,
        automatic_solving_enabled: enabled,
        jobs: enabled
          ? current?.jobs
          : (current?.jobs || []).map((job) => (
            ['pending', 'needs_login'].includes(job.status) ? { ...job, status: 'cancelled' } : job
          )),
      }));
      setBrowserNotice(enabled
        ? 'Automatic solving is enabled for newly detected eligible assignments.'
        : 'Automatic solving is disabled. Waiting jobs were cancelled; jobs already running will finish.');
    } catch (err) {
      setBrowserError(err.message || 'Could not update automatic solving.');
    } finally {
      setBrowserBusy(false);
    }
  };

  const resumeClaudeJobs = async () => {
    setBrowserBusy(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      const result = await api.resumeClaudeJobs(token);
      setBrowserNotice(`${result.resumed || 0} assignment job(s) resumed.`);
      await loadBrowserStatus();
    } catch (err) {
      setBrowserError(err.message || 'Could not resume Claude jobs.');
    } finally {
      setBrowserBusy(false);
    }
  };

  const [sessionKeyInput, setSessionKeyInput] = useState('');
  const [syncingKey, setSyncingKey] = useState(false);

  const handleSyncSessionKey = async (e) => {
    if (e) e.preventDefault();
    if (!sessionKeyInput.trim()) {
      setBrowserError('Please enter a valid Claude sessionKey.');
      return;
    }
    setSyncingKey(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      const res = await api.syncClaudeSession(sessionKeyInput.trim(), navigator.userAgent, token);
      setBrowserNotice(res?.message || 'Claude session connected successfully!');
      setSessionKeyInput('');
      await loadBrowserStatus();
    } catch (err) {
      setBrowserError(err.message || 'Could not sync Claude session key.');
    } finally {
      setSyncingKey(false);
    }
  };

  const handleDisconnectSessionKey = async () => {
    if (!window.confirm('Disconnect your Claude session key? Automatic solving will need to be reconnected.')) {
      return;
    }
    setSyncingKey(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      await api.disconnectClaudeSession(token);
      setBrowserNotice('Claude session disconnected.');
      await loadBrowserStatus();
    } catch (err) {
      setBrowserError(err.message || 'Could not disconnect Claude session.');
    } finally {
      setSyncingKey(false);
    }
  };

  const deleteClaudeProfile = async () => {
    if (!window.confirm('Delete your saved Claude browser profile and sign-in session? Automatic solving will also be disabled.')) {
      return;
    }
    setBrowserBusy(true);
    setBrowserError('');
    setBrowserNotice('');
    try {
      const token = await getToken();
      await api.deleteClaudeBrowserProfile(token);
      setBrowserStatus((current) => ({
        ...current,
        active: false,
        is_open: false,
        has_session_key: false,
        profile_exists: false,
        automatic_solving_enabled: false,
        viewer_url: null,
      }));
      setBrowserNotice('Your private Claude profile was deleted and automatic solving was disabled.');
    } catch (err) {
      setBrowserError(err.message || 'Could not delete your Claude browser profile.');
    } finally {
      setBrowserBusy(false);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!notificationEmail.trim()) {
      setError('Please enter an email address');
      return;
    }
    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(notificationEmail)) {
      setError('Please enter a valid email address');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      await api.setNotificationEmail(notificationEmail.trim(), token);
      setSuccess('Notification email saved successfully!');
    } catch (err) {
      setError(err.message || 'Could not save notification email');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Are you sure you want to remove your notification email? You will no longer receive email alerts.')) {
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      await api.deleteNotificationEmail(token);
      setNotificationEmail('');
      setSuccess('Notification email removed');
    } catch (err) {
      setError(err.message || 'Could not remove notification email');
    } finally {
      setSaving(false);
    }
  };

  const handleTestEmail = async () => {
    if (!notificationEmail.trim()) {
      setError('Please save an email address first');
      return;
    }

    setSaving(true);
    setError('');
    setSuccess('');

    try {
      const token = await getToken();
      const res = await api.sendTestEmail(notificationEmail.trim(), token);
      setSuccess(res?.message || `Test alert successfully delivered to ${notificationEmail.trim()} via SendGrid! Check your inbox.`);
    } catch (err) {
      setError(err.message || 'Could not send test email');
    } finally {
      setSaving(false);
    }
  };

  const userEmail = user?.primaryEmailAddress?.emailAddress || 'your-email@example.com';

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">PREFERENCES</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-xs text-[#858998]">Manage your notification preferences and account settings.</p>
        </div>
      </header>

      {error && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]" role="alert">{error}</div>}
      {success && <div className="rounded-lg border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2.5 text-xs text-[#43816b]" role="status">{success}</div>}
      {browserError && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]" role="alert">{browserError}</div>}
      {/* Student Academic Profile Section */}
      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="border-b border-[#f0f0f3] px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">STUDENT ACADEMIC PROFILE</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Full Name & Registration ID</h2>
          </div>
          {rollNo && studentName ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f3fbf7] px-2.5 py-1 text-xs font-semibold text-[#3a8369] border border-[#d8eee4]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#3a8369]" /> {rollNo} · {studentName}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#fff8f8] px-2.5 py-1 text-xs font-medium text-[#a04a4a] border border-[#f1dede]">
              Profile Incomplete
            </span>
          )}
        </header>
        <div className="p-5 flex flex-col gap-4">
          <p className="rounded-lg bg-[#faf9fe] border border-[#e8e7f8] p-3 text-xs leading-relaxed text-[#686c80]">
            Used automatically on official Google Docs cover pages, Google Doc filenames (<code className="font-mono text-[#5142c1]">&lt;Name&gt;_&lt;Assignment&gt;_&lt;RegID&gt;</code>), and authentic terminal execution screenshot directories.
          </p>

          {profileError && <div className="rounded-md border border-[#f1dede] bg-[#fff8f8] px-3 py-2 text-xs text-[#a04a4a]">{profileError}</div>}
          {profileSuccess && <div className="rounded-md border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2 text-xs text-[#43816b]">{profileSuccess}</div>}

          <form onSubmit={handleSaveProfile} className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl">
            <div>
              <label htmlFor="studentName" className="mb-1 block text-xs font-medium text-[#696d7d]">
                Full Student Name
              </label>
              <input
                type="text"
                id="studentName"
                className="w-full rounded-md border border-[#e4e4eb] bg-white px-3 py-2 text-xs text-[#343746] outline-none focus:border-[#6657d9] focus:ring-2 focus:ring-[#6657d9]/20"
                value={studentName}
                onChange={(e) => setStudentName(e.target.value)}
                placeholder="e.g. Ahmed Khan"
                required
              />
            </div>
            <div>
              <label htmlFor="rollNo" className="mb-1 block text-xs font-medium text-[#696d7d]">
                Registration ID / Roll No
              </label>
              <input
                type="text"
                id="rollNo"
                className="w-full rounded-md border border-[#e4e4eb] bg-white px-3 py-2 text-xs font-mono text-[#343746] outline-none focus:border-[#6657d9] focus:ring-2 focus:ring-[#6657d9]/20"
                value={rollNo}
                onChange={(e) => setRollNo(e.target.value)}
                placeholder="e.g. 232530"
                required
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={savingProfile || !studentName.trim() || !rollNo.trim()}
                className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-4 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55"
              >
                {savingProfile ? 'Saving…' : 'Save Academic Identity'}
              </button>
            </div>
          </form>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="border-b border-[#f0f0f3] px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">CLAUDE AI CONNECTION</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">1-Click Sync & Automatic Solving</h2>
          </div>
          {browserStatus?.has_session_key ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f3fbf7] px-2.5 py-1 text-xs font-semibold text-[#3a8369] border border-[#d8eee4]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#3a8369]" /> Connected (Session Cookie)
            </span>
          ) : browserStatus?.is_open ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f6f5fe] px-2.5 py-1 text-xs font-semibold text-[#6657d9] border border-[#e5e1fc]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#6657d9]" /> Browser Running
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f8f8fb] px-2.5 py-1 text-xs font-medium text-[#747887] border border-[#ebebf0]">
              Not Connected
            </span>
          )}
        </header>

        <div className="flex flex-col gap-5 p-5">
          {/* Method 1: Instant Session Cookie Connection */}
          <div className="rounded-lg border border-[#e8e7f8] bg-[#faf9fe] p-4 flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 className="text-xs font-semibold text-[#483ba6]">⚡ 1-Click Fast Sync (No Captchas, No VNC Lag)</h3>
                <p className="mt-1 text-xs leading-relaxed text-[#686c80] max-w-2xl">
                  Sync your Claude session directly. Eliminates Google OAuth &quot;Insecure browser&quot; blocks, avoids Cloudflare captchas, and requires zero remote browser streaming.
                </p>
              </div>
              {browserStatus?.has_session_key && (
                <button
                  type="button"
                  className="rounded-md border border-[#e0c4c4] bg-white px-3 py-1.5 text-xs font-semibold text-[#a04a4a] hover:bg-[#fff5f5] disabled:opacity-55"
                  onClick={handleDisconnectSessionKey}
                  disabled={syncingKey || browserBusy}
                >
                  {syncingKey ? 'Disconnecting…' : 'Disconnect Claude Session'}
                </button>
              )}
            </div>

            {!browserStatus?.has_session_key && (
              <form onSubmit={handleSyncSessionKey} className="mt-1 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <input
                  id="claudeSessionInputMain"
                  type="password"
                  placeholder="Paste Claude sessionKey (sk-ant-sid01-...)"
                  className="flex-1 rounded-md border border-[#d6d4f0] bg-white px-3 py-2 text-xs font-mono text-[#292d3a] placeholder:text-[#9fa3b5] focus:border-[#6657d9] focus:outline-none"
                  value={sessionKeyInput}
                  onChange={(e) => setSessionKeyInput(e.target.value)}
                  disabled={syncingKey || browserBusy}
                />
                <button
                  type="submit"
                  className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-4 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55"
                  disabled={syncingKey || browserBusy || !sessionKeyInput.trim()}
                >
                  {syncingKey ? 'Syncing…' : 'Connect Claude'}
                </button>
              </form>
            )}

            <div className="rounded-md border border-[#ececf4] bg-white p-3 text-xs text-[#6e7284]">
              <p className="font-semibold text-[#4b4e60]">How to get your session key in 5 seconds:</p>
              <ol className="mt-1.5 list-decimal pl-4 space-y-1">
                <li>Log in to <a href="https://claude.ai" target="_blank" rel="noreferrer" className="text-[#6657d9] underline font-medium">claude.ai</a> on your computer.</li>
                <li>Press <kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">F12</kbd> (or right click → Inspect) → click the <strong>Application</strong> tab (or <strong>Storage</strong> in Firefox).</li>
                <li>On the left panel, click <strong>Cookies</strong> → <strong>https://claude.ai</strong>.</li>
                <li>Find the cookie named <strong>sessionKey</strong>, double-click its value, copy it, and paste it above!</li>
              </ol>
            </div>
          </div>

          {/* Automatic Solving Opt-in */}
          <label className="flex max-w-3xl items-start gap-2 text-xs leading-relaxed text-[#5d6170]">
            <input
              type="checkbox"
              className="mt-0.5 accent-[#6657d9]"
              checked={Boolean(browserStatus?.automatic_solving_enabled)}
              onChange={(event) => setAutomaticSolving(event.target.checked)}
              disabled={browserBusy || (!browserStatus?.has_session_key && !browserStatus?.is_open)}
            />
            <span>
              <strong>Automatically solve eligible assignments:</strong> Solves newly detected, published, unsubmitted assignments via Claude without manual triggers.
              {(!browserStatus?.has_session_key && !browserStatus?.is_open) && (
                <span className="block mt-0.5 text-[#a04a4a]"> (Connect Claude above to enable automatic solving)</span>
              )}
            </span>
          </label>

          {/* Fallback Method: Streamed Browser Window */}
          <details className="rounded-lg border border-[#ebebf0] bg-[#fafafc] p-3 text-xs">
            <summary className="cursor-pointer font-semibold text-[#5c6070] hover:text-[#292d3a]">
              Alternative / Visual Window: Streamed Chromium Browser (VNC)
            </summary>
            <div className="mt-3 flex flex-col gap-3 pt-2 border-t border-[#ededf2]">
              <p className="text-[#747887]">
                If you prefer to sign in visually, you can start an isolated hosted Chromium container.
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55"
                  onClick={startClaudeBrowser}
                  disabled={browserBusy}
                >
                  {browserBusy ? 'Starting…' : browserStatus?.is_open ? 'Open sign-in window' : 'Start hosted browser'}
                </button>
                <button
                  type="button"
                  className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55"
                  onClick={loadBrowserStatus}
                  disabled={browserBusy}
                >
                  Refresh status
                </button>
                {browserStatus?.viewer_url && (
                  <a
                    className="text-xs font-semibold text-[#5142c1] underline"
                    href={browserStatus.viewer_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open streamed browser tab
                  </a>
                )}
                {browserStatus?.profile_exists && (
                  <button
                    type="button"
                    className="text-xs font-semibold text-[#a04a4a] underline disabled:opacity-55"
                    onClick={deleteClaudeProfile}
                    disabled={browserBusy}
                  >
                    Delete saved profile
                  </button>
                )}
              </div>
            </div>
          </details>

          {browserStatus?.automatic_solving_enabled
            && (browserStatus?.jobs || []).some((job) => ['needs_login', 'failed'].includes(job.status)) && (
            <button
              type="button"
              className="self-start text-xs font-semibold text-[#5142c1] underline disabled:opacity-55"
              onClick={resumeClaudeJobs}
              disabled={browserBusy}
            >
              Resume waiting or failed assignments
            </button>
          )}
          {browserStatus?.jobs?.length > 0 && (
            <ul className="flex max-w-3xl flex-col gap-2 border-t border-[#f0f0f3] pt-3">
              {browserStatus.jobs.map((job) => (
                <li key={job.id} className="flex flex-wrap justify-between gap-2 text-xs text-[#747887]">
                  <span>{job.assignment_title || `Assignment ${job.assignment_id}`}</span>
                  <span className="font-medium text-[#5d6170]">
                    {job.status.replaceAll('_', ' ')}{job.error ? ` · ${job.error}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* University Portal Session Key Section */}
      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="border-b border-[#f0f0f3] px-5 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">UNIVERSITY PORTAL CONNECTION</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Air University Session & Fast Attendance Sync</h2>
          </div>
          {portalStatus?.has_session_cookies ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f3fbf7] px-2.5 py-1 text-xs font-semibold text-[#3a8369] border border-[#d8eee4]">
              <span className="h-1.5 w-1.5 rounded-full bg-[#3a8369]" /> Connected (ASP.NET Session)
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#f8f8fb] px-2.5 py-1 text-xs font-medium text-[#747887] border border-[#ebebf0]">
              Not Connected
            </span>
          )}
        </header>

        <div className="flex flex-col gap-5 p-5">
          <div className="rounded-lg border border-[#e8e7f8] bg-[#faf9fe] p-4 flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 className="text-xs font-semibold text-[#483ba6]">⚡ Instant Portal Sync (Session Key / ASP.NET_SessionId)</h3>
                <p className="mt-1 text-xs leading-relaxed text-[#686c80] max-w-2xl">
                  Connect your Air University student portal session. Our server communicates with the portal directly in milliseconds to sync course attendance, schedules, and class updates.
                </p>
              </div>
              {portalStatus?.has_session_cookies && (
                <button
                  type="button"
                  className="rounded-md border border-[#e0c4c4] bg-white px-3 py-1.5 text-xs font-semibold text-[#a04a4a] hover:bg-[#fff5f5] disabled:opacity-55"
                  onClick={handleDisconnectPortalCookie}
                  disabled={syncingPortalCookie || browserBusy}
                >
                  {syncingPortalCookie ? 'Disconnecting…' : 'Disconnect Portal Session'}
                </button>
              )}
            </div>

            <form onSubmit={handleSyncPortalCookie} className="mt-1 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
              <input
                id="portalCookieInputMain"
                type="text"
                placeholder="Paste portal session key (ASP.NET_SessionId or cookie header)"
                className="flex-1 rounded-md border border-[#d6d4f0] bg-white px-3 py-2 text-xs font-mono text-[#292d3a] placeholder:text-[#9fa3b5] focus:border-[#6657d9] focus:outline-none"
                value={portalCookieInput}
                onChange={(e) => setPortalCookieInput(e.target.value)}
                disabled={syncingPortalCookie || browserBusy}
              />
              <button
                type="submit"
                className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-4 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55"
                disabled={syncingPortalCookie || browserBusy || !portalCookieInput.trim()}
              >
                {syncingPortalCookie ? 'Syncing…' : portalStatus?.has_session_cookies ? 'Update Session' : 'Connect & Sync Portal'}
              </button>
            </form>

            <div className="rounded-md border border-[#ececf4] bg-white p-3 text-xs text-[#6e7284]">
              <p className="font-semibold text-[#4b4e60]">How to copy your portal session key in 5 seconds:</p>
              <ol className="mt-1.5 list-decimal pl-4 space-y-1">
                <li>Log in to <a href="https://portals.au.edu.pk/students/" target="_blank" rel="noreferrer" className="text-[#6657d9] underline font-medium">portals.au.edu.pk/students/</a> in your browser.</li>
                <li>Press <kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">F12</kbd> (Inspect) → click <strong>Application</strong> (or <strong>Storage</strong> in Firefox).</li>
                <li>On the left panel, click <strong>Cookies</strong> → <strong>https://portals.au.edu.pk</strong>.</li>
                <li>Copy the value of <strong>ASP.NET_SessionId</strong> and paste it above!</li>
              </ol>
            </div>
          </div>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">EMAIL NOTIFICATIONS</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Alert Email Address</h2>
          </div>
        </header>
        <div className="p-5">
          <p className="mb-4 rounded-lg bg-[#f6f5ff] px-3 py-2.5 text-xs leading-relaxed text-[#77729b]">
            Enter an email address to receive alerts for assignment deadlines, grade updates, 
            class changes, and other important notifications from Uniflow.
          </p>

          <form onSubmit={handleSave} className="flex max-w-[480px] flex-col gap-4">
            <div>
              <label htmlFor="notificationEmail" className="mb-1 block text-xs font-medium text-[#696d7d]">
                Notification Email
              </label>
              <input
                type="email"
                id="notificationEmail"
                className="w-full rounded-md border border-[#e4e4eb] bg-white px-3 py-2 text-xs text-[#343746] outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:opacity-50"
                value={notificationEmail}
                onChange={(e) => setNotificationEmail(e.target.value)}
                placeholder="your-email@university.edu.pk"
                disabled={saving || loading}
                autoComplete="email"
                required
              />
              <small className="mt-1 block text-xs text-[#9295a2]">
                This email will be used for all Uniflow alerts. Your Clerk account email: <strong>{userEmail}</strong>
              </small>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="submit"
                className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:cursor-not-allowed disabled:opacity-55"
                disabled={saving || loading}
              >
                {saving ? 'Saving…' : 'Save Email'}
              </button>

              {notificationEmail && (
                <button
                  type="button"
                  className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55"
                  onClick={handleTestEmail}
                  disabled={saving || loading}
                >
                  {saving ? 'Sending…' : 'Send Test Email'}
                </button>
              )}

              {notificationEmail && (
                <button
                  type="button"
                  className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#f0dada] bg-white px-3 text-xs font-semibold text-[#b34d4d] hover:bg-[#fff4f4] disabled:opacity-55"
                  onClick={handleDelete}
                  disabled={saving || loading}
                >
                  {saving ? 'Removing…' : 'Remove Email'}
                </button>
              )}
            </div>
          </form>

          {notificationEmail && (
            <div className="mt-6 flex items-center gap-3 rounded-lg border border-green-200 bg-green-50 p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-green-100 text-green-700"><Icon name="checkCircle" size={19} /></span>
              <div className="flex min-w-0 flex-col gap-1 text-xs">
                <span className="text-neutral-600">Current notification email</span>
                <strong className="break-all text-sm text-neutral-900">{notificationEmail}</strong>
                <small className="text-neutral-500">You will receive alerts at this address</small>
              </div>
            </div>
          )}

          {!notificationEmail && (
            <div className="mt-6 flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-red-100 text-red-700"><Icon name="alert" size={19} /></span>
              <div className="flex min-w-0 flex-col gap-1 text-xs">
                <span className="text-neutral-600">No notification email configured</span>
                <strong className="text-sm text-neutral-900">You won&apos;t receive email alerts</strong>
                <small className="text-neutral-500">Add an email above to enable notifications</small>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">ACCOUNT & INTEGRATIONS</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Connected Services & Disconnect Controls</h2>
          </div>
        </header>
        <div className="p-5">
          <p className="mb-4 text-xs text-[#858998]">
            Connect or disconnect your academic integrations and AI solvers. You have full control to connect or disconnect any service at any time.
          </p>
          <div className="flex flex-col divide-y divide-[#f1f1f4]">
            {/* 1. Google Classroom (GCR) */}
            <article className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-3.5 first:pt-0">
              <div className="flex items-start sm:items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]">
                  <Icon name="school" size={18} />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <strong className="text-xs font-semibold text-[#414553]">Google Classroom (GCR)</strong>
                    {googleConnected ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#eaf7f1] px-2 py-0.5 text-[11px] font-semibold text-[#438a71]">
                        <span className="size-1.5 rounded-full bg-[#438a71]" /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#f8f8fb] px-2 py-0.5 text-[11px] font-medium text-[#747887] border border-[#ebebf0]">
                        <span className="size-1.5 rounded-full bg-[#9fa3b5]" /> Disconnected
                      </span>
                    )}
                  </div>
                  <small className="text-xs text-[#9295a2]">
                    {googleConnected
                      ? (googleEmail ? `${googleEmail} · Syncs courses, slides, announcements & turn-in` : 'Connected · Syncs courses, slides, announcements & turn-in')
                      : 'Connect your student Google account to sync courses, slides, announcements, and submit work.'}
                  </small>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 self-end sm:self-center pl-12 sm:pl-0">
                {googleConnected ? (
                  <>
                    <button
                      type="button"
                      onClick={handleConnectGoogle}
                      disabled={googleBusy}
                      className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55"
                      title="Re-authorize Google Classroom or refresh permissions"
                    >
                      {googleBusy ? 'Working…' : 'Reconnect'}
                    </button>
                    <button
                      type="button"
                      onClick={handleDisconnectGoogle}
                      disabled={googleBusy}
                      className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#f0dada] bg-white px-3 text-xs font-semibold text-[#b34d4d] hover:bg-[#fff4f4] disabled:opacity-55"
                      title="Disconnect Google Classroom"
                    >
                      {googleBusy ? 'Disconnecting…' : 'Disconnect GCR'}
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={handleConnectGoogle}
                    disabled={googleBusy}
                    className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3.5 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55"
                  >
                    {googleBusy ? 'Connecting…' : 'Connect Google Classroom'}
                  </button>
                )}
              </div>
            </article>

            {/* Companion Extension Quick Status Notice */}
            <div className="py-2.5">
              {gcrBrowserStatus?.has_synced_session ? (
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg bg-emerald-50/70 border border-emerald-200 px-3 py-2 text-xs text-emerald-800">
                  <div className="flex items-center gap-2">
                    <span className="size-2 rounded-full bg-emerald-600 animate-pulse" />
                    <span><strong>Active Companion Session:</strong> Google Classroom autonomous turn-in is ready.</span>
                  </div>
                  <a href="#companion-extension" className="font-semibold text-emerald-900 underline hover:text-emerald-950 text-[11px] self-start sm:self-auto">
                    Manage Extension & Sessions ↓
                  </a>
                </div>
              ) : (
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-lg bg-violet-light/30 border border-violet/20 px-3 py-2 text-xs text-violet-dark">
                  <div className="flex items-center gap-2">
                    <span className="grid size-5 place-items-center rounded bg-violet text-white text-[10px] font-bold">U</span>
                    <span><strong>Companion Extension Available:</strong> 1-click sync your Classroom & university logins without password prompts.</span>
                  </div>
                  <div className="flex items-center gap-2 self-start sm:self-auto">
                    <a
                      href="/uniflow-companion.zip"
                      download="uniflow-companion.zip"
                      className="font-semibold underline hover:text-violet-dark text-[11px]"
                    >
                      📥 Download (.zip)
                    </a>
                    <span className="text-violet/40">·</span>
                    <a href="#companion-extension" className="font-semibold underline hover:text-violet-dark text-[11px]">
                      Setup Controls ↓
                    </a>
                  </div>
                </div>
              )}
            </div>

            {/* Extension Help Modal */}
            {showExtensionHelp && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
                <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl border border-line">
                  <div className="flex items-center justify-between border-b border-line pb-3">
                    <div className="flex items-center gap-2">
                      <span className="grid size-7 place-items-center rounded-lg bg-violet-light text-violet font-bold text-xs">U</span>
                      <h3 className="text-sm font-semibold text-ink">Load Uniflow Companion Extension</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowExtensionHelp(false)}
                      className="text-muted hover:text-ink text-sm font-bold"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="mt-3 space-y-3 text-xs text-muted leading-relaxed">
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900 text-xs">
                      <strong className="block font-semibold mb-1">Why is the Extension needed?</strong>
                      <p className="text-[11px] leading-relaxed">
                        Google blocks Google Account logins on in-app / automated browsers with <em>&quot;This browser or app may not be secure&quot;</em> or continuous captchas.
                        Since you are <strong>already logged in</strong> to Google Classroom in your normal Chrome browser, the Uniflow Companion securely copies your active session with zero password prompts!
                      </p>
                    </div>

                    <div className="rounded-lg border border-violet/20 bg-violet-light/30 p-3">
                      <strong className="text-violet-dark block font-semibold text-xs mb-1">Fast 2-Step Setup (100% Free)</strong>
                      <p className="text-[11px] text-muted mb-2.5">Download the companion extension package and load it once into your Chrome browser:</p>
                      <a
                        href="/uniflow-companion.zip"
                        download="uniflow-companion.zip"
                        className="inline-flex items-center gap-1.5 rounded-lg bg-violet px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-violet-dark transition"
                      >
                        <Icon name="download" size={13} />
                        <span>📥 Download Extension (.zip)</span>
                      </a>
                    </div>

                    <div className="rounded-lg border border-line bg-paper p-3">
                      <strong className="text-ink block font-semibold text-xs mb-1">How to load in Chrome (15 seconds):</strong>
                      <ol className="list-decimal pl-4 space-y-1 text-[11px] text-muted">
                        <li>Unzip the downloaded <code className="rounded bg-white px-1 py-0.5 text-ink font-mono border border-line">uniflow-companion.zip</code> file.</li>
                        <li>In Chrome, go to <code className="rounded bg-white px-1 py-0.5 text-ink font-mono border border-line">chrome://extensions</code></li>
                        <li>Enable <strong>Developer mode</strong> (toggle in top-right corner).</li>
                        <li>Click <strong>Load unpacked</strong> and select the unzipped folder.</li>
                      </ol>
                    </div>

                    <p className="rounded-lg bg-emerald-50 border border-emerald-200 p-2 text-emerald-800 text-[11px]">
                      ✨ <strong>Instant detection:</strong> Once loaded, Uniflow detects it immediately. Click <strong>⚡ 1-Click Allow & Sync Selected</strong> to sync all your university sessions!
                    </p>
                  </div>
                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      onClick={() => setShowExtensionHelp(false)}
                      className="rounded-lg border border-line bg-white px-4 py-1.5 text-xs font-semibold text-ink hover:bg-paper"
                    >
                      Close
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 2. University Portal (Air University) */}
            <article className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-3.5">
              <div className="flex items-start sm:items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]">
                  <Icon name="globe" size={18} />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <strong className="text-xs font-semibold text-[#414553]">University Student Portal</strong>
                    {portalStatus?.has_session_cookies || portalStatus?.session_status === 'ACTIVE' ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#eaf7f1] px-2 py-0.5 text-[11px] font-semibold text-[#438a71]">
                        <span className="size-1.5 rounded-full bg-[#438a71]" /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#f8f8fb] px-2 py-0.5 text-[11px] font-medium text-[#747887] border border-[#ebebf0]">
                        <span className="size-1.5 rounded-full bg-[#9fa3b5]" /> Disconnected
                      </span>
                    )}
                  </div>
                  <small className="text-xs text-[#9295a2]">
                    {portalStatus?.has_session_cookies || portalStatus?.session_status === 'ACTIVE'
                      ? 'ASP.NET session active · Live timetable, attendance records, and section schedules synced'
                      : 'Sync your timetable, class schedule, and real-time attendance stats via session cookies.'}
                  </small>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 self-end sm:self-center pl-12 sm:pl-0">
                {portalStatus?.has_session_cookies || portalStatus?.session_status === 'ACTIVE' ? (
                  <button
                    type="button"
                    onClick={handleDisconnectPortalCookie}
                    disabled={syncingPortalCookie}
                    className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#f0dada] bg-white px-3 text-xs font-semibold text-[#b34d4d] hover:bg-[#fff4f4] disabled:opacity-55"
                  >
                    {syncingPortalCookie ? 'Disconnecting…' : 'Disconnect Portal'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      const portalInput = document.getElementById('portalCookieInputMain');
                      if (portalInput) {
                        portalInput.scrollIntoView({ behavior: 'smooth' });
                        portalInput.focus();
                      }
                    }}
                    className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3.5 text-xs font-semibold text-white hover:bg-[#5142c1]"
                  >
                    Connect Portal
                  </button>
                )}
              </div>
            </article>

            {/* 3. Claude AI Assistant */}
            <article className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-3.5">
              <div className="flex items-start sm:items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]">
                  <Icon name="brain" size={18} />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <strong className="text-xs font-semibold text-[#414553]">Claude AI Solver (claude.ai)</strong>
                    {browserStatus?.has_session_key ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#eaf7f1] px-2 py-0.5 text-[11px] font-semibold text-[#438a71]">
                        <span className="size-1.5 rounded-full bg-[#438a71]" /> Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#f8f8fb] px-2 py-0.5 text-[11px] font-medium text-[#747887] border border-[#ebebf0]">
                        <span className="size-1.5 rounded-full bg-[#9fa3b5]" /> Disconnected
                      </span>
                    )}
                  </div>
                  <small className="text-xs text-[#9295a2]">
                    {browserStatus?.has_session_key
                      ? 'SessionKey cookie active · 1-click automatic solving & terminal output generation enabled'
                      : 'Connect your sessionKey to solve assignments, labs, and generate academic code.'}
                  </small>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 self-end sm:self-center pl-12 sm:pl-0">
                {browserStatus?.has_session_key ? (
                  <button
                    type="button"
                    onClick={handleDisconnectSessionKey}
                    disabled={syncingKey || browserBusy}
                    className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#f0dada] bg-white px-3 text-xs font-semibold text-[#b34d4d] hover:bg-[#fff4f4] disabled:opacity-55"
                  >
                    {syncingKey ? 'Disconnecting…' : 'Disconnect Claude'}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      const claudeInput = document.getElementById('claudeSessionInputMain');
                      if (claudeInput) {
                        claudeInput.scrollIntoView({ behavior: 'smooth' });
                        claudeInput.focus();
                      }
                    }}
                    className="inline-flex min-h-8 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3.5 text-xs font-semibold text-white hover:bg-[#5142c1]"
                  >
                    Connect Claude
                  </button>
                )}
              </div>
            </article>

            {/* 4. Clerk Account */}
            <article className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-3.5 last:pb-0">
              <div className="flex items-start sm:items-center gap-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]">
                  <Icon name="user" size={18} />
                </span>
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <strong className="text-xs font-semibold text-[#414553]">Clerk Security Account</strong>
                    <span className="inline-flex items-center gap-1 rounded-full bg-[#eaf7f1] px-2 py-0.5 text-[11px] font-semibold text-[#438a71]">
                      <span className="size-1.5 rounded-full bg-[#438a71]" /> Active
                    </span>
                  </div>
                  <small className="text-xs text-[#9295a2]">{userEmail} · Primary Single Sign-On</small>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>

      {/* ─────────────────────────────────────────────────────────────
          DEDICATED SECTION: UNIFLOW ACADEMIC COMPANION EXTENSION
          Separate, dedicated card to download and configure extension anytime
      ───────────────────────────────────────────────────────────── */}
      <section id="companion-extension" className="min-w-0 rounded-xl border border-violet/30 bg-white shadow-sm overflow-hidden">
        <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#ecebf8] bg-gradient-to-r from-[#faf9fe] to-white px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-violet text-white font-bold text-sm shadow-xs">
              U
            </span>
            <div>
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold uppercase tracking-[.12em] text-violet">CHROME COMPANION</p>
                <span className="rounded-full bg-violet-light px-2 py-0.5 text-[10px] font-bold text-violet">v{EXTENSION_VERSION}</span>
              </div>
              <h2 className="text-[14px] font-semibold text-[#343746]">Uniflow Academic Companion Extension</h2>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 shrink-0">
            <a
              href="/uniflow-companion.zip"
              download="uniflow-companion.zip"
              className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-violet px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-violet-dark transition"
              title="Download uniflow-companion.zip package anytime"
            >
              <Icon name="download" size={14} />
              <span>📥 Download Extension (.zip)</span>
            </a>
            {extensionDetected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-800 border border-emerald-200">
                <span className="size-2 rounded-full bg-emerald-600 animate-pulse" /> Active in Chrome
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setShowExtensionHelp(true)}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink hover:bg-paper"
              >
                <Icon name="help" size={13} />
                <span>Setup Guide</span>
              </button>
            )}
          </div>
        </header>

        <div className="p-5 flex flex-col gap-4">
          {/* Informational Callout & Direct Download */}
          <div className="rounded-xl border border-violet/15 bg-violet-light/25 p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="space-y-1">
              <strong className="text-xs font-semibold text-ink flex items-center gap-1.5">
                <span>⚡ 1-Click Session Extraction & Autonomous Turn-In</span>
              </strong>
              <p className="text-[11px] text-muted leading-relaxed max-w-2xl">
                Google blocks automated cloud browsers from logging in directly with <em>&quot;This browser or app may not be secure&quot;</em>. 
                The Companion Extension securely captures your active university logins from your Chrome profile so Uniflow can submit assignments and solve labs with zero captchas.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              <a
                href="/uniflow-companion.zip"
                download="uniflow-companion.zip"
                className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-violet/30 bg-white px-3 py-1 text-xs font-semibold text-violet hover:bg-violet-light/50 transition"
              >
                <Icon name="download" size={13} />
                <span>Download .zip</span>
              </a>
              <button
                type="button"
                onClick={() => setShowExtensionHelp(true)}
                className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1 text-xs font-semibold text-ink hover:bg-paper"
              >
                <Icon name="help" size={12} />
                <span>Installation Steps</span>
              </button>
            </div>
          </div>

          {/* Quick Setup Instructions (3 Steps) */}
          <div className="rounded-xl border border-line bg-paper/60 p-3.5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-ink">How to Load / Update in Chrome (15 Seconds):</span>
              <span className="text-[10px] text-muted font-mono">Folder: extension/</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 text-[11px] text-muted">
              <div className="rounded-lg bg-white border border-line p-2.5">
                <span className="font-bold text-violet mr-1">1.</span>
                Download & unzip <code className="font-mono bg-paper px-1 py-0.5 rounded text-ink border border-line">uniflow-companion.zip</code> (or use local <code className="font-mono text-ink">extension/</code> folder).
              </div>
              <div className="rounded-lg bg-white border border-line p-2.5">
                <span className="font-bold text-violet mr-1">2.</span>
                Open <code className="font-mono bg-paper px-1 py-0.5 rounded text-ink border border-line">chrome://extensions</code> and toggle <strong>Developer mode</strong> (top-right).
              </div>
              <div className="rounded-lg bg-white border border-line p-2.5">
                <span className="font-bold text-violet mr-1">3.</span>
                Click <strong>Load unpacked</strong> and pick the folder (or click 🔄 Reload if already installed).
              </div>
            </div>
          </div>

          {/* Service Selection Checkboxes */}
          <div>
            <span className="text-xs font-semibold text-ink block mb-2">Select Services to Synchronize:</span>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              {/* 1. GCR */}
              <label className="flex items-start gap-2.5 rounded-lg border border-line bg-white p-3 cursor-pointer hover:border-violet/40 transition">
                <input
                  type="checkbox"
                  checked={syncOptionGcr}
                  onChange={(e) => setSyncOptionGcr(e.target.checked)}
                  className="mt-0.5 accent-violet cursor-pointer"
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <strong className="text-xs font-semibold text-ink">Classroom</strong>
                    {gcrBrowserStatus?.has_synced_session ? (
                      <span className="text-[10px] text-emerald-700 font-bold">✓ Synced</span>
                    ) : (
                      <span className="text-[10px] text-amber-700 font-semibold">Needs Sync</span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted block mt-0.5">Autonomous turn-in cookies</span>
                </div>
              </label>

              {/* 2. Claude */}
              <label className="flex items-start gap-2.5 rounded-lg border border-line bg-white p-3 cursor-pointer hover:border-violet/40 transition">
                <input
                  type="checkbox"
                  checked={syncOptionClaude}
                  onChange={(e) => setSyncOptionClaude(e.target.checked)}
                  className="mt-0.5 accent-violet cursor-pointer"
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <strong className="text-xs font-semibold text-ink">Claude.ai</strong>
                    {browserStatus?.has_session_key ? (
                      <span className="text-[10px] text-emerald-700 font-bold">✓ Active</span>
                    ) : (
                      <span className="text-[10px] text-amber-700 font-semibold">Needs Key</span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted block mt-0.5">
                    {browserStatus?.has_session_key ? 'Kept connected (skipped)' : '1-click solver key'}
                  </span>
                </div>
              </label>

              {/* 3. Portal */}
              <label className="flex items-start gap-2.5 rounded-lg border border-line bg-white p-3 cursor-pointer hover:border-violet/40 transition">
                <input
                  type="checkbox"
                  checked={syncOptionPortal}
                  onChange={(e) => setSyncOptionPortal(e.target.checked)}
                  className="mt-0.5 accent-violet cursor-pointer"
                />
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <strong className="text-xs font-semibold text-ink">Uni Portal</strong>
                    {portalStatus?.has_session_cookies || portalStatus?.session_status === 'ACTIVE' ? (
                      <span className="text-[10px] text-emerald-700 font-bold">✓ Active</span>
                    ) : (
                      <span className="text-[10px] text-amber-700 font-semibold">Needs Sync</span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted block mt-0.5">
                    {portalStatus?.has_session_cookies ? 'Kept connected (skipped)' : 'Timetable & attendance'}
                  </span>
                </div>
              </label>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#ecebf8]">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => handleExtensionSyncSelected(false)}
                disabled={extensionSyncBusy || !extensionDetected}
                className="inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg bg-violet px-3 py-1.5 text-xs font-semibold text-white shadow-xs hover:bg-violet-dark disabled:opacity-50"
              >
                <Icon name="upload" size={13} />
                <span>{extensionSyncBusy ? 'Syncing…' : '⚡ 1-Click Allow & Sync Selected'}</span>
              </button>
              <button
                type="button"
                onClick={() => handleExtensionSyncSelected(true)}
                disabled={extensionSyncBusy || !extensionDetected}
                className="inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink hover:bg-paper disabled:opacity-50"
                title="Visits necessary URLs and captures missing sessions"
              >
                <Icon name="externalLink" size={13} />
                <span>{extensionSyncBusy ? 'Auto-Visiting…' : '🚀 Auto-Visit & Extract'}</span>
              </button>
              <button
                type="button"
                onClick={handleCopyAuthToken}
                className="inline-flex min-h-8 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink hover:bg-paper"
                title="Copy a fresh, active Clerk session token to paste into the Companion Extension popup"
              >
                <Icon name="copy" size={13} />
                <span>{tokenCopied ? '✓ Copied Token!' : '📋 Copy Fresh Token'}</span>
              </button>
            </div>

            {gcrBrowserStatus?.has_synced_session && (
              <button
                type="button"
                onClick={handleDisconnectGcrSession}
                disabled={gcrBusy}
                className="rounded-md border border-[#e0c4c4] bg-white px-2.5 py-1 text-xs font-semibold text-[#a04a4a] hover:bg-[#fff5f5] disabled:opacity-55"
              >
                {gcrBusy ? 'Disconnecting…' : 'Disconnect GCR Session'}
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">NOTIFICATION TYPES</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">What you&apos;ll be notified about</h2>
          </div>
        </header>
        <div className="p-5">
          <ul className="m-0 flex list-none flex-col gap-3 p-0">
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Assignment due date reminders</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>New assignment posted notifications</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Grade updates and feedback</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Class schedule changes (cancellations, room changes)</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>Exam and quiz announcements</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>University portal grade sync results</span>
            </li>
            <li className="flex items-center gap-3 rounded-lg bg-neutral-50 p-3">
              <Icon name="checkCircle" size={18} className="text-green-600" />
              <span>AI solution generation completion</span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}