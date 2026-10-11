'use client';

import { useEffect, useState } from 'react';
import { requestNotificationPermission, onMessageListener } from '@/app/lib/firebase';
import Icon from '@/app/dashboard/Icon';

export default function FirebaseAlertsBanner() {
  const [permission, setPermission] = useState('default');
  const [token, setToken] = useState(null);
  const [activeAlert, setActiveAlert] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      setPermission(Notification.permission);
    }

    // Attach real-time foreground Firebase alert listener
    let unsubscribe = null;
    const setupListener = async () => {
      unsubscribe = await onMessageListener((payload) => {
        const title = payload.notification?.title || payload.data?.title || 'Uniflow Alert';
        const body = payload.notification?.body || payload.data?.body || '';
        const type = payload.data?.type || (title.includes('Attendance') ? 'attendance' : 'timetable');

        setActiveAlert({
          title,
          body,
          type,
          timestamp: new Date().toLocaleTimeString(),
        });
      });
    };

    setupListener();
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, []);

  const handleEnableAlerts = async () => {
    setBusy(true);
    try {
      const fcmToken = await requestNotificationPermission();
      if (fcmToken) {
        setToken(fcmToken);
        setPermission('granted');
        // Save to backend or local storage
        if (typeof window !== 'undefined') {
          localStorage.setItem('uniflow_fcm_token', fcmToken);
        }
      } else if (typeof window !== 'undefined' && 'Notification' in window) {
        setPermission(Notification.permission);
      }
    } catch (err) {
      console.error('Failed to enable Firebase alerts:', err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {/* Real-time Floating In-App Alert Toast */}
      {activeAlert && (
        <div className={`fixed right-6 top-6 z-[9999] w-[90%] max-w-[420px] animate-in slide-in-from-top-2 overflow-hidden rounded-xl border-2 bg-white shadow-xl duration-300 ${activeAlert.type === 'attendance' ? 'border-red-500' : 'border-indigo-500'}`}>
          <div className={`flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4 ${activeAlert.type === 'attendance' ? 'bg-red-50' : 'bg-indigo-50'}`}>
            <div className="flex items-center gap-2.5">
              <span className="text-lg">
                {activeAlert.type === 'attendance' ? '⚠️' : '🔔'}
              </span>
              <strong className={`text-sm ${activeAlert.type === 'attendance' ? 'text-red-800' : 'text-indigo-800'}`}>
                {activeAlert.title}
              </strong>
            </div>
            <button
              onClick={() => setActiveAlert(null)}
              className="border-0 bg-transparent text-lg leading-none text-slate-500 hover:text-slate-800"
              aria-label="Dismiss alert"
            >
              ×
            </button>
          </div>
          <div className="p-5">
            <p className="m-0 whitespace-pre-line text-[13px] leading-relaxed text-slate-700">
              {activeAlert.body}
            </p>
            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs text-slate-400">Received {activeAlert.timestamp}</span>
              <button
                onClick={() => setActiveAlert(null)}
                className="cursor-pointer rounded-md border border-slate-300 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Keep notification opt-in available without displacing page content. */}
      {permission !== 'granted' && (
        <aside className="fixed bottom-5 right-5 z-50 flex max-w-md items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-xl">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-50 text-indigo-600"><Icon name="bell" size={17} /></span>
          <div className="min-w-0 flex-1">
            <strong className="text-sm font-semibold text-slate-900">{permission === 'denied' ? 'Desktop alerts are blocked' : 'Get class reminders'}</strong>
            <p className="mt-1 text-xs leading-relaxed text-slate-600">{permission === 'denied' ? 'Allow notifications in your browser settings to receive attendance and class reminders.' : 'Optional reminders for attendance warnings and upcoming classes.'}</p>
          </div>
          {permission !== 'denied' && (
            <button className="shrink-0 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50" onClick={handleEnableAlerts} disabled={busy}>
              {busy ? 'Enabling…' : 'Enable alerts'}
            </button>
          )}
        </aside>
      )}
    </>
  );
}
