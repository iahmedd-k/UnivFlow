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

  return <div className="product-page">
    <header className="product-heading"><div><p className="eyebrow">CONNECTED WORKSPACE</p><h1>Mail & Drive</h1><p>See recent Google mail and course files alongside your studies.</p></div>{connected && <button className="product-action secondary" type="button" onClick={disconnect} disabled={busy}>{busy ? 'Working…' : 'Disconnect Google'}</button>}</header>
    {error && <div className="product-alert">{error}</div>}{message && <div className="product-alert ok">{message}</div>}
    {!connected && !loading ? <section className="product-card google-connect-card"><span className="google-connect-icon">G</span><h2>Connect your Google account</h2><p>Uniflow uses the connected account to show recent inbox messages and Drive files for your academic workspace.</p><button className="product-action" type="button" onClick={connect} disabled={busy}>{busy ? 'Connecting…' : 'Connect Google'}</button><small>Connection is handled by Google OAuth.</small></section> : <div className="product-grid mail-drive-grid">
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">INBOX</p><h2>Recent messages</h2></div><span className="product-pill">{emails.length}</span></header><nav className="product-tabs" aria-label="Email category">{categories.map((item) => <button className={`product-tab ${category === item.key ? 'active' : ''}`} type="button" key={item.key} onClick={() => changeCategory(item.key)}>{item.label}</button>)}</nav>
        {loading ? <div className="product-empty">Loading messages…</div> : emails.length ? <div className="product-list">{emails.map((item) => <article className="product-row" key={item.id}><span className={`mail-unread ${item.unread ? 'active' : ''}`}/><span className="product-row-main"><strong>{item.subject || '(no subject)'}</strong><small>{item.from} · {item.snippet}</small></span><span className="product-row-meta">{item.date ? new Date(item.date).toLocaleDateString() : ''}</span></article>)}</div> : <div className="product-empty">No recent messages in this category.</div>}
      </section>
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">GOOGLE DRIVE</p><h2>Recent files</h2></div><span className="product-pill">{files.length}</span></header>
        {loading ? <div className="product-empty">Loading files…</div> : files.length ? <div className="product-list">{files.map((file) => <a className="product-row" href={file.webViewLink || '#'} target="_blank" rel="noreferrer" key={file.id}><span className="product-icon"><Icon name="file" size={15}/></span><span className="product-row-main"><strong>{filename(file)}</strong><small>{file.owners?.[0]?.displayName || 'Google Drive'} · {file.mimeType?.split('.').pop()?.toUpperCase() || 'File'}</small></span><span className="product-row-meta">{file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}</span></a>)}</div> : <div className="product-empty">No recent Drive files were found.</div>}
      </section>
    </div>}
    {connected && email && <p className="connected-account-note">Connected account: <strong>{email}</strong></p>}
  </div>;
}
