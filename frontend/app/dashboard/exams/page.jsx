'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';

export default function ExamsPage() {
  const { getToken } = useAuth();
  const [exams, setExams] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState([]);
  const [examId, setExamId] = useState('');
  const [syllabus, setSyllabus] = useState('');
  const [plan, setPlan] = useState('');
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    const token = await getToken();
    const [examRows, materialRows] = await Promise.all([api.getExams(token), api.getClassroomStudyMaterials(token)]);
    setExams(examRows || []); setMaterials(materialRows || []);
    setSelected((current) => current.length ? current : (materialRows || []).map((item) => item.id));
  }, [getToken]);
  useEffect(() => { load().catch((e) => setError(e.message || 'Could not load exam data.')).finally(() => setLoading(false)); }, [load]);

  const selectedExam = exams.find((exam) => String(exam.id) === examId);
  const runPlan = async (event) => {
    event.preventDefault(); setBusy(true); setError(''); setPlan('');
    try { const token = await getToken(); const result = await api.generateStudyPlan({ syllabus, document_ids: selected, exam_title: selectedExam?.title }, token); setPlan(result.plan || 'No plan was returned.'); }
    catch (e) { setError(e.message || 'Could not create a study plan.'); } finally { setBusy(false); }
  };
  const ask = async (event) => {
    event.preventDefault(); if (!question.trim()) return;
    const prompt = question.trim(); setMessages((items) => [...items, { role: 'you', text: prompt }]); setQuestion(''); setBusy(true); setError('');
    try { const token = await getToken(); const result = await api.askCourseMaterials({ query: prompt, document_ids: selected, syllabus }, token); setMessages((items) => [...items, { role: 'assistant', text: result.answer || 'No answer returned.' }]); }
    catch (e) { setError(e.message || 'Could not answer from course materials.'); }
    finally { setBusy(false); }
  };

  const cardClass = 'min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm';
  const cardHeaderClass = 'flex items-center justify-between gap-3 border-b border-line px-5 py-4';
  const eyebrowClass = 'mb-1 text-xs font-semibold uppercase tracking-wide text-muted';
  const fieldClass = 'flex flex-col gap-1.5 text-sm font-medium text-ink';
  const inputClass = 'w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20';
  const buttonClass = 'inline-flex min-h-10 items-center justify-center rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50';

  return <main className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-ink">
    <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"><div><p className={eyebrowClass}>Exam preparation</p><h1 className="text-2xl font-semibold tracking-tight">Study planner</h1><p className="mt-1 max-w-2xl text-sm leading-6 text-muted">Paste your syllabus, select synced Classroom materials, and build a grounded plan or ask questions.</p></div><span className="inline-flex w-fit rounded-full bg-violet-light px-3 py-1.5 text-sm font-semibold text-violet-dark">{exams.length} upcoming exams</span></header>
    {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
    <section className={cardClass}><header className={cardHeaderClass}><div><p className={eyebrowClass}>Your exams</p><h2 className="text-base font-semibold">Upcoming schedule</h2></div></header>
      {loading ? <div className="p-8 text-center text-sm text-muted" role="status">Loading exam data…</div> : exams.length ? <div className="divide-y divide-line">{exams.map((exam) => <Link key={exam.id} href={`/dashboard/exams/${exam.id}`} className="flex flex-col gap-3 px-5 py-4 transition hover:bg-paper sm:flex-row sm:items-center sm:justify-between"><span className="flex min-w-0 flex-col gap-1"><strong className="text-sm font-semibold">{exam.title}</strong><small className="text-sm text-muted">{exam.date ? format(new Date(exam.date), 'EEE, MMM d, yyyy') : 'Date to be announced'} · {exam.time || 'Time TBA'} · {exam.room || 'Room TBA'}</small></span><span className="inline-flex min-h-9 w-fit items-center rounded-lg border border-line px-3 text-sm font-semibold text-ink">View exam</span></Link>)}</div> : <div className="p-8 text-center"><strong className="block text-sm font-semibold">No exams synced yet</strong><span className="mt-1 block text-sm text-muted">Sync your university portal or Classroom to populate exam dates.</span></div>}
    </section>
    <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
      <section className={cardClass}><header className={cardHeaderClass}><div><p className={eyebrowClass}>Build a plan</p><h2 className="text-base font-semibold">Syllabus and materials</h2></div></header><form className="flex flex-col gap-4 p-5" onSubmit={runPlan}>
        <label className={fieldClass}>Exam (optional)<select className={inputClass} value={examId} onChange={(e) => setExamId(e.target.value)}><option value="">General study plan</option>{exams.map((exam) => <option key={exam.id} value={exam.id}>{exam.title}</option>)}</select></label>
        <label className={fieldClass}>Paste your syllabus or topic list<textarea className={`${inputClass} min-h-40 resize-y`} required minLength={10} value={syllabus} onChange={(e) => setSyllabus(e.target.value)} placeholder={'Paste topics, chapters, or learning outcomes here…\n\nExample: Week 1 — data structures; Week 2 — trees and graphs'} rows={7} /></label>
        <div className={fieldClass}><span>Synced Google Classroom materials <small className="ml-1 font-normal text-muted">{selected.length} selected</small></span>{materials.length ? <div className="max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line">{materials.map((item) => <label className="flex cursor-pointer items-start gap-3 p-3 hover:bg-paper" key={item.id}><input className="mt-1 size-4 accent-violet" type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} /><span className="flex min-w-0 flex-col gap-1"><strong className="text-sm">{item.title}</strong><small className="text-xs text-muted">{item.course_name}{item.assignment ? ` · ${item.assignment}` : ''}</small></span></label>)}</div> : <p className="rounded-lg bg-paper p-3 text-sm leading-6 text-muted">No Google Classroom Drive materials are synced yet. Connect Google and sync coursework first.</p>}</div>
        <button className={buttonClass} type="submit" disabled={busy || loading || syllabus.trim().length < 10}>{busy ? 'Building study plan…' : 'Generate study plan'}</button>
      </form></section>
      <section className={`${cardClass} flex min-h-[520px] flex-col`}><header className={cardHeaderClass}><div><p className={eyebrowClass}>Ask your course materials</p><h2 className="text-base font-semibold">Study chat</h2></div></header><div className="flex min-h-0 flex-1 flex-col gap-4 p-5">
        <p className="text-sm leading-6 text-muted">Answers use the selected Classroom files and pasted syllabus. Uniflow will say when the material does not cover a question.</p>
        <div className="flex min-h-[300px] flex-1 flex-col gap-3 overflow-y-auto rounded-lg bg-paper p-4" aria-live="polite">
          {messages.length ? messages.map((message, index) => <article className={`max-w-[90%] rounded-xl border px-4 py-3 text-sm leading-6 ${message.role === 'you' ? 'ml-auto border-violet bg-violet text-white' : 'border-line bg-white text-ink'}`} key={index}><small className={`mb-1 block text-xs font-semibold ${message.role === 'you' ? 'text-white/75' : 'text-muted'}`}>{message.role === 'you' ? 'You' : 'Study assistant'}</small>{message.role === 'you' ? <p className="whitespace-pre-wrap">{message.text}</p> : <MarkdownRenderer content={message.text} />}</article>) : <div className="m-auto max-w-sm text-center text-sm leading-6 text-muted">Ask about a topic, request an explanation, or quiz yourself.</div>}
          {busy && <p className="text-sm text-muted" role="status">Thinking…</p>}
        </div>
        <form className="flex gap-2" onSubmit={ask}><input className={inputClass} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your syllabus…" aria-label="Ask about your course materials" /><button className={buttonClass} disabled={busy || !question.trim()}>{busy ? 'Thinking…' : 'Ask'}</button></form>
      </div></section>
    </div>
    {plan && <section className={cardClass}><header className={cardHeaderClass}><div><p className={eyebrowClass}>Generated from your input</p><h2 className="text-base font-semibold">Study plan</h2></div><button className={secondaryButtonClass} type="button" onClick={() => navigator.clipboard?.writeText(plan)}>Copy plan</button></header><div className="p-5" aria-live="polite"><MarkdownRenderer content={plan} /></div></section>}
  </main>;
}
