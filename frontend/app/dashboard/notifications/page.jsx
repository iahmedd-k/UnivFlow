'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const filters = [{ key: '', label: 'All' }, { key: 'PENDING', label: 'Pending' }, { key: 'SENT', label: 'Sent' }, { key: 'FAILED', label: 'Failed' }];
const statusTone = (status) => status === 'SENT'
  ? 'bg-[#eaf7f1] text-[#438a71]'
  : status === 'FAILED'
    ? 'bg-[#fff0f0] text-[#b15252]'
    : 'bg-[#fff4e4] text-[#a87936]';

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

  const checkAlerts = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const token = await getToken();
      const res = await api.checkAlerts(token);
      setNotice(`Alert scan complete: Generated ${res.attendance_warnings_generated || 0} attendance warning(s) and ${res.timetable_reminders_generated || 0} timetable reminder(s).`);
      await load();
    } catch (err) {
      setError(err.message || 'Could not evaluate alerts.');
    } finally {
      setBusy(false);
    }
  };

  return <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
    <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">OUTBOUND UPDATES</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Notifications & Alerts</h1>
        <p className="mt-1 text-xs text-[#858998]">Real-time attendance warnings, 10-minute timetable reminders, and outbound delivery queue.</p>
      </div>
      <div className="flex flex-wrap gap-2.5">
        <button className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55" type="button" onClick={checkAlerts} disabled={busy}>
          {busy ? 'Scanning…' : 'Scan Today’s Alerts'}
        </button>
        {(stats?.pending || 0) > 0 && <button className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1] disabled:opacity-55" type="button" onClick={sendPending} disabled={busy}>{busy ? 'Queueing…' : `Send pending (${stats.pending})`}</button>}
      </div>
    </header>
    {error && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]">{error}</div>}{notice && <div className="rounded-lg border border-[#d8eee4] bg-[#f3fbf7] px-3 py-2.5 text-xs text-[#43816b]">{notice}</div>}
    <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3">{[['Total queued', loading ? '—' : stats?.total ?? 0], ['Pending', loading ? '—' : stats?.pending ?? 0], ['Sent / failed', loading ? '—' : `${stats?.sent ?? 0} / ${stats?.failed ?? 0}`]].map(([label, value]) => <article className="rounded-xl border border-[#ededf2] bg-white p-4" key={label}><span className="block text-xs text-[#858998]">{label}</span><strong className="mt-2 block text-[22px] font-semibold text-[#343746]">{value}</strong></article>)}</section>
    <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm"><header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">DELIVERY QUEUE</p><h2 className="text-[13px] font-semibold text-[#343746]">Recent notifications</h2></div><span className="inline-flex items-center rounded-full bg-[#f1f1f6] px-2 py-1 text-xs font-semibold text-[#6e7281]">{items.length}</span></header><nav className="flex gap-1.5 overflow-auto border-b border-[#efeff3] px-4 py-3" aria-label="Notification status">{filters.map((item) => <button key={item.key || 'all'} type="button" className={`whitespace-nowrap rounded-md border px-2.5 py-1.5 text-xs ${filter === item.key ? 'border-[#e9e5ff] bg-[#f2efff] font-semibold text-[#5e4fc5]' : 'border-transparent text-[#777b89]'}`} onClick={() => changeFilter(item.key)}>{item.label}</button>)}</nav>
      {loading ? <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">Loading notifications…</div> : items.length ? <div className="flex flex-col">{items.map((item) => <article className="flex min-h-[60px] items-center gap-3 border-b border-[#f1f1f4] px-4 py-3 last:border-b-0 hover:bg-[#fafafd]" key={item.id}><span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]"><Icon name="messageText" size={15}/></span><span className="flex min-w-0 flex-1 flex-col gap-1"><strong className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-semibold text-[#414553]">{item.subject || 'Uniflow notification'}</strong><small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[#9295a2]">{item.recipient} · {item.notification_type || 'General'}{item.error ? ` · ${item.error}` : ''}</small><small className="overflow-hidden text-ellipsis whitespace-nowrap text-xs text-[#9295a2]">{item.payload}</small></span><span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${statusTone(item.status)}`}>{(item.status || 'PENDING').toLowerCase()}</span>{item.status === 'PENDING' && <button className="inline-flex min-h-9 shrink-0 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb] disabled:opacity-55" type="button" disabled={busy} onClick={() => sendOne(item.id)}>Send</button>}</article>)}</div> : <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]"><strong className="mb-1 block text-xs text-[#515563]">No notifications here</strong>New notifications appear when Uniflow queues an email for delivery.</div>}
    </section>
    <p className="mt-1 rounded-lg bg-[#f6f5ff] px-3 py-2.5 text-xs leading-relaxed text-[#77729b]">This is the outbound email queue. Google Classroom sync runs every 30 minutes and a saved university portal session syncs hourly, but those syncs do not yet create student alert emails automatically. Emails shown here are sent when a user or an automation explicitly queues them.</p>
  </div>;
}
