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
  const [stats, setStats] = useState(null);
  const [sync, setSync] = useState(null);
  const [expandedRun, setExpandedRun] = useState(null);
  const [runEvents, setRunEvents] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      const results = await Promise.allSettled([
        api.getAgentRuns(20, token),
        api.getAgentRunStats(token),
        api.getSyncStatus(token),
      ]);
      setRuns(results[0].status === 'fulfilled' ? results[0].value || [] : []);
      setStats(results[1].status === 'fulfilled' ? results[1].value : null);
      setSync(results[2].status === 'fulfilled' ? results[2].value : null);
      const failed = results.find((result) => result.status === 'rejected');
      if (failed) setError(failed.reason?.message || 'Some sync activity could not be loaded.');
    } catch (err) {
      setError(err.message || 'Could not load sync activity.');
    }
  }, [getToken]);

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
    <div className="mx-auto flex w-full max-w-[1080px] flex-col gap-5 text-[#292d3a]">
      <header className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">BACKGROUND WORK</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[#292d3a]">Sync history</h1>
          <p className="mt-1 text-xs text-[#858998]">Check recent academic sync runs and what they updated.</p>
        </div>
        <button
          type="button"
          className="inline-flex min-h-9 items-center justify-center gap-2 rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] transition-colors hover:bg-[#f8f8fb]"
          onClick={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        >
          <Icon name="refresh" size={14} /> Refresh
        </button>
      </header>

      {error && <div className="rounded-lg border border-[#f1dede] bg-[#fff8f8] px-3 py-2.5 text-xs text-[#a04a4a]">{error}</div>}

      <section className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        <article className="rounded-xl border border-[#ededf2] bg-white p-4">
          <span className="block text-xs text-[#858998]">Agent runs</span>
          <strong className="mt-2 block text-[22px] font-semibold text-[#343746]">{loading ? '—' : (stats?.total_runs ?? 0)}</strong>
        </article>
        <article className="rounded-xl border border-[#ededf2] bg-white p-4">
          <span className="block text-xs text-[#858998]">Completed</span>
          <strong className="mt-2 block text-[22px] font-semibold text-[#343746]">{loading ? '—' : (stats?.completed ?? 0)}</strong>
        </article>
        <article className="rounded-xl border border-[#ededf2] bg-white p-4">
          <span className="block text-xs text-[#858998]">Google Classroom sync</span>
          <strong className="mt-2 block text-base font-semibold capitalize text-[#343746]">{loading ? '—' : syncStatus}</strong>
          <small className="mt-1 block text-xs text-[#858998]">
            {sync?.last_sync ? new Date(sync.last_sync).toLocaleString() : 'No successful sync yet'}
          </small>
        </article>
      </section>

      <section className="min-w-0 rounded-xl border border-[#ebebf0] bg-white shadow-sm">
        <header className="flex items-center justify-between gap-3.5 border-b border-[#f0f0f3] px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[.12em] text-[#858998]">AUTOMATION ACTIVITY</p>
            <h2 className="text-[13px] font-semibold text-[#343746]">Recent agent runs</h2>
          </div>
          <span className="inline-flex items-center rounded-full bg-[#f1f1f6] px-2 py-1 text-xs font-semibold text-[#6e7281]">{runs.length}</span>
        </header>

        {loading ? (
          <div className="px-5 py-8 text-center text-xs leading-relaxed text-[#9396a3]">Loading sync history…</div>
        ) : runs.length ? (
          <div className="flex flex-col">
            {runs.map((run) => (
              <article className="border-t border-[#f1f1f4] first:border-t-0" key={run.id}>
                <div className="flex min-h-[60px] items-center gap-3 px-4 py-3 hover:bg-[#fafafd]">
                  <span className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-lg bg-[#f0edff] text-[#6657d9]">
                    <Icon name="refresh" size={15} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <strong className="overflow-hidden text-ellipsis whitespace-nowrap text-xs font-semibold text-[#414553]">{(run.trigger || 'Sync').replaceAll('_', ' ')}</strong>
                    <small className="text-xs text-[#9295a2]">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : 'Time unavailable'}
                      {run.duration_seconds != null
                        ? ` · ${Math.round(run.duration_seconds)} sec`
                        : ''}
                    </small>
                    <small className="text-xs text-[#9295a2]">
                      {run.assignments_found ?? 0} assignments found · {run.changes_found ?? 0} changes ·{' '}
                      {run.notifications_sent ?? 0} notifications
                    </small>
                    {run.errors > 0 && (
                      <small className="text-xs text-[#b34f4f]">
                        {run.error_details || `${run.errors} run errors`}
                      </small>
                    )}
                  </span>
                  <span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${run.status === 'COMPLETED' ? 'bg-[#eaf7f1] text-[#438a71]' : run.status === 'FAILED' ? 'bg-[#fff0f0] text-[#b15252]' : 'bg-[#fff4e4] text-[#a87936]'}`}>
                    {(run.status || 'unknown').toLowerCase()}
                  </span>
                  <button
                    type="button"
                    className="inline-flex min-h-9 shrink-0 items-center justify-center rounded-md border border-[#e5e5ec] bg-white px-3 text-xs font-semibold text-[#5c6070] hover:bg-[#f8f8fb]"
                    onClick={() => toggleEvents(run.id)}
                  >
                    {expandedRun === run.id ? 'Hide details' : 'View details'}
                  </button>
                </div>

                {expandedRun === run.id && (
                  <div className="flex flex-col gap-2 border-t border-[#f1f1f4] px-4 pb-4 pl-14 pt-2 text-xs text-[#888c99]">
                    {runEvents[run.id] ? (
                      runEvents[run.id].length ? (
                        runEvents[run.id].map((event) => (
                          <div className="flex items-start gap-2" key={event.id}>
                            <span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${event.status?.toUpperCase() === 'COMPLETED' ? 'bg-[#eaf7f1] text-[#438a71]' : event.status?.toUpperCase() === 'FAILED' ? 'bg-[#fff0f0] text-[#b15252]' : 'bg-[#fff4e4] text-[#a87936]'}`}>
                              {event.status || event.event_type}
                            </span>
                            <span className="flex flex-col gap-1">
                              <strong className="text-xs font-medium text-[#5e6270]">{event.message || event.source || 'Sync event'}</strong>
                              {event.created_at && (
                                <small className="text-xs text-[#a0a2ad]">{new Date(event.created_at).toLocaleString()}</small>
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
