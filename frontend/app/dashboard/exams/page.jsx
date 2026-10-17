'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@clerk/nextjs';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';
import Icon from '@/app/dashboard/Icon';

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
  const [planBusy, setPlanBusy] = useState(false);
  const [error, setError] = useState('');
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [activeTab, setActiveTab] = useState('plan');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const initializedConversation = useRef(false);
  const scrollRef = useRef(null);

  const loadMessages = async (conversationId, token) => {
    try {
      const rows = await api.getRagConversationMessages(conversationId, token);
      setMessages((rows || []).map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'you', text: m.content })));
      setActiveConversationId(conversationId);
    } catch (e) {
      setError(e.message || 'Could not load conversation history.');
    }
  };

  const load = useCallback(async () => {
    const token = await getToken();
    const [examRows, materialRows, conversationRows] = await Promise.all([
      api.getExams(token),
      api.getClassroomStudyMaterials(token),
      api.getRagConversations(token),
    ]);
    setExams(examRows || []);
    setMaterials(materialRows || []);
    setSelected((materialRows || []).map((item) => item.id));
    setConversations(conversationRows || []);
    if (!initializedConversation.current) {
      initializedConversation.current = true;
      const latest = (conversationRows || [])[0] || null;
      setActiveConversationId(latest ? latest.id : null);
      if (latest) {
        const rows = await api.getRagConversationMessages(latest.id, token);
        setMessages((rows || []).map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'you', text: m.content })));
      }
    }
  }, [getToken]);

  useEffect(() => {
    load().catch((e) => setError(e.message || 'Could not load exam data.')).finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const selectedExam = exams.find((exam) => String(exam.id) === examId);

  const runPlan = async (event) => {
    event.preventDefault(); setPlanBusy(true); setError(''); setPlan('');
    try {
      const token = await getToken();
      const result = await api.generateStudyPlan({ syllabus, document_ids: selected, exam_title: selectedExam?.title }, token);
      setPlan(result.plan || 'No plan was returned.');
    } catch (e) {
      setError(e.message || 'Could not create a study plan.');
    } finally {
      setPlanBusy(false);
    }
  };

  const ask = async (event) => {
    event.preventDefault(); if (!question.trim()) return;
    const prompt = question.trim(); setMessages((items) => [...items, { role: 'you', text: prompt }]); setQuestion(''); setBusy(true); setError('');
    const nextMessages = [...messages, { role: 'you', text: prompt }];
    try {
      const token = await getToken();
      const result = await api.askCourseMaterials({ query: prompt, document_ids: selected, syllabus, conversation_id: activeConversationId, history: nextMessages }, token);
      const conversationId = result.conversation_id;
      setActiveConversationId(conversationId);
      setMessages([...nextMessages, { role: 'assistant', text: result.answer || 'No answer returned.' }]);
      if (!conversations.find((c) => c.id === conversationId)) {
        setConversations((prev) => [{ id: conversationId, title: prompt.slice(0, 60), source: 'rag' }, ...prev]);
      }
    } catch (e) {
      setError(e.message || 'Could not answer from course materials.');
      setMessages((m) => m.slice(0, -1));
      setQuestion(prompt);
    } finally {
      setBusy(false);
    }
  };

  const startNewConversation = () => {
    setActiveConversationId(null);
    setMessages([]);
    setQuestion('');
    setError('');
  };

  const toggleSidebar = () => setSidebarOpen(!sidebarOpen);

  const cardClass = 'min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm';
  const labelClass = 'mb-1 block text-xs font-semibold uppercase tracking-wide text-muted';
  const secondaryButtonClass = 'inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-white px-3 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';
  const buttonClass = 'inline-flex min-h-10 items-center justify-center rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50';
  const inputClass = 'min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20';
  const fieldClass = 'flex flex-col gap-1.5 text-sm font-medium text-ink';

  return (
    <main className="mx-auto flex w-full max-w-[1280px] flex-col gap-0 pb-10 text-ink">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between border-b border-line pb-6">
        <div>
          <p className={labelClass}>Exam preparation</p>
          <h1 className="text-2xl font-semibold tracking-tight">Study Planner</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">Build grounded study plans from your syllabus and Classroom materials, then ask questions about them.</p>
        </div>
        <span className="inline-flex items-center gap-2 rounded-full bg-violet-light px-3 py-1.5 text-sm font-semibold text-violet-dark">{exams.length} upcoming exams</span>
      </header>
      {error && <div className="mx-4 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
      <div className="flex min-h-[700px] flex-1">
        {sidebarOpen && (
          <aside className="hidden lg:flex flex-col gap-4 w-[340px] border-r border-line bg-white px-5 py-4">
            <section className="flex flex-col gap-4">
              <div>
                <p className={labelClass}>Upcoming exams</p>
                {exams.length ? (
                  <div className="divide-y divide-line">
                    {exams.map((exam) => (
                      <button key={exam.id} type="button" onClick={() => setExamId(String(exam.id))} className={`flex items-center gap-3 px-3 py-2.5 text-left rounded transition ${examId === String(exam.id) ? 'border-violet bg-violet-light' : 'hover:bg-paper'}`}>
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <strong className="text-sm font-semibold text-ink line-clamp-1">{exam.title}</strong>
                          <small className="text-xs text-muted">{exam.date ? format(new Date(exam.date), 'EEE, MMM d') : 'Date TBA'} · {exam.time || 'Time TBA'}</small>
                        </span>
                        <span className="ml-auto text-xs text-muted">Select</span>
                      </button>
                    ))}
                  </div>
                ) : <div className="p-4 text-center text-sm text-muted">No exams synced yet</div>}
              </div>
              {materials.length > 0 && (
                <section className="flex flex-col gap-3 border-t border-line pt-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className={labelClass}>Source materials</p>
                    <span className="text-xs font-medium text-violet-dark">{selected.length} selected</span>
                  </div>
                  <div className="max-h-[220px] overflow-y-auto divide-y divide-line rounded-lg border border-line">
                    {materials.map((item) => (
                      <label key={item.id} className="flex cursor-pointer items-start gap-3 px-3 py-2.5 transition hover:bg-paper">
                        <input className="mt-1 size-4 accent-violet shrink-0" type="checkbox" checked={selected.includes(item.id)} onChange={(e) => setSelected((ids) => e.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="text-sm font-semibold text-ink line-clamp-1">{item.title || 'Untitled file'}</span>
                          <small className="text-xs text-muted">{[item.course_name, item.assignment].filter(Boolean).join(' · ') || 'Course material'}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                  <div className="flex gap-2 pt-2">
                    <button type="button" className="flex-1 text-xs font-semibold text-violet hover:text-violet-dark" onClick={() => setSelected(materials.map((item) => item.id))}>Select all</button>
                    <button type="button" className="flex-1 text-xs font-semibold text-violet hover:text-violet-dark" onClick={() => setSelected([])}>Clear</button>
                  </div>
                </section>
              )}
            </section>
            {conversations.length > 0 && (
              <section className="flex flex-col gap-3 border-t border-line pt-4">
                <p className={labelClass}>Recent conversations</p>
                <div className="max-h-[200px] overflow-y-auto divide-y divide-line">
                  {conversations.map((c) => (
                    <button key={c.id} type="button" onClick={async () => {
                      const token = await getToken();
                      await loadMessages(c.id, token);
                      setActiveTab('chat');
                    }} className={`flex items-center gap-3 px-3 py-2.5 text-left text-sm rounded transition ${activeConversationId === c.id ? 'border-violet bg-violet-light' : 'border-transparent hover:bg-paper'}`}>
                      <span className="line-clamp-1">{c.title}</span>
                      <span className="ml-auto text-xs text-muted">Study</span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </aside>
        )}
        <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex items-center justify-between gap-3 border-b border-line bg-white px-5 py-4 shrink-0">
            <div className="flex items-center gap-3">
              <span className="grid size-8 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="bookOpen" size={16} /></span>
              <div>
                <strong className="block text-sm font-semibold text-ink">Study Planner</strong>
                <small className="mt-0.5 text-xs text-muted">Build a plan, then ask questions grounded in your materials.</small>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {sidebarOpen && <button type="button" className="lg:hidden text-muted hover:text-ink" onClick={toggleSidebar}><Icon name="chevronLeft" size={18} /></button>}
              <button type="button" className={secondaryButtonClass} onClick={startNewConversation}>New chat</button>
            </div>
          </header>
          <div className="flex min-h-0 flex-1">
            <div className="hidden lg:block w-[200px] border-r border-line bg-paper px-4 py-4">
              <p className={labelClass}>Features</p>
              <div className="flex flex-col gap-2">
                <button type="button" onClick={() => setActiveTab('plan')} className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition ${activeTab === 'plan' ? 'bg-violet bg-violet/10 text-violet-dark border border-violet/20' : 'text-ink hover:bg-white border-transparent'}`}>
                  <Icon name="fileText" size={14} /> Study plan
                </button>
                <button type="button" onClick={() => setActiveTab('chat')} className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition ${activeTab === 'chat' ? 'bg-violet bg-violet/10 text-violet-dark border border-violet/20' : 'text-ink hover:bg-white border-transparent'}`}>
                  <Icon name="messageCircle" size={14} /> Study chat
                </button>
              </div>
            </div>
            <div className="min-w-0 flex-1 flex-col overflow-hidden">
              {activeTab === 'plan' && (
                <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-5">
                  <section className="mb-6">
                    <h2 className="text-base font-semibold text-ink">Build a study plan</h2>
                    <p className="mt-1 text-sm text-muted">Paste your syllabus and select materials to generate a grounded plan.</p>
                    <form className="flex flex-col gap-4 mt-4" onSubmit={runPlan}>
                      <label className={fieldClass}>
                        Exam (optional)
                        <select className={inputClass} value={examId} onChange={(e) => setExamId(e.target.value)}>
                          <option value="">General study plan</option>
                          {exams.map((exam) => <option key={exam.id} value={String(exam.id)}>{exam.title}</option>)}
                        </select>
                      </label>
                      <label className={fieldClass}>
                        Paste your syllabus or topic list
                        <textarea className={`${inputClass} min-h-[140px] resize-y`} required minLength={10} value={syllabus} onChange={(e) => setSyllabus(e.target.value)} placeholder="Paste topics, chapters, or learning outcomes here…" rows={6} />
                      </label>
                      <button type="submit" className={buttonClass} disabled={planBusy || loading || syllabus.trim().length < 10}>{planBusy ? 'Building study plan…' : 'Generate study plan'}</button>
                    </form>
                  </section>
                  {plan && (
                    <section className="rounded-xl border border-line bg-white p-6">
                      <header className="flex items-center justify-between gap-3 mb-4">
                        <h2 className="text-base font-semibold text-ink">Generated study plan</h2>
                        <button type="button" className={secondaryButtonClass} onClick={() => navigator.clipboard?.writeText(plan)}>Copy plan</button>
                      </header>
                      <div className="prose prose-sm max-w-none text-ink"><MarkdownRenderer content={plan} /></div>
                    </section>
                  )}
                </div>
              )}
              {activeTab === 'chat' && (
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                  <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-5">
                    {loading ? (
                      <div className="m-auto py-10 text-center text-sm text-muted" role="status">Loading study materials…</div>
                    ) : messages.length ? (
                      messages.map((message, index) => (
                        <article key={index} className={`flex gap-3 ${message.role === 'you' ? 'justify-end' : 'justify-start'}`}>
                          {message.role !== 'you' && (
                            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">AI</span>
                          )}
                          <div className={`max-w-[90%] rounded-xl px-4 py-3 text-sm leading-6 ${message.role === 'you' ? 'bg-violet text-white' : 'border border-line bg-paper text-ink'}`}>
                            {message.role === 'you' ? <p className="whitespace-pre-wrap">{message.text}</p> : <MarkdownRenderer content={message.text} />}
                          </div>
                        </article>
                      ))
                    ) : (
                      <div className="m-auto w-full max-w-lg py-10 text-center">
                        <span className="mx-auto mb-4 grid size-16 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="messageCircle" size={28} /></span>
                        <strong className="block text-base font-semibold text-ink">Ask about your materials</strong>
                        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Switch to the Study chat tab and ask questions grounded in your selected sources and syllabus.</p>
                        {!selected.length && <div className="mt-6 rounded-lg border border-line bg-paper p-4 text-sm leading-6 text-muted">
                          <strong className="block text-xs font-semibold uppercase tracking-wide text-muted">No sources selected</strong>
                          <span>Choose course files from the sidebar to ground your questions.</span>
                        </div>}
                      </div>
                    )}
                    {busy && <div className="flex items-center gap-2 text-sm text-muted" role="status"><span className="size-4 animate-spin rounded-full border-2 border-violet-light border-t-violet" />Study assistant is thinking…</div>}
                  </div>
                  <form className="flex gap-2 border-t border-line bg-white p-4 shrink-0" onSubmit={ask}>
                    <input className={inputClass} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about your syllabus and materials…" aria-label="Ask about your course materials" disabled={!selected.length} />
                    <button type="submit" className={buttonClass} disabled={busy || !question.trim() || !selected.length}>{busy ? 'Working…' : 'Ask'}</button>
                  </form>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
