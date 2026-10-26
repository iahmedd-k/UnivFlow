'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const categories = [{ key: 'all', label: 'All mail' }, { key: 'university', label: 'University' }, { key: 'other', label: 'Other' }];

export default function MailDrivePage() {
  const { getToken } = useAuth();
  const [connected, setConnected] = useState(false);
  const [email, setEmail] = useState('');
  const [emails, setEmails] = useState([]);
  const [files, setFiles] = useState([]);
  const [category, setCategory] = useState('all');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(async (mailCategory = category) => {
    const token = await getToken();
    const auth = await api.getAuthStatus(token);
    setConnected(Boolean(auth?.google_connected)); setEmail(auth?.google_email || '');
    if (!auth?.google_connected) { setEmails([]); setFiles([]); return; }
    const result = await Promise.allSettled([api.getRecentEmails(token, null, mailCategory), api.getRecentDriveFiles(token)]);
    setEmails(result[0].status === 'fulfilled' ? result[0].value || [] : []);
    setFiles(result[1].status === 'fulfilled' ? result[1].value || [] : []);
    const failure = result.find((item) => item.status === 'rejected');
    if (failure) setError(failure.reason?.message || 'Google data could not be loaded.');
  }, [category, getToken]);

  useEffect(() => {
    const timer = setTimeout(() => {
      load().catch((err) => setError(err.message || 'Could not check Google connection.')).finally(() => setLoading(false));
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  const connect = async () => {
    setBusy(true); setError('');
    try { const token = await getToken(); const result = await api.getGoogleAuthUrl(token, '/dashboard/mail-drive'); if (result.auth_url) window.location.assign(result.auth_url); else throw new Error('Google did not return a sign-in URL.'); }
    catch (err) { setError(err.message || 'Could not connect Google.'); setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true); setError('');
    try { const token = await getToken(); await api.disconnectGoogle(token); setMessage('Google account disconnected.'); await load(); }
    catch (err) { setError(err.message || 'Could not disconnect Google.'); }
    finally { setBusy(false); }
  };
  const changeCategory = async (key) => { setCategory(key); setLoading(true); setError(''); try { await load(key); } catch (err) { setError(err.message || 'Could not load mail.'); } finally { setLoading(false); } };
  const filename = (file) => file.name || 'Untitled file';

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-heading">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">CONNECTED WORKSPACE</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">Mail & Drive</h1>
          <p className="text-sm font-normal text-muted leading-relaxed">See recent Google mail and course files alongside your studies.</p>
        </div>
        {connected && (
          <button className="inline-flex min-h-9 items-center justify-center rounded-md border border-border-input bg-surface px-3 text-sm font-medium text-nav hover:bg-surface-secondary" type="button" onClick={disconnect} disabled={busy}>
            {busy ? 'Working…' : 'Disconnect Google'}
          </button>
        )}
      </header>

      {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm font-normal text-rose">{error}</div>}
      {message && <div className="rounded-lg border border-success/30 bg-success-bg px-4 py-3 text-sm font-normal text-success">{message}</div>}

      {!connected && !loading ? (
        <section className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-border bg-surface p-8 text-center shadow-xs">
          <span className="mb-4 grid h-12 w-12 place-items-center rounded-xl border border-border-input bg-surface text-xl font-bold text-google">G</span>
          <h2 className="text-lg font-semibold text-heading">Connect your Google account</h2>
          <p className="mb-5 mt-2 max-w-md text-sm font-normal leading-relaxed text-muted">Uniflow uses the connected account to show recent inbox messages and Drive files for your academic workspace.</p>
          <button className="inline-flex min-h-9 items-center justify-center rounded-md border border-violet bg-violet px-4 text-sm font-medium text-white hover:bg-violet-dark disabled:opacity-55" type="button" onClick={connect} disabled={busy}>
            {busy ? 'Connecting…' : 'Connect Google'}
          </button>
          <small className="mt-3 text-xs font-normal text-subtle">Connection is handled securely via Google OAuth.</small>
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Inbox Section */}
          <section className="min-w-0 rounded-xl border border-border bg-surface shadow-xs">
            <header className="flex items-center justify-between gap-3.5 border-b border-border-light px-5 py-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-label">INBOX</p>
                <h2 className="text-lg font-semibold text-heading">Recent messages</h2>
              </div>
              <span className="inline-flex items-center rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-nav tabular-nums">{emails.length}</span>
            </header>
            <nav className="flex gap-1.5 overflow-auto border-b border-border-light px-4 py-3" aria-label="Email category">
              {categories.map((item) => (
                <button
                  className={`whitespace-nowrap rounded-md border px-3 py-1.5 text-sm font-medium transition ${
                    category === item.key
                      ? 'border-violet-light bg-violet-light text-violet font-semibold'
                      : 'border-transparent text-nav hover:bg-surface-secondary'
                  }`}
                  type="button"
                  key={item.key}
                  onClick={() => changeCategory(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </nav>
            {loading ? (
              <div className="px-5 py-10 text-center text-sm font-normal text-muted">Loading messages…</div>
            ) : emails.length ? (
              <div className="flex flex-col">
                {emails.map((item) => (
                  <article className="flex min-h-[60px] items-center gap-3 border-b border-border-light px-4 py-3 last:border-b-0 hover:bg-surface-secondary transition" key={item.id}>
                    <span className={`h-2 w-2 shrink-0 rounded-full ${item.unread ? 'bg-violet' : 'bg-border-input'}`}/>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-sm font-semibold text-heading">{item.subject || '(no subject)'}</strong>
                      <small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-normal text-muted">{item.from} · {item.snippet}</small>
                    </span>
                    <span className="whitespace-nowrap text-xs font-normal text-subtle tabular-nums">{item.date ? new Date(item.date).toLocaleDateString() : ''}</span>
                  </article>
                ))}
              </div>
            ) : (
              <div className="px-5 py-10 text-center text-sm font-normal text-muted">No recent messages in this category.</div>
            )}
          </section>

          {/* Drive Section */}
          <section className="min-w-0 rounded-xl border border-border bg-surface shadow-xs">
            <header className="flex items-center justify-between gap-3.5 border-b border-border-light px-5 py-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-label">GOOGLE DRIVE</p>
                <h2 className="text-lg font-semibold text-heading">Recent files</h2>
              </div>
              <span className="inline-flex items-center rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-nav tabular-nums">{files.length}</span>
            </header>
            {loading ? (
              <div className="px-5 py-10 text-center text-sm font-normal text-muted">Loading files…</div>
            ) : files.length ? (
              <div className="flex flex-col">
                {files.map((file) => (
                  <a className="flex min-h-[60px] items-center gap-3 border-b border-border-light px-4 py-3 text-inherit no-underline last:border-b-0 hover:bg-surface-secondary transition" href={file.webViewLink || '#'} target="_blank" rel="noreferrer" key={file.id}>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="file" size={15}/></span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-sm font-semibold text-heading">{filename(file)}</strong>
                      <small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-normal text-muted">{file.owners?.[0]?.displayName || 'Google Drive'} · {file.mimeType?.split('.').pop()?.toUpperCase() || 'File'}</small>
                    </span>
                    <span className="whitespace-nowrap text-xs font-normal text-subtle tabular-nums">{file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}</span>
                  </a>
                ))}
              </div>
            ) : (
              <div className="px-5 py-10 text-center text-sm font-normal text-muted">No recent Drive files were found.</div>
            )}
          </section>
        </div>
      )}

      {connected && email && <p className="text-xs font-normal text-muted">Connected account: <strong className="font-semibold text-heading">{email}</strong></p>}
    </div>
  );
}
