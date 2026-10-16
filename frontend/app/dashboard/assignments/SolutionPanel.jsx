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
  const [refreshingStatus, setRefreshingStatus] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [imagePrompt, setImagePrompt] = useState('A clear, simple educational illustration for this assignment. No text or labels.');
  const [generatingImage, setGeneratingImage] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [claudeViewerUrl, setClaudeViewerUrl] = useState('');
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [activeFileTab, setActiveFileTab] = useState(0);
  const [selectedTaskTab, setSelectedTaskTab] = useState('all');
  const [uploadingMaterial, setUploadingMaterial] = useState(false);
  const [uploadedMaterials, setUploadedMaterials] = useState([]);
  const materialsList = [...(assignment?.materials || []), ...uploadedMaterials];

  const claudeRateLimit = solution?.claude_rate_limit || (
    typeof solution?.validation_errors === 'string' &&
    solution.validation_errors.toLowerCase().includes('claude free tier limit reached')
      ? { is_limited: true, message: solution.validation_errors }
      : null
  );

  const handleMaterialUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingMaterial(true);
    setError('');
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.uploadAssignmentMaterial(assignment.id, file, token);
      setNotice(`Uploaded "${file.name}"! Document ready for autonomous solving.`);
      setUploadedMaterials((prev) => [...prev, { id: res.material_id, title: file.name, material_type: 'local_upload' }]);
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
        setNotice('Claude pipeline active: preparing assignment materials and connecting to your private hosted browser. Sign in through Settings if this is your first run.');
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

  const refreshSolverStatus = async () => {
    setRefreshingStatus(true);
    setError('');
    try {
      await refresh();
    } catch (e) {
      setError(e.message || 'Could not refresh solver status.');
    } finally {
      setRefreshingStatus(false);
    }
  };

  const openClaudeWindow = async () => {
    try {
      const token = getToken ? await getToken() : null;
      const res = await api.openClaudeBrowser(token);
      setClaudeViewerUrl(res.viewer_url || '');
      setNotice(res.message || 'Your private hosted Claude browser is ready.');
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

  const crewProgress = solution?.crew_progress;
  const isGenerating = state === 'generating' || starting;
  const activeStep = crewProgress?.current_step || (starting ? 1 : 2);
  const totalSteps = crewProgress?.total_steps || 5;
  const stepTitle = crewProgress?.step_title || (starting ? 'Connecting to Solver' : 'Synthesizing Solution');
  const stepDetail = crewProgress?.detail || (starting ? 'Initializing browser and preparing materials...' : 'Claude is generating solution code and analysis...');

  const getStepStyle = (stepNum) => {
    let isDone = false;
    let isActive = false;
    if (state === 'completed') {
      isDone = true;
    } else if (isGenerating) {
      if (stepNum === 1) {
        isDone = activeStep > 1;
        isActive = activeStep === 1;
      } else if (stepNum === 2) {
        isDone = activeStep > 3;
        isActive = activeStep === 2 || activeStep === 3;
      } else if (stepNum === 3) {
        isDone = activeStep > 4;
        isActive = activeStep === 4;
      } else if (stepNum === 4) {
        isDone = false;
        isActive = activeStep >= 5;
      }
    }
    return {
      bg: isDone ? '#eaf7f1' : isActive ? '#eeeafe' : '#f4f4f7',
      color: isDone ? '#438a71' : isActive ? '#6657d9' : '#9a9cab',
      boxShadow: isActive ? '0 0 0 2px #6657d9' : 'none',
      isDone,
      isActive,
    };
  };

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

      {/* Hero Solver Station Card (shown while starting/running) */}
      {state !== 'completed' && (
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
            ) : isGenerating ? (
              <span
                className="inline-flex items-center gap-2 rounded-full border border-amber-border bg-amber-bg px-3 py-1.5 text-xs font-semibold text-amber"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                <span className="size-2 animate-spin rounded-full border-2 border-amber-border border-t-amber" />
                <span>{stepTitle ? `${stepTitle}…` : 'Generating Solution…'}</span>
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

        {/* Claude Free Tier Rate Limit Banner */}
        {claudeRateLimit && (
          <div
            style={{
              marginTop: 18,
              padding: '14px 20px',
              borderRadius: 10,
              background: '#fffbeb',
              border: '1px solid #fde68a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 22 }}>⏳</span>
              <div>
                <strong style={{ display: 'block', fontSize: 13, color: '#92400e' }}>
                  Claude Free Tier Message Limit Reached
                </strong>
                <span style={{ fontSize: 12, color: '#b45309', lineHeight: 1.4 }}>
                  {claudeRateLimit.message || 'Claude is temporarily at capacity. The limit will reset automatically.'}
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                onClick={() => startSolver('crewai')}
                disabled={starting}
                className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg bg-violet px-3.5 text-xs font-semibold text-white shadow-sm transition hover:bg-violet-dark"
                style={{ cursor: 'pointer', background: '#6657d9' }}
              >
                <Icon name="code" size={13} />
                <span>Solve with Multi-Agent (Groq/Gemini)</span>
              </button>
            </div>
          </div>
        )}

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
          {[
            { num: 1, title: 'Rubric Analysis', sub: 'Decompose tasks' },
            { num: 2, title: 'Code Synthesis', sub: 'Generate solution' },
            { num: 3, title: 'Sandbox Run', sub: 'Terminal verification' },
            { num: 4, title: 'Report Build', sub: 'Docs & Word report' },
          ].map(({ num, title, sub }) => {
            const style = getStepStyle(num);
            return (
              <div
                key={num}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '6px 8px',
                  borderRadius: 8,
                  boxShadow: style.boxShadow,
                  background: style.isActive ? '#faf9ff' : 'transparent',
                  transition: 'all 0.3s ease',
                }}
              >
                <span
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 8,
                    background: style.bg,
                    color: style.color,
                    display: 'grid',
                    placeItems: 'center',
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  {style.isDone ? <Icon name="check" size={14} /> : num}
                </span>
                <div>
                  <strong style={{ display: 'block', fontSize: 11, color: style.isActive ? '#5b4cc6' : '#2c2f3b' }}>
                    {title}
                  </strong>
                  <small style={{ fontSize: 10, color: style.isActive ? '#6657d9' : '#858998' }}>
                    {style.isActive ? 'In progress…' : sub}
                  </small>
                </div>
              </div>
            );
          })}
        </div>

        {/* Real-time Solver Progress Indicator with Live Step Subtext */}
        {isGenerating && (
          <div
            style={{
              marginTop: 18,
              padding: '16px 20px',
              background: 'linear-gradient(135deg, #fbfaff 0%, #f4f1fe 100%)',
              border: '1px solid #dcd7fa',
              borderRadius: 10,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              boxShadow: '0 2px 8px rgba(102, 87, 217, 0.06)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: '#7c3aed',
                    boxShadow: '0 0 0 3px rgba(124, 58, 237, 0.2)',
                  }}
                />
                <span style={{ fontSize: 13, fontWeight: 700, color: '#312e81' }}>
                  Step {activeStep} of {totalSteps}: {stepTitle}
                </span>
              </div>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: '#6d28d9',
                  background: '#ede9fe',
                  padding: '2px 8px',
                  borderRadius: 6,
                }}
              >
                Live Solver Pipeline
              </span>
            </div>

            {/* Progress Track */}
            <div
              style={{
                width: '100%',
                height: 6,
                background: '#e0e7ff',
                borderRadius: 99,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${Math.min(100, Math.max(15, (activeStep / totalSteps) * 100))}%`,
                  background: 'linear-gradient(90deg, #6366f1, #8b5cf6)',
                  borderRadius: 99,
                  transition: 'width 0.5s ease',
                }}
              />
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <p style={{ margin: 0, fontSize: 12, color: '#4b5563', lineHeight: 1.4, fontWeight: 500 }}>
                {stepDetail}
              </p>
              <span style={{ fontSize: 11, color: '#9ca3af', whiteSpace: 'nowrap' }}>
                Auto-updating
              </span>
            </div>
          </div>
        )}

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
                  Claude Browser Pipeline
                </strong>
                <span style={{ fontSize: 11, color: '#858998' }}>
                  Uses only materials attached to this assignment · Opens Uniflow’s persistent browser profile
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
                title="Start your private hosted Claude browser"
              >
                <Icon name="external-link" size={14} /> Open Claude Window
              </button>
              {claudeViewerUrl && (
                <a
                  href={claudeViewerUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-violet/30 bg-white px-4 text-xs font-semibold text-violet"
                >
                  Open private browser
                </a>
              )}
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
                The solver is analyzing the assignment, preparing its task deliverables, and building the final report.
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
            <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
              <button
                type="button"
                onClick={refreshSolverStatus}
                disabled={refreshingStatus}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-4 text-sm font-semibold text-ink transition hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50"
                style={{ cursor: 'pointer' }}
              >
                <Icon name="refresh" size={13} /> {refreshingStatus ? 'Refreshing…' : 'Refresh status'}
              </button>
              <button
                type="button"
                onClick={startSolver}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
                style={{ cursor: 'pointer' }}
              >
                <Icon name="refresh" size={13} /> Retry Solver
              </button>
            </div>
          </div>
        )}
        </section>
      )}

      {/* State: Completed Results Studio */}
      {state === 'completed' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          {/* 1. Sleek Action Header Card */}
          <section
            className="rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              flexWrap: 'wrap',
              background: 'linear-gradient(135deg, #ffffff 0%, #faf8ff 100%)',
              border: '1px solid #e7e3fc',
              borderRadius: 12,
            }}
          >
            <div>
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '3px 10px',
                  background: '#ecfdf5',
                  color: '#059669',
                  borderRadius: 99,
                  fontSize: 11,
                  fontWeight: 700,
                  marginBottom: 8,
                  border: '1px solid #a7f3d0',
                }}
              >
                <Icon name="checkCircle" size={13} />
                <span>Solution Ready · Verified</span>
              </div>
              <h2
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: '#1e293b',
                  margin: '0 0 4px',
                  letterSpacing: '-0.3px',
                }}
              >
                Assignment Deliverables & Final Report
              </h2>
              <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>
                {files.length > 0
                  ? `${files.length} standalone task deliverables decomposed, code executed, and terminal screenshots embedded.`
                  : 'Academic paper and theoretical analysis compiled for submission.'}
              </p>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {solution.google_doc_url ? (
                <a
                  href={solution.google_doc_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark shadow-sm"
                  style={{ textDecoration: 'none', background: '#6657d9' }}
                >
                  <Icon name="file" size={15} />
                  <span>Open Google Doc</span>
                  <Icon name="externalLink" size={13} />
                </a>
              ) : (
                <button
                  type="button"
                  onClick={exportGoogleDoc}
                  disabled={exporting}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-violet px-4 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:cursor-not-allowed disabled:opacity-50"
                  style={{ cursor: 'pointer', background: '#6657d9' }}
                >
                  <Icon name="fileAdd" size={15} />
                  <span>{exporting ? 'Creating Doc…' : 'Create Google Doc Report'}</span>
                </button>
              )}

              {files.length > 0 && (
                <button
                  type="button"
                  onClick={() => downloadAllFilesBundle(files)}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 text-xs font-semibold text-ink transition hover:bg-paper shadow-sm"
                  style={{ cursor: 'pointer' }}
                  title="Download all code files"
                >
                  <Icon name="download" size={13} />
                  <span>Download Code (.zip)</span>
                </button>
              )}

              <a
                href={`/api/backend/classroom/assignments/${assignment.id}/solution/report/docx`}
                download={`assignment-${assignment.id}-report.docx`}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 text-xs font-semibold text-ink transition hover:bg-paper shadow-sm"
                style={{ textDecoration: 'none' }}
              >
                <Icon name="download" size={13} />
                <span>Word (.docx)</span>
              </a>

              <a
                href={`/api/backend/classroom/assignments/${assignment.id}/solution/report`}
                download={`assignment-${assignment.id}-report.html`}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-line bg-white px-3.5 text-xs font-semibold text-ink transition hover:bg-paper shadow-sm"
                style={{ textDecoration: 'none' }}
              >
                <Icon name="download" size={13} />
                <span>HTML</span>
              </a>

              <button
                type="button"
                onClick={() => startSolver('claude_browser')}
                disabled={starting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-amber/40 bg-amber-50 px-3 text-xs font-semibold text-amber-800 transition hover:bg-amber-100 disabled:opacity-50"
                style={{ cursor: 'pointer' }}
                title="Re-run assignment solver with Claude"
              >
                <Icon name="sparkles" size={13} />
                <span>Re-Solve</span>
              </button>
            </div>
          </section>

          {/* 2. Task Selection Filter Pills (when multiple tasks exist) */}
          {files.length > 1 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflowX: 'auto', paddingBottom: 2 }}>
              <button
                type="button"
                onClick={() => setSelectedTaskTab('all')}
                style={{
                  padding: '6px 16px',
                  borderRadius: 99,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  border: selectedTaskTab === 'all' ? '1px solid #6657d9' : '1px solid #e2e8f0',
                  background: selectedTaskTab === 'all' ? '#eeeafe' : '#ffffff',
                  color: selectedTaskTab === 'all' ? '#6657d9' : '#64748b',
                  transition: 'all 0.15s ease',
                }}
              >
                All Tasks ({files.length})
              </button>
              {files.map((file, idx) => {
                const taskNum = file.task || idx + 1;
                const isSelected = String(selectedTaskTab) === String(taskNum);
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setSelectedTaskTab(String(taskNum))}
                    style={{
                      padding: '6px 16px',
                      borderRadius: 99,
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: 'pointer',
                      border: isSelected ? '1px solid #6657d9' : '1px solid #e2e8f0',
                      background: isSelected ? '#eeeafe' : '#ffffff',
                      color: isSelected ? '#6657d9' : '#64748b',
                      transition: 'all 0.15s ease',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Task {taskNum}
                  </button>
                );
              })}
            </div>
          )}

          {/* 3. Unified Task Cards */}
          {files.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
              {files
                .filter(
                  (file, idx) =>
                    selectedTaskTab === 'all' ||
                    String(file.task || idx + 1) === String(selectedTaskTab)
                )
                .map((file, idx) => {
                  const isNotebook = file.name.endsWith('.ipynb');
                  const isDiagram =
                    file.name.endsWith('.drawio.xml') ||
                    file.name.endsWith('.mmd') ||
                    file.name.endsWith('.xml');
                  const output = outputs.find(
                    (o) =>
                      o.filename === file.name || String(o.task) === String(file.task)
                  );
                  const screenshot = screenshots.find(
                    (s) =>
                      s.filename === file.name || String(s.task) === String(file.task)
                  );
                  const langLabel = isNotebook
                    ? 'JUPYTER NOTEBOOK'
                    : isDiagram
                    ? 'DRAW.IO XML'
                    : String(file.language || file.name.split('.').pop() || 'CODE').toUpperCase();

                  return (
                    <article
                      key={idx}
                      style={{
                        border: '1px solid #e2e8f0',
                        borderRadius: 12,
                        overflow: 'hidden',
                        background: '#ffffff',
                        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
                      }}
                    >
                      {/* Card Header Bar */}
                      <header
                        style={{
                          padding: '12px 18px',
                          background: '#f8fafc',
                          borderBottom: '1px solid #e2e8f0',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 12,
                          flexWrap: 'wrap',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span
                            style={{
                              padding: '3px 10px',
                              borderRadius: 99,
                              background: '#eeeafe',
                              color: '#6657d9',
                              fontSize: 11,
                              fontWeight: 700,
                            }}
                          >
                            Task {file.task || idx + 1}
                          </span>
                          <strong
                            style={{
                              fontSize: 13,
                              color: '#0f172a',
                              fontFamily: 'monospace',
                            }}
                          >
                            {file.name}
                          </strong>
                          <span
                            style={{
                              fontSize: 10,
                              padding: '2px 8px',
                              background: '#e2e8f0',
                              color: '#475569',
                              borderRadius: 4,
                              fontWeight: 700,
                              letterSpacing: '0.04em',
                            }}
                          >
                            {langLabel}
                          </span>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <span
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              padding: '3px 10px',
                              borderRadius: 99,
                              background: '#ecfdf5',
                              color: '#059669',
                              border: '1px solid #a7f3d0',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                            }}
                          >
                            <Icon name="check" size={12} />
                            <span>
                              {isNotebook ? 'Google Colab Ready' : 'Execution Verified'}
                            </span>
                          </span>

                          <button
                            type="button"
                            onClick={() => copyCode(file.content, idx)}
                            style={{
                              padding: '5px 10px',
                              background: '#ffffff',
                              border: '1px solid #cbd5e1',
                              borderRadius: 6,
                              fontSize: 11,
                              cursor: 'pointer',
                              color: '#334155',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontWeight: 500,
                            }}
                          >
                            {copiedIndex === idx ? (
                              <>
                                <Icon name="check" size={12} /> Copied!
                              </>
                            ) : (
                              <>
                                <Icon name="copyCode" size={12} /> Copy Code
                              </>
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={() => downloadSingleFile(file.name, file.content)}
                            style={{
                              padding: '5px 12px',
                              background: '#6657d9',
                              color: '#ffffff',
                              border: 'none',
                              borderRadius: 6,
                              fontSize: 11,
                              cursor: 'pointer',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 4,
                              fontWeight: 600,
                            }}
                          >
                            <Icon name="download" size={12} />
                            <span>Download</span>
                          </button>
                        </div>
                      </header>

                      <div
                        style={{
                          padding: '18px 20px',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 16,
                        }}
                      >
                        {/* 1. Problem Statement / Question */}
                        {file.description && (
                          <div
                            style={{
                              padding: '12px 14px',
                              background: '#f8fafc',
                              border: '1px solid #e2e8f0',
                              borderRadius: 8,
                            }}
                          >
                            <span
                              style={{
                                display: 'block',
                                fontSize: 11,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                color: '#64748b',
                                letterSpacing: '0.05em',
                                marginBottom: 4,
                              }}
                            >
                              Problem Statement / Requirements
                            </span>
                            <p
                              style={{
                                margin: 0,
                                fontSize: 13,
                                color: '#334155',
                                lineHeight: 1.5,
                              }}
                            >
                              {file.description}
                            </p>
                          </div>
                        )}

                        {/* 2. Terminal Execution Screenshot Evidence */}
                        {(screenshot?.data_uri || output?.terminal_output) && !isNotebook && (
                          <div>
                            <span
                              style={{
                                display: 'block',
                                fontSize: 11,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                color: '#64748b',
                                letterSpacing: '0.05em',
                                marginBottom: 6,
                              }}
                            >
                              Terminal Output & Execution Screenshot
                            </span>
                            {screenshot?.data_uri ? (
                              <div
                                style={{
                                  borderRadius: 8,
                                  overflow: 'hidden',
                                  border: '1px solid #334155',
                                  background: '#0f172a',
                                  padding: 10,
                                  display: 'flex',
                                  justifyContent: 'center',
                                }}
                              >
                                <img
                                  src={screenshot.data_uri}
                                  alt={`Terminal output for Task ${file.task || idx + 1}`}
                                  style={{
                                    width: '100%',
                                    maxWidth: 780,
                                    borderRadius: 6,
                                    display: 'block',
                                  }}
                                />
                              </div>
                            ) : (
                              <div
                                style={{
                                  borderRadius: 8,
                                  border: '1px solid #1e293b',
                                  background: '#0f172a',
                                  overflow: 'hidden',
                                }}
                              >
                                <div
                                  style={{
                                    padding: '6px 12px',
                                    background: '#1e293b',
                                    borderBottom: '1px solid #334155',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 6,
                                  }}
                                >
                                  <div
                                    style={{
                                      width: 10,
                                      height: 10,
                                      borderRadius: '50%',
                                      background: '#ef4444',
                                    }}
                                  />
                                  <div
                                    style={{
                                      width: 10,
                                      height: 10,
                                      borderRadius: '50%',
                                      background: '#f59e0b',
                                    }}
                                  />
                                  <div
                                    style={{
                                      width: 10,
                                      height: 10,
                                      borderRadius: '50%',
                                      background: '#10b981',
                                    }}
                                  />
                                  <span
                                    style={{
                                      fontSize: 11,
                                      color: '#94a3b8',
                                      fontFamily: 'monospace',
                                      marginLeft: 8,
                                    }}
                                  >
                                    Terminal Output
                                  </span>
                                </div>
                                <pre
                                  style={{
                                    margin: 0,
                                    padding: '12px 14px',
                                    color: '#cbd5e1',
                                    fontSize: 11,
                                    lineHeight: 1.5,
                                    fontFamily: 'ui-monospace, monospace',
                                    maxHeight: 200,
                                    overflowY: 'auto',
                                  }}
                                >
                                  <code>
                                    {output?.command ? `$ ${output.command}\n` : ''}
                                    {output?.terminal_output || ''}
                                  </code>
                                </pre>
                              </div>
                            )}
                          </div>
                        )}

                        {/* 3. Source Code Implementation */}
                        <div>
                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              marginBottom: 6,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 11,
                                fontWeight: 700,
                                textTransform: 'uppercase',
                                color: '#64748b',
                                letterSpacing: '0.05em',
                              }}
                            >
                              Source Code Implementation
                            </span>
                            <span
                              style={{
                                fontSize: 11,
                                color: '#94a3b8',
                                fontFamily: 'monospace',
                              }}
                            >
                              {file.content ? file.content.split('\n').length : 0} lines
                            </span>
                          </div>
                          <div
                            style={{
                              borderRadius: 8,
                              border: '1px solid #1e293b',
                              background: '#0f172a',
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                padding: '6px 12px',
                                background: '#1e293b',
                                borderBottom: '1px solid #334155',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                              }}
                            >
                              <span
                                style={{
                                  color: '#94a3b8',
                                  fontSize: 11,
                                  fontFamily: 'monospace',
                                }}
                              >
                                {file.name}
                              </span>
                              <button
                                type="button"
                                onClick={() => copyCode(file.content, idx)}
                                style={{
                                  padding: '2px 8px',
                                  background: '#334155',
                                  color: '#e2e8f0',
                                  border: 'none',
                                  borderRadius: 4,
                                  fontSize: 10,
                                  cursor: 'pointer',
                                }}
                              >
                                {copiedIndex === idx ? '✓ Copied' : 'Copy'}
                              </button>
                            </div>
                            <pre
                              style={{
                                margin: 0,
                                padding: '14px 16px',
                                color: '#f8fafc',
                                fontSize: 11,
                                lineHeight: 1.55,
                                maxHeight: 260,
                                overflowY: 'auto',
                                fontFamily: 'ui-monospace, monospace',
                              }}
                            >
                              <code>{file.content}</code>
                            </pre>
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
            </div>
          )}

          {/* 4. Essay / Theoretical Paper View (when no files exist) */}
          {files.length === 0 && (
            <section
              style={{
                borderRadius: 12,
                border: '1px solid #e2e8f0',
                background: '#ffffff',
                overflow: 'hidden',
                boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
              }}
            >
              <header
                style={{
                  padding: '14px 20px',
                  background: '#f8fafc',
                  borderBottom: '1px solid #e2e8f0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                }}
              >
                <strong style={{ fontSize: 13, color: '#1e293b' }}>
                  Academic Research & Essay Report
                </strong>
                <button
                  type="button"
                  onClick={() =>
                    copyCode(
                      solution.validated_content || solution.draft_content || '',
                      999
                    )
                  }
                  style={{
                    padding: '4px 10px',
                    background: '#ffffff',
                    border: '1px solid #cbd5e1',
                    borderRadius: 6,
                    fontSize: 11,
                    cursor: 'pointer',
                  }}
                >
                  {copiedIndex === 999 ? '✓ Copied' : 'Copy Paper'}
                </button>
              </header>
              <div
                style={{
                  padding: '24px',
                  color: '#1e293b',
                  fontSize: 13,
                  lineHeight: 1.7,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {solution.validated_content ||
                  solution.draft_content ||
                  'No text content available.'}
              </div>
            </section>
          )}

          {/* 5. Minimal Academic Integrity Notice */}
          <div
            style={{
              padding: '10px 14px',
              background: '#fef3c7',
              borderRadius: 8,
              border: '1px solid #fde68a',
              fontSize: 11,
              color: '#92400e',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <Icon name="checkCircle" size={13} />
            <span>
              Review all generated code files, terminal outputs, and reports before final
              submission to your instructor.
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
