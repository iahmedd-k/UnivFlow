'use client';

import { useAuth } from '@clerk/nextjs';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import Icon from '@/app/dashboard/Icon';

export default function QuizzesPage() {
  const { getToken, userId } = useAuth();
  const ownerKey = getQueryOwnerKey(userId);
  const quizzesQuery = useQuery({
    queryKey: ['quizzes', ownerKey, 'list', 500, 0],
    queryFn: async ({ signal }) => api.getQuizzes(await api.getRequestToken(getToken), null, { signal, direct: true }),
  });
  const quizzes = quizzesQuery.data || [];
  const loading = quizzesQuery.isPending;
  const error = quizzesQuery.error?.message;

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading quizzes…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}<button type="button" className="ml-2 font-semibold underline" onClick={() => quizzesQuery.refetch()}>Retry</button></div>;

  return (
    <main className="mx-auto flex w-full max-w-none flex-col gap-4 pb-8 text-ink">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Quizzes</h1>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-line bg-white shadow-sm" aria-label="Quizzes">
        {quizzes.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted">
            No quizzes scheduled.
          </div>
        ) : (
          <div className="divide-y divide-line">
            {quizzes.map((quiz) => (
              <Link
                key={quiz.id}
                href={`/dashboard/quizzes/${quiz.id}`}
                className="flex flex-col gap-4 px-5 py-4 transition-colors hover:bg-paper sm:flex-row sm:items-center sm:justify-between sm:px-6"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-3">
                    <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="help" size={18}/></div>
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate text-base font-semibold text-ink">{quiz.title}</h2>
                      <p className="mt-1 text-sm text-muted">
                        {quiz.date ? format(new Date(quiz.date), 'MMMM d, yyyy') : 'TBA'} • {quiz.time || 'TBA'} • {quiz.room || 'TBA'}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
                    quiz.date && new Date(quiz.date) < new Date() ? 'bg-neutral-100 text-neutral-700' : 'bg-violet-light text-violet-dark'
                  }`}>
                    {quiz.date && new Date(quiz.date) < new Date() ? 'Completed' : 'Upcoming'}
                  </span>
                  <Icon name="arrowUpRight" size={16} className="text-muted" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
