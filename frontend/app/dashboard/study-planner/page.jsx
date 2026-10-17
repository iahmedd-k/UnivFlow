'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import MarkdownRenderer from '../MarkdownRenderer';
import Icon from '@/app/dashboard/Icon';

const SESSION_TYPE_LABELS = {
  learn: 'Learn',
  review: 'Recall',
  final_review: 'Final Review',
};
const SESSION_TYPE_COLORS = {
  learn: 'bg-violet-light text-violet-dark border-violet/20',
  review: 'bg-emerald-light text-emerald-dark border-emerald/20',
  final_review: 'bg-rose-light text-rose-dark border-rose/20',
};
const STATUS_COLORS = {
  pending: 'bg-paper text-muted border-line',
  done: 'bg-emerald-light text-emerald-dark border-emerald/20',
  partial: 'bg-amber-light text-amber-dark border-amber/20',
  missed: 'bg-rose-light text-rose-dark border-rose/20',
};

export default function StudyPlannerPage() {
  const { getToken } = useAuth();
  const [token, setToken] = useState(null);
  const [plans, setPlans] = useState([]);
  const [activePlanId, setActivePlanId] = useState(null);
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  // Creation form state
  const [syllabus, setSyllabus] = useState('');
  const [examTitle, setExamTitle] = useState('');
  const [examDate, setExamDate] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [hoursPerDay, setHoursPerDay] = useState(3);
  const [planMode, setPlanMode] = useState('spaced_repetition');
  const [topics, setTopics] = useState([]);
  const [topicsLoaded, setTopicsLoaded] = useState(false);
  const [showTopicEditor, setShowTopicEditor] = useState(false);
  const [view, setView] = useState('plans'); // 'plans' | 'create' | 'plan'

  const scrollRef = useRef(null);

  const loadPlans = async (token) => {
    try {
      const rows = await api.getStudyPlans(token);
      setPlans(rows || []);
      if (rows && rows.length > 0 && !activePlanId) {
        setActivePlanId(rows[0].id);
        await loadPlan(token, rows[0].id);
      }
    } catch (e) {
      setError(e.message || 'Could not load study plans.');
    }
  };

  const loadPlan = async (token, planId) => {
    try {
      const data = await api.getStudyPlan(planId, token);
      setPlan(data);
      setActivePlanId(planId);
      setView('plan');
    } catch (e) {
      setError(e.message || 'Could not load study plan.');
    }
  };

  useEffect(() => {
    (async () => {
      const t = getToken ? await getToken() : null;
      setToken(t);
      await loadPlans(t);
      setLoading(false);
    })();
  }, [getToken]);

  const extractTopics = async () => {
    if (!syllabus.trim()) {
      setError('Please paste a syllabus first.');
      return;
    }
    setBusy(true); setError(null);
    try {
      const t = await getToken();
      // Call generate-study-plan with minimal input to get topic extraction;
      // we reuse the endpoint but only surface topics for editing.
      const data = await api.generateStudyPlan({
        syllabus,
        exam_title: examTitle || undefined,
        exam_date: examDate || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        hours_per_day: hoursPerDay,
        plan_mode: planMode,
      }, t);
      setTopics(data.topics || []);
      setShowTopicEditor(true);
      setView('topics');
    } catch (e) {
      setError(e.message || 'Could not extract topics.');
    } finally {
      setBusy(false);
    }
  };

  const generatePlan = async () => {
    if (!syllabus.trim()) {
      setError('Please paste a syllabus first.');
      return;
    }
    setBusy(true); setError(null);
    try {
      const t = await getToken();
      const data = await api.generateStudyPlan({
        syllabus,
        exam_title: examTitle || undefined,
        exam_date: examDate || undefined,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        hours_per_day: hoursPerDay,
        session_minutes: 60,
        plan_mode: planMode,
        topics,
      }, t);
      setPlan(data);
      setActivePlanId(data.id);
      setView('plan');
      setPlans((prev) => [
        {
          id: data.id,
          title: data.title,
          exam_title: data.exam_title,
          exam_date: data.exam_date,
          status: 'active',
          stats: data.stats,
          created_at: data.created_at,
          updated_at: data.updated_at,
        },
        ...prev.filter((p) => p.id !== data.id),
      ]);
    } catch (e) {
      setError(e.message || 'Could not generate study plan.');
    } finally {
      setBusy(false);
    }
  };

  const updateSession = async (sessionId, status, notes) => {
    if (!activePlanId) return;
    setBusy(true);
    try {
      const t = await getToken();
      const data = await api.updateStudyPlanSession(activePlanId, sessionId, { status, notes }, t);
      setPlan((p) => ({
        ...p,
        sessions: (p.sessions || []).map((s) =>
          s.id === sessionId ? { ...s, status: data.status, notes: data.notes } : s
        ),
        stats: data.stats,
      }));
    } catch (e) {
      setError(e.message || 'Could not update session.');
    } finally {
      setBusy(false);
    }
  };

  const deletePlan = async (planId) => {
    if (!window.confirm('Delete this study plan?')) return;
    // No delete endpoint yet; mark as archived client-side and filter.
    setPlans((prev) => prev.filter((p) => p.id !== planId));
    if (activePlanId === planId) {
      setPlan(null);
      setActivePlanId(null);
      setView('plans');
    }
  };

  const formatDate = (iso) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  };

  const sessionsByDay = (plan) => {
    if (!plan || !plan.sessions) return [];
    const map = new Map();
    for (const s of plan.sessions) {
      const key = s.session_date.split('T')[0];
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(s);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  };

  const planStats = (plan) => {
    if (!plan || !plan.stats) return null;
    return plan.stats;
  };

  const statusColor = (status) => STATUS_COLORS[status] || STATUS_COLORS.pending;
  const typeColor = (type) => SESSION_TYPE_COLORS[type] || SESSION_TYPE_COLORS.learn;

  return (
    <main className="mx-auto flex w-full max-w-[1280px] flex-col gap-0 pb-10 text-ink">
      {/* Top nav: plans list + actions */}
      <header className="flex flex-col gap-3 border-b border-line pb-6 px-4 sm:px-0">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <p className="mb-1 block text-xs font-semibold uppercase tracking-wide text-muted">Study Planner</p>
            <h1 className="text-2xl font-semibold tracking-tight">Study Planner</h1>
            <p className="mt-1 text-sm leading-6 text-muted">Build day-by-day study plans from your syllabus with spaced repetition and progress tracking.</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-violet px-3 px-4 py-2 text-sm font-semibold text-white transition hover:bg-violet-dark" onClick={() => setView('create')}>
              <Icon name="plus" size={16} /> New plan
            </button>
          </div>
        </div>
        {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm text-rose" role="alert">{error}</div>}
      </header>

      {/* Plans list view */}
      {view === 'plans' && (
        <section className="px-4 sm:px-0 py-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {plans.length ? plans.map((p) => {
              const stats = p.stats || {};
              const completion = stats.completion_pct || 0;
              return (
                <article key={p.id} className="rounded-xl border border-line bg-white shadow-sm hover:shadow-md transition p-5 cursor-pointer" onClick={() => loadPlan(token, p.id)}>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="flex-1">
                      <h3 className="text-sm font-semibold text-ink line-clamp-1">{p.title}</h3>
                      {p.exam_title && <p className="mt-0.5 text-xs text-muted line-clamp-1">{p.exam_title}</p>}
                    </div>
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${
                      p.status === 'active' ? 'border-emerald/20 text-emerald-dark bg-emerald/50' : 'border-line text-muted'
                    }`}>{p.status}</span>
                  </div>
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="text-muted">{p.exam_date ? formatDate(p.exam_date) : 'No exam date'}</span>
                      <span className="ml-auto text-xs text-muted">{stats.total_sessions || 0} sessions</span>
                    </div>
                    <div className="w-full bg-paper rounded-full h-2">
                      <div className={`bg-violet h-2 rounded-full transition`} style={{ width: `${Math.min(completion, 100)}%` }} />
                    </div>
                    <div className="flex justify-between text-xs text-muted">
                      <span>{completion}% complete</span>
                      <span>{formatDate(p.created_at)}</span>
                    </div>
                  </div>
                </article>
              );
            }) : (
              <div className="lg:col-span-3 rounded-xl border border-dashed border-line bg-paper p-12 text-center text-muted">
                <span className="mb-3 block grid size-12 place-items-center rounded-full bg-white text-violet mx-auto"><Icon name="bookOpen" size={32} /></span>
                <h3 className="text-sm font-semibold text-ink">No study plans yet</h3>
                <p className="mt-1 text-sm">Create your first plan from a syllabus and track your progress session by session.</p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Create view */}
      {view === 'create' && (
        <section className="px-4 sm:px-0 py-4">
          <button type="button" onClick={() => setView('plans')} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-ink mb-4">
            <Icon name="arrowLeft" size={16} /> Back to plans
          </button>
          <div className="rounded-xl border border-line bg-white shadow-sm p-6">
            <h2 className="text-base font-semibold text-ink mb-4">Create a study plan</h2>
            <form onSubmit={(e) => { e.preventDefault(); extractTopics(); }} className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <div className="lg:col-span-2">
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Syllabus / topics</label>
                <textarea className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" minLength={10} value={syllabus} onChange={(e) => setSyllabus(e.target.value)} rows={6} placeholder="Paste your syllabus, topic list, or learning outcomes here…" aria-label="Syllabus" />
              </div>
              <div>
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Exam title (optional)</label>
                <input className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" value={examTitle} onChange={(e) => setExamTitle(e.target.value)} placeholder="e.g. Data Structures Final" aria-label="Exam title" />
              </div>
              <div>
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Exam date</label>
                <input className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" type="date" value={examDate} onChange={(e) => setExamDate(e.target.value)} aria-label="Exam date" />
              </div>
              <div>
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Start date</label>
                <input className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} aria-label="Start date" />
              </div>
              <div>
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">End date</label>
                <input className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} aria-label="End date" />
              </div>
              <div>
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Hours per day</label>
                <input className="w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-violet focus:ring-2 focus:ring-violet/20" type="number" min="0.5" max="12" step="0.5" value={hoursPerDay} onChange={(e) => setHoursPerDay(parseFloat(e.target.value) || 3)} aria-label="Hours per day" />
              </div>
              <div className="lg:col-span-2">
                <label className="block mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Planning mode</label>
                <div className="flex gap-2">
                  <label className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition ${planMode === 'spaced_repetition' ? 'border-violet bg-violet/50 text-violet-dark' : 'border-line bg-white text-ink hover:bg-paper'}`}>
                    <input type="radio" name="planMode" checked={planMode === 'spaced_repetition'} onChange={() => setPlanMode('spaced_repetition')} className="accent-violet" /> Spaced repetition (exam-anchored)
                  </label>
                  <label className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition ${planMode === 'coverage' ? 'border-violet bg-violet/50 text-violet-dark' : 'border-line bg-white text-ink hover:bg-paper'}`}>
                    <input type="radio" name="planMode" checked={planMode === 'coverage'} onChange={() => setPlanMode('coverage')} className="accent-violet" /> Coverage (interleaved learn → review)
                  </label>
                </div>
                <p className="mt-1 text-xs text-muted">Spaced repetition schedules reviews at +1d, +3d, +7d, +14d, +28d before your exam. Coverage distributes topics with next-day review.</p>
              </div>
              <div className="lg:col-span-2 flex items-end gap-3">
                <button type="button" onClick={() => setView('plans')} className="rounded-lg border border-line px-4 py-2.5 text-sm text-ink transition hover:bg-paper">Cancel</button>
                <button type="submit" className={`rounded-lg bg-violet px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:opacity-50 disabled:cursor-not-allowed ${busy ? 'opacity-50 cursor-not-allowed' : ''}`} disabled={busy || !syllabus.trim()}>{busy ? 'Extracting topics…' : 'Next: Review topics'}</button>
              </div>
            </form>
          </div>
        </section>
      )}

      {/* Topics editor view */}
      {view === 'topics' && (
        <section className="px-4 sm:px-0 py-4">
          <button type="button" onClick={() => setView('create')} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-ink mb-4">
            <Icon name="arrowLeft" size={16} /> Back
          </button>
          <div className="rounded-xl border border-line bg-white shadow-sm p-6">
            <h2 className="text-base font-semibold text-ink mb-4">Review and adjust topics</h2>
            <p className="mb-4 text-sm text-muted">Topics were extracted from your syllabus. Edit titles, difficulty (1-5) and importance weight (1-5) before generating the plan.</p>
            <div className="space-y-2">
              {topics.map((t, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-lg border border-line bg-white hover:bg-paper transition">
                  <span className="mt-1 shrink-0 rounded bg-violet-light px-2 py-0.5 text-xs font-semibold text-violet-dark">#{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <input className="w-full border-none bg-transparent text-sm text-ink outline-none focus:ring-0" value={t.title} onChange={(e) => {
                      const next = [...topics];
                      next[i].title = e.target.value;
                      setTopics(next);
                    }} aria-label={`Topic ${i + 1} title`} />
                    <div className="flex gap-3 mt-2 text-xs">
                      <span className="flex items-center gap-1 text-muted">Difficulty <input type="number" min="1" max="5" value={t.difficulty} onChange={(e) => { const next = [...topics]; next[i].difficulty = Math.max(1, Math.min(5, parseInt(e.target.value) || 3)); setTopics(next); }} className="w-12 border border-line rounded px-1 py-0.5 text-xs text-ink" /></span>
                      <span className="flex items-center gap-1 text-muted">Weight <input type="number" min="1" max="5" value={t.weight} onChange={(e) => { const next = [...topics]; next[i].weight = Math.max(1, Math.min(5, parseInt(e.target.value) || 3)); setTopics(next); }} className="w-12 border border-line rounded px-1 py-0.5 text-xs text-ink" /></span>
                    </div>
                  </div>
                  <button type="button" onClick={() => { setTopics(topics.filter((_, idx) => idx !== i)); }} className="ml-2 text-muted hover:text-ink" title="Remove topic"><Icon name="trash2" size={16} /></button>
                </div>
              ))}
              {topics.length === 0 && <p className="text-sm text-muted italic">No topics extracted.</p>}
            </div>
            <div className="mt-6 flex items-end gap-3">
              <button type="button" onClick={() => setView('create')} className="rounded-lg border border-line px-4 py-2.5 text-sm text-ink transition hover:bg-paper">Back</button>
              <button type="button" onClick={generatePlan} className={`rounded-lg bg-violet px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-dark disabled:opacity-50 disabled:cursor-not-allowed ${busy ? 'opacity-50 cursor-not-allowed' : ''}`} disabled={busy}>{busy ? 'Generating plan…' : 'Generate study plan'}</button>
            </div>
          </div>
        </section>
      )}

      {/* Plan view */}
      {view === 'plan' && plan && (
        <section className="px-4 sm:px-0 py-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <div>
              <h2 className="text-base font-semibold text-ink">{plan.title}</h2>
              {plan.exam_title && <p className="mt-0.5 text-sm text-muted">{plan.exam_title}</p>}
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setView('plans')} className="text-sm font-medium text-muted hover:text-ink">Back to plans</button>
              <button type="button" onClick={() => deletePlan(plan.id)} className="text-sm font-medium text-rose hover:text-rose-dark">Delete</button>
            </div>
          </div>

          {/* Stats cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
            <div className="rounded-xl border border-line bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Completion</p>
              <p className="text-2xl font-bold text-ink">{planStats(plan)?.completion_pct ?? 0}%</p>
            </div>
            <div className="rounded-xl border border-line bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Sessions</p>
              <p className="text-2xl font-bold text-ink">{planStats(plan)?.total_sessions ?? 0}</p>
            </div>
            <div className="rounded-xl border border-line bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Done</p>
              <p className="text-2xl font-bold text-emerald-dark">{planStats(plan)?.done ?? 0}</p>
            </div>
            <div className="rounded-xl border border-line bg-white p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted">Time</p>
              <p className="text-2xl font-bold text-ink">{planStats(plan)?.total_hours_scheduled ?? 0} hrs</p>
            </div>
          </div>

          {/* Calendar / daily view */}
          <div className="rounded-xl border border-line bg-white shadow-sm overflow-hidden">
            <div className="border-b border-line bg-white px-5 py-4 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-ink">Daily study schedule</h3>
                <p className="text-xs text-muted">{plan.sessions?.length ?? 0} sessions across {new Set(plan.sessions?.map((s) => s.session_date.split('T')[0])).size} days</p>
              </div>
              <div className="flex gap-2">
                <span className="text-xs font-medium text-muted">Schedule</span>
              </div>
            </div>
            <div ref={scrollRef} className="divide-y divide-line overflow-y-auto max-h-[70vh]">
              {sessionsByDay(plan).length ? sessionsByDay(plan).map(([day, daySessions]) => {
                const dayUsed = daySessions.reduce((sum, s) => sum + s.duration_minutes, 0);
                return (
                  <section key={day} className="px-5 py-4">
                    <div className="flex items-center gap-3 mb-3 border-b border-line pb-2">
                      <h4 className="text-sm font-semibold text-ink">{new Date(day).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}</h4>
                      <span className="ml-auto text-xs font-medium text-muted">{dayUsed} min</span>
                    </div>
                    <div className="space-y-2">
                      {daySessions.map((s) => (
                        <div key={s.id} className="flex items-start gap-3 p-3 rounded-lg border bg-white transition hover:shadow-sm" style={{ borderColor: typeColor(s.session_type).includes('border') ? 'transparent' : 'border-line' }}>
                          <span className={`mt-1 shrink-0 rounded px-2 py-0.5 text-xs font-bold ${typeColor(s.session_type)}`}>{SESSION_TYPE_LABELS[s.session_type]}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className="text-sm font-medium text-ink truncate">{s.topic}</span>
                              <span className="ml-auto text-xs font-medium text-muted">{s.duration_minutes} min</span>
                            </div>
                            <div className="flex gap-2">
                              {['pending', 'done', 'partial', 'missed'].map((st) => (
                                <button key={st} type="button" onClick={() => updateSession(s.id, st, s.notes)} className={`px-2.5 py-1 rounded text-xs font-medium border transition ${STATUS_COLORS[st]} ${s.status === st ? 'ring-2 ring-violet' : ''}`} aria-label={`Mark ${s.topic} as ${st}`}>{st.charAt(0).toUpperCase() + st.slice(1)}</button>
                              ))}
                              <button type="button" onClick={() => {
                                const n = window.prompt('Notes for this session:', s.notes || '');
                                if (n !== null) updateSession(s.id, s.status, n);
                              }} className="text-xs text-muted underline underline-offset-4 hover:text-ink">Notes</button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                );
              }) : (
                <div className="p-8 text-center text-muted">No sessions in this plan.</div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* Plan view: no plan selected */}
      {view === 'plan' && !plan && (
        <section className="px-4 sm:px-0 py-4">
          <div className="rounded-xl border border-dashed border-line bg-paper p-12 text-center text-muted">
            <span className="mb-3 block grid size-12 place-items-center rounded-full bg-white text-violet mx-auto"><Icon name="bookOpen" size={32} /></span>
            <h3 className="text-sm font-semibold text-ink">Select a study plan</h3>
            <p className="mt-1 text-sm">Choose a plan from the list above or create a new one.</p>
          </div>
        </section>
      )}
    </main>
  );
}
