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

  return <main className="product-page">
    <header className="product-heading"><div><p className="eyebrow">EXAM PREPARATION</p><h1>Study planner</h1><p>Paste your syllabus, select synced Classroom materials, and build a grounded plan or ask questions.</p></div><span className="product-pill">{exams.length} upcoming exams</span></header>
    {error && <div className="product-alert">{error}</div>}
    <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">YOUR EXAMS</p><h2>Upcoming schedule</h2></div></header>
      {loading ? <div className="product-empty">Loading exam data…</div> : exams.length ? <div className="product-list">{exams.map((exam) => <Link key={exam.id} href={`/dashboard/exams/${exam.id}`} className="product-row"><span className="product-row-main"><strong>{exam.title}</strong><small>{exam.date ? format(new Date(exam.date), 'EEE, MMM d, yyyy') : 'Date to be announced'} · {exam.time || 'Time TBA'} · {exam.room || 'Room TBA'}</small></span><span className="product-action secondary">View exam</span></Link>)}</div> : <div className="product-empty"><strong>No exams synced yet</strong>Sync your university portal or Classroom to populate exam dates.</div>}
    </section>
    <div className="product-grid study-grid">
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">BUILD A PLAN</p><h2>Syllabus and materials</h2></div></header><form className="product-card-body" onSubmit={runPlan}>
        <label className="product-field"><span>Exam (optional)</span><select value={examId} onChange={(e) => setExamId(e.target.value)}><option value="">General study plan</option>{exams.map((exam) => <option key={exam.id} value={exam.id}>{exam.title}</option>)}</select></label>
        <label className="product-field"><span>Paste your syllabus or topic list</span><textarea required minLength={10} value={syllabus} onChange={(e) => setSyllabus(e.target.value)} placeholder={'Paste topics, chapters, or learning outcomes here…\n\nExample: Week 1 — data structures; Week 2 — trees and graphs'} rows={7} /></label>
        <div className="product-field"><span>Synced Google Classroom materials <small>{selected.length} selected</small></span>{materials.length ? <div className="study-materials">{materials.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} /><span><strong>{item.title}</strong><small>{item.course_name}{item.assignment ? ` · ${item.assignment}` : ''}</small></span></label>)}</div> : <p className="product-note">No Google Classroom Drive materials are synced yet. Connect Google and sync coursework first.</p>}</div>
        <button className="product-action" type="submit" disabled={busy || loading || syllabus.trim().length < 10}>{busy ? 'Building study plan…' : 'Generate study plan'}</button>
      </form></section>
      <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">ASK YOUR COURSE MATERIALS</p><h2>Study chat</h2></div></header><div className="product-card-body study-chat">
        <p className="product-note">Answers use the selected Classroom files and pasted syllabus. Uniflow will say when the material does not cover a question.</p>
        <div className="study-messages" aria-live="polite">
              {messages.length ? messages.map((message, index) => (
                <article className={`study-message ${message.role}`} key={index}>
                  <small>{message.role === 'you' ? 'You' : 'Study assistant'}</small>
                  {message.role === 'you' ? (
                    <p style={{ whiteSpace: 'pre-wrap' }}>{message.text}</p>
                  ) : (
                    <MarkdownRenderer content={message.text} />
                  )}
                </article>
              )) : <div className="product-empty">Ask about a topic, request an explanation, or quiz yourself.</div>}
            </div>
        <form className="study-chat-form" onSubmit={ask}><input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your syllabus…" aria-label="Ask about your course materials" /><button className="product-action" disabled={busy || !question.trim()}>{busy ? 'Thinking…' : 'Ask'}</button></form>
      </div></section>
    </div>
    {plan && <section className="product-card"><header className="product-card-head"><div><p className="eyebrow">GENERATED FROM YOUR INPUT</p><h2>Study plan</h2></div><button className="product-action secondary" type="button" onClick={() => navigator.clipboard?.writeText(plan)}>Copy plan</button></header><div className="product-card-body study-plan" aria-live="polite"><MarkdownRenderer content={plan} /></div></section>}
  </main>;
}
