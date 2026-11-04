'use client';

import { useParams } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

export default function AnnouncementDetailPage() {
  const params = useParams();
  const { getToken, userId } = useAuth();
  const announcementId = params.id;
  const ownerKey = getQueryOwnerKey(userId);
  const announcementsQuery = useQuery({
    queryKey: ['announcements', ownerKey, 'university'],
    queryFn: async ({ signal }) => api.getAnnouncements(await api.getRequestToken(getToken), null, { signal, direct: true }),
  });
  const announcement = (announcementsQuery.data || []).find((item) => String(item.id) === String(announcementId)) || null;
  const loading = announcementsQuery.isPending;
  const error = announcementsQuery.error?.message;

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading announcement…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}<button type="button" className="ml-2 font-semibold underline" onClick={() => announcementsQuery.refetch()}>Retry</button></div>;
  if (!announcement) return <div className="rounded-xl border border-line bg-white p-8 text-center text-sm text-muted">Announcement not found</div>;

  const publishedAt = announcement.published_at ? format(new Date(announcement.published_at), 'MMMM d, yyyy \'at\' h:mm a') : 'Unknown';

  return (
    <main className="mx-auto flex w-full max-w-none flex-col gap-4 pb-8 text-ink">
      <header className="flex items-center gap-4">
        <Link href="/dashboard/announcements" className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-white text-muted transition hover:bg-paper hover:text-ink" aria-label="Back to announcements"><Icon name="arrowLeft" size={16}/></Link>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Activity & updates</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">{announcement.title}</h1>
          <p className="mt-1 text-sm text-muted">Announcement details</p>
        </div>
      </header>

      <article className="rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
        <div className="mb-5">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Published</p>
          <p className="text-sm text-ink">{publishedAt}</p>
        </div>

        <div className="mb-5">
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Source</p>
          <p className="text-sm font-medium text-ink">{announcement.source || 'Unknown'}</p>
        </div>

        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Content</p>
          <div className="whitespace-pre-wrap break-words rounded-lg bg-paper p-4 text-sm leading-6 text-ink">
            {announcement.content || 'No content'}
          </div>
        </div>

        {announcement.url && (
          <div className="mt-6 border-t border-line pt-5">
            <a href={announcement.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm font-semibold text-violet hover:text-violet-dark hover:underline">
              View in Google Classroom <Icon name="externalLink" size={13}/>
            </a>
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2 border-t border-line pt-5">
          <Link href="/dashboard/announcements" className="inline-flex min-h-10 items-center rounded-lg border border-line px-4 text-sm font-semibold text-ink transition hover:bg-paper">
            Back to Announcements
          </Link>
        </div>
      </article>
    </main>
  );
}
