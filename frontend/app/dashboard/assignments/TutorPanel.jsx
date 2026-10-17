'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import MarkdownRenderer from '../MarkdownRenderer';

/**
 * Tutor tab: a fixed-height, non-scrolling study assistant.
 * Left: conversation history. Center: chat. Right: requirements breakdown.
 * Only the inner regions (history list, task list, message list) scroll;
 * the page itself never does.
 *
 * NOTE: all data/API logic below is unchanged from the original component.
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
  const [drawer, setDrawer] = useState(null); // UI only: 'history' | 'tasks' | null
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
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
  }, [messages, sending]);

  // UI only: auto-grow the composer up to a max height
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const startNewConversation = () => {
    setActiveConversationId(null);
    setMessages([]);
    setInput('');
    setError(null);
    setDrawer(null);
  };

  const loadConversation = async (conversationId) => {
    setActiveConversationId(conversationId);
    setMessages([]);
    setDrawer(null);
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
    setDrawer(null);
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
    'Can you walk me through the step-by-step solution approach for this assignment?',
    'What code architecture, libraries, and functions do I need to implement?',
    'Prepare a comprehensive summary of key concepts and edge cases for this lab.',
  ];

  const iconButton = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3 text-sm font-medium text-ink transition hover:bg-paper focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/30 disabled:cursor-not-allowed disabled:opacity-50';

  const requirementCount = breakdown?.requirements?.length || 0;

  /* ---------- Left: history ---------- */
  const historyPanel = (
    <aside
      className={`${drawer === 'history' ? 'absolute inset-y-0 left-0 z-30 flex shadow-xl' : 'hidden'} w-72 shrink-0 flex-col border-r border-line bg-paper lg:static lg:z-auto lg:flex lg:shadow-none`}
      aria-label="Conversation history"
    >
      <div className="p-3">
        <button type="button" onClick={startNewConversation} className="flex w-full items-center justify-between rounded-lg border border-line bg-white px-3 py-2.5 text-sm font-semibold text-ink transition hover:border-violet/40 hover:bg-violet-light/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/30">
          New chat
          <Icon name="message" size={16} className="text-violet" />
        </button>
      </div>
      <p className="px-4 pb-1 text-xs font-semibold text-muted">Recent</p>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-sm leading-5 text-muted">Your conversations will show up here.</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => loadConversation(c.id)}
                  aria-current={activeConversationId === c.id ? 'true' : undefined}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/30 ${activeConversationId === c.id ? 'bg-violet-light font-semibold text-violet-dark' : 'text-ink hover:bg-white'}`}
                >
                  <span className="line-clamp-1 min-w-0 flex-1">{c.title}</span>
                  <span className="shrink-0 text-xs font-normal text-muted">{c.source === 'tutor' ? 'Tutor' : 'Study'}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>
      <div className="border-t border-line p-3 lg:hidden">
        <button type="button" className={`${iconButton} w-full`} onClick={() => setDrawer(null)}>Close</button>
      </div>
    </aside>
  );

  /* ---------- Right: requirements ---------- */
  const tasksPanel = (
    <aside
      className={`${drawer === 'tasks' ? 'absolute inset-y-0 right-0 z-30 flex shadow-xl' : 'hidden'} w-80 shrink-0 flex-col border-l border-line bg-white xl:static xl:z-auto xl:flex xl:shadow-none`}
      aria-label="Requirements breakdown"
    >
      <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3.5">
        <span className="text-sm font-semibold text-ink">Requirements</span>
        {requirementCount > 0 && <span className="rounded-full bg-violet-light px-2.5 py-0.5 text-xs font-semibold text-violet-dark">{requirementCount} tasks</span>}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loadingBreakdown ? (
          <div className="p-8 text-center text-sm text-muted" role="status">
            <span className="mx-auto mb-3 block size-6 animate-spin rounded-full border-2 border-violet-light border-t-violet" />
            Analyzing rubric criteria…
          </div>
        ) : requirementCount ? (
          <ul className="flex flex-col gap-2 p-3">
            {breakdown.requirements.map((req, idx) => (
              <li key={req.id || idx}>
                <button
                  type="button"
                  onClick={() => send(`Can you walk me through requirement #${idx + 1}: "${req.description}"?`)}
                  disabled={sending}
                  className="group w-full rounded-lg border border-line bg-white p-3 text-left transition hover:border-violet/40 hover:bg-violet-light/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/30 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="mb-1.5 flex items-center justify-between gap-3">
                    <span className="rounded bg-violet-light px-2 py-0.5 text-xs font-semibold text-violet-dark">Task {idx + 1}</span>
                    {req.priority && <span className={`text-xs font-semibold ${req.priority.toLowerCase() === 'high' ? 'text-rose' : 'text-muted'}`}>{req.priority}</span>}
                  </span>
                  <span className="line-clamp-3 block text-sm leading-5 text-ink">{req.description}</span>
                  <span className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-violet">Ask tutor <Icon name="arrowUpRight" size={14} /></span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="p-8 text-center">
            <strong className="block text-sm font-semibold text-ink">No structured task list</strong>
            <span className="mt-1 block text-sm text-muted">Ask the tutor directly for help breaking down the assignment.</span>
          </div>
        )}
      </div>

      <div className="border-t border-line bg-violet-light/60 p-3 text-xs leading-5 text-violet-dark">
        <strong>AI Assignment Tutor:</strong> Grounded in your assignment instructions, attached documents, and rubric.
      </div>
      <div className="border-t border-line p-3 xl:hidden">
        <button type="button" className={`${iconButton} w-full`} onClick={() => setDrawer(null)}>Close</button>
      </div>
    </aside>
  );

  /* ---------- Center: chat ---------- */
  return (
    <div className="relative flex h-[calc(100dvh-9rem)] min-h-[560px] w-full min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
      {drawer && <div className="absolute inset-0 z-20 bg-black/30 xl:hidden" onClick={() => setDrawer(null)} aria-hidden="true" />}

      {historyPanel}

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Tutor chat">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name="lightbulb" size={18} /></span>
            <span className="min-w-0">
              <strong className="block truncate text-sm font-semibold text-ink">Course academic tutor</strong>
              <small className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-brand-hover"><span className="size-1.5 rounded-full bg-brand" />Ready to answer questions</small>
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" className={`${iconButton} lg:hidden`} onClick={() => setDrawer('history')}>History</button>
            <button type="button" className={`${iconButton} xl:hidden`} onClick={() => setDrawer('tasks')}>Tasks</button>
            {messages.length > 0 && <button type="button" onClick={startNewConversation} className="px-2 text-sm font-medium text-muted transition hover:text-ink">Clear chat</button>}
          </div>
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6 px-4 py-6">
            {messages.length === 0 && (
              <div className="m-auto w-full py-6 text-center">
                <span className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-violet-light text-violet"><Icon name="lightbulb" size={22} /></span>
                <h2 className="text-xl font-semibold text-ink">How can the tutor help you today?</h2>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted">Ask about concepts, request help planning your approach, or paste your draft logic for Socratic feedback.</p>
                <div className="mt-6 grid grid-cols-1 gap-2 text-left md:grid-cols-3">
                  {suggestedPrompts.map((p, idx) => (
                    <button key={idx} type="button" onClick={() => send(p)} className="flex flex-col items-start gap-2 rounded-xl border border-line bg-white p-3 text-sm leading-5 text-ink transition hover:border-violet/40 hover:bg-violet-light/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/30">
                      <Icon name="message" size={16} className="shrink-0 text-violet" />
                      <span className="line-clamp-4">{p}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, idx) => (
              m.role === 'student' ? (
                <div key={idx} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl bg-violet px-4 py-2.5 text-sm leading-6 text-white">
                    <p className="whitespace-pre-wrap break-words">{m.text}</p>
                  </div>
                </div>
              ) : (
                <div key={idx} className="flex items-start gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">AI</span>
                  <div className="min-w-0 flex-1 pt-1 text-sm leading-6 text-ink">
                    <MarkdownRenderer content={m.text} />
                  </div>
                </div>
              )
            ))}

            {sending && (
              <div className="flex items-center gap-3" role="status">
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-xs font-bold text-violet">AI</span>
                <span className="inline-flex items-center gap-2 text-sm text-muted">
                  <span className="size-4 animate-spin rounded-full border-2 border-violet-light border-t-violet" />
                  Tutor is formulating an explanation…
                </span>
              </div>
            )}

            {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
          </div>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send(); }} className="shrink-0 bg-white px-4 pb-3 pt-2">
          <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-2xl border border-line bg-white py-2 pl-4 pr-2 shadow-sm transition focus-within:border-violet focus-within:ring-2 focus-within:ring-violet/20">
            <textarea
              ref={textareaRef}
              rows={1}
              className="max-h-40 min-w-0 flex-1 resize-none bg-transparent py-1.5 text-sm leading-6 text-ink outline-none placeholder:text-muted"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about a requirement or concept…"
              aria-label="Message the tutor"
            />
            <button type="submit" disabled={sending || !input.trim()} aria-label="Ask tutor" className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl bg-violet text-white transition hover:bg-violet-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet/40 disabled:cursor-not-allowed disabled:opacity-40">
              <Icon name="send" size={16} />
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-muted">Enter to send, Shift+Enter for a new line. Check important details against your course materials.</p>
        </form>
      </section>

      {tasksPanel}
    </div>
  );
}