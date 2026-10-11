'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function QuizDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { getToken } = useAuth();
  const quizId = params.id;
  const [quiz, setQuiz] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getQuizzes(token);
        const found = data.find(q => q.id == quizId);
        if (!found) throw new Error('Quiz not found');
        setQuiz(found);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [quizId, getToken]);

  if (loading) return <div className="flex min-h-64 items-center justify-center text-sm text-muted" role="status">Loading quiz…</div>;
  if (error) return <div className="rounded-lg border border-rose-border bg-rose-bg p-4 text-sm text-rose" role="alert">Error: {error}</div>;
  if (!quiz) return <div className="rounded-xl border border-line bg-white p-8 text-center text-sm text-muted">Quiz not found</div>;

  const quizDate = quiz.date ? format(new Date(quiz.date), 'MMMM d, yyyy') : 'TBA';
  const quizTime = quiz.time || 'TBA';
  const isPast = quiz.date && new Date(quiz.date) < new Date();

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-ink">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <Link href="/dashboard/quizzes" className="grid size-10 shrink-0 place-items-center rounded-lg border border-line bg-white text-muted transition hover:bg-paper hover:text-ink" aria-label="Back to quizzes"><Icon name="arrowLeft" size={16}/></Link>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Study & coursework</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">{quiz.title}</h1>
            <p className="mt-1 text-sm text-muted">Quiz details</p>
          </div>
        </div>
        <span className={`w-fit rounded-full px-3 py-1.5 text-xs font-semibold ${
          isPast ? 'bg-neutral-100 text-neutral-700' : 'bg-violet-light text-violet-dark'
        }`}>
          {isPast ? 'Completed' : 'Upcoming'}
        </span>
      </header>

      <section className="rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <div className="rounded-lg bg-paper p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Date</p>
            <p className="mt-1 text-sm font-semibold text-ink">{quizDate}</p>
          </div>
          <div className="rounded-lg bg-paper p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Time</p>
            <p className="mt-1 text-sm font-semibold text-ink">{quizTime}</p>
          </div>
          <div className="rounded-lg bg-paper p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Room</p>
            <p className="mt-1 text-sm font-semibold text-ink">{quiz.room || 'TBA'}</p>
          </div>
          <div className="rounded-lg bg-paper p-4 sm:col-span-2 lg:col-span-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">Status</p>
            <p className="mt-1 text-sm font-semibold capitalize text-ink">{quiz.status || 'scheduled'}</p>
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-line pt-5">
          <Link href="/dashboard/quizzes" className="inline-flex min-h-10 items-center rounded-lg border border-line px-4 text-sm font-semibold text-ink transition hover:bg-paper">
            Back to Quizzes
          </Link>
        </div>
      </section>
    </main>
  );
}
