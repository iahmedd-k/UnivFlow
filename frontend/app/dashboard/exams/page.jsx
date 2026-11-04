'use client';

import { useAuth } from '@clerk/nextjs';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import { getQueryOwnerKey } from '@/app/lib/manual-auth';
import ExamTools from './ExamTools';

export default function ExamsPage() {
  const { getToken, userId } = useAuth();
  const ownerKey = getQueryOwnerKey(userId);
  const queryClient = useQueryClient();
  const examsQuery = useQuery({
    queryKey: ['exams', ownerKey, 'list', 500, 0],
    queryFn: async ({ signal }) => api.getExams(await api.getRequestToken(getToken), null, { signal, direct: true }),
  });
  const materialsQuery = useQuery({
    queryKey: ['rag', ownerKey, 'documents', 'all'],
    queryFn: async ({ signal }) => {
      const response = await api.getRagDocuments(await api.getRequestToken(getToken), { signal, direct: true });
      return response?.data || response || [];
    },
    refetchInterval: (query) => query.state.data?.some((item) => ['processing', 'pending', 'indexing'].includes(String(item.status || '').toLowerCase())) ? 5000 : false,
  });
  const exams = examsQuery.data || [];
  const materials = materialsQuery.data || [];
  const error = examsQuery.error?.message || materialsQuery.error?.message;
  const slipDetails = (status) => { try { return status?.startsWith('{') ? JSON.parse(status) : {}; } catch { return {}; } };

  return <main className="mx-auto w-full max-w-none pb-8 text-ink">
    <header className="flex flex-col gap-2 border-b border-line pb-3 sm:flex-row sm:items-end sm:justify-between">
      <div><h1 className="text-2xl font-semibold tracking-tight">Exams</h1></div>
      <span className="inline-flex w-fit items-center rounded-full bg-violet-light px-3 py-1.5 text-sm font-semibold text-violet-dark">{exams.length} saved exam{exams.length === 1 ? '' : 's'}</span>
    </header>
    {error && <div className="mt-4 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}<button type="button" className="ml-2 font-semibold underline" onClick={() => { examsQuery.refetch(); materialsQuery.refetch(); }}>Retry</button></div>}
    <ExamTools materials={materials} ownerKey={ownerKey} onSaved={() => queryClient.invalidateQueries({ queryKey: ['exams', ownerKey] })} />
    <section className="mt-4 rounded-xl border border-line bg-white p-4">
      <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">Saved exams</h2>{examsQuery.isPending && <span className="text-sm text-muted">Loading…</span>}</div>
      {exams.length ? <div className="mt-4 divide-y divide-line rounded-lg border border-line">{exams.map((exam) => { const details = slipDetails(exam.status); return <article key={exam.id} className="p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-semibold">{exam.title}</h3><p className="mt-1 text-sm text-muted">{exam.date ? format(new Date(exam.date), 'EEE, MMM d, yyyy') : 'Date TBA'} · {exam.time || 'Time TBA'} · {exam.room || 'Room TBA'}</p></div>{details.source === 'roll_no_slip' && <span className="rounded-full bg-violet-light px-2.5 py-1 text-xs font-semibold text-violet-dark">Roll no slip</span>}</div>{(details.seating_plan || details.instructions) && <dl className="mt-3 grid gap-2 border-t border-line pt-3 text-sm sm:grid-cols-2">{details.seating_plan && <div><dt className="font-semibold">Seating plan</dt><dd className="text-muted">{details.seating_plan}</dd></div>}{details.instructions && <div><dt className="font-semibold">Instructions</dt><dd className="text-muted">{details.instructions}</dd></div>}</dl>}</article>; })}</div> : <p className="mt-4 rounded-lg bg-paper p-4 text-sm text-muted">No saved exams yet. Upload your roll number slip above to get started.</p>}
    </section>
  </main>;
}
