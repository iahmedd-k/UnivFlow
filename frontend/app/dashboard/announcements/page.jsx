'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function AnnouncementsPage() {
  const { getToken } = useAuth();
  const [announcements, setAnnouncements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getAnnouncements(token);
        setAnnouncements(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken]);

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading announcements…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}</div>;

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-ink">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Activity & updates</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Announcements</h1>
          <p className="mt-1 text-sm text-muted">Class announcements and updates</p>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-line bg-white shadow-sm" aria-label="Announcements">
        {announcements.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted">
            No announcements.
          </div>
        ) : (
          <div className="divide-y divide-line">
            {announcements.map((ann) => (
              <Link
                key={ann.id}
                href={`/dashboard/announcements/${ann.id}`}
                className="block px-5 py-4 transition-colors hover:bg-paper sm:px-6"
              >
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <h2 className="truncate text-base font-semibold text-ink">{ann.title}</h2>
                    <p className="mt-1 text-sm text-muted">
                      {ann.published_at ? format(new Date(ann.published_at), 'MMM d, yyyy h:mm a') : 'Unknown date'} • {ann.source || 'Unknown'}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="rounded-full bg-violet-light px-3 py-1.5 text-xs font-semibold text-violet-dark">
                      {ann.source || 'Announcement'}
                    </span>
                    <Icon name="arrowUpRight" size={16} className="text-muted" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
