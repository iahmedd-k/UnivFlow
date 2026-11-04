'use client';

import { useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

export default function AnnouncementsPage() {
  const { getToken, userId } = useAuth();
  const ownerKey = getQueryOwnerKey(userId);
  const announcementsQuery = useQuery({
    queryKey: ['announcements', ownerKey, 'university'],
    queryFn: async ({ signal }) => api.getAnnouncements(await api.getRequestToken(getToken), null, { signal, direct: true }),
  });
  const announcements = Array.isArray(announcementsQuery.data) ? announcementsQuery.data : [];
  const loading = announcementsQuery.isPending;
  const error = announcementsQuery.error?.message;

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading announcements…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}<button type="button" className="ml-2 font-semibold underline" onClick={() => announcementsQuery.refetch()}>Retry</button></div>;

  return (
    <main className="mx-auto flex w-full max-w-none flex-col gap-4 pb-8 text-ink">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Announcements</h1>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-line bg-white shadow-sm" aria-label="Announcements">
        {announcements.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted">
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
