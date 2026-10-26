'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const runTone = (status) =>
  status === 'COMPLETED' ? 'success' : status === 'FAILED' ? 'error' : 'warning';

export default function ActivityPage() {
  const { getToken } = useAuth();
  const [runs, setRuns] = useState([]);
  const [automationHistory, setAutomationHistory] = useState([]);
  const [stats, setStats] = useState(null);
  const [sync, setSync] = useState(null);
  const [expandedRun, setExpandedRun] = useState(null);
  const [runEvents, setRunEvents] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionMessage, setActionMessage] = useState('');

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const results = await Promise.allSettled([
        api.getAgentRuns(20, token),
        api.getAgentRunStats(token),
        api.getSyncStatus(token),
        api.getAutomationHistory(40, token),
      ]);
      setRuns(results[0].status === 'fulfilled' ? results[0].value || [] : []);
      setStats(results[1].status === 'fulfilled' ? results[1].value : null);
      setSync(results[2].status === 'fulfilled' ? results[2].value : null);
      setAutomationHistory(results[3].status === 'fulfilled' ? results[3].value || [] : []);
      const failed = results.find((result) => result.status === 'rejected');
      if (failed) setError(failed.reason?.message || 'Some sync activity could not be loaded.');
    } catch (err) {
      setError(err.message || 'Could not load sync activity.');
    }
  }, [getToken]);

  const retryAutomation = async (item) => {
    setActionMessage('');
    try {
      const token = await getToken();
      if (item.kind === 'classroom_turn_in') {
        if (!window.confirm(`Retry submission of "${item.assignment_title}" to Google Classroom now?`)) return;
        const result = await api.quickTurnInAssignment(item.assignment_id, token);
        setActionMessage(result.message || 'Classroom submission retry finished.');
      } else {
        await api.generateAssignmentSolution(item.assignment_id, { create_google_doc: true }, token);
        setActionMessage(`Claude started a new draft for "${item.assignment_title}".`);
      }
      await load();
    } catch (err) {
      setError(err.message || 'Could not retry this automation.');
    }
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      load().finally(() => setLoading(false));
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  const toggleEvents = async (runId) => {
    if (expandedRun === runId) {
      setExpandedRun(null);
      return;
    }
    setExpandedRun(runId);
    if (runEvents[runId]) return;
    try {
      const token = await getToken();
      const events = await api.getAgentRunEvents(runId, token);
      setRunEvents((current) => ({ ...current, [runId]: events || [] }));
    } catch (err) {
      setError(err.message || 'Could not load run details.');
    }
  };

  const syncStatus = sync?.sync_run?.status || 'not started';

  return (
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 pb-10 text-heading">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-label">BACKGROUND WORK</p>
          <h1 className="my-1 text-2xl sm:text-3xl font-semibold tracking-tight text-heading">Sync history</h1>
          <p className="text-sm font-normal text-muted leading-relaxed">Check recent academic sync runs and what they updated.</p>
        </div>
        <button
          type="button"
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-border-input bg-surface px-3 text-sm font-medium text-nav transition-colors hover:bg-surface-secondary"
          onClick={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        >
          <Icon name="refresh" size={14} /> Refresh
        </button>
      </header>

      {error && <div className="rounded-lg border border-rose-border bg-rose-bg px-4 py-3 text-sm font-normal text-rose">{error}</div>}
      {actionMessage && <div role="status" className="rounded-lg border border-success/30 bg-success-bg px-4 py-3 text-sm font-normal text-success">{actionMessage}</div>}

      <section className="min-w-0 rounded-xl border border-border bg-surface shadow-xs">
        <header className="flex items-center justify-between gap-3.5 border-b border-border-light px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-label">AUTOMATION HISTORY</p>
            <h2 className="text-lg font-semibold text-heading">Claude drafts and Classroom submissions</h2>
          </div>
          <span className="inline-flex items-center rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-nav tabular-nums">{automationHistory.length}</span>
        </header>
        {loading ? <p className="px-5 py-8 text-center text-sm font-normal text-muted">Loading automation history…</p> : automationHistory.length ? (
          <div className="divide-y divide-border-light">
            {automationHistory.map((item) => (
              <article key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-violet"><Icon name={item.kind === 'claude_assignment' ? 'sparkles' : 'upload'} size={15} /></span>
                <div className="min-w-0 flex-1">
                  <strong className="block truncate text-sm font-semibold text-heading">{item.assignment_title}</strong>
                  <span className="block text-xs font-normal text-muted">{item.course_name} · {item.kind === 'claude_assignment' ? 'Claude draft' : 'Classroom turn-in'} · <span className="tabular-nums">{item.started_at ? new Date(item.started_at).toLocaleString() : 'Time unavailable'}</span></span>
                  {item.error && <span className="mt-1 block text-xs font-normal text-danger">{item.error}</span>}
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${['completed', 'TURNED_IN'].includes(item.status) ? 'bg-success-bg text-success' : ['failed', 'FAILED'].includes(item.status) ? 'bg-rose-bg text-rose' : 'bg-warning-bg text-warning'}`}>{item.status?.replaceAll('_', ' ')}</span>
                {item.retryable && <button type="button" onClick={() => retryAutomation(item)} className="min-h-8 rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-nav hover:bg-surface-secondary">{item.kind === 'claude_assignment' ? 'Retry with Claude' : 'Retry turn-in'}</button>}
              </article>
            ))}
          </div>
        ) : <p className="px-5 py-8 text-center text-sm font-normal text-muted">No assignment automation or Classroom submission history yet.</p>}
      </section>

      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Agent runs</span>
          <strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{loading ? '—' : (stats?.total_runs ?? 0)}</strong>
        </article>
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Completed</span>
          <strong className="mt-2 block text-2xl sm:text-3xl font-semibold text-heading tabular-nums">{loading ? '—' : (stats?.completed ?? 0)}</strong>
        </article>
        <article className="rounded-xl border border-border bg-surface p-4 shadow-xs">
          <span className="block text-xs font-medium uppercase tracking-wider text-muted">Google Classroom sync</span>
          <strong className="mt-2 block text-base font-semibold capitalize text-heading">{loading ? '—' : syncStatus}</strong>
          <small className="mt-1 block text-xs font-normal text-subtle tabular-nums">
            {sync?.last_sync ? new Date(sync.last_sync).toLocaleString() : 'No successful sync yet'}
          </small>
        </article>
      </section>

      <section className="min-w-0 rounded-xl border border-border bg-surface shadow-xs">
        <header className="flex items-center justify-between gap-3.5 border-b border-border-light px-5 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-label">AUTOMATION ACTIVITY</p>
            <h2 className="text-lg font-semibold text-heading">Recent agent runs</h2>
          </div>
          <span className="inline-flex items-center rounded-full bg-surface-secondary px-2.5 py-0.5 text-xs font-medium text-nav tabular-nums">{runs.length}</span>
        </header>

        {loading ? (
          <div className="px-5 py-8 text-center text-sm font-normal text-muted">Loading sync history…</div>
        ) : runs.length ? (
          <div className="flex flex-col">
            {runs.map((run) => (
              <article className="border-t border-border-light first:border-t-0" key={run.id}>
                <div className="flex min-h-[60px] items-center gap-3 px-4 py-3 hover:bg-surface-secondary transition">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-violet-light text-violet">
                    <Icon name="refresh" size={15} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-sm font-semibold text-heading">{(run.trigger || 'Sync').replaceAll('_', ' ')}</strong>
                    <small className="text-xs font-normal text-muted tabular-nums">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : 'Time unavailable'}
                      {run.duration_seconds != null
                        ? ` · ${Math.round(run.duration_seconds)} sec`
                        : ''}
                    </small>
                    <small className="text-xs font-normal text-subtle tabular-nums">
                      {run.assignments_found ?? 0} assignments found · {run.changes_found ?? 0} changes ·{' '}
                      {run.notifications_sent ?? 0} notifications
                    </small>
                    {run.errors > 0 && (
                      <small className="text-xs font-normal text-danger">
                        {run.error_details || `${run.errors} run errors`}
                      </small>
                    )}
                  </span>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${run.status === 'COMPLETED' ? 'bg-success-bg text-success' : run.status === 'FAILED' ? 'bg-rose-bg text-rose' : 'bg-warning-bg text-warning'}`}>
                    {(run.status || 'unknown').toLowerCase()}
                  </span>
                  <button
                    type="button"
                    className="inline-flex min-h-8 shrink-0 items-center justify-center rounded-md border border-border-input bg-surface px-3 text-xs font-medium text-nav hover:bg-surface-secondary"
                    onClick={() => toggleEvents(run.id)}
                  >
                    {expandedRun === run.id ? 'Hide details' : 'View details'}
                  </button>
                </div>

                {expandedRun === run.id && (
                  <div className="flex flex-col gap-2 border-t border-border-light px-4 pb-4 pl-14 pt-2 text-xs font-normal text-muted">
                    {runEvents[run.id] ? (
                      runEvents[run.id].length ? (
                        runEvents[run.id].map((event) => (
                          <div className="flex items-start gap-2" key={event.id}>
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${event.status?.toUpperCase() === 'COMPLETED' ? 'bg-success-bg text-success' : event.status?.toUpperCase() === 'FAILED' ? 'bg-rose-bg text-rose' : 'bg-warning-bg text-warning'}`}>
                              {event.status || event.event_type}
                            </span>
                            <span className="flex flex-col gap-0.5">
                              <strong className="text-xs font-medium text-heading">{event.message || event.source || 'Sync event'}</strong>
                              {event.created_at && (
                                <small className="text-xs font-normal text-subtle tabular-nums">{new Date(event.created_at).toLocaleString()}</small>
                              )}
                            </span>
                          </div>
                        ))
                      ) : (
                        <p>No detailed events were recorded for this run.</p>
                      )
                    ) : (
                      <p>Loading run details…</p>
                    )}
                  </div>
                )}
              </article>
            ))}
          </div>
        ) : (
          <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">
            <strong className="mb-1 block text-xs text-[#515563]">No automation runs yet</strong>
            Run a Classroom sync to start recording background activity.
          </div>
        )}
      </section>

      <p className="mt-1 rounded-lg bg-[#f6f5ff] px-3 py-2.5 text-xs leading-relaxed text-[#77729b]">
        This page reports recent agent runs and the latest Classroom sync status. Syncs run in the
        background after you start them.
      </p>
    </div>
  );
}
