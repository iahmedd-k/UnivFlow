'use client';

import { useState } from 'react';
import Icon from '@/app/dashboard/Icon';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';

const STATUS_STYLE = {
  met: { label: 'Met', icon: 'check', pillClass: 'product-pill success' },
  partial: { label: 'Partial', icon: 'alert', pillClass: 'product-pill warning' },
  missing: { label: 'Missing', icon: 'close', pillClass: 'product-pill error' },
};

export default function ReviewPanel({ assignment }) {
  const { getToken } = useAuth();
  const [text, setText] = useState('');
  const [file, setFile] = useState(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  };

  const runReview = async () => {
    if (!text.trim() && !file) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const token = getToken ? await getToken() : null;
      const data = await api.reviewDraft(assignment.id, { text, file }, token);
      setResult(data);
    } catch (e) {
      setError(e.message || 'Could not run rubric review right now.');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1fr) minmax(0, 1.2fr)', gap: 16 }}>
      {/* Left Column: Draft Input & Attachment Studio */}
      <section className="product-card" style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <span className="eyebrow">PRE-SUBMISSION AUDIT</span>
          <h3 style={{ margin: '3px 0 6px', fontSize: 15, fontWeight: 700, color: '#252837' }}>
            Check Draft Against Rubric
          </h3>
          <p style={{ fontSize: 11, color: '#858998', lineHeight: 1.5, margin: 0 }}>
            Paste your solution or attach your draft file. Uniflow checks requirements, logic completeness, and citations without modifying your submission.
          </p>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#858998' }}>
            <span style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Draft Text / Source</span>
            <span>{text.length} characters</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste your draft report, code, or essay here…"
            rows={10}
            style={{
              width: '100%',
              padding: '12px 14px',
              borderRadius: 8,
              border: '1px solid #e4e4eb',
              background: '#fafafd',
              color: '#2c2f3b',
              fontSize: 12,
              fontFamily: 'ui-monospace, monospace',
              lineHeight: 1.5,
              outline: 'none',
              resize: 'vertical',
            }}
          />
        </div>

        {/* File Attachment Strip */}
        <div style={{ padding: '10px 14px', background: '#f8f8fb', border: '1px solid #ebebf0', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
          <label style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: '#5b4cc6' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon name="paperclip" size={14}/>{file ? 'Change file' : 'Attach draft file'}</span>
            <input
              type="file"
              onChange={handleFile}
              accept=".pdf,.doc,.docx,.txt,.py,.js,.ts,.jsx,.tsx"
              style={{ display: 'none' }}
            />
          </label>
          {file && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, maxWidth: 180 }}>
              <span style={{ fontSize: 11, color: '#2c2f3b', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {file.name}
              </span>
              <button
                type="button"
                onClick={() => setFile(null)}
                style={{ background: 'none', border: 'none', color: '#b34d4d', cursor: 'pointer', fontWeight: 'bold', fontSize: 11 }}
              >
                <Icon name="close" size={13}/>
              </button>
            </div>
          )}
        </div>

        {error && (
          <div className="product-alert" role="alert">
            {error}
          </div>
        )}

        <button
          type="button"
          onClick={runReview}
          disabled={running || (!text.trim() && !file)}
          className="primary-action"
          style={{ width: '100%', minHeight: 38, fontSize: 12, cursor: 'pointer' }}
        >
          {running ? (
            <span>Auditing Draft against Rubric…</span>
          ) : (
            <span><Icon name="search" size={14}/> Run Pre-Submission Review</span>
          )}
        </button>
      </section>

      {/* Right Column: Scorecard & Verification Results */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {!result && !running && (
          <div className="product-card" style={{ padding: '36px 24px', textAlign: 'center', margin: 'auto 0' }}>
            <span style={{ width: 40, height: 40, borderRadius: 10, background: '#f0edff', color: '#6657d9', display: 'grid', placeItems: 'center', fontSize: 18, margin: '0 auto 10px' }}>
              <Icon name="barChart" size={19}/>
            </span>
            <strong style={{ fontSize: 13, color: '#2c2f3b', display: 'block' }}>
              Rubric Scorecard will appear here
            </strong>
            <p style={{ fontSize: 11, color: '#858998', margin: '4px auto 0', maxWidth: 320, lineHeight: 1.5 }}>
              Paste your writing or code to evaluate requirement coverage, rubric alignment, and academic citations.
            </p>
          </div>
        )}

        {running && (
          <div className="product-card" style={{ padding: '40px 24px', textAlign: 'center' }}>
            <span className="loading-dot" style={{ display: 'inline-block', marginBottom: 8 }} />
            <strong style={{ fontSize: 13, color: '#2c2f3b', display: 'block' }}>Evaluating your draft…</strong>
            <p style={{ fontSize: 11, color: '#858998', margin: '4px 0 0' }}>Checking criteria fulfillment and citation validity.</p>
          </div>
        )}

        {result && (
          <>
            {/* Executive Summary Card */}
            <section className="product-card" style={{ padding: '16px 18px', background: '#f8f7ff', border: '1px solid #ded8fa' }}>
              <header style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Icon name="clipboardCheck" size={14}/>
                <span style={{ fontSize: 11, fontWeight: 700, color: '#5b4cc6', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Auditor Verdict
                </span>
              </header>
              <p style={{ fontSize: 12, color: '#2c2f3b', lineHeight: 1.6, margin: 0, fontWeight: 500 }}>
                {result.summary}
              </p>
            </section>

            {/* Requirement Checklist */}
            <section className="product-card" style={{ overflow: 'hidden' }}>
              <header className="product-card-head" style={{ background: '#fafafd' }}>
                <h3 style={{ margin: 0, fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#696d7d' }}>
                  Requirement Coverage
                </h3>
              </header>
              <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                {(result.requirement_coverage || []).map((r, idx) => {
                  const s = STATUS_STYLE[r.status] || STATUS_STYLE.partial;
                  return (
                    <div
                      key={idx}
                      style={{
                        padding: '10px 12px',
                        background: '#fafafd',
                        border: '1px solid #f0f0f4',
                        borderRadius: 7,
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: 10,
                      }}
                    >
                      <span className={s.pillClass} style={{ flexShrink: 0, marginTop: 1 }}>
                        <><Icon name={s.icon} size={12}/>{s.label}</>
                      </span>
                      <div>
                        <strong style={{ display: 'block', fontSize: 12, color: '#2c2f3b' }}>
                          {r.requirement}
                        </strong>
                        <p style={{ margin: '2px 0 0', fontSize: 11, color: '#858998' }}>
                          {r.reason}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* Issues to Fix */}
            {result.issues?.length > 0 && (
              <section className="product-card" style={{ padding: '16px 18px' }}>
                <h3 style={{ margin: '0 0 10px', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#b15252' }}>
                  <Icon name="alert" size={15}/> Recommendations to Revise
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {result.issues.map((issue, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '10px 12px',
                        background: '#fff8f8',
                        border: '1px solid #f1dede',
                        borderRadius: 7,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                        <strong style={{ fontSize: 11, color: '#b15252' }}>{issue.type}</strong>
                        {issue.location && (
                          <span style={{ fontSize: 10, color: '#858998', fontFamily: 'monospace' }}>{issue.location}</span>
                        )}
                      </div>
                      <p style={{ margin: 0, fontSize: 11, color: '#555866' }}>{issue.description}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Citation Flags */}
            {result.citation_check?.length > 0 && (
              <section className="product-card" style={{ padding: '16px 18px' }}>
                <h3 style={{ margin: '0 0 10px', fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#696d7d' }}>
                  Citation & Attribution
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {result.citation_check.map((c, idx) => (
                    <div key={idx} style={{ padding: '10px 12px', background: '#fafafd', border: '1px solid #ececf2', borderRadius: 7 }}>
                      <p style={{ margin: '0 0 3px', fontStyle: 'italic', fontSize: 11, color: '#334155' }}>
                        &ldquo;{c.excerpt}&rdquo;
                      </p>
                      <span style={{ fontSize: 10, color: '#858998' }}>{c.concern}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
