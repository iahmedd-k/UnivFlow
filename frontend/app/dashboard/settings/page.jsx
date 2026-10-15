'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

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
    loadEmail();
  }, [loadEmail]);

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
    loadBrowserStatus();
  }, [loadBrowserStatus]);

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
      {browserNotice && <div className="rounded-lg border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2.5 text-xs text-[#43816b]" role="status">{browserNotice}</div>}

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
                  Sync your Claude session directly. Eliminates Google OAuth "Insecure browser" blocks, avoids Cloudflare captchas, and requires zero remote browser streaming.
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
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">ACCOUNT</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Connected Services</h2>
          </div>
        </header>
        <div className="p-5">
          <div className="flex flex-col">
            <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] py-3 last:border-b-0">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="user" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">Clerk Account</strong>
                <small className="text-xs text-[#9295a2]">Primary authentication via Clerk</small>
              </span>
              <span className="inline-flex rounded-full bg-[#eaf7f1] px-2 py-1 text-xs font-semibold text-[#438a71]">Connected</span>
            </article>
            <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] py-3 last:border-b-0">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="mail" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">Google Classroom</strong>
                <small className="text-xs text-[#9295a2]">Sync courses, assignments, and grades</small>
              </span>
              <span className="inline-flex rounded-full bg-[#eaf7f1] px-2 py-1 text-xs font-semibold text-[#438a71]">Connected</span>
            </article>
            <article className="flex min-h-[60px] items-center gap-3 py-3">
              <span className="grid h-[30px] w-[30px] place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="globe" size={18} /></span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <strong className="text-xs font-semibold text-[#414553]">University Portal</strong>
                <small className="text-xs text-[#9295a2]">Access grades, schedules, and announcements</small>
              </span>
              <span className="inline-flex rounded-full bg-[#fff4e4] px-2 py-1 text-xs font-semibold text-[#a87936]">Configure in Portal</span>
            </article>
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