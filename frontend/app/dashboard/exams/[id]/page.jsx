'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';

export default function ExamDetailPage() {
  const params = useParams();
  const { getToken } = useAuth();
  const examId = params.id;
  const [exam, setExam] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getExams(token);
        const found = data.find(e => e.id == examId);
        if (!found) throw new Error('Exam not found');
        setExam(found);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [examId, getToken]);

  if (loading) return <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5"><div className="rounded-xl border border-neutral-200 bg-white px-5 py-8 text-center text-xs text-neutral-500">Loading exam details…</div></main>;
  if (error) return <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5"><div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-800">{error}</div></main>;
  if (!exam) return <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5"><div className="rounded-xl border border-neutral-200 bg-white px-5 py-8 text-center text-xs text-neutral-500">Exam not found</div></main>;

  const examDate = exam.date ? format(new Date(exam.date), 'MMMM d, yyyy') : 'TBA';
  const examTime = exam.time || 'TBA';
  const isPast = exam.date && new Date(exam.date) < new Date();

  return (
    <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">EXAM DETAILS</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">{exam.title}</h1><p className="mt-1 text-xs text-[#858998]">Review the date and location, then prepare from the exam list.</p></div><span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${isPast ? 'bg-[#f1f1f6] text-[#6e7281]' : 'bg-[#eaf7f1] text-[#438a71]'}`}>{isPast ? 'Completed' : 'Upcoming'}</span></header>
      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3">{[[ 'Date', examDate ], [ 'Time', examTime ], [ 'Room', exam.room || 'TBA' ]].map(([label, value]) => <article className="rounded-xl border border-[#ededf2] bg-white p-4" key={label}><span className="block text-xs text-[#858998]">{label}</span><strong className="mt-2 block text-[22px] font-semibold text-[#343746]">{value}</strong></article>)}</section>
      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm"><header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">SCHEDULE STATUS</p><h2 className="text-[13px] font-semibold text-[#343746]">{exam.status || 'Scheduled'}</h2></div><Link href="/dashboard/exams" className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]">Back to exams</Link></header><div className="space-y-3 p-5"><p className="rounded-lg bg-[#f6f5ff] px-3 py-2.5 text-xs leading-relaxed text-[#77729b]">Use the Study Planner on the Exams page to paste your syllabus, select Classroom materials, and create a revision plan for this exam.</p><Link href="/dashboard/exams" className="inline-flex min-h-9 items-center justify-center rounded-md border border-[#6657d9] bg-[#6657d9] px-3 text-xs font-semibold text-white hover:bg-[#5142c1]">Open study planner</Link></div></section>
    </main>
  );
}
