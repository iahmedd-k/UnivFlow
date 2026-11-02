'use client';

import { useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

const categories = [
  { key: 'all', label: 'All mail' },
  { key: 'university', label: 'University' },
  { key: 'other', label: 'Other' },
];

const actionClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border-input bg-surface px-3.5 text-sm font-medium text-nav transition hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-55';
const primaryActionClass = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-55';

function formatDate(value) {
  if (!value) return 'Date unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(date);
}

function getFileType(file) {
  const mimeType = file.mimeType || '';
  if (mimeType.includes('google-apps.document')) return 'Google Doc';
  if (mimeType.includes('google-apps.spreadsheet')) return 'Spreadsheet';
  if (mimeType.includes('google-apps.presentation')) return 'Presentation';
  if (mimeType === 'application/pdf') return 'PDF';
  return mimeType.split('.').pop()?.toUpperCase() || 'Drive file';
}

export default function MailDrivePage() {
  const { getToken, userId } = useAuth();
  const ownerKey = getQueryOwnerKey(userId);
  const queryClient = useQueryClient();
  const [category, setCategory] = useState('all');
  const [query, setQuery] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const authQuery = useQuery({
    queryKey: ['auth', ownerKey, 'status'],
    queryFn: async ({ signal }) => api.getAuthStatus(await api.getRequestToken(getToken), { signal, direct: true }),
  });
  const connected = Boolean(authQuery.data?.google_connected);
  const email = authQuery.data?.google_email || '';
  const emailsQuery = useQuery({
    queryKey: ['mail-drive', ownerKey, 'emails', category],
    enabled: connected,
    queryFn: async ({ signal }) => api.getRecentEmails(await api.getRequestToken(getToken), null, category, { signal, direct: true }),
  });
  const filesQuery = useQuery({
    queryKey: ['mail-drive', ownerKey, 'drive'],
    enabled: connected,
    queryFn: async ({ signal }) => api.getRecentDriveFiles(await api.getRequestToken(getToken), { signal, direct: true }),
  });
  const emails = Array.isArray(emailsQuery.data) ? emailsQuery.data : [];
  const files = Array.isArray(filesQuery.data) ? filesQuery.data : [];
  const loading = authQuery.isPending || (connected && (emailsQuery.isPending || filesQuery.isPending));
  const queryError = authQuery.error?.message || emailsQuery.error?.message || filesQuery.error?.message || '';

  const connect = async () => {
    setBusy(true);
    setError('');
    try {
      const token = await getToken();
      const result = await api.getGoogleAuthUrl(token, '/dashboard/mail-drive');
      if (result.auth_url) {
        window.location.assign(result.auth_url);
      } else {
        throw new Error('Google did not return a sign-in URL.');
      }
    } catch (err) {
      setError(err.message || 'Could not connect Google.');
      setBusy(false);
    }
  };

  const disconnect = async () => {
    if (!window.confirm('Disconnect this Google account from Uniflow?')) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const token = await getToken();
      await api.disconnectGoogle(token);
      queryClient.setQueryData(['auth', ownerKey, 'status'], (current) => ({ ...current, google_connected: false, google_email: null }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['mail-drive', ownerKey] }),
        queryClient.invalidateQueries({ queryKey: ['auth', ownerKey, 'status'] }),
      ]);
      setMessage('Google account disconnected.');
    } catch (err) {
      setError(err.message || 'Could not disconnect Google.');
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setError('');
    try {
      await Promise.all([authQuery.refetch(), emailsQuery.refetch(), filesQuery.refetch()]);
    } catch (err) {
      setError(err.message || 'Could not refresh Google data.');
    } finally {
      setRefreshing(false);
    }
  };

  const changeCategory = async (key) => {
    if (key === category) return;
    setCategory(key);
    setError('');
  };

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredEmails = emails.filter((item) =>
    [item.subject, item.from, item.snippet, item.category_label]
      .some((value) => String(value || '').toLocaleLowerCase().includes(normalizedQuery))
  );
  const filteredFiles = files.filter((file) =>
    [file.name, file.owners?.[0]?.displayName, getFileType(file)]
      .some((value) => String(value || '').toLocaleLowerCase().includes(normalizedQuery))
  );
  const unreadCount = emails.filter((item) => item.unread).length;
  const visibleError = error || queryError;

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-6 pb-10 text-heading">
      <header className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-lg border border-border bg-surface text-google shadow-xs" aria-hidden="true">
              <span className="text-base font-bold">G</span>
            </span>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-label">Your connected workspace</p>
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-heading sm:text-4xl">Mail & Drive</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
            Find university messages and jump back into your latest files, all in one place.
          </p>
        </div>

        {connected && (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={actionClass} onClick={refresh} disabled={refreshing || busy}>
              <Icon name="refresh" size={15} className={refreshing ? 'animate-spin' : ''} />
              {refreshing ? 'Refreshing' : 'Refresh'}
            </button>
            <a className={actionClass} href="https://mail.google.com/" target="_blank" rel="noreferrer">
              <Icon name="externalLink" size={15} /> Open Gmail
            </a>
            <a className={actionClass} href="https://drive.google.com/" target="_blank" rel="noreferrer">
              <Icon name="externalLink" size={15} /> Open Drive
            </a>
          </div>
        )}
      </header>

      {visibleError && <div role="alert" className="flex items-start gap-2 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose"><Icon name="alert" size={16} className="mt-0.5 shrink-0" />{visibleError}</div>}
      {message && <div role="status" className="rounded-lg border border-success/30 bg-success-bg px-4 py-3 text-sm text-success">{message}</div>}

      {loading && !connected ? (
        <section className="flex min-h-64 flex-col items-center justify-center rounded-2xl border border-border bg-surface p-8 text-center shadow-xs" aria-live="polite">
          <span className="mb-3 grid size-11 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="folder" size={20} /></span>
          <p className="text-sm font-medium text-heading">Checking your Google connection…</p>
        </section>
      ) : !connected ? (
        <section className="overflow-hidden rounded-2xl border border-border bg-surface shadow-xs">
          <div className="grid gap-8 p-6 sm:p-9 md:grid-cols-[1.1fr_0.9fr] md:items-center">
            <div>
              <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-secondary px-3 py-1 text-xs font-medium text-nav">
                <span className="size-1.5 rounded-full bg-subtle" /> Not connected
              </span>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-heading">Bring your study files together</h2>
              <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted">
                Connect your Google account to see recent inbox messages and Drive files here. You can still use the rest of Uniflow without connecting.
              </p>
              <button type="button" className={`${primaryActionClass} mt-5`} onClick={connect} disabled={busy}>
                <Icon name="link" size={16} /> {busy ? 'Connecting…' : 'Connect Google'}
              </button>
              <p className="mt-3 text-xs text-subtle">You’ll be redirected to Google to approve access.</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-1">
              <article className="flex items-start gap-3 rounded-xl border border-border-light bg-surface-secondary p-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="messageText" size={17} /></span>
                <div><h3 className="text-sm font-semibold text-heading">University inbox</h3><p className="mt-1 text-xs leading-relaxed text-muted">Browse recent messages and filter university updates.</p></div>
              </article>
              <article className="flex items-start gap-3 rounded-xl border border-border-light bg-surface-secondary p-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-700"><Icon name="folder" size={17} /></span>
                <div><h3 className="text-sm font-semibold text-heading">Recent Drive files</h3><p className="mt-1 text-xs leading-relaxed text-muted">Open course documents directly from your workspace.</p></div>
              </article>
            </div>
          </div>
        </section>
      ) : (
        <>
          <section className="flex flex-col justify-between gap-4 rounded-2xl border border-border bg-surface p-4 shadow-xs sm:flex-row sm:items-center sm:px-5">
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-success-bg text-success"><Icon name="checkCircle" size={19} /></span>
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-wide text-label">Google connected</p>
                <p className="truncate text-sm font-semibold text-heading">{email || 'Account connected'}</p>
              </div>
            </div>
            <button type="button" className="min-h-9 self-start rounded-lg px-3 text-sm font-medium text-muted transition hover:bg-surface-secondary hover:text-heading sm:self-auto" onClick={disconnect} disabled={busy}>
              {busy ? 'Working…' : 'Disconnect'}
            </button>
          </section>

          <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <article className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-xs">
              <span className="grid size-10 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="messageText" size={18} /></span>
              <div><p className="text-xs font-medium text-muted">Messages in view</p><p className="mt-0.5 text-xl font-semibold tabular-nums text-heading">{loading ? '—' : emails.length}</p></div>
            </article>
            <article className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-xs">
              <span className="grid size-10 place-items-center rounded-lg bg-amber-50 text-amber-700"><Icon name="bell" size={18} /></span>
              <div><p className="text-xs font-medium text-muted">Unread messages</p><p className="mt-0.5 text-xl font-semibold tabular-nums text-heading">{loading ? '—' : unreadCount}</p></div>
            </article>
            <article className="flex items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-xs">
              <span className="grid size-10 place-items-center rounded-lg bg-blue-50 text-blue-700"><Icon name="files" size={18} /></span>
              <div><p className="text-xs font-medium text-muted">Recent Drive files</p><p className="mt-0.5 text-xl font-semibold tabular-nums text-heading">{loading ? '—' : files.length}</p></div>
            </article>
          </section>

          <label className="flex min-h-11 items-center gap-3 rounded-xl border border-border-input bg-surface px-4 shadow-xs focus-within:border-violet focus-within:ring-2 focus-within:ring-violet/15">
            <Icon name="search" size={17} className="shrink-0 text-muted" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search message subjects, senders, snippets, or file names…"
              className="w-full bg-transparent text-sm text-heading outline-none placeholder:text-subtle"
              aria-label="Search mail and Drive files"
            />
            {query && <button type="button" onClick={() => setQuery('')} className="shrink-0 rounded px-1 text-xs font-medium text-muted hover:text-heading">Clear</button>}
          </label>

          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
            <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
              <header className="flex items-center justify-between gap-3 border-b border-border-light px-5 py-4">
                <div className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="messageText" size={17} /></span>
                  <div><h2 className="text-base font-semibold text-heading">Inbox</h2><p className="text-xs text-muted">Recent messages</p></div>
                </div>
                <span className="rounded-full bg-surface-secondary px-2.5 py-1 text-xs font-semibold tabular-nums text-nav">{filteredEmails.length}</span>
              </header>
              <nav className="flex gap-1 overflow-x-auto border-b border-border-light px-4 py-2.5" aria-label="Filter inbox messages">
                {categories.map((item) => (
                  <button
                    className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition ${category === item.key ? 'bg-violet-light text-violet' : 'text-muted hover:bg-surface-secondary hover:text-heading'}`}
                    type="button"
                    key={item.key}
                    aria-pressed={category === item.key}
                    onClick={() => changeCategory(item.key)}
                  >
                    {item.label}
                  </button>
                ))}
              </nav>
              {loading ? (
                <p className="px-5 py-10 text-center text-sm text-muted" aria-live="polite">Loading messages…</p>
              ) : filteredEmails.length ? (
                <div className="divide-y divide-border-light">
                  {filteredEmails.map((item) => (
                    <a
                      className="flex min-h-[76px] items-start gap-3 px-4 py-3.5 text-inherit no-underline transition hover:bg-surface-secondary"
                      href={`https://mail.google.com/mail/u/0/#all/${encodeURIComponent(item.thread_id || item.id)}`}
                      target="_blank"
                      rel="noreferrer"
                      key={item.id}
                      aria-label={`Open email: ${item.subject || 'No subject'}`}
                    >
                      <span className={`mt-1.5 size-2 shrink-0 rounded-full ${item.unread ? 'bg-violet' : 'bg-border-input'}`} aria-label={item.unread ? 'Unread' : 'Read'} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center justify-between gap-3">
                          <strong className="truncate text-sm font-semibold text-heading">{item.subject || '(no subject)'}</strong>
                          <time className="shrink-0 text-xs tabular-nums text-subtle">{formatDate(item.date)}</time>
                        </span>
                        <span className="mt-1 block truncate text-xs text-muted">{item.from || 'Unknown sender'}</span>
                        <span className="mt-1 block truncate text-xs text-subtle">{item.snippet || 'No message preview available.'}</span>
                      </span>
                    </a>
                  ))}
                </div>
              ) : (
                <div className="px-5 py-10 text-center">
                  <span className="mx-auto grid size-10 place-items-center rounded-xl bg-surface-secondary text-muted"><Icon name={query ? 'search' : 'messageText'} size={18} /></span>
                  <p className="mt-3 text-sm font-medium text-heading">{query ? 'No matching messages' : 'No recent messages'}</p>
                  <p className="mt-1 text-xs text-muted">{query ? 'Try another search or clear the search field.' : 'Messages from this inbox filter will appear here.'}</p>
                </div>
              )}
            </section>

            <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-surface shadow-xs">
              <header className="flex items-center justify-between gap-3 border-b border-border-light px-5 py-4">
                <div className="flex items-center gap-3">
                  <span className="grid size-9 place-items-center rounded-lg bg-blue-50 text-blue-700"><Icon name="folder" size={17} /></span>
                  <div><h2 className="text-base font-semibold text-heading">Google Drive</h2><p className="text-xs text-muted">Recently updated files</p></div>
                </div>
                <span className="rounded-full bg-surface-secondary px-2.5 py-1 text-xs font-semibold tabular-nums text-nav">{filteredFiles.length}</span>
              </header>
              {loading ? (
                <p className="px-5 py-10 text-center text-sm text-muted" aria-live="polite">Loading files…</p>
              ) : filteredFiles.length ? (
                <div className="divide-y divide-border-light">
                  {filteredFiles.map((file) => (
                    <a
                      className={`flex min-h-[76px] items-center gap-3 px-4 py-3.5 text-inherit no-underline transition ${file.webViewLink ? 'hover:bg-surface-secondary' : 'cursor-default'}`}
                      href={file.webViewLink || undefined}
                      target={file.webViewLink ? '_blank' : undefined}
                      rel={file.webViewLink ? 'noreferrer' : undefined}
                      key={file.id}
                      aria-label={file.webViewLink ? `Open Drive file: ${file.name || 'Untitled file'}` : undefined}
                    >
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-700"><Icon name="file" size={17} /></span>
                      <span className="min-w-0 flex-1">
                        <strong className="block truncate text-sm font-semibold text-heading">{file.name || 'Untitled file'}</strong>
                        <span className="mt-1 block truncate text-xs text-muted">{getFileType(file)}{file.owners?.[0]?.displayName ? ` · ${file.owners[0].displayName}` : ''}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5 text-xs tabular-nums text-subtle">
                        <Icon name="clock" size={13} /> {formatDate(file.modifiedTime)}
                      </span>
                    </a>
                  ))}
                </div>
              ) : (
                <div className="px-5 py-10 text-center">
                  <span className="mx-auto grid size-10 place-items-center rounded-xl bg-surface-secondary text-muted"><Icon name={query ? 'search' : 'files'} size={18} /></span>
                  <p className="mt-3 text-sm font-medium text-heading">{query ? 'No matching files' : 'No recent files found'}</p>
                  <p className="mt-1 text-xs text-muted">{query ? 'Try a different search term.' : 'Files you recently updated will show up here.'}</p>
                </div>
              )}
            </section>
          </div>

          <footer className="flex flex-col justify-between gap-2 border-t border-border-light pt-4 text-xs text-muted sm:flex-row sm:items-center">
            <span>Showing recent items from your connected Google account.</span>
            <button type="button" className="self-start font-medium text-nav underline-offset-4 hover:text-violet hover:underline sm:self-auto" onClick={disconnect} disabled={busy}>
              Manage connection
            </button>
          </footer>
        </>
      )}
    </div>
  );
}
