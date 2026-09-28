'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const filters = [{ key: '', label: 'All' }, { key: 'PENDING', label: 'Pending' }, { key: 'SENT', label: 'Sent' }, { key: 'FAILED', label: 'Failed' }];
const statusTone = (status) => status === 'SENT' ? 'success' : status === 'FAILED' ? 'error' : 'warning';

export default function NotificationsPage() {
  const { getToken } = useAuth();
  const [items, setItems] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async (status = filter) => {
    const token = await getToken();
    const [notifications, summary] = await Promise.all([api.getNotifications(status || null, 50, token), api.getNotificationStats(token)]);
    setItems(notifications || []); setStats(summary || null);
  }, [filter, getToken]);
  useEffect(() => { load().catch((err) => setError(err.message || 'Could not load notifications.')).finally(() => setLoading(false)); }, [load]);

  const changeFilter = async (status) => { setFilter(status); setLoading(true); setError(''); try { await load(status); } catch (err) { setError(err.message || 'Could not load notifications.'); } finally { setLoading(false); } };
  const sendPending = async () => {
    setBusy(true); setError(''); setNotice('');
    try { const token = await getToken(); const result = await api.sendPendingNotifications(50, token); setNotice(result.message || 'Pending notifications queued.'); await load(); }
    catch (err) { setError(err.message || 'Could not queue notifications.'); }
    finally { setBusy(false); }
  };
  const sendOne = async (id) => {
    setBusy(true); setError(''); setNotice('');
    try { const token = await getToken(); const result = await api.sendNotification(id, token); setNotice(result.message || 'Notification queued.'); await load(); }
    catch (err) { setError(err.message || 'Could not queue this notification.'); }
    finally { setBusy(false); }
  };

  return <div className="product-page">
    <header className="product-heading"><div><p className="eyebrow">OUTBOUND UPDATES</p><h1>Notifications</h1><p>Review queued email notifications and delivery status.</p></div>{(stats?.pending || 0) > 0 && <button className="product-action" type="button" onClick={sendPending} disabled={busy}>{busy ? 'Queueing…' : `Send pending (${stats.pending})`}</button>}</header>
    {error && <div className="product-alert">{error}</div>}{notice && <div className="product-alert ok">{notice}</div>}
    <section className="product-grid three"><article className="product-stat"><span>Total queued</span><strong>{loading ? '—' : stats?.total ?? 0}</strong></article><article className="product-stat"><span>Pending</span><strong>{loading ? '—' : stats?.pending ?? 0}</strong></article><article className="product-stat"><span>Sent / failed</span><strong>{loading ? '—' : `${stats?.sent ?? 0} / ${stats?.failed ?? 0}`}</strong></article></section>
    <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">DELIVERY QUEUE</p><h2>Recent notifications</h2></div><span className="product-pill">{items.length}</span></header><nav className="product-tabs" aria-label="Notification status">{filters.map((item) => <button key={item.key || 'all'} type="button" className={`product-tab ${filter === item.key ? 'active' : ''}`} onClick={() => changeFilter(item.key)}>{item.label}</button>)}</nav>
      {loading ? <div className="product-empty">Loading notifications…</div> : items.length ? <div className="product-list">{items.map((item) => <article className="product-row notification-row" key={item.id}><span className="product-icon"><Icon name="messageText" size={15}/></span><span className="product-row-main"><strong>{item.subject || 'Uniflow notification'}</strong><small>{item.recipient} · {item.notification_type || 'General'}{item.error ? ` · ${item.error}` : ''}</small><small>{item.payload}</small></span><span className={`product-pill ${statusTone(item.status)}`}>{(item.status || 'PENDING').toLowerCase()}</span>{item.status === 'PENDING' && <button className="product-action secondary" type="button" disabled={busy} onClick={() => sendOne(item.id)}>Send</button>}</article>)}</div> : <div className="product-empty"><strong>No notifications here</strong>New notifications appear when Uniflow queues an email for delivery.</div>}
    </section>
    <p className="product-note">This is the outbound email queue. Google Classroom sync runs every 30 minutes and a saved university portal session syncs hourly, but those syncs do not yet create student alert emails automatically. Emails shown here are sent when a user or an automation explicitly queues them.</p>
  </div>;
}
