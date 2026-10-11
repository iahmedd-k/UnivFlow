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

  useEffect(() => { load().catch((err) => setError(err.message || 'Could not check Google connection.')).finally(() => setLoading(false)); }, [load]);

  const connect = async () => {
    setBusy(true); setError('');
    try { const token = await getToken(); const result = await api.getGoogleAuthUrl(token); if (result.auth_url) window.location.assign(result.auth_url); else throw new Error('Google did not return a sign-in URL.'); }
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

  return <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
    <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">CONNECTED WORKSPACE</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">Mail & Drive</h1><p className="mt-1 text-xs text-[#858998]">See recent Google mail and course files alongside your studies.</p></div>{connected && <button className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]" type="button" onClick={disconnect} disabled={busy}>{busy ? 'Working…' : 'Disconnect Google'}</button>}</header>
    {error && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]">{error}</div>}{message && <div className="rounded-lg border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2.5 text-xs text-[#43816b]">{message}</div>}
    {!connected && !loading ? <section className="flex min-h-[300px] flex-col items-center justify-center rounded-xl border border-[#ebebf0] bg-white p-8 text-center shadow-sm"><span className="mb-4 grid h-11 w-11 place-items-center rounded-xl border border-[#ededf2] bg-white text-xl font-bold text-[#4285f4]">G</span><h2 className="text-base font-semibold text-[#363a48]">Connect your Google account</h2><p className="mb-4 mt-2 max-w-md text-xs leading-relaxed text-[#888c9a]">Uniflow uses the connected account to show recent inbox messages and Drive files for your academic workspace.</p><button className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55" type="button" onClick={connect} disabled={busy}>{busy ? 'Connecting…' : 'Connect Google'}</button><small className="mt-2 text-xs text-[#a1a3ae]">Connection is handled by Google OAuth.</small></section> : <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm"><header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">INBOX</p><h2 className="text-[13px] font-semibold text-[#343746]">Recent messages</h2></div><span className="inline-flex items-center rounded-full bg-[#f1f1f6] px-2 py-1 text-xs font-semibold text-[#6e7281]">{emails.length}</span></header><nav className="flex gap-1.5 overflow-auto border-b border-[#efeff3] px-4 py-3" aria-label="Email category">{categories.map((item) => <button className={`whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs ${category === item.key ? 'border-[#e9e5ff] bg-[#f2efff] font-semibold text-[#5e4fc5]' : 'border-transparent text-[#777b89]'}`} type="button" key={item.key} onClick={() => changeCategory(item.key)}>{item.label}</button>)}</nav>
        {loading ? <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">Loading messages…</div> : emails.length ? <div className="flex flex-col">{emails.map((item) => <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] px-4 py-3 last:border-b-0 hover:bg-[#fafafd]" key={item.id}><span className={`h-2 w-2 shrink-0 rounded-full ${item.unread ? 'bg-[#6b5cda]' : 'bg-[#e2e3e9]'}`}/><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-semibold text-[#414553]">{item.subject || '(no subject)'}</strong><small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[#9295a2]">{item.from} · {item.snippet}</small></span><span className="whitespace-nowrap text-xs text-[#808493]">{item.date ? new Date(item.date).toLocaleDateString() : ''}</span></article>)}</div> : <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">No recent messages in this category.</div>}
      </section>
      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm"><header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">GOOGLE DRIVE</p><h2 className="text-[13px] font-semibold text-[#343746]">Recent files</h2></div><span className="inline-flex items-center rounded-full bg-[#f1f1f6] px-2 py-1 text-xs font-semibold text-[#6e7281]">{files.length}</span></header>
        {loading ? <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">Loading files…</div> : files.length ? <div className="flex flex-col">{files.map((file) => <a className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] px-4 py-3 text-inherit no-underline last:border-b-0 hover:bg-[#fafafd]" href={file.webViewLink || '#'} target="_blank" rel="noreferrer" key={file.id}><span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="file" size={15}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-semibold text-[#414553]">{filename(file)}</strong><small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[#9295a2]">{file.owners?.[0]?.displayName || 'Google Drive'} · {file.mimeType?.split('.').pop()?.toUpperCase() || 'File'}</small></span><span className="whitespace-nowrap text-xs text-[#808493]">{file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}</span></a>)}</div> : <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">No recent Drive files were found.</div>}
      </section>
    </div>}
    {connected && email && <p className="text-xs text-[#9295a2]">Connected account: <strong className="font-semibold text-[#606474]">{email}</strong></p>}
  </div>;
}
