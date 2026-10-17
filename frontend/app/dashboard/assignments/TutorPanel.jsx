'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import MarkdownRenderer from '../MarkdownRenderer';

/**
 * Tutor tab: shows the assignment broken into requirements, then a chat
 * where the student can ask for explanations or paste their own draft for
 * feedback. Conversations are persisted so the student can see previous
 * questions and responses.
 */
export default function TutorPanel({ assignment }) {
  const { getToken } = useAuth();
  const [breakdown, setBreakdown] = useState(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(true);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeConversationId, setActiveConversationId] = useState(null);
  const scrollRef = useRef(null);
  const initializedConversation = useRef(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingBreakdown(true);
      try {
        const token = getToken ? await getToken() : null;
        const data = await api.getAssignmentBreakdown(assignment.id, token);
        if (!cancelled) setBreakdown(data);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not load assignment breakdown.');
      } finally {
        if (!cancelled) setLoadingBreakdown(false);
      }
    })();
    return () => { cancelled = true; };
  }, [assignment.id, getToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const rows = await api.getTutorConversations(assignment.id, token);
        if (!cancelled) setConversations(rows || []);
        if (!initializedConversation.current) {
          initializedConversation.current = true;
          const latest = (rows || [])[0] || null;
          setActiveConversationId(latest ? latest.id : null);
          if (latest) {
            const messagesRows = await api.getTutorConversationMessages(assignment.id, latest.id, token);
            if (!cancelled) setMessages((messagesRows || []).map((m) => ({ role: m.role === 'assistant' ? 'tutor' : 'student', text: m.content })));
          }
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not load tutor conversations.');
      }
    })();
    return () => { cancelled = true; };
  }, [assignment.id, getToken]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const startNewConversation = () => {
    setActiveConversationId(null);
    setMessages([]);
    setInput('');
    setError(null);
  };

  const loadConversation = async (conversationId) => {
    setActiveConversationId(conversationId);
    setMessages([]);
    try {
      const token = getToken ? await getToken() : null;
      const rows = await api.getTutorConversationMessages(assignment.id, conversationId, token);
      setMessages((rows || []).map((m) => ({ role: m.role === 'assistant' ? 'tutor' : 'student', text: m.content })));
    } catch (e) {
      setError(e.message || 'Could not load conversation history.');
    }
  };

  const send = async (text) => {
    const trimmed = (text ?? input).trim();
    if (!trimmed || sending) return;
    setInput('');
    setError(null);
    const next = [...messages, { role: 'student', text: trimmed }];
    setMessages(next);
    setSending(true);
    try {
      const token = getToken ? await getToken() : null;
      const reply = await api.askTutor(
        assignment.id,
        {
          message: trimmed,
          history: next,
          conversation_id: activeConversationId,
        },
        token
      );
      const conversationId = reply.conversation_id;
      setActiveConversationId(conversationId);
      const tutorMsg = { role: 'tutor', text: reply.text };
      setMessages((m) => [...next, tutorMsg]);
      if (!conversations.find((c) => c.id === conversationId)) {
        setConversations((prev) => [{ id: conversationId, title: trimmed.slice(0, 60), source: 'tutor' }, ...prev]);
      }
    } catch (e) {
      setError(e.message || 'The tutor is unavailable right now.');
      setMessages((m) => m.slice(0, -1));
      setInput(trimmed);
    } finally {
      setSending(false);
    }
  };

  const suggestedPrompts = [
    'Can you explain what this requirement is actually asking for?',
    'I’m stuck on where to start — what’s the general approach and architecture?',
    'Here’s my logic so far, what edge cases or gaps am I missing?',
  ];

  const secondaryButtonClass = 'inline-flex min-h-9 items-center justify-center rounded-lg border border-line bg-white px-3 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50';

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <div className="flex min-w-0 flex-col gap-4">
        <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
          <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold text-ink">Requirements breakdown</span>
              {breakdown?.requirements?.length > 0 && <span className="rounded-full bg-violet-light px-3 py-1 text-xs font-semibold text-violet-dark">{breakdown.requirements.length} tasks</span>}
            </div>
            <button type="button" className={secondaryButtonClass} onClick={startNewConversation}>New chat</button>
          </header>
          {loadingBreakdown ? <div className="p-8 text-center text-sm text-muted" role="status"><span className="mx-auto mb-3 block size-6 animate-spin rounded-full border-2 border-violet-light border-t-violet" />Analyzing rubric criteria…</div> : breakdown?.requirements?.length ? (
            <div className="flex max-h-[440px] flex-col gap-2 overflow-y-auto p-4">
              {breakdown.requirements.map((req, idx) => <button key={req.id || idx} type="button" onClick={() => send(`Can you walk me through requirement #${idx + 1}: "${req.description}"?`)} className="rounded-lg border border-line bg-white p-3 text-left transition hover:border-violet/40 hover:bg-violet-light/30">
                <span className="mb-2 flex items-center justify-between gap-3"><span className="rounded bg-violet-light px-2 py-1 text-xs font-semibold text-violet-dark">Task {idx + 1}</span>{req.priority && <span className={`text-xs font-semibold uppercase ${req.priority.toLowerCase() === 'high' ? 'text-rose' : 'text-muted'}`}>{req.priority}</span>}</span>
                <span className="block text-sm leading-5 text-ink">{req.description}</span>
                <span className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-violet">Ask tutor <Icon name="arrowUpRight" size={14}/></span>
              </button>)}
            </div>
          ) : <div className="p-8 text-center"><strong className="block text-sm font-semibold text-ink">No structured task list</strong><span className="mt-1 block text-sm text-muted">Ask the tutor directly for help breaking down the assignment.</span></div>}
          {conversations.length > 0 && (
            <div className="border-t border-line pt-4 px-5 py-3">
              <p className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Recent conversations</p>
              <div className="max-h-[150px] overflow-y-auto divide-y divide-line">
                {conversations.map((c) => (
                  <button key={c.id} type="button" onClick={() => loadConversation(c.id)} className={`w-full flex items-center gap-3 px-4 py-2 text-left text-sm rounded border transition ${activeConversationId === c.id ? 'border-violet bg-violet-light' : 'border-transparent hover:bg-paper'}`}>
                    <span className="line-clamp-1">{c.title}</span>
                    <span className="ml-auto text-xs text-muted">{c.source === 'tutor' ? 'Tutor' : 'Study'}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>
        <aside className="rounded-xl border border-violet/20 bg-violet-light/60 p-4 text-sm leading-6 text-violet-dark"><strong>Socratic tutoring:</strong> The AI tutor guides your understanding and points out edge cases. It explains concepts using non-assignment examples without authoring deliverables for you.</aside>
      </div>

      <section className="flex min-h-[520px] min-w-0 flex-col overflow-hidden rounded-xl border border-line bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3 border-b border-line bg-paper px-5 py-4">
          <div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="lightbulb" size={18}/></span><span><strong className="block text-sm font-semibold text-ink">Course academic tutor</strong><small className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-brand-hover"><span className="size-1.5 rounded-full bg-brand"/>Ready to answer questions</small></span></div>
          <div className="flex items-center gap-2">
            {messages.length > 0 && <button type="button" onClick={startNewConversation} className="text-sm font-medium text-muted hover:text-ink">Clear chat</button>}
          </div>
        </header>

        <div ref={scrollRef} className="flex min-h-[360px] flex-1 flex-col gap-4 overflow-y-auto p-5">
          {messages.length === 0 && <div className="m-auto w-full max-w-lg py-5 text-center">
            <span className="mx-auto mb-3 grid size-11 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="lightbulb" size={20}/></span>
            <strong className="text-base font-semibold text-ink">How can the tutor help you today?</strong>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Ask about concepts, request help planning your approach, or paste your draft logic for Socratic feedback.</p>
            <div className="mt-5 flex flex-col gap-2 text-left">{suggestedPrompts.map((p, idx) => <button key={idx} type="button" onClick={() => send(p)} className="flex items-start gap-2 rounded-lg border border-line bg-white p-3 text-sm leading-5 text-ink transition hover:border-violet/40 hover:bg-violet-light/30"><Icon name="message" size={16} className="mt-0.5 shrink-0 text-violet"/>{p}</button>)}</div>
          </div>}

          {messages.map((m, idx) => <div key={idx} className={`flex gap-2 ${m.role === 'student' ? 'justify-end' : 'justify-start'}`}>
            {m.role !== 'student' && <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">AI</span>}
            <div className={`max-w-[88%] rounded-xl px-4 py-3 text-sm leading-6 ${m.role === 'student' ? 'bg-violet text-white' : 'border border-line bg-paper text-ink'}`}>
              {m.role === 'student' ? <p className="whitespace-pre-wrap">{m.text}</p> : <MarkdownRenderer content={m.text}/>}
            </div>
          </div>)}

          {sending && <div className="flex items-center gap-2" role="status"><span className="grid size-8 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">AI</span><span className="inline-flex items-center gap-2 rounded-xl border border-line bg-paper px-4 py-3 text-sm text-muted"><span className="size-4 animate-spin rounded-full border-2 border-violet-light border-t-violet"/>Tutor is formulating an explanation…</span></div>}
          {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send(); }} className="flex gap-2 border-t border-line bg-white p-4">
          <input className="min-w-0 flex-1 rounded-lg border border-line px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about a requirement or concept…" />
          <button type="submit" disabled={sending || !input.trim()} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50">Ask tutor <Icon name="send" size={15}/></button>
        </form>
      </section>
    </div>
  );
}
