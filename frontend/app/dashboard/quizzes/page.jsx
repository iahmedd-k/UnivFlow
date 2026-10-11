'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function QuizzesPage() {
  const { getToken } = useAuth();
  const [quizzes, setQuizzes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getQuizzes(token);
        setQuizzes(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken]);

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading quizzes…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}</div>;

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-ink">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">Study & coursework</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Quizzes</h1>
          <p className="mt-1 text-sm text-muted">View and track your quizzes</p>
        </div>
      </header>

      <section className="overflow-hidden rounded-xl border border-line bg-white shadow-sm" aria-label="Quizzes">
        {quizzes.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted">
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
