'use client';

import { X } from 'lucide-react';

export default function HostedBrowserDialog({ url, onClose }) {
  if (!url) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-2 sm:p-5" role="dialog" aria-modal="true" aria-label="Google Classroom sign-in browser">
      <section className="flex h-[min(92dvh,900px)] w-full max-w-7xl flex-col overflow-hidden rounded-lg bg-white shadow-2xl">
        <header className="flex min-h-14 items-center justify-between gap-4 border-b border-line px-4 sm:px-5">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-ink">Google Classroom sign-in</h2>
            <p className="truncate text-xs text-muted">Sign in directly in your private server browser. Uniflow never receives your Google password.</p>
          </div>
          <button type="button" onClick={onClose} title="Close browser" aria-label="Close browser" className="inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted transition hover:bg-paper hover:text-ink">
            <X size={18} />
          </button>
        </header>
        <iframe key={url} src={url} title="Private Google Classroom browser" className="min-h-0 w-full flex-1 bg-[#151515]" allow="clipboard-read; clipboard-write" referrerPolicy="no-referrer" />
      </section>
    </div>
  );
}