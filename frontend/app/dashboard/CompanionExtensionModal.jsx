'use client';

import { useState, useEffect } from 'react';
import { isExtensionInstalled, syncGcrViaExtension, EXTENSION_VERSION } from '@/app/lib/extensionBridge';
import Icon from '@/app/dashboard/Icon';

export function ExtensionSetupBox({ onSynced, token, className = '' }) {
  const [installed, setInstalled] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncNotice, setSyncNotice] = useState('');
  const [syncError, setSyncError] = useState('');

  useEffect(() => {
    setInstalled(isExtensionInstalled());
    const onReady = () => setInstalled(true);
    window.addEventListener('uniflow-companion-ready', onReady);
    const interval = setInterval(() => {
      if (isExtensionInstalled()) {
        setInstalled(true);
        clearInterval(interval);
      }
    }, 1200);
    return () => {
      window.removeEventListener('uniflow-companion-ready', onReady);
      clearInterval(interval);
    };
  }, []);

  const handleCopyUrl = async () => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText('chrome://extensions');
      }
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2200);
    } catch (_) {}
  };

  const handleQuickSync = async () => {
    setSyncing(true);
    setSyncNotice('');
    setSyncError('');
    try {
      const res = await syncGcrViaExtension({ token });
      setSyncNotice(res?.message || 'Google Classroom and university cookies synced successfully!');
      if (onSynced) onSynced(res);
    } catch (err) {
      setSyncError(err?.message || 'Could not sync sessions. Ensure you are signed into your student accounts in Chrome.');
    } finally {
      setSyncing(false);
    }
  };

  if (installed) {
    return (
      <div className={`rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/5 via-surface to-emerald-500/10 p-5 shadow-sm ${className}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-emerald-500/10 text-emerald-600 ring-1 ring-emerald-500/20">
              <Icon name="checkCircle" size={20} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-heading">Companion Extension Active</h4>
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold text-emerald-700">v{EXTENSION_VERSION}</span>
              </div>
              <p className="text-xs text-muted">Direct Chrome profile integration active. Cookies sync automatically with zero password prompts.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleQuickSync}
            disabled={syncing}
            className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-emerald-600 px-3.5 text-xs font-semibold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50 cursor-pointer"
          >
            <Icon name="refresh" size={13} className={syncing ? 'animate-spin' : ''} />
            <span>{syncing ? 'Syncing...' : '1-Click Sync Now'}</span>
          </button>
        </div>

        {syncNotice && (
          <div className="mt-3 flex items-center gap-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-3 py-2 text-xs text-emerald-800">
            <Icon name="checkCircle" size={14} className="shrink-0 text-emerald-600" />
            <span>{syncNotice}</span>
          </div>
        )}
        {syncError && (
          <div className="mt-3 flex items-center gap-2 rounded-xl bg-rose-50 border border-rose-200 px-3 py-2 text-xs text-rose-700">
            <Icon name="alert" size={14} className="shrink-0" />
            <span>{syncError}</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`rounded-2xl border border-violet/25 bg-gradient-to-br from-violet/5 via-surface to-violet/10 p-5 shadow-sm ${className}`}>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light pb-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-violet/10 text-violet ring-1 ring-violet/25">
            <Icon name="download" size={20} />
          </span>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-semibold text-heading">Uniflow Companion Extension</h4>
              <span className="rounded-full bg-violet-light px-2 py-0.5 text-[10px] font-bold text-violet-dark">Setup Needed</span>
            </div>
            <p className="text-xs text-muted">Captures your active university cookies locally. Zero passwords required.</p>
          </div>
        </div>
        <a
          href="/uniflow-companion.zip"
          download="uniflow-companion.zip"
          className="inline-flex h-9 items-center gap-2 rounded-xl bg-violet px-4 text-xs font-semibold text-white shadow-sm transition hover:bg-violet-dark hover:-translate-y-px cursor-pointer"
        >
          <Icon name="download" size={14} />
          <span>Download Extension (.zip)</span>
        </a>
      </div>

      {/* 3 Step Visual Guide */}
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        {/* Step 1 */}
        <div className="flex flex-col gap-1.5 rounded-xl border border-border/80 bg-surface/90 p-3.5">
          <div className="flex items-center gap-2">
            <span className="grid size-6 place-items-center rounded-lg bg-violet text-white text-xs font-bold">1</span>
            <strong className="text-xs font-bold text-heading">Download & Unzip</strong>
          </div>
          <p className="text-[11px] text-muted leading-relaxed">
            Click <strong>Download Extension (.zip)</strong>. Right-click the file in Downloads and choose <em>&quot;Extract All&quot;</em>.
          </p>
        </div>

        {/* Step 2 */}
        <div className="flex flex-col gap-1.5 rounded-xl border border-border/80 bg-surface/90 p-3.5">
          <div className="flex items-center gap-2">
            <span className="grid size-6 place-items-center rounded-lg bg-violet text-white text-xs font-bold">2</span>
            <strong className="text-xs font-bold text-heading">Open Extensions</strong>
          </div>
          <p className="text-[11px] text-muted leading-relaxed">
            Go to <code className="rounded bg-paper px-1 py-0.5 font-mono text-[10px] border border-border">chrome://extensions</code> and switch <strong>Developer mode</strong> ON in the top-right corner.
          </p>
          <button
            type="button"
            onClick={handleCopyUrl}
            className="mt-1 inline-flex w-fit items-center gap-1 rounded-md border border-border bg-surface px-2 py-0.5 text-[10px] font-semibold text-muted hover:text-heading cursor-pointer transition"
          >
            <Icon name={copiedUrl ? 'check' : 'copy'} size={11} />
            <span>{copiedUrl ? 'Copied URL!' : 'Copy chrome://extensions'}</span>
          </button>
        </div>

        {/* Step 3 */}
        <div className="flex flex-col gap-1.5 rounded-xl border border-border/80 bg-surface/90 p-3.5">
          <div className="flex items-center gap-2">
            <span className="grid size-6 place-items-center rounded-lg bg-violet text-white text-xs font-bold">3</span>
            <strong className="text-xs font-bold text-heading">Click &quot;Load unpacked&quot;</strong>
          </div>
          <p className="text-[11px] text-muted leading-relaxed">
            Click top-left <strong>Load unpacked</strong> and select the unzipped folder. Uniflow detects it immediately!
          </p>
        </div>
      </div>

      {/* Detection Live Ping Footer */}
      <div className="mt-3.5 flex items-center justify-between rounded-xl bg-surface/80 border border-violet/20 px-3.5 py-2 text-[11px] text-violet-dark">
        <span className="flex items-center gap-2">
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-violet opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-violet" />
          </span>
          <span>Waiting for extension detection in Chrome...</span>
        </span>
        <span className="text-[10px] text-muted font-medium">100% Free · No Google bot blocks</span>
      </div>
    </div>
  );
}

export default function CompanionExtensionModal({ isOpen, onClose, token }) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-xs p-4 animate-in fade-in duration-150">
      <div className="relative w-full max-w-2xl rounded-2xl bg-surface border border-border shadow-2xl p-6 overflow-hidden">
        <div className="flex items-center justify-between pb-3 border-b border-border-light mb-4">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-xl bg-violet-light text-violet font-bold text-sm">U</span>
            <div>
              <h3 className="text-base font-bold text-heading">Companion Extension Setup</h3>
              <p className="text-xs text-muted">Required for automated Google Classroom and Portal cookie syncing</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid size-8 place-items-center rounded-lg text-muted hover:text-heading hover:bg-surface-secondary transition cursor-pointer"
          >
            <Icon name="close" size={16} />
          </button>
        </div>

        <ExtensionSetupBox token={token} />

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-border bg-surface px-4 py-2 text-xs font-semibold text-heading hover:bg-surface-secondary transition cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
