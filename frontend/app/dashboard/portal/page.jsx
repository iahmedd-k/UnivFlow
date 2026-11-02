'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';
import { ExtensionSetupBox } from '@/app/dashboard/CompanionExtensionModal';

const AIR_UNIVERSITY_PORTAL = 'https://portals.au.edu.pk/students/';

function timeLabel(value) {
  if (!value) return 'Never';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Never' : date.toLocaleString();
}

export default function PortalPage() {
  const { getToken, userId } = useAuth();
  const queryClient = useQueryClient();
  const ownerKey = getQueryOwnerKey(userId);
  const portalSettingsKey = ['portal', ownerKey, 'settings'];
  const settingsQuery = useQuery({
    queryKey: portalSettingsKey,
    queryFn: async ({ signal }) => api.getPortalSettings(await api.getRequestToken(getToken), { signal, direct: true }),
    staleTime: 30_000,
  });
  const { refetch: refetchSettings } = settingsQuery;
  const settings = settingsQuery.data;
  const loading = settingsQuery.isPending;
  const [signInOpen, setSignInOpen] = useState(false);
  const [jobId, setJobId] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [portalUrlDraft, setPortalUrlDraft] = useState(null);
  const portalUrl = portalUrlDraft ?? settings?.url ?? AIR_UNIVERSITY_PORTAL;

  const connected = settings?.session_status === 'ACTIVE';
  const reconnect = settings?.session_status === 'REAUTH_REQUIRED';

  const loadSettings = useCallback(async () => {
    const result = await refetchSettings();
    if (result.error) throw result.error;
    return result.data;
  }, [refetchSettings]);

  const [cookieInput, setCookieInput] = useState('');
  const [syncingCookie, setSyncingCookie] = useState(false);

  const handleSyncCookie = async (e) => {
    if (e) e.preventDefault();
    if (!portalUrl.trim()) {
      setError('Please enter your university portal address.');
      return;
    }
    if (!cookieInput.trim()) {
      setError('Please paste your portal session cookie (full cookie header or .AspNetCore.Cookies).');
      return;
    }
    setSyncingCookie(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      const res = await api.syncPortalCookies(cookieInput.trim(), portalUrl.trim(), token);
      setNotice(res?.message || `Successfully synced ${res?.attendance_count || 0} course attendance records!`);
      setCookieInput('');
      await loadSettings();
    } catch (err) {
      setError(err.message || 'Could not sync portal cookies. Check if the session is still active.');
    } finally {
      setSyncingCookie(false);
    }
  };

  const handleDisconnectCookie = async () => {
    if (!window.confirm('Disconnect your portal session cookies?')) return;
    setSyncingCookie(true);
    setError('');
    setNotice('');
    try {
      const token = await api.getRequestToken(getToken);
      await api.disconnectPortalCookies(token);
      setNotice('Portal session cookies disconnected.');
      await loadSettings();
    } catch (err) {
      setError(err.message || 'Could not disconnect cookies.');
    } finally {
      setSyncingCookie(false);
    }
  };


  const jobQuery = useQuery({
    queryKey: ['portal', ownerKey, 'sync-job', jobId],
    enabled: Boolean(jobId),
    queryFn: async ({ signal }) => api.getPortalSyncStatus(jobId, await api.getRequestToken(getToken), { signal, direct: true }),
    staleTime: 0,
    retry: false,
    refetchInterval: (query) => {
      if (query.state.status === 'error') return query.state.errorUpdateCount < 4 ? 1_500 : false;
      return ['queued', 'running'].includes(query.state.data?.status) ? 1_200 : false;
    },
    refetchIntervalInBackground: false,
  });
  const syncMutation = useMutation({
    mutationFn: async () => api.queuePortalSync(await api.getRequestToken(getToken)),
    onMutate: () => {
      setError('');
      setNotice('');
    },
    onSuccess: (result) => setJobId(result.job_id),
    onError: (err) => setError(err.message || 'Could not start portal sync.'),
  });
  const terminalStatuses = ['success', 'partial', 'error', 'reconnect_required', 'session_expired', 'already_running'];
  const jobStatus = jobQuery.data?.status;
  const jobIsTerminal = terminalStatuses.includes(jobStatus);
  const jobCheckFailed = jobQuery.isError && jobQuery.failureCount >= 4;
  const isSyncing = syncMutation.isPending || (Boolean(jobId) && !jobIsTerminal && !jobCheckFailed);
  const busy = isSyncing;
  const syncState = jobQuery.data;
  const report = settings?.report || syncState?.summary || {};
  const statusError = jobIsTerminal && !['success', 'partial', 'already_running'].includes(jobStatus)
    ? syncState.error || syncState.detail || 'Portal sync could not complete.'
    : jobCheckFailed ? jobQuery.error?.message || 'Could not check sync progress.' : '';
  const pageError = error || settingsQuery.error?.message || statusError || '';
  const pageNotice = notice || (jobIsTerminal && ['success', 'partial', 'already_running'].includes(jobStatus)
    ? syncState.message || (jobStatus === 'already_running' ? 'A portal sync is already running.' : 'Your portal data is up to date.')
    : '');

  useEffect(() => {
    if (jobId && ['success', 'partial', 'reconnect_required', 'session_expired'].includes(jobStatus)) {
      void queryClient.invalidateQueries({ queryKey: ['portal', ownerKey, 'settings'] });
    }
  }, [jobId, jobStatus, ownerKey, queryClient]);

  const startSync = () => syncMutation.mutate();

  if (loading) {
    return <div className="mx-auto flex min-h-72 max-w-6xl items-center justify-center text-sm text-slate-500">Loading university connection…</div>;
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 pb-12 text-heading">
      <header className="flex flex-col gap-4 border-b border-border-light pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">Academic integrations</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">University portal</h1>
          <p className="mt-1 max-w-2xl text-sm font-normal text-muted leading-relaxed">Connect once to sync your attendance, class schedule, and academic results automatically.</p>
        </div>
        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-heading shadow-xs">
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-success' : reconnect ? 'bg-warning' : 'bg-muted'}`} />
          {connected ? 'Connected' : reconnect ? 'Reconnect needed' : 'Not connected'}
        </div>
      </header>

      {pageError && <div role="alert" className="rounded-xl border border-rose-border bg-rose-bg px-4 py-3 text-sm font-normal text-rose">{pageError}</div>}
      {pageNotice && <div role="status" className="rounded-xl border border-success/30 bg-success-bg px-4 py-3 text-sm font-normal text-success">{pageNotice}</div>}

      <section className="grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-border bg-surface p-6 shadow-xs sm:p-7 flex flex-col gap-6">
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-light text-lg font-bold text-violet" aria-hidden="true">U</div>
            <div>
              <h2 className="text-lg font-semibold text-heading">
                {connected ? 'Your portal is connected' : reconnect ? 'Sign in to restore automatic sync' : 'Connect your student account'}
              </h2>
              <p className="mt-1 text-sm font-normal leading-relaxed text-muted">
                {connected ? 'Uniflow reuses your saved university session. Attendance, schedules, and grades sync automatically.' : 'Connect via fast session cookies or automated browser to sync attendance in milliseconds.'}
              </p>
            </div>
          </div>

          {/* ⚡ Method 1: Instant Session Cookie Sync */}
          <div className="rounded-xl border border-violet-light bg-surface-secondary p-4 flex flex-col gap-3">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wider text-violet">⚡ 1-Click Fast Sync (Session Cookies)</h3>
                <p className="mt-1 text-xs font-normal leading-relaxed text-muted max-w-xl">
                  Bypasses heavy browser instances. Directly queries the university portal APIs in &lt;300ms using your active session.
                </p>
              </div>
              {settings?.has_session_cookies && (
                <button
                  type="button"
                  className="rounded-md border border-rose-border bg-surface px-3 py-1.5 text-xs font-medium text-rose hover:bg-rose-bg disabled:opacity-55"
                  onClick={handleDisconnectCookie}
                  disabled={syncingCookie || busy}
                >
                  {syncingCookie ? 'Disconnecting…' : 'Disconnect Cookie'}
                </button>
              )}
            </div>

            <form onSubmit={handleSyncCookie} className="mt-2 flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium uppercase tracking-wider text-muted">
                  1. University Portal Address
                </label>
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  <input
                    type="url"
                    placeholder="https://portals.au.edu.pk/students/"
                    className="flex-1 rounded-lg border border-border-input bg-surface px-3 py-2 text-sm font-normal text-heading placeholder:text-muted focus:border-violet focus:outline-none"
                    value={portalUrl}
                    onChange={(e) => setPortalUrlDraft(e.target.value)}
                    disabled={syncingCookie || busy}
                  />
                  <a
                    href={portalUrl || AIR_UNIVERSITY_PORTAL}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex min-h-9 items-center justify-center gap-1 rounded-lg border border-border-input bg-surface px-3 text-sm font-medium text-violet hover:bg-violet-light whitespace-nowrap"
                  >
                    Open Portal <Icon name="externalLink" size={13} />
                  </a>
                </div>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium uppercase tracking-wider text-muted">
                  2. Session Cookies (Full Cookie Header or .AspNetCore.Cookies)
                </label>
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                  <input
                    type="password"
                    placeholder="Paste full Cookie header or .AspNetCore.Cookies session string"
                    className="flex-1 rounded-lg border border-border-input bg-surface px-3 py-2 text-sm font-normal font-mono text-heading placeholder:text-muted focus:border-violet focus:outline-none"
                    value={cookieInput}
                    onChange={(e) => setCookieInput(e.target.value)}
                    disabled={syncingCookie || busy}
                  />
                  <button
                    type="submit"
                    className="inline-flex min-h-9 items-center justify-center rounded-lg border border-violet bg-violet px-4 text-sm font-medium text-white hover:bg-violet-dark disabled:opacity-55 whitespace-nowrap"
                    disabled={syncingCookie || busy || !cookieInput.trim()}
                  >
                    {syncingCookie ? 'Syncing…' : settings?.has_session_cookies ? 'Update & Sync' : 'Connect & Sync'}
                  </button>
                </div>
              </div>
            </form>

            <details className="mt-1 rounded-lg border border-border bg-surface p-3 text-xs text-muted">
              <summary className="cursor-pointer font-medium text-heading hover:text-violet">
                How to copy your session cookie in 10 seconds (click to view)
              </summary>
              <div className="mt-2 space-y-2 text-[#5d6170]">
                <div className="rounded bg-[#f5f4fd] p-2 text-[11px] text-[#483ba6]">
                  <strong>Important:</strong> Air University requires <code>.AspNetCore.Cookies</code> for student authentication (not just <code>ASP.NET_SessionId</code>). Follow either method below:
                </div>
                <div>
                  <p className="flex items-center gap-1.5 font-semibold text-[#3b3e4a]">
                    <Icon name="zap" size={13} className="text-amber-500" />
                    <span>Method 1: Network Tab (Recommended - 2 clicks)</span>
                  </p>
                  <ol className="mt-1 list-decimal pl-4 space-y-1">
                    <li>Sign into <a href={portalUrl} target="_blank" rel="noreferrer" className="text-[#6657d9] underline font-medium">portals.au.edu.pk</a> in your browser.</li>
                    <li>Press <kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">F12</kbd> → click the <strong>Network</strong> tab → reload the page (<kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">Ctrl+R</kbd>).</li>
                    <li>Click the first request (e.g. <code>students</code> or <code>Attendance</code>) → under <strong>Request Headers</strong>, right-click <strong>Cookie</strong> → click <strong>Copy value</strong>.</li>
                    <li>Paste into the box above and click <strong>Connect & Sync</strong>!</li>
                  </ol>
                </div>
                <div>
                  <p className="flex items-center gap-1.5 font-semibold text-[#3b3e4a]">
                    <Icon name="key" size={13} className="text-indigo-500" />
                    <span>Method 2: Application / Storage Tab</span>
                  </p>
                  <ol className="mt-1 list-decimal pl-4 space-y-1">
                    <li>Press <kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">F12</kbd> → click <strong>Application</strong> (or <strong>Storage</strong> in Firefox) → <strong>Cookies</strong> → <strong>https://portals.au.edu.pk</strong>.</li>
                    <li>Select all rows (<kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">Ctrl+A</kbd>) and copy (<kbd className="rounded bg-[#f0f0f4] px-1 py-0.5 font-mono text-[11px]">Ctrl+C</kbd>), or double-click and copy the value of <strong>.AspNetCore.Cookies</strong>.</li>
                    <li>Paste into the box above and click <strong>Connect & Sync</strong>!</li>
                  </ol>
                </div>
              </div>
            </details>
          </div>

          {/* Automated Extension Sync */}
          <div className="mt-2">
            <ExtensionSetupBox onSynced={() => loadSettings()} />
          </div>

          {connected && (
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <button type="button" disabled={busy || syncingCookie} onClick={startSync} className="rounded-xl bg-violet px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-dark disabled:opacity-50">
                {isSyncing ? 'Syncing your portal…' : 'Sync All Portal Data'}
              </button>
              <span className="text-xs font-normal text-subtle tabular-nums">Last synced {timeLabel(settings?.last_synced_at)}</span>
            </div>
          )}
        </div>

        <aside className="rounded-2xl border border-border bg-surface-secondary p-6">
          <h2 className="text-base font-semibold text-heading">What syncs automatically</h2>
          <ul className="mt-4 space-y-3 text-sm text-nav font-normal">
            {['Attendance by course', 'Class timetable and schedule', 'Grades and academic summary'].map((item) => (
              <li key={item} className="flex items-center gap-3"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-success-light text-success"><Icon name="check" size={12}/></span>{item}</li>
            ))}
          </ul>
          <div className="mt-5 border-t border-border-light pt-4 text-xs font-normal leading-relaxed text-muted">
            Sign in is normally needed once. If the university expires the session or asks for verification again, reconnect to resume syncing. Your browser session is kept separate from other accounts.
          </div>
        </aside>
      </section>

      <section aria-label="Academic overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ['Cumulative GPA', report.cgpa == null ? '—' : Number(report.cgpa).toFixed(2)],
          ['Semester GPA', report.sgpa == null ? '—' : Number(report.sgpa).toFixed(2)],
          ['Credits earned', report.earned_credits == null ? '—' : `${report.earned_credits}`],
          ['Last updated', settings?.last_synced_at ? new Date(settings?.last_synced_at).toLocaleDateString() : '—'],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-border bg-surface p-5 shadow-xs">
            <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
            <p className="mt-2 text-2xl sm:text-3xl font-semibold tracking-tight text-heading tabular-nums">{value}</p>
          </div>
        ))}
      </section>

      {syncState?.pages_synced?.length > 0 && (
        <section className="rounded-2xl border border-border bg-surface p-6 shadow-xs">
          <h2 className="text-lg font-semibold text-heading">Pages found</h2>
          <div className="mt-4 divide-y divide-border-light">
            {syncState.pages_synced.map((page) => <div key={page.url} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm"><span className="font-medium text-heading">{page.title || page.url}</span><span className="text-muted tabular-nums">{page.tables} data tables</span></div>)}
          </div>
        </section>
      )}
    </main>
  );
}
