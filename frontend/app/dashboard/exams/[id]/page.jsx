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

  if (loading) return <main className="product-page"><div className="product-empty">Loading exam details…</div></main>;
  if (error) return <main className="product-page"><div className="product-alert">{error}</div></main>;
  if (!exam) return <main className="product-page"><div className="product-empty">Exam not found</div></main>;

  const examDate = exam.date ? format(new Date(exam.date), 'MMMM d, yyyy') : 'TBA';
  const examTime = exam.time || 'TBA';
  const isPast = exam.date && new Date(exam.date) < new Date();

  return (
    <main className="product-page">
      <header className="product-heading"><div><p className="eyebrow">EXAM DETAILS</p><h1>{exam.title}</h1><p>Review the date and location, then prepare from the exam list.</p></div><span className={`product-pill ${isPast ? '' : 'success'}`}>{isPast ? 'Completed' : 'Upcoming'}</span></header>
      <section className="product-grid three"><article className="product-stat"><span>Date</span><strong>{examDate}</strong></article><article className="product-stat"><span>Time</span><strong>{examTime}</strong></article><article className="product-stat"><span>Room</span><strong>{exam.room || 'TBA'}</strong></article></section>
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">SCHEDULE STATUS</p><h2>{exam.status || 'Scheduled'}</h2></div><Link href="/dashboard/exams" className="product-action secondary">Back to exams</Link></header><div className="product-card-body"><p className="product-note">Use the Study Planner on the Exams page to paste your syllabus, select Classroom materials, and create a revision plan for this exam.</p><Link href="/dashboard/exams" className="product-action">Open study planner</Link></div></section>
    </main>
  );
}
