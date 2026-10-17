'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';
import Icon from '@/app/dashboard/Icon';

export default function CoursesPage() {
  const { getToken } = useAuth();
  const [materials, setMaterials] = useState([]);
  const [selected, setSelected] = useState([]);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const initializedSelection = useRef(false);
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
    const [materialRows, conversationRows] = await Promise.all([
      api.getClassroomStudyMaterials(token),
      api.getRagConversations(token),
    ]);
    setMaterials(materialRows || []);
    setConversations(conversationRows || []);
    if (!initializedSelection.current) {
      initializedSelection.current = true;
      setSelected((materialRows || []).map((item) => item.id));
    } else {
      setSelected((current) => current.filter((id) => materialRows.some((item) => item.id === id)));
    }
    if (!initializedConversation.current) {
      initializedConversation.current = true;
      const latest = (conversationRows || [])[0] || null;
      setActiveConversationId(latest ? latest.id : null);
      if (latest) {
        loadMessages(latest.id, token);
      }
    }
  }, [getToken]);

  useEffect(() => {
    load().catch((e) => setError(e.message || 'Could not load course materials.')).finally(() => setLoading(false));
  }, [load]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const send = async (event) => {
    event.preventDefault(); if (!question.trim()) return;
    const prompt = question.trim(); setQuestion(''); setError(''); setBusy(true);
    const nextMessages = [...messages, { role: 'you', text: prompt }];
    setMessages(nextMessages);
    try {
      const token = await getToken();
      const result = await api.askCourseMaterials({
        query: prompt,
        document_ids: selected,
        conversation_id: activeConversationId,
        history: nextMessages,
      }, token);
      const conversationId = result.conversation_id;
      const assistant = { role: 'assistant', text: result.answer || 'No answer returned.' };
      setMessages([...nextMessages, assistant]);
      if (!conversations.find((c) => c.id === conversationId)) {
        setConversations((prev) => [{ id: conversationId, title: prompt.slice(0, 60), source: 'rag' }, ...prev]);
      }
    } catch (e) {
      setError(e.message || 'Could not answer from the selected materials.');
      setMessages((m) => m.slice(0, -1));
      setQuestion(prompt);
    } finally {
      setBusy(false);
    }
  };

  const refreshMaterials = () => {
    setLoading(true);
    setError('');
    load().catch((e) => setError(e.message || 'Could not refresh course materials.')).finally(() => setLoading(false));
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

  return (
    <main className="mx-auto flex w-full max-w-[1280px] flex-col gap-0 pb-10 text-ink">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between border-b border-line pb-6">
        <div>
          <p className={labelClass}>Coursework</p>
          <h1 className="text-2xl font-semibold tracking-tight">Study Assistant</h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-muted">Grounded answers from your selected Classroom materials, with full conversation history.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-full bg-violet-light px-3 py-1.5 text-sm font-semibold text-violet-dark">{selected.length} of {materials.length} sources</span>
          <button type="button" className={secondaryButtonClass} onClick={startNewConversation}>New chat</button>
        </div>
      </header>
      {error && <div className="mx-4 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
      <div className="flex min-h-[700px] flex-1">
        {sidebarOpen && (
          <aside className="hidden lg:flex flex-col gap-4 w-[340px] border-r border-line bg-white px-5 py-4">
            <section className="flex flex-col gap-3">
              <p className={labelClass}>Conversations</p>
              <div className="flex min-h-[60px] items-center justify-between border border-line rounded-lg bg-paper px-3 py-2">
                <input className="flex-1 bg-transparent border-none outline-none text-sm text-ink placeholder:text-muted" placeholder="Search conversations…" />
                <button type="button" className="text-violet hover:text-violet-dark" title="Search">
                  <Icon name="search" size={16} />
                </button>
              </div>
              <div className="max-h-[320px] overflow-y-auto divide-y divide-line">
                {conversations.length ? conversations.map((c) => (
                  <button key={c.id} type="button" onClick={async () => {
                    const token = await getToken();
                    await loadMessages(c.id, token);
                  }} className={`flex items-center gap-3 px-3 py-2.5 text-left text-sm rounded transition ${activeConversationId === c.id ? 'border-violet bg-violet-light' : 'border-transparent hover:bg-paper'}`}>
                    <span className="line-clamp-1">{c.title}</span>
                    <span className="ml-auto text-xs text-muted">{c.source === 'tutor' ? 'Tutor' : 'Study'}</span>
                  </button>
                )) : <div className="p-4 text-center text-sm text-muted">No conversations yet</div>}
              </div>
            </section>
            {materials.length > 0 && (
              <section className="flex flex-col gap-3 border-t border-line pt-4">
                <div className="flex items-center justify-between gap-2">
                  <p className={labelClass}>Source materials</p>
                  <span className="text-xs font-medium text-violet-dark">{selected.length} selected</span>
                </div>
                <div className="max-h-[260px] overflow-y-auto divide-y divide-line rounded-lg border border-line">
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
          </aside>
        )}
        <section className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex items-center justify-between gap-3 border-b border-line bg-white px-5 py-4 shrink-0">
            <div className="flex items-center gap-3">
              <span className="grid size-8 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="lightbulb" size={16} /></span>
              <div>
                <strong className="block text-sm font-semibold text-ink">{activeConversationId ? 'Study Assistant' : 'Start a new conversation'}</strong>
                <small className="mt-0.5 text-xs text-muted">Answers use your selected sources and pasted syllabus.</small>
              </div>
            </div>
            {sidebarOpen && <button type="button" className="lg:hidden text-muted hover:text-ink" onClick={toggleSidebar}><Icon name="chevronLeft" size={18} /></button>}
          </header>
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
              <div className="m-auto w-full max-w-lg py-8 text-center">
                <span className="mx-auto mb-4 grid size-16 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="messageCircle" size={28} /></span>
                <strong className="block text-base font-semibold text-ink">University Study & Exam Assistant</strong>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">
                  {selected.length
                    ? `Ready to answer questions, explain topics, or prepare study materials using ${selected.length} selected source${selected.length > 1 ? 's' : ''}.`
                    : 'Ask anything about your courses, topics, or request study notes & cheat sheets across all course materials.'}
                </p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  <button type="button" onClick={() => setQuestion("Prepare a high-yield study sheet and key formulas for my upcoming exam.")} className="rounded-lg border border-line bg-paper px-3 py-1.5 text-xs font-semibold text-ink transition hover:border-violet/40 hover:bg-violet-light/30">
                    📝 Prepare exam cheat sheet
                  </button>
                  <button type="button" onClick={() => setQuestion("Explain the core concepts and common exam questions from this course.")} className="rounded-lg border border-line bg-paper px-3 py-1.5 text-xs font-semibold text-ink transition hover:border-violet/40 hover:bg-violet-light/30">
                    💡 Explain core concepts
                  </button>
                  <button type="button" onClick={() => setQuestion("Generate a 5-question practice quiz with detailed explanations.")} className="rounded-lg border border-line bg-paper px-3 py-1.5 text-xs font-semibold text-ink transition hover:border-violet/40 hover:bg-violet-light/30">
                    🎯 Practice quiz
                  </button>
                </div>
              </div>
            )}
            {busy && <div className="flex items-center gap-2 text-sm text-muted" role="status"><span className="size-4 animate-spin rounded-full border-2 border-violet-light border-t-violet" />Study assistant is thinking…</div>}
          </div>
          <form className="flex gap-2 border-t border-line bg-white p-4 shrink-0" onSubmit={send}>
            <input 
              className={inputClass} 
              value={question} 
              onChange={(e) => setQuestion(e.target.value)} 
              placeholder={selected.length ? `Ask about ${selected.length} selected source${selected.length > 1 ? 's' : ''}…` : "Ask about your courses or request study materials…"} 
              aria-label="Ask study assistant" 
            />
            <button type="submit" className={buttonClass} disabled={busy || !question.trim()}>{busy ? 'Working…' : 'Ask'}</button>
          </form>
        </section>
      </div>
    </main>
  );
}
