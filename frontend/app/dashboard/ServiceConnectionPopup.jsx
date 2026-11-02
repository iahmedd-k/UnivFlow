'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '@clerk/nextjs';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/app/lib/api';
import { getManualSession } from '@/app/lib/manual-auth';
import {
  isExtensionInstalled,
  autoSyncAllServicesViaExtension,
} from '@/app/lib/extensionBridge';
import Icon from '@/app/dashboard/Icon';

const AUTO_DISMISS_SECONDS = 5;

export default function ServiceConnectionPopup() {
  const { userId, getToken } = useAuth();
  const queryClient = useQueryClient();

  const [isOpen, setIsOpen] = useState(true);
  const [isMinimized, setIsMinimized] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [status, setStatus] = useState(null);
  const [syncNotice, setSyncNotice] = useState('');
  const [countdown, setCountdown] = useState(AUTO_DISMISS_SECONDS);
  const [keepOpen, setKeepOpen] = useState(false);

  const countdownTimerRef = useRef(null);
  const autoSyncedRef = useRef(false);

  const shouldAutoDismiss = Boolean(isOpen && !isMinimized && status?.all_connected && !syncing && !keepOpen);
  const isAutoDismissing = shouldAutoDismiss && countdown > 0;

  // Helper to fetch services status
  const fetchStatus = useCallback(async () => {
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.getServicesStatus(token);
      setStatus(res);
      return res;
    } catch (err) {
      console.warn('Could not fetch services status:', err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  // Run auto-reconnect if any service needs reconnect
  const triggerAutoReconnect = useCallback(
    async (currentStatus) => {
      const needsGcr = !currentStatus?.services?.google_classroom?.connected;
      const needsClaude = !currentStatus?.services?.claude?.connected;
      const needsPortal = !currentStatus?.services?.portal?.connected;

      if (!needsGcr && !needsClaude && !needsPortal) {
        return;
      }

      const hasExt = isExtensionInstalled();
      if (!hasExt) {
        setSyncNotice('Companion extension not detected in this browser profile.');
        return;
      }

      setSyncing(true);
      setSyncNotice('Auto-reconnecting services via companion extension…');

      try {
        const token = getToken ? await getToken() : null;
        await autoSyncAllServicesViaExtension({
          token,
          syncGcr: needsGcr,
          syncClaude: needsClaude,
          syncPortal: needsPortal,
          forceClaude: true,
          forcePortal: true,
          autoVisit: false,
        });

        // Refresh status after extension sync
        const freshStatus = await fetchStatus();
        queryClient.invalidateQueries({ queryKey: ['classroom'] });
        queryClient.invalidateQueries({ queryKey: ['portal'] });

        if (freshStatus?.all_connected) {
          setSyncNotice('All services connected successfully!');
        } else {
          setSyncNotice('Some services require an active session in your browser.');
        }
      } catch (err) {
        console.warn('Auto-sync error:', err);
        setSyncNotice(err?.message || 'Auto-reconnect encountered an issue.');
      } finally {
        setSyncing(false);
      }
    },
    [fetchStatus, getToken, queryClient]
  );

  // Initialize on mount: check if this login session has already shown the popup
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const manual = getManualSession();
    const effectiveUid = userId || manual?.user?.id || 'guest_student';
    const sessionKey = `uniflow_login_services_popup_shown_${effectiveUid}`;
    sessionStorage.setItem(sessionKey, 'true');

    // Initial status fetch and auto-reconnect
    (async () => {
      setLoading(true);
      const initialStatus = await fetchStatus();
      if (initialStatus && !initialStatus.all_connected && !autoSyncedRef.current) {
        autoSyncedRef.current = true;
        await triggerAutoReconnect(initialStatus);
      }
    })();
  }, [userId, fetchStatus, triggerAutoReconnect]);

  // Listen for custom trigger event from navbar or anywhere in app
  useEffect(() => {
    const handleOpen = () => {
      setIsOpen(true);
      setIsMinimized(false);
      setKeepOpen(false);
      setCountdown(AUTO_DISMISS_SECONDS);
      if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
      fetchStatus();
    };

    window.addEventListener('uniflow-open-services-popup', handleOpen);
    return () => window.removeEventListener('uniflow-open-services-popup', handleOpen);
  }, [fetchStatus]);

  // Auto-dismiss countdown when all services are connected
  useEffect(() => {
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }

    if (shouldAutoDismiss) {
      countdownTimerRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(countdownTimerRef.current);
            setIsMinimized(true);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }

    return () => {
      if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
    };
  }, [shouldAutoDismiss]);

  // Manual re-sync action
  const handleManualResync = async () => {
    if (syncing) return;
    setIsAutoDismissing(false);
    if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);

    setSyncing(true);
    setSyncNotice('Re-checking & fetching cookies…');
    try {
      const token = getToken ? await getToken() : null;
      await autoSyncAllServicesViaExtension({
        token,
        syncGcr: true,
        syncClaude: true,
        syncPortal: true,
        forceClaude: true,
        forcePortal: true,
        autoVisit: false,
      });
      await fetchStatus();
      queryClient.invalidateQueries({ queryKey: ['classroom'] });
      queryClient.invalidateQueries({ queryKey: ['portal'] });
      setSyncNotice('Sync completed.');
    } catch (err) {
      setSyncNotice(err?.message || 'Sync failed.');
    } finally {
      setSyncing(false);
    }
  };

  const handleConnectGoogle = async () => {
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.getGoogleAuthUrl(token, '/dashboard');
      if (res?.auth_url) window.location.assign(res.auth_url);
    } catch (err) {
      alert(err.message || 'Could not connect Google Classroom.');
    }
  };

  const handleOpenClaude = () => {
    window.open('https://claude.ai', '_blank', 'noopener,noreferrer');
  };

  const handleOpenPortal = () => {
    window.open('https://portals.au.edu.pk/students/', '_blank', 'noopener,noreferrer');
  };

  if (!isOpen) return null;

  // Minimized Floating Pill View (bottom right)
  if (isMinimized) {
    const allOk = Boolean(status?.all_connected);
    const count = status?.connected_count ?? 0;
    const total = status?.total_services ?? 3;

    return (
      <aside aria-label="Services Status Widget" className="fixed bottom-5 right-5 z-50">
        <button
          type="button"
          onClick={() => {
            setIsMinimized(false);
            setIsAutoDismissing(false);
            fetchStatus();
          }}
          className={`flex items-center gap-2.5 px-3.5 py-2 rounded-full border shadow-lg backdrop-blur-md transition-all cursor-pointer hover:scale-105 active:scale-95 ${
            allOk
              ? 'bg-surface/95 border-emerald-500/30 text-emerald-600 shadow-emerald-500/10'
              : 'bg-surface/95 border-amber-500/30 text-amber-600 shadow-amber-500/10 animate-pulse'
          }`}
          title="Click to view Services Status"
        >
          <span
            className={`size-2 rounded-full ${
              allOk ? 'bg-emerald-500 shadow-sm shadow-emerald-500/50' : 'bg-amber-500 shadow-sm shadow-amber-500/50'
            }`}
          />
          <span className="text-xs font-semibold text-heading">
            Services: {count}/{total}
          </span>
          <span className="text-[11px] text-muted font-normal">
            {allOk ? 'Connected' : 'Needs attention'}
          </span>
          <Icon name="arrowUpRight" size={13} className="text-subtle ml-0.5" />
        </button>
      </aside>
    );
  }

  // Expanded Short Popup View
  const gcrOk = Boolean(status?.services?.google_classroom?.connected);
  const claudeOk = Boolean(status?.services?.claude?.connected);
  const portalOk = Boolean(status?.services?.portal?.connected);
  const allOk = Boolean(status?.all_connected);
  const connectedCount = status?.connected_count ?? (gcrOk ? 1 : 0) + (claudeOk ? 1 : 0) + (portalOk ? 1 : 0);

  return (
    <aside aria-label="Connected Services Dialog" className="fixed bottom-5 right-5 z-50 w-92 max-w-[calc(100vw-2.5rem)] animate-in fade-in slide-in-from-bottom-4 duration-200">
      <div className="rounded-2xl border border-line bg-surface/95 p-4.5 shadow-2xl backdrop-blur-xl ring-1 ring-black/5">
        {/* Top Header */}
        <div className="flex items-center justify-between gap-2 pb-3 border-b border-line/60">
          <div className="flex items-center gap-2.5">
            <div
              className={`size-7 rounded-lg flex items-center justify-center text-xs font-bold ${
                allOk
                  ? 'bg-emerald-50 text-emerald-600 ring-1 ring-emerald-500/20'
                  : 'bg-amber-50 text-amber-600 ring-1 ring-amber-500/20'
              }`}
            >
              <Icon name={allOk ? 'checkCircle' : 'refresh'} size={15} className={syncing ? 'animate-spin' : ''} />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-heading leading-tight flex items-center gap-1.5">
                <span>Services Status</span>
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${
                    allOk ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
                  }`}
                >
                  {connectedCount}/3 Connected
                </span>
              </h2>
              <p className="text-[11px] text-muted leading-none mt-0.5">
                {syncing
                  ? 'Auto-reconnecting services…'
                  : allOk
                  ? 'All services active and ready'
                  : 'Auto-fetching cookies & sessions'}
              </p>
            </div>
          </div>

          {/* Window Controls */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setIsMinimized(true)}
              className="size-7 grid place-items-center rounded-lg text-muted hover:text-heading hover:bg-surface-secondary transition cursor-pointer"
              title="Minimize to pill"
              aria-label="Minimize"
            >
              <span className="block w-2.5 h-0.5 bg-current rounded-full" />
            </button>
            <button
              type="button"
              onClick={() => {
                setIsOpen(false);
                if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
              }}
              className="size-7 grid place-items-center rounded-lg text-muted hover:text-heading hover:bg-surface-secondary transition cursor-pointer"
              title="Close popup"
              aria-label="Close"
            >
              <Icon name="close" size={14} />
            </button>
          </div>
        </div>

        {/* Status Notice if any */}
        {syncNotice && (
          <div className="mt-2.5 px-2.5 py-1.5 rounded-lg bg-surface-secondary border border-line text-[11px] text-body flex items-center justify-between gap-2">
            <span className="truncate">{syncNotice}</span>
            {syncing && <span className="size-2 rounded-full bg-violet animate-ping shrink-0" />}
          </div>
        )}

        {/* Service Rows */}
        <div className="mt-3 space-y-2">
          {/* Google Classroom */}
          <div className="flex items-center justify-between p-2 rounded-xl bg-surface-secondary/60 border border-line/40">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="size-6 rounded-md bg-violet/10 text-violet flex items-center justify-center shrink-0">
                <Icon name="school" size={13} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-heading truncate">Google Classroom</p>
                <p className="text-[10px] text-muted truncate">
                  {gcrOk ? (status?.services?.google_classroom?.email || 'Synced') : 'Needs connection'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {gcrOk ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200/60">
                  <Icon name="check" size={11} strokeWidth={2.5} />
                  <span>Ready</span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleConnectGoogle}
                  className="text-[11px] font-semibold text-violet hover:text-violet-dark hover:underline cursor-pointer"
                >
                  Connect
                </button>
              )}
            </div>
          </div>

          {/* University Portal */}
          <div className="flex items-center justify-between p-2 rounded-xl bg-surface-secondary/60 border border-line/40">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="size-6 rounded-md bg-cyan-500/10 text-cyan-600 flex items-center justify-center shrink-0">
                <Icon name="globe" size={13} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-heading truncate">University Portal</p>
                <p className="text-[10px] text-muted truncate">
                  {portalOk ? 'Attendance & Timetable Active' : 'Disconnected'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {portalOk ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200/60">
                  <Icon name="check" size={11} strokeWidth={2.5} />
                  <span>Ready</span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleOpenPortal}
                  className="text-[11px] font-semibold text-cyan-600 hover:text-cyan-700 hover:underline cursor-pointer inline-flex items-center gap-0.5"
                  title="Open Portal login in new tab"
                >
                  <span>Open Portal</span>
                  <Icon name="arrowUpRight" size={10} />
                </button>
              )}
            </div>
          </div>

          {/* Claude AI Solver */}
          <div className="flex items-center justify-between p-2 rounded-xl bg-surface-secondary/60 border border-line/40">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="size-6 rounded-md bg-amber-500/10 text-amber-600 flex items-center justify-center shrink-0">
                <Icon name="brain" size={13} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-semibold text-heading truncate">Claude AI Solver</p>
                <p className="text-[10px] text-muted truncate">
                  {claudeOk ? 'Zero-latency Engine Active' : 'Disconnected'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {claudeOk ? (
                <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200/60">
                  <Icon name="check" size={11} strokeWidth={2.5} />
                  <span>Ready</span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={handleOpenClaude}
                  className="text-[11px] font-semibold text-amber-600 hover:text-amber-700 hover:underline cursor-pointer inline-flex items-center gap-0.5"
                  title="Open Claude in new tab"
                >
                  <span>Open Claude</span>
                  <Icon name="arrowUpRight" size={10} />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="mt-3.5 pt-2.5 border-t border-line/60 flex items-center justify-between gap-2">
          {/* Re-sync Button */}
          <button
            type="button"
            disabled={syncing || loading}
            onClick={handleManualResync}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-line bg-surface hover:bg-surface-secondary text-xs font-medium text-heading transition disabled:opacity-50 cursor-pointer"
          >
            <Icon name="refresh" size={12} className={syncing ? 'animate-spin text-violet' : 'text-muted'} />
            <span>{syncing ? 'Syncing…' : 'Re-sync All'}</span>
          </button>

          {/* Right Status / Auto-dismiss counter */}
          {isAutoDismissing ? (
            <div className="flex items-center gap-2 text-[11px] text-muted">
              <span>Auto-minimizing ({countdown}s)</span>
              <button
                type="button"
                onClick={() => {
                  setKeepOpen(true);
                  if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
                }}
                className="font-semibold text-violet hover:underline cursor-pointer"
              >
                Keep Open
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setIsMinimized(true)}
              className="text-xs font-semibold text-violet hover:underline cursor-pointer"
            >
              Done
            </button>
          )}
        </div>

        {/* Auto-dismiss progress bar */}
        {isAutoDismissing && (
          <div className="mt-2 h-1 w-full rounded-full bg-line overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all duration-1000 ease-linear rounded-full"
              style={{ width: `${(countdown / AUTO_DISMISS_SECONDS) * 100}%` }}
            />
          </div>
        )}
      </div>
    </aside>
  );
}

