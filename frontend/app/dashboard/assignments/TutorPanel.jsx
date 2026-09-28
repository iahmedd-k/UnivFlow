'use client';

import { useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';
import MarkdownRenderer from '../MarkdownRenderer';

/**
 * Tutor tab: shows the assignment broken into requirements, then a chat
 * where the student can ask for explanations or paste their own draft for
 * feedback. Calls api.askTutor(...), which is server-side wired to
 * TUTOR_SYSTEM_PROMPT in lib/prompts.js.
 */
export default function TutorPanel({ assignment }) {
  const { getToken } = useAuth();
  const [breakdown, setBreakdown] = useState(null);
  const [loadingBreakdown, setLoadingBreakdown] = useState(true);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const scrollRef = useRef(null);

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
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

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
        },
        token
      );
      setMessages((m) => [...m, { role: 'tutor', text: reply.text }]);
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

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(0, 2fr)', gap: 16 }}>
      {/* Left Column: Requirements & Concepts */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <section className="product-card" style={{ padding: '18px 20px' }}>
          <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f2f2f5', paddingBottom: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#858998', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Requirements Breakdown
            </span>
            {breakdown?.requirements?.length > 0 && (
              <span className="product-pill">{breakdown.requirements.length} tasks</span>
            )}
          </header>

          {loadingBreakdown ? (
            <div style={{ padding: '16px 0', textAlign: 'center', color: '#858998', fontSize: 11 }}>
              <span className="loading-dot" style={{ display: 'inline-block', marginBottom: 6 }} />
              <p style={{ margin: 0 }}>Analyzing rubric criteria…</p>
            </div>
          ) : breakdown?.requirements?.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 380, overflowY: 'auto' }}>
              {breakdown.requirements.map((req, idx) => (
                <button
                  key={req.id || idx}
                  type="button"
                  onClick={() => send(`Can you walk me through requirement #${idx + 1}: "${req.description}"?`)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: 8,
                    border: '1px solid #ececf2',
                    background: '#fafafd',
                    textAlign: 'left',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#5b4cc6', background: '#eeeafe', padding: '1px 6px', borderRadius: 4 }}>
                      Task {idx + 1}
                    </span>
                    {req.priority && (
                      <span style={{ fontSize: 9, fontWeight: 600, color: req.priority.toLowerCase() === 'high' ? '#b34d4d' : '#858998', textTransform: 'uppercase' }}>
                        {req.priority}
                      </span>
                    )}
                  </div>
                  <p style={{ fontSize: 11, fontWeight: 500, color: '#2c2f3b', margin: 0, lineHeight: 1.4 }}>
                    {req.description}
                  </p>
                  <span style={{ display: 'inline-block', fontSize: 10, fontWeight: 600, color: '#6657d9', marginTop: 4 }}>
                    Ask tutor <Icon name="arrowUpRight" size={13}/>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="product-empty" style={{ padding: '20px 10px' }}>
              <strong>No structured task list</strong>
              <span>Ask the tutor directly for help breaking down the assignment.</span>
            </div>
          )}
        </section>

        {/* Academic Socratic Note */}
        <div className="product-note">
          <strong>Socratic Tutoring:</strong> The AI tutor guides your understanding and points out edge cases. It explains concepts using non-assignment examples without authoring deliverables for you.
        </div>
      </div>

      {/* Right Column: AI Chat Stream Studio */}
      <section className="product-card" style={{ display: 'flex', flexDirection: 'column', height: 560, overflow: 'hidden' }}>
        {/* Chat Studio Topbar */}
        <header style={{ padding: '14px 18px', background: '#fafafd', borderBottom: '1px solid #f0f0f3', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 28, height: 28, borderRadius: 8, background: '#eeeafe', color: '#5b4cc6', display: 'grid', placeItems: 'center', fontSize: 14 }}>
              <Icon name="lightbulb" size={17}/>
            </span>
            <div>
              <strong style={{ fontSize: 12, color: '#2c2f3b', display: 'block' }}>Course Academic Tutor</strong>
              <small style={{ fontSize: 10, color: '#47a887', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#47a887' }} />
                Ready to answer questions
              </small>
            </div>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              onClick={() => setMessages([])}
              style={{ background: 'none', border: 'none', color: '#858998', fontSize: 11, cursor: 'pointer' }}
            >
              Clear chat
            </button>
          )}
        </header>

        {/* Chat History Messages */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: 'auto', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {messages.length === 0 && (
            <div style={{ margin: 'auto', maxWidth: 440, textAlign: 'center', padding: '20px 0' }}>
              <span style={{ width: 42, height: 42, borderRadius: 12, background: '#f0edff', color: '#6657d9', display: 'grid', placeItems: 'center', fontSize: 20, margin: '0 auto 12px' }}>
                <Icon name="lightbulb" size={16}/>
              </span>
              <strong style={{ fontSize: 14, color: '#2c2f3b', display: 'block' }}>
                How can the tutor help you today?
              </strong>
              <p style={{ fontSize: 11, color: '#858998', margin: '6px 0 16px', lineHeight: 1.6 }}>
                Ask about concepts, request help planning your approach, or paste your draft logic for Socratic feedback.
              </p>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, textAlign: 'left' }}>
                {suggestedPrompts.map((p, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => send(p)}
                    style={{
                      padding: '8px 12px',
                      borderRadius: 8,
                      border: '1px solid #ececf2',
                      background: '#ffffff',
                      color: '#454856',
                      fontSize: 11,
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <><Icon name="message" size={13}/> {p}</>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, idx) => (
            <div
              key={idx}
              style={{
                display: 'flex',
                justifyContent: m.role === 'student' ? 'flex-end' : 'flex-start',
                gap: 8,
              }}
            >
              {m.role !== 'student' && (
                <span style={{ width: 24, height: 24, borderRadius: 6, background: '#eeeafe', color: '#5b4cc6', display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>
                  AI
                </span>
              )}
              <div
                style={{
                  maxWidth: '82%',
                  padding: '10px 14px',
                  borderRadius: 10,
                  fontSize: 12,
                  lineHeight: 1.6,
                  whiteSpace: 'pre-wrap',
                  background: m.role === 'student' ? '#6657d9' : '#f4f3f9',
                  color: m.role === 'student' ? '#ffffff' : '#2c2f3b',
                  border: m.role === 'student' ? 'none' : '1px solid #e7e6ee',
                }}
              >
                {m.role === 'student' ? (
                  <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{m.text}</p>
                ) : (
                  <MarkdownRenderer content={m.text} />
                )}
              </div>
            </div>
          ))}

          {sending && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 24, height: 24, borderRadius: 6, background: '#eeeafe', color: '#5b4cc6', display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 700 }}>
                AI
              </span>
              <div style={{ padding: '8px 14px', background: '#f4f3f9', border: '1px solid #e7e6ee', borderRadius: 10, fontSize: 11, color: '#858998', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span className="loading-dot" style={{ width: 6, height: 6 }} />
                <span>Tutor is formulating an explanation…</span>
              </div>
            </div>
          )}
        </div>

        {/* Input Bar */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          style={{
            padding: '12px 16px',
            borderTop: '1px solid #f0f0f3',
            background: '#fafafd',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about a requirement or concept… (Press Enter to send)"
            style={{
              flex: 1,
              height: 38,
              padding: '0 14px',
              border: '1px solid #e4e4eb',
              borderRadius: 8,
              fontSize: 12,
              color: '#2c2f3b',
              outline: 'none',
              background: '#ffffff',
            }}
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="product-action"
            style={{ minHeight: 38, padding: '0 16px', fontSize: 11, cursor: 'pointer' }}
          >
            <span>Ask Tutor <Icon name="send" size={13}/></span>
          </button>
        </form>
      </section>
    </div>
  );
}
