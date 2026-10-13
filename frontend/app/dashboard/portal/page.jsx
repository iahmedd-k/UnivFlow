'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const AIR_UNIVERSITY_PORTAL = 'https://portals.au.edu.pk/students/';

function timeLabel(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Never' : date.toLocaleString();
}

export default function PortalPage() {
  const { getToken } = useAuth();
  const [settings, setSettings] = useState(null);
  const [portalUrl, setPortalUrl] = useState(AIR_UNIVERSITY_PORTAL);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [signInOpen, setSignInOpen] = useState(false);
  const [jobId, setJobId] = useState('');
  const [syncState, setSyncState] = useState(null);
  const autoSyncStarted = useRef(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const connected = settings?.session_status === 'ACTIVE';
  const reconnect = settings?.session_status === 'REAUTH_REQUIRED';
  const isSyncing = Boolean(jobId) || ['queued', 'running'].includes(syncState?.status);
  const report = settings?.report || syncState?.summary || {};

  const loadSettings = useCallback(async () => {
    const token = await getToken();
    const result = await api.getPortalSettings(token);
    setSettings(result);
    setPortalUrl(result?.url || AIR_UNIVERSITY_PORTAL);
    return result;
  }, [getToken]);

  useEffect(() => {
    let cancelled = false;
    const loadInitialSettings = async () => {
      try {
        const token = await getToken();
        const result = await api.getPortalSettings(token);
        if (!cancelled) {
          setSettings(result);
          setPortalUrl(result?.url || AIR_UNIVERSITY_PORTAL);
          setSignInOpen(Boolean(result?.browser_open && result?.session_status !== 'ACTIVE'));
        }
      } catch (err) {
        if (!cancelled) setError(err.message || 'Could not load portal settings.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    loadInitialSettings();
    return () => {
      cancelled = true;
    };
  }, [getToken]);

  useEffect(() => {
    if (!jobId) return undefined;
    let cancelled = false;
    let timer;
    let consecutiveErrors = 0;
    const poll = async () => {
      try {
        const token = await getToken();
        const result = await api.getPortalSyncStatus(jobId, token);
        if (cancelled) return;
        consecutiveErrors = 0;
        setSyncState(result);
        if (['success', 'partial', 'error', 'reconnect_required', 'session_expired', 'already_running'].includes(result.status)) {
          setJobId('');
          setBusy(false);
          if (result.status === 'success' || result.status === 'partial') {
            setNotice(result.message || 'Your portal data is up to date.');
            setSignInOpen(false);
            await loadSettings();
          } else if (result.status === 'already_running') {
            setNotice(result.message || 'A portal sync is already running.');
          } else {
            setError(result.error || result.detail || 'Portal sync could not complete.');
            if (['reconnect_required', 'session_expired'].includes(result.status)) {
              autoSyncStarted.current = false;
              await loadSettings();
            }
          }
          return;
        }
        timer = setTimeout(poll, 1200);
      } catch (err) {
        if (!cancelled) {
          consecutiveErrors += 1;
          if (consecutiveErrors < 4) {
            timer = setTimeout(poll, 1500);
            return;
          }
          setError(err.message || 'Could not check sync progress.');
          setBusy(false);
          setJobId('');
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [jobId, getToken, loadSettings]);

  const connect = async () => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const token = await getToken();
      await api.savePortalUrl(portalUrl, token, { auth_method: 'google' });
      const result = await api.openPortalBrowser(token);
      autoSyncStarted.current = false;
      setSignInOpen(true);
      setNotice(result.message || 'Sign in to the university portal in the window that opened.');
      await loadSettings();
    } catch (err) {
      setError(err.message || 'Could not open the university sign-in window.');
    } finally {
      setBusy(false);
    }
  };

  const startSync = useCallback(async () => {
    setBusy(true);
    setError('');
    setNotice('');
    setSyncState({ status: 'queued' });
    try {
      const token = await getToken();
      const result = await api.queuePortalSync(token);
      setJobId(result.job_id);
      setBusy(true);
    } catch (err) {
      setBusy(false);
      setSyncState(null);
      setError(err.message || 'Could not start portal sync.');
    }
  }, [getToken]);

  useEffect(() => {
    if (!signInOpen || connected || jobId || autoSyncStarted.current) return undefined;
    let cancelled = false;
    let timer;
    let consecutiveAuthenticatedChecks = 0;
    const check = async () => {
      try {
        const token = await getToken();
        const result = await api.getPortalConnectionStatus(token);
        if (cancelled) return;
        if (result.status === 'authenticated') {
          if (result.job_id) {
            autoSyncStarted.current = true;
            setJobId(result.job_id);
            setNotice('Sign-in verified! Automatically syncing your university portal records…');
            setSignInOpen(false);
            return;
          }
          consecutiveAuthenticatedChecks += 1;
          if (consecutiveAuthenticatedChecks >= 1) {
            autoSyncStarted.current = true;
            setNotice('Sign-in confirmed. Automatically starting your portal sync…');
            await startSync();
            return;
          }
        } else {
          consecutiveAuthenticatedChecks = 0;
        }
      } catch (err) {
        consecutiveAuthenticatedChecks = 0;
        // Keep checking through temporary gateway/network issues, but don't hide
        // authorization or server errors behind an endless "waiting" state.
        if ([401, 403].includes(err?.status) || (err?.status >= 500 && ![502, 503, 504].includes(err.status))) {
          if (!cancelled) {
            setError(err.message || 'Could not verify the university sign-in.');
            setSignInOpen(false);
          }
          return;
        }
      }
      if (!cancelled) timer = setTimeout(check, 1800);
    };
    timer = setTimeout(check, 1500);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [signInOpen, connected, jobId, getToken, startSync]);

  const closeBrowser = async () => {
    setBusy(true);
    try {
      const token = await getToken();
      await api.closePortalBrowser(token);
      setSignInOpen(false);
      autoSyncStarted.current = false;
      await loadSettings();
    } catch (err) {
      setError(err.message || 'Could not close the sign-in window.');
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="mx-auto flex min-h-72 max-w-6xl items-center justify-center text-sm text-slate-500">Loading university connection…</div>;
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 pb-12">
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-indigo-700">Academic integrations</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-slate-950">University portal</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">Connect once to sync your attendance, class schedule, and academic results automatically.</p>
        </div>
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 shadow-sm">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-500' : reconnect ? 'bg-amber-500' : 'bg-slate-400'}`} />
          {connected ? 'Connected' : reconnect ? 'Reconnect needed' : settings?.browser_open ? 'Sign-in in progress' : 'Not connected'}
        </div>
      </header>

      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>}
      {notice && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">{notice}</div>}

      <section className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-7">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-lg text-indigo-700" aria-hidden="true">U</div>
            <div>
              <h2 className="text-lg font-semibold text-slate-950">{connected ? 'Your portal is connected' : reconnect ? 'Sign in to restore automatic sync' : 'Connect your student account'}</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">{connected ? 'Uniflow reuses your saved university session. You do not need to open or capture each report page.' : 'We will open the university sign-in in a separate browser profile. After you sign in, Uniflow finds the academic pages for you.'}</p>
            </div>
          </div>

          {!connected && (
            <div className="mt-6 space-y-3">
              <label htmlFor="portal-url" className="block text-sm font-medium text-slate-800">University portal address</label>
              <input id="portal-url" type="url" value={portalUrl} onChange={(event) => setPortalUrl(event.target.value)} className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 text-sm text-slate-900 outline-none transition focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100" placeholder="https://portals.au.edu.pk/students/" />
              <div className="flex flex-wrap gap-2.5">
                <button type="button" disabled={busy || !portalUrl} onClick={connect} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-800 disabled:cursor-not-allowed disabled:opacity-55 sm:w-auto">
                  {busy && !isSyncing ? 'Opening secure sign-in…' : reconnect ? 'Reconnect university account' : settings?.browser_open ? 'Return to sign-in window' : 'Connect university account'}
                </button>
                <a
                  href={portalUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 sm:w-auto text-decoration-none"
                >
                  Open in this browser tab <Icon name="externalLink" size={14} />
                </a>
              </div>
              <p className="text-xs text-slate-500">
                Tip: Run <code className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-800 font-mono">launch_chrome_unified.bat</code> to open the persistent Uniflow browser used by Claude and your university portal. Sign in there the first time; your normal Chrome profile stays untouched.
              </p>
            </div>
          )}

          {(settings?.browser_open || signInOpen) && !connected && (
            <div className="mt-6 rounded-xl border border-indigo-100 bg-indigo-50/70 p-4">
              <p className="text-sm font-semibold text-indigo-950">1. Sign in to your university account</p>
              <p className="mt-1 text-sm leading-5 text-indigo-900">Complete Google sign-in and any university security check in the browser window. Keep this page open; Uniflow will wait for sign-in to settle, then start syncing automatically.</p>
              <button type="button" disabled={busy} onClick={startSync} className="mt-4 inline-flex items-center justify-center rounded-lg border border-indigo-200 bg-white px-4 py-2.5 text-sm font-semibold text-indigo-800 hover:bg-indigo-50 disabled:opacity-50">
                {isSyncing ? 'Finding your academic pages…' : 'Start sync now'}
              </button>
              {settings?.browser_open && <button type="button" disabled={busy} onClick={closeBrowser} className="ml-3 mt-4 rounded-lg px-3 py-2.5 text-sm font-medium text-slate-600 hover:bg-white">Close sign-in window</button>}
            </div>
          )}

          {connected && (
            <div className="mt-6 flex flex-wrap gap-3">
              <button type="button" disabled={busy} onClick={startSync} className="rounded-xl bg-indigo-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-indigo-800 disabled:opacity-50">{isSyncing ? 'Syncing your portal…' : 'Sync now'}</button>
              <span className="self-center text-sm text-slate-500">Last synced {timeLabel(settings?.last_synced_at)}</span>
            </div>
          )}
        </div>

        <aside className="rounded-2xl border border-slate-200 bg-slate-50 p-6">
          <h2 className="text-sm font-semibold text-slate-950">What syncs automatically</h2>
          <ul className="mt-4 space-y-3 text-sm text-slate-700">
            {['Attendance by course', 'Class timetable and schedule', 'Grades and academic summary'].map((item) => (
              <li key={item} className="flex items-center gap-3"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"><Icon name="check" size={12}/></span>{item}</li>
            ))}
          </ul>
          <div className="mt-5 border-t border-slate-200 pt-4 text-xs leading-5 text-slate-500">
            Sign in is normally needed once. If the university expires the session or asks for verification again, reconnect to resume syncing. Your browser session is kept separate from other accounts.
          </div>
        </aside>
      </section>

      <section aria-label="Academic overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Cumulative GPA', report.cgpa == null ? '—' : Number(report.cgpa).toFixed(2)],
          ['Semester GPA', report.sgpa == null ? '—' : Number(report.sgpa).toFixed(2)],
          ['Credits earned', report.earned_credits == null ? '—' : `${report.earned_credits}`],
          ['Last updated', settings?.last_synced_at ? new Date(settings.last_synced_at).toLocaleDateString() : '—'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">{value}</p>
          </div>
        ))}
      </section>

      {syncState?.pages_synced?.length > 0 && (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-950">Pages found</h2>
          <div className="mt-4 divide-y divide-slate-100">
            {syncState.pages_synced.map((page) => <div key={page.url} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span className="font-medium text-slate-800">{page.title || page.url}</span><span className="text-slate-500">{page.tables} data tables</span></div>)}
          </div>
        </section>
      )}
    </main>
  );
}
