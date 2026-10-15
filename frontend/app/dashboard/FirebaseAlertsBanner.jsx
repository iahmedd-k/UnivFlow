'use client';

import { useEffect, useState } from 'react';
import { requestNotificationPermission, onMessageListener, isFirebaseConfigured } from '@/app/lib/firebase';
import Icon from '@/app/dashboard/Icon';

export default function FirebaseAlertsBanner() {
  if (!isFirebaseConfigured) return null;

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

  const isAttendance = activeAlert?.type === 'attendance';

  return (
    <>
      {/* Real-time Floating In-App Alert Toast */}
      {activeAlert && (
        <div className={`fixed right-6 top-6 z-[9999] w-[90%] max-w-md animate-in slide-in-from-top-2 overflow-hidden rounded-xl border-2 bg-surface shadow-xl duration-300 ${isAttendance ? 'border-rose' : 'border-violet'}`}>
          <div className={`flex items-center justify-between gap-3 border-b px-4 py-3 ${isAttendance ? 'border-rose-border bg-rose-bg' : 'border-violet/20 bg-violet-light'}`}>
            <div className="flex items-center gap-2.5">
              <span className="text-lg">
                {isAttendance ? '⚠️' : '🔔'}
              </span>
              <strong className={`text-sm ${isAttendance ? 'text-rose' : 'text-violet-dark'}`}>
                {activeAlert.title}
              </strong>
            </div>
            <button
              onClick={() => setActiveAlert(null)}
              className="border-0 bg-transparent text-lg leading-none text-muted hover:text-ink"
              aria-label="Dismiss alert"
            >
              ×
            </button>
          </div>
          <div className="p-4">
            <p className="m-0 whitespace-pre-line text-sm leading-relaxed text-body">
              {activeAlert.body}
            </p>
            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs text-subtle">Received {activeAlert.timestamp}</span>
              <button
                onClick={() => setActiveAlert(null)}
                className="cursor-pointer rounded-md border border-border-input bg-surface-secondary px-3 py-1 text-xs font-medium text-nav hover:bg-surface-hover"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Keep notification opt-in available without displacing page content. */}
      {permission !== 'granted' && (
        <aside className="fixed bottom-5 right-5 z-50 flex max-w-md items-start gap-3 rounded-xl border border-border bg-surface p-4 shadow-xl">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="bell" size={17} /></span>
          <div className="min-w-0 flex-1">
            <strong className="text-sm font-semibold text-ink">{permission === 'denied' ? 'Desktop alerts are blocked' : 'Get class reminders'}</strong>
            <p className="mt-1 text-xs leading-relaxed text-muted">{permission === 'denied' ? 'Allow notifications in your browser settings to receive attendance and class reminders.' : 'Optional reminders for attendance warnings and upcoming classes.'}</p>
          </div>
          {permission !== 'denied' && (
            <button className="shrink-0 rounded-lg bg-violet px-3 py-2 text-xs font-semibold text-white hover:bg-violet-dark disabled:opacity-50" onClick={handleEnableAlerts} disabled={busy}>
              {busy ? 'Enabling…' : 'Enable alerts'}
            </button>
          )}
        </aside>
      )}
    </>
  );
}
