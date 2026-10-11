'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

export default function SolutionPanel({ assignment }) {
  const { getToken } = useAuth();
  const [solution, setSolution] = useState(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [imagePrompt, setImagePrompt] = useState('A clear, simple educational illustration for this assignment. No text or labels.');
  const [generatingImage, setGeneratingImage] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [activeFileTab, setActiveFileTab] = useState(0);
  const [uploadingMaterial, setUploadingMaterial] = useState(false);
  const [materialsList, setMaterialsList] = useState(assignment?.materials || []);

  const handleMaterialUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingMaterial(true);
    setError('');
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.uploadAssignmentMaterial(assignment.id, file, token);
      setNotice(`Uploaded "${file.name}"! Document ready for autonomous solving.`);
      setMaterialsList((prev) => [...prev, { id: res.material_id, title: file.name, material_type: 'local_upload' }]);
    } catch (err) {
      setError(err.message || 'Failed to upload document.');
    } finally {
      setUploadingMaterial(false);
      e.target.value = '';
    }
  };

  const refresh = useCallback(async () => {
    const token = getToken ? await getToken() : null;
    const current = await api.getSolutionStatus(assignment.id, token, { noCache: true });
    setSolution(current);
    setError('');
    return current;
  }, [assignment.id, getToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const current = await api.getSolutionStatus(assignment.id, token, { noCache: true });
        if (!cancelled) {
          setSolution(current);
          setError('');
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Could not load solver status.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [assignment.id, getToken]);

  useEffect(() => {
    if (solution?.status !== 'generating') return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const current = await refresh();
        if (!cancelled && current.status === 'generating') {
          timer = window.setTimeout(poll, 3000);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e.message || 'Retrying solver connection…');
          timer = window.setTimeout(poll, 6000);
        }
      }
    };
    timer = window.setTimeout(poll, 1500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [solution?.status, refresh]);

  const startSolver = async (provider = 'claude_browser') => {
    if (starting || solution?.status === 'generating') return;
    setStarting(true);
    setError('');
    setNotice('');
    setSolution((prev) => ({ ...(prev || {}), status: 'generating' }));
    try {
      const token = getToken ? await getToken() : null;
      await api.generateAssignmentSolution(
        assignment.id,
        { provider, create_google_doc: true },
        token
      );
      if (provider === 'claude_browser') {
        setNotice('Zero-Touch Pipeline Active: Auto-fetching Drive docs, scanning Downloads, opening Chrome, auto-authenticating into Claude with Google, and synthesizing your solution…');
      } else {
        setNotice('The autonomous multi-agent solver has started! Breaking down rubric requirements…');
      }
    } catch (e) {
      setError(e.message || 'Could not start the assignment solver.');
      try {
        await refresh();
      } catch (_) {}
    } finally {
      setStarting(false);
    }
  };

  const openClaudeWindow = async () => {
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.openClaudeBrowser(token);
      setNotice(res.message || 'Chrome window opened for Claude.');
    } catch (e) {
      setError(e.message || 'Could not open Chrome window.');
    }
  };

  const exportGoogleDoc = async () => {
    setExporting(true);
    setError('');
    setNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.exportAssignmentDoc(assignment.id, token);
      setSolution((current) => ({
        ...current,
        google_doc_url: result.doc_url,
        google_doc_id: result.doc_id,
      }));
      setNotice('Report successfully created in your connected Google Drive!');
    } catch (e) {
      setError(e.message || 'Could not create the Google Doc.');
    } finally {
      setExporting(false);
    }
  };

  const generateImage = async () => {
    if (generatingImage || !imagePrompt.trim()) return;
    setGeneratingImage(true);
    setError('');
    setNotice('');
    try {
      const token = getToken ? await getToken() : null;
      const result = await api.generateAssignmentImage(assignment.id, imagePrompt.trim(), token);
      setSolution((current) => ({ ...current, generated_images: result.images || [result.image] }));
      setNotice('Illustration generated and included in the downloadable HTML and Word reports.');
    } catch (e) {
      setError(e.message || 'Could not generate the illustration.');
    } finally {
      setGeneratingImage(false);
    }
  };

  const copyCode = (content, index) => {
    navigator.clipboard.writeText(content);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const downloadSingleFile = (filename, content) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const downloadAllFilesBundle = (filesList) => {
    if (!filesList || !filesList.length) return;
    filesList.forEach((file, idx) => {
      setTimeout(() => {
        downloadSingleFile(file.name || `task_${idx + 1}_solution.py`, file.content);
      }, idx * 250);
    });
  };

  const files = solution?.generated_files || [];
  const outputs = solution?.terminal_outputs || [];
  const screenshots = solution?.terminal_screenshots || [];
  const generatedImages = solution?.generated_images || [];
  const crewAgents = solution?.crew_progress?.agents || [];
  const state = solution?.status || 'not_started';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Alert Notices */}
      {error && (
        <div
          className="flex items-center justify-between gap-3 rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose"
          role="alert"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <div>
            <strong>Solver Notice:</strong> {error}
          </div>
          <button
            type="button"
            onClick={() => setError('')}
            style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            aria-label="Dismiss error"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}
      {notice && (
        <div
          className="flex items-center justify-between gap-3 rounded-lg border border-brand-border bg-brand-bg px-4 py-3 text-sm text-brand-hover"
          role="status"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <div>
            <Icon name="checkCircle" size={14} /> {notice}
          </div>
          <button
            type="button"
            onClick={() => setNotice('')}
            style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            aria-label="Dismiss message"
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}

      {/* Hero Solver Station Card */}
      <section
        className="rounded-xl border border-violet/20 bg-gradient-to-br from-white to-violet-light/40 p-5 shadow-sm sm:p-7"
        style={{
          padding: '24px 28px',
          background: 'linear-gradient(135deg, #ffffff 0%, #f9f8ff 100%)',
          border: '1px solid #e7e3fc',
          borderRadius: 12,
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 20,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ maxWidth: 640 }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '3px 10px',
                background: '#eeeafe',
                color: '#5b4cc6',
                borderRadius: 99,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                marginBottom: 10,
              }}
            >
              <Icon name="sparkles" size={14} />
              <span>Autonomous Solver Engine</span>
            </div>
            <h2
              style={{
                fontSize: 20,
                fontWeight: 700,
                color: '#252837',
                margin: '0 0 6px',
                letterSpacing: '-0.4px',
              }}
            >
              Assignment Solver & Report Generator
            </h2>
            <p style={{ margin: 0, fontSize: 13, color: '#686d80', lineHeight: 1.5 }}>
              Runs the four configured CrewAI specialists in sequence, executes technical files when
              a supported runner is available, and prepares reviewable Google Docs and Word reports
              with actual run output and terminal screenshots.
            </p>
          </div>

          <div>
            {loading ? (
              <span className="inline-flex items-center rounded-full border border-line bg-paper px-3 py-1.5 text-xs font-semibold text-muted">Checking status…</span>
            ) : state === 'generating' ? (
              <span
                className="inline-flex items-center gap-2 rounded-full border border-amber-border bg-amber-bg px-3 py-1.5 text-xs font-semibold text-amber"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <span className="size-2 animate-spin rounded-full border-2 border-amber-border border-t-amber" />
                <span>Generating Solution…</span>
              </span>
            ) : state === 'completed' ? (
              <span
                className="inline-flex items-center gap-2 rounded-full border border-brand-border bg-brand-bg px-3 py-1.5 text-xs font-semibold text-brand-hover"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <Icon name="checkCircle" size={14} />
                <span>Ready for Student Review</span>
              </span>
            ) : state === 'failed' ? (
              <span className="inline-flex items-center rounded-full border border-rose-border bg-rose-bg px-3 py-1.5 text-xs font-semibold text-rose">Execution failed</span>
            ) : (
              <span className="inline-flex items-center rounded-full border border-line bg-paper px-3 py-1.5 text-xs font-semibold text-muted">Ready to start</span>
            )}
          </div>
        </div>

        {/* 4-Step Visual Workflow Pipeline */}
        <div
          style={{
            marginTop: 22,
            padding: '16px 20px',
            background: '#ffffff',
            border: '1px solid #ebebf0',
            borderRadius: 10,
            display: 'grid',
            gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: state !== 'not_started' ? '#f0edff' : '#f4f4f7',
                color: state !== 'not_started' ? '#6657d9' : '#9a9cab',
                display: 'grid',
                placeItems: 'center',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              1
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 11, color: '#2c2f3b' }}>
                Rubric Analysis
              </strong>
              <small style={{ fontSize: 10, color: '#858998' }}>Decompose tasks</small>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background:
                  state === 'completed' || state === 'generating' ? '#f0edff' : '#f4f4f7',
                color: state === 'completed' || state === 'generating' ? '#6657d9' : '#9a9cab',
                display: 'grid',
                placeItems: 'center',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              2
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 11, color: '#2c2f3b' }}>
                Code Synthesis
              </strong>
              <small style={{ fontSize: 10, color: '#858998' }}>Generate solution</small>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: state === 'completed' ? '#f0edff' : '#f4f4f7',
                color: state === 'completed' ? '#6657d9' : '#9a9cab',
                display: 'grid',
                placeItems: 'center',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              3
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 11, color: '#2c2f3b' }}>
                Sandbox Run
              </strong>
              <small style={{ fontSize: 10, color: '#858998' }}>Terminal verification</small>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                width: 28,
                height: 28,
                borderRadius: 8,
                background: state === 'completed' ? '#eaf7f1' : '#f4f4f7',
                color: state === 'completed' ? '#438a71' : '#9a9cab',
                display: 'grid',
                placeItems: 'center',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              4
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 11, color: '#2c2f3b' }}>
                Report Build
              </strong>
              <small style={{ fontSize: 10, color: '#858998' }}>Docs & Word report</small>
            </div>
          </div>
        </div>

        {/* State: Not Started Launch Hub */}
        {state === 'not_started' && (
          <div
            style={{
              marginTop: 20,
              paddingTop: 18,
              borderTop: '1px solid #ecebf3',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              flexWrap: 'wrap',
            }}
          >
            {/* Reference Materials & Local Upload Bar */}
            <div style={{ width: '100%', marginBottom: 14, padding: '12px 14px', background: '#f8f8fc', borderRadius: 8, border: '1px solid #ebebf2' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="fileText" size={15} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: '#333745' }}>
                    Reference Materials & Question Sheets ({materialsList.length} attached)
                  </span>
                </div>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 600, color: '#6657d9', cursor: 'pointer', background: '#ffffff', padding: '4px 10px', borderRadius: 6, border: '1px solid #dcd7fa' }}>
                  <Icon name="upload" size={13} />
                  <span>{uploadingMaterial ? 'Uploading…' : '+ Attach Question Sheet / PDF'}</span>
                  <input
                    type="file"
                    accept=".pdf,.docx,.doc,.txt"
                    onChange={handleMaterialUpload}
                    disabled={uploadingMaterial}
                    style={{ display: 'none' }}
                  />
                </label>
              </div>
              {materialsList.length > 0 && (
                <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {materialsList.map((m, idx) => (
                    <span key={m.id || idx} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, background: '#ffffff', border: '1px solid #e2e2ec', padding: '3px 8px', borderRadius: 5, fontSize: 11, color: '#4b5063' }}>
                      <Icon name="file" size={12} />
                      <span style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.title || 'Attachment'}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 10,
                  background: '#eeeafe',
                  color: '#6657d9',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 18,
                }}
              >
                <Icon name="code" size={18} />
              </div>
              <div>
                <strong style={{ display: 'block', fontSize: 12, color: '#2c2f3b' }}>
                  Zero-Touch Autonomous Pipeline
                </strong>
                <span style={{ fontSize: 11, color: '#858998' }}>
                  Auto-fetches Drive files · Scans Downloads · Auto-signs in with Google
                </span>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => startSolver('claude_browser')}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
                style={{
                  cursor: 'pointer',
                  padding: '10px 18px',
                  fontSize: 13,
                  background: 'linear-gradient(135deg, #d97706, #b45309)',
                  borderColor: '#92400e',
                  boxShadow: '0 2px 8px rgba(180, 83, 9, 0.25)',
                }}
              >
                <span>
                  {starting ? (
                    'Connecting to Claude…'
                  ) : (
                    <>
                      <Icon name="sparkles" size={15} /> Solve with Claude (Browser · Free)
                    </>
                  )}
                </span>
              </button>

              <button
                type="button"
                onClick={() => startSolver('crewai')}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
                style={{ cursor: 'pointer', padding: '10px 18px', fontSize: 13 }}
              >
                <span>
                  {starting ? (
                    'Starting Pipeline…'
                  ) : (
                    <>
                      <Icon name="code" size={15} /> Multi-Agent (Groq/Gemini)
                    </>
                  )}
                </span>
              </button>

              <button
                type="button"
                onClick={openClaudeWindow}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-violet/30 bg-white px-4 text-sm font-semibold text-violet transition hover:bg-violet-light"
                style={{ cursor: 'pointer', padding: '10px 14px', fontSize: 12, color: '#6657d9' }}
                title="Launch or bring Claude Chrome automation window to front"
              >
                <Icon name="external-link" size={14} /> Open Claude Window
              </button>
            </div>
          </div>
        )}

        {/* State: Generating Loader */}
        {state === 'generating' && (
          <div
            style={{
              marginTop: 20,
              padding: '24px',
              borderRadius: 10,
              background: '#ffffff',
              border: '1px solid #e7e3fc',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              textAlign: 'center',
              gap: 12,
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: '50%',
                border: '3px solid #eeeafe',
                borderTopColor: '#6657d9',
                animation: 'spin 1s linear infinite',
              }}
            />
            <div>
              <strong style={{ display: 'block', fontSize: 14, color: '#2c2f3b' }}>
                Autonomous Agent Synthesis in Progress…
              </strong>
              <p
                style={{
                  margin: '4px 0 0',
                  fontSize: 12,
                  color: '#858998',
                  maxWidth: 480,
                }}
              >
                The four CrewAI agents are working in sequence. Progress updates as each specialist finishes.
              </p>
            </div>
          </div>
        )}

        {state === 'generating' && crewAgents.length > 0 && (
          <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
            {crewAgents.map((agent) => (
              <div key={agent.id} style={{ padding: '10px 12px', border: '1px solid #e7e3fc', borderRadius: 9, background: '#fff' }}>
                <strong style={{ display: 'block', fontSize: 11, color: '#2c2f3b' }}>
                  {({ planner: '1 · Planner / Analyzer', theory_research: '2 · Theory / Research', coder_diagram: '3 · Coder / Diagram', reporter_fixer: '4 · Reporter / Fixer' })[agent.id] || agent.id}
                </strong>
                <span style={{ fontSize: 10, color: agent.status === 'completed' ? '#059669' : agent.status === 'failed' ? '#dc2626' : '#858998' }}>
                  {agent.status === 'running' ? 'Working…' : agent.status === 'completed' ? 'Complete' : agent.status === 'not_run' ? 'Not run' : 'Waiting'}
                </span>
                {agent.summary && <p title={agent.summary} style={{ margin: '4px 0 0', color: '#64748b', fontSize: 10, lineHeight: 1.4 }}>{agent.summary}</p>}
              </div>
            ))}
          </div>
        )}

        {/* State: Failed Error Fallback */}
        {state === 'failed' && (
          <div
            style={{
              marginTop: 20,
              padding: '16px 20px',
              borderRadius: 10,
              background: '#fff5f5',
              border: '1px solid #fed7d7',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
            }}
          >
            <div>
              <strong style={{ display: 'block', fontSize: 12, color: '#c53030' }}>
                Solver encountered an issue
              </strong>
              <span style={{ fontSize: 11, color: '#e53e3e' }}>
                {solution?.validation_errors || solution?.error ||
                  'The solver run could not complete. You can retry with fresh parameters.'}
              </span>
            </div>
            <button
              type="button"
              onClick={startSolver}
              disabled={starting}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
              style={{ cursor: 'pointer' }}
            >
              <span>
                <Icon name="refresh" size={13} /> Retry Solver
              </span>
            </button>
          </div>
        )}
      </section>

      {/* State: Completed Results Studio */}
      {state === 'completed' && (
        <>
          {/* Deliverables Action Toolbar */}
          <section
            className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm"
            style={{
              padding: '16px 20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 14,
              flexWrap: 'wrap',
            }}
          >
            <div>
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">Final report & deliverables</span>
              <h3 style={{ margin: '2px 0 0', fontSize: 14, fontWeight: 600, color: '#2c2f3b' }}>
                Generated Reports & Code Bundles
              </h3>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {solution.google_doc_url ? (
                <a
                  href={solution.google_doc_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark"
                  style={{ textDecoration: 'none' }}
                >
                  <span>
                    <Icon name="file" size={14} /> Open Google Doc{' '}
                    <Icon name="externalLink" size={13} />
                  </span>
                </a>
              ) : (
                <button
                  type="button"
                  onClick={exportGoogleDoc}
                  disabled={exporting}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ cursor: 'pointer' }}
                >
                  <span>
                    {exporting ? (
                      'Creating Doc…'
                    ) : (
                      <>
                        <Icon name="fileAdd" size={14} /> Create Google Doc Report
                      </>
                    )}
                  </span>
                </button>
              )}

              {files.length > 0 && (
                <button
                  type="button"
                  onClick={() => downloadAllFilesBundle(files)}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper"
                  style={{ cursor: 'pointer' }}
                  title="Download all generated code files directly"
                >
                  <span>
                    <Icon name="download" size={14} /> Download All Files ({files.length})
                  </span>
                </button>
              )}

              <a
                href={`/api/backend/classroom/assignments/${assignment.id}/solution/report`}
                download={`assignment-${assignment.id}-report.html`}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper"
                style={{ textDecoration: 'none' }}
              >
                <span><Icon name="download" size={14} /> Download HTML Report</span>
              </a>

              <a
                href={`/api/backend/classroom/assignments/${assignment.id}/solution/report/docx`}
                download={`assignment-${assignment.id}-report.docx`}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper"
                style={{ textDecoration: 'none' }}
              >
                <span>
                  <Icon name="download" size={14} /> Download Word (.docx)
                </span>
              </a>

              <button
                type="button"
                onClick={() => startSolver('claude_browser')}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-amber px-4 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-50"
                style={{
                  cursor: 'pointer',
                  background: 'linear-gradient(135deg, #d97706, #b45309)',
                  borderColor: '#92400e',
                }}
                title="Re-run assignment using Claude in your logged-in Chrome browser"
              >
                <span>
                  <Icon name="sparkles" size={13} /> Re-Solve with Claude
                </span>
              </button>

              <button
                type="button"
                onClick={() => startSolver('crewai')}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper disabled:opacity-50"
                style={{ cursor: 'pointer' }}
                title="Regenerate using CrewAI (Groq & Gemini)"
              >
                <span>
                  <Icon name="refresh" size={13} /> Multi-Agent API
                </span>
              </button>
            </div>
          </section>

          <section className="min-w-0 rounded-xl border border-line bg-white p-5 shadow-sm">
            <div style={{ marginBottom: 12 }}>
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">Optional visuals</span>
              <h3 style={{ margin: '2px 0 4px', fontSize: 14, color: '#2c2f3b' }}>Generate an illustration</h3>
              <p style={{ margin: 0, color: '#737888', fontSize: 11, lineHeight: 1.5 }}>
                Pollinations generation is optional and requires a backend API key plus available provider credits. Images appear here and in the downloadable HTML/Word reports.
              </p>
            </div>
            <div style={{ display: 'flex', alignItems: 'stretch', gap: 8, flexWrap: 'wrap' }}>
              <input
                value={imagePrompt}
                onChange={(event) => setImagePrompt(event.target.value)}
                maxLength={800}
                aria-label="Image description"
                placeholder="Describe an educational illustration…"
                style={{ flex: '1 1 360px', minWidth: 220, border: '1px solid #d8dbe4', borderRadius: 8, padding: '9px 11px', fontSize: 12 }}
              />
              <button type="button" className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50" disabled={generatingImage || !imagePrompt.trim()} onClick={generateImage}>
                <Icon name="sparkles" size={14} /> {generatingImage ? 'Generating…' : 'Generate image'}
              </button>
            </div>
            {generatedImages.length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12, marginTop: 16 }}>
                {generatedImages.map((item) => (
                  <figure key={item.id} style={{ margin: 0, border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', background: '#fff' }}>
                    <img src={item.data_uri} alt={item.prompt || 'Generated assignment illustration'} style={{ display: 'block', width: '100%', aspectRatio: '1 / 1', objectFit: 'contain', background: '#f8fafc' }} />
                    <figcaption style={{ padding: 9, color: '#64748b', fontSize: 10, lineHeight: 1.4 }}>{item.prompt}</figcaption>
                  </figure>
                ))}
              </div>
            )}
          </section>

          {/* Modality A: 🎓 Dedicated Academic Essay / Theory Research Paper Viewer */}
          {files.length === 0 && (
            <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
              <header className="flex items-center justify-between gap-4 border-b border-line bg-paper px-5 py-4">
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      background: '#eeeafe',
                      color: '#6657d9',
                      display: 'grid',
                      placeItems: 'center',
                    }}
                  >
                    <Icon name="fileText" size={17} />
                  </div>
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted">Academic research & essay report</p>
                    <h2 style={{ margin: 0, fontSize: 14, color: '#1e293b' }}>
                      Executive Summary, Theoretical Analysis & Discussion
                    </h2>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-border bg-brand-bg px-3 py-1.5 text-xs font-semibold text-brand-hover">
                    📖 {solution.validated_content ? solution.validated_content.split(/\s+/).length : 0} Words
                  </span>
                  <button
                    type="button"
                    onClick={() => copyCode(solution.validated_content || solution.draft_content || '', 999)}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper"
                    style={{ minHeight: 28, padding: '0 10px', fontSize: 11, cursor: 'pointer' }}
                  >
                    {copiedIndex === 999 ? (
                      <>
                        <Icon name="check" size={12} /> Copied!
                      </>
                    ) : (
                      <>
                        <Icon name="copyCode" size={12} /> Copy Full Paper
                      </>
                    )}
                  </button>
                </div>
              </header>

              <div style={{ padding: '24px 28px', background: '#ffffff' }}>
                <div
                  style={{
                    color: '#2d3748',
                    fontSize: 13,
                    lineHeight: 1.75,
                    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {solution.validated_content || solution.draft_content || 'No text content available.'}
                </div>
              </div>
            </section>
          )}

          {/* Modality B: 📂 Dedicated Deliverable Code Files Card (For Programming Labs) */}
          {files.length > 0 && (
            <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
              <header className="flex items-center justify-between gap-4 border-b border-line bg-paper px-5 py-4">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="code" size={17} />
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted">Individual code files</p>
                    <h2 style={{ margin: 0, fontSize: 13 }}>
                      Standalone Source Files ({files.length})
                    </h2>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => downloadAllFilesBundle(files)}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper"
                  style={{ minHeight: 26, padding: '0 10px', fontSize: 11, cursor: 'pointer' }}
                >
                  <Icon name="download" size={12} /> Download All
                </button>
              </header>

              <div style={{ padding: '16px 20px' }}>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
                    gap: 12,
                    marginBottom: 16,
                  }}
                >
                  {files.map((file, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: '12px 14px',
                        background: activeFileTab === idx ? '#f8f6ff' : '#ffffff',
                        border:
                          activeFileTab === idx ? '1px solid #7c3aed' : '1px solid #e2e8f0',
                        borderRadius: 8,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 10,
                        transition: 'all 0.15s ease',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          overflow: 'hidden',
                          cursor: 'pointer',
                        }}
                        onClick={() => setActiveFileTab(idx)}
                      >
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 6,
                            background: '#eeeafe',
                            color: '#6657d9',
                            display: 'grid',
                            placeItems: 'center',
                            flexShrink: 0,
                          }}
                        >
                          <Icon name="codeFile" size={15} />
                        </div>
                        <div style={{ overflow: 'hidden' }}>
                          <strong
                            style={{
                              display: 'block',
                              fontSize: 12,
                              color: '#1e293b',
                              fontFamily: 'monospace',
                              whiteSpace: 'nowrap',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                            }}
                          >
                            {file.name}
                          </strong>
                          <span style={{ fontSize: 10, color: '#64748b' }}>
                            Task {file.task || idx + 1} · {String(file.language || 'py').toUpperCase()} ·{' '}
                            {file.content ? file.content.split('\n').length : 0} lines
                          </span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                        <button
                          type="button"
                          onClick={() => copyCode(file.content, idx)}
                          title="Copy Code"
                          style={{
                            padding: '4px 8px',
                            background: '#f1f5f9',
                            border: '1px solid #cbd5e1',
                            borderRadius: 6,
                            fontSize: 10,
                            cursor: 'pointer',
                            color: '#334155',
                          }}
                        >
                          {copiedIndex === idx ? <Icon name="check" size={12} /> : <Icon name="copyCode" size={12} />}
                        </button>
                        <button
                          type="button"
                          onClick={() => downloadSingleFile(file.name, file.content)}
                          title={`Download ${file.name}`}
                          style={{
                            padding: '4px 8px',
                            background: '#6657d9',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: 6,
                            fontSize: 10,
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            fontWeight: 600,
                          }}
                        >
                          <Icon name="download" size={12} /> Download
                        </button>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Active File Code Inspector */}
                {files[activeFileTab] && (
                  <div
                    style={{
                      borderRadius: 8,
                      border: '1px solid #e2e8f0',
                      overflow: 'hidden',
                      background: '#0f172a',
                    }}
                  >
                    <header
                      style={{
                        padding: '10px 14px',
                        background: '#1e293b',
                        borderBottom: '1px solid #334155',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <strong style={{ color: '#f8fafc', fontSize: 12, fontFamily: 'monospace' }}>
                          {files[activeFileTab].name}
                        </strong>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '2px 6px',
                            background: '#334155',
                            color: '#94a3b8',
                            borderRadius: 4,
                            textTransform: 'uppercase',
                          }}
                        >
                          {String(files[activeFileTab].language || 'python')}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <button
                          type="button"
                          onClick={() => copyCode(files[activeFileTab].content, activeFileTab)}
                          style={{
                            padding: '4px 10px',
                            background: '#334155',
                            color: '#e2e8f0',
                            border: 'none',
                            borderRadius: 5,
                            fontSize: 11,
                            cursor: 'pointer',
                          }}
                        >
                          {copiedIndex === activeFileTab ? '✓ Copied' : 'Copy'}
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            downloadSingleFile(
                              files[activeFileTab].name,
                              files[activeFileTab].content
                            )
                          }
                          style={{
                            padding: '4px 10px',
                            background: '#6657d9',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: 5,
                            fontSize: 11,
                            cursor: 'pointer',
                            fontWeight: 600,
                          }}
                        >
                          Download File
                        </button>
                      </div>
                    </header>
                    <pre
                      style={{
                        padding: '16px 18px',
                        margin: 0,
                        color: '#f8fafc',
                        fontSize: 11,
                        lineHeight: 1.6,
                        overflowX: 'auto',
                        maxHeight: 320,
                        fontFamily: 'ui-monospace, monospace',
                      }}
                    >
                      <code>{files[activeFileTab].content}</code>
                    </pre>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* 📑 Structured Report Section: Task Statement ➔ Code ➔ Screenshot (Only for Code Labs) */}
          {files.length > 0 && (
            <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-white shadow-sm">
              <header className="flex items-center justify-between gap-4 border-b border-line bg-paper px-5 py-4">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="fileText" size={17} />
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted">Final report structure</p>
                    <h2 style={{ margin: 0, fontSize: 13 }}>
                      Task Statement, Implementation Code & Execution Evidence
                    </h2>
                  </div>
                </div>
                <span className="inline-flex items-center rounded-full border border-brand-border bg-brand-bg px-3 py-1.5 text-xs font-semibold text-brand-hover">Labeled & formatted for Google Docs</span>
              </header>

            <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 20 }}>
              {files.map((file, idx) => {
                const output = outputs.find(
                  (o) => o.filename === file.name || String(o.task) === String(file.task)
                );
                const screenshot = screenshots.find(
                  (s) => s.filename === file.name || String(s.task) === String(file.task)
                );
                return (
                  <article
                    key={idx}
                    style={{
                      border: '1px solid #e2e8f0',
                      borderRadius: 10,
                      overflow: 'hidden',
                      background: '#ffffff',
                    }}
                  >
                    {/* 1. Task Statement Header */}
                    <div
                      style={{
                        padding: '12px 16px',
                        background: '#f8fafc',
                        borderBottom: '1px solid #e2e8f0',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span
                          style={{
                            padding: '3px 8px',
                            borderRadius: 99,
                            background: '#eeeafe',
                            color: '#6657d9',
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          Task {file.task || idx + 1}
                        </span>
                        <strong style={{ fontSize: 13, color: '#1e293b' }}>
                          {file.title || `Deliverable: ${file.name}`}
                        </strong>
                        <span
                          style={{
                            fontSize: 10,
                            padding: '2px 8px',
                            background: '#f1f5f9',
                            color: '#475569',
                            borderRadius: 6,
                            fontWeight: 600,
                            border: '1px solid #e2e8f0',
                          }}
                        >
                          🛠️ {screenshot?.tool || output?.tool || (file.name.endsWith('.mmd') || file.name.endsWith('.xml') ? 'Mermaid / Draw.io Tool' : `${String(file.language || 'py').toUpperCase()} Runner`)}
                        </span>
                      </div>
                      <span
                        style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: '2px 8px',
                          borderRadius: 99,
                          background: output?.status === 'passed' ? '#10b98122' : output ? '#f43f5e22' : '#f1f5f9',
                          color: output?.status === 'passed' ? '#059669' : output ? '#dc2626' : '#64748b',
                          border:
                            output?.status === 'passed'
                              ? '1px solid #10b98144'
                              : output ? '1px solid #f43f5e44' : '1px solid #e2e8f0',
                        }}
                      >
                        {output?.status === 'passed'
                          ? `✓ Run passed (Exit ${output.exit_code ?? 0})`
                          : output
                            ? `Run ${String(output.status || 'checked').replaceAll('_', ' ')}`
                            : 'Not executed'}
                      </span>
                    </div>

                    <div style={{ padding: '16px' }}>
                      {/* Task Objective Description */}
                      <p style={{ margin: '0 0 12px', fontSize: 12, color: '#475569', lineHeight: 1.5 }}>
                        <strong>Objective: </strong>
                        {file.description ||
                          `Implement standalone module ${file.name} adhering to assignment rubric requirements and verifying outputs.`}
                      </p>

                      {/* 2. Code Listing Box */}
                      <div
                        style={{
                          borderRadius: 8,
                          border: '1px solid #e2e8f0',
                          overflow: 'hidden',
                          marginBottom: 14,
                        }}
                      >
                        <div
                          style={{
                            padding: '8px 12px',
                            background: '#1e293b',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                        >
                          <span style={{ color: '#94a3b8', fontSize: 11, fontFamily: 'monospace' }}>
                            {file.name.endsWith('.mmd') || file.name.endsWith('.xml') ? '📊' : '💻'} {file.name}
                          </span>
                          <button
                            type="button"
                            onClick={() => downloadSingleFile(file.name, file.content)}
                            style={{
                              padding: '3px 8px',
                              background: '#334155',
                              color: '#ffffff',
                              border: 'none',
                              borderRadius: 4,
                              fontSize: 10,
                              cursor: 'pointer',
                            }}
                          >
                            Download .{file.name.split('.').pop()}
                          </button>
                        </div>
                        <pre
                          style={{
                            margin: 0,
                            padding: '12px 14px',
                            background: '#0f172a',
                            color: '#e2e8f0',
                            fontSize: 11,
                            lineHeight: 1.5,
                            maxHeight: 180,
                            overflowY: 'auto',
                            fontFamily: 'ui-monospace, monospace',
                          }}
                        >
                          <code>{file.content}</code>
                        </pre>
                      </div>

                      {/* 3. Terminal Execution Output & Screenshot */}
                      {(output || screenshot) && (
                        <div
                          style={{
                            borderRadius: 8,
                            border: '1px solid #e2e8f0',
                            overflow: 'hidden',
                            background: '#0b0f19',
                          }}
                        >
                          <div
                            style={{
                              padding: '8px 12px',
                              background: '#161f30',
                              borderBottom: '1px solid #232d42',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                            }}
                          >
                            <span style={{ color: '#38bdf8', fontSize: 11, fontFamily: 'monospace' }}>
                              📸 Execution Evidence & Output ({screenshot?.tool || output?.tool || 'Cloud Runner'})
                            </span>
                            <span style={{ color: '#34d399', fontSize: 10, fontFamily: 'monospace' }}>
                              Exit code: {output?.exit_code ?? 0}
                            </span>
                          </div>

                          {screenshot?.data_uri ? (
                            <div style={{ padding: '12px 14px', background: '#0b0f19', display: 'flex', justifyContent: 'center' }}>
                              <img
                                src={screenshot.data_uri}
                                alt={`Execution evidence for Task ${file.task || idx + 1}`}
                                style={{ width: '100%', borderRadius: 8, border: '1px solid #2d3748', display: 'block' }}
                              />
                            </div>
                          ) : (
                            <pre
                              style={{
                                margin: 0,
                                padding: '12px 14px',
                                color: '#34d399',
                                fontSize: 11,
                                lineHeight: 1.5,
                                fontFamily: 'ui-monospace, monospace',
                                maxHeight: 180,
                                overflowY: 'auto',
                              }}
                            >
                              <code>
                                {output?.command ? `$ ${output.command}\n` : ''}
                                {output?.terminal_output || 'No terminal screenshot was available for this artifact.'}
                              </code>
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
          )}

          {/* ⚡ Auto-Trigger & Review Workflow Explainer */}
          <section
            className="min-w-0 rounded-xl border border-line bg-white p-5 shadow-sm"
            style={{
              padding: '16px 20px',
              background: '#f8f7fe',
              border: '1px solid #e5e0fb',
              borderRadius: 10,
              display: 'flex',
              alignItems: 'flex-start',
              gap: 14,
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 8,
                background: '#eeeafe',
                color: '#6657d9',
                display: 'grid',
                placeItems: 'center',
                flexShrink: 0,
              }}
            >
              <Icon name="sparkles" size={18} />
            </div>
            <div>
              <strong style={{ display: 'block', fontSize: 13, color: '#2c2f3b', marginBottom: 4 }}>
                Autonomous Background Trigger & User Review Flow
              </strong>
              <p style={{ margin: 0, fontSize: 12, color: '#686d80', lineHeight: 1.5 }}>
                When a new assignment is detected from Google Classroom or the University Portal, the
                autonomous pipeline automatically decomposes tasks, generates standalone code files,
                runs sandbox verification, and composes the final report in Google Docs. It stages the
                deliverables under the <strong>Pre-Submit Review</strong> tab for your inspection before
                final submission.
              </p>
            </div>
          </section>

          <div className="rounded-lg border border-amber-border bg-amber-bg p-4 text-sm leading-6 text-amber">
            <strong>Academic Integrity Reminder:</strong> Review all generated code files and terminal
            run outputs before turning in your work. Verify that all requirements set by the instructor
            are addressed.
          </div>
        </>
      )}
    </div>
  );
}
