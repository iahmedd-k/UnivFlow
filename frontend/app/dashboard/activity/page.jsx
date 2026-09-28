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
    load().finally(() => setLoading(false));
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
    <div className="product-page">
      <header className="product-heading">
        <div>
          <p className="eyebrow">BACKGROUND WORK</p>
          <h1>Sync history</h1>
          <p>Check recent academic sync runs and what they updated.</p>
        </div>
        <button
          type="button"
          className="product-action secondary"
          onClick={() => {
            setLoading(true);
            load().finally(() => setLoading(false));
          }}
        >
          <Icon name="refresh" size={14} /> Refresh
        </button>
      </header>

      {error && <div className="product-alert">{error}</div>}

      <section className="product-grid three">
        <article className="product-stat">
          <span>Agent runs</span>
          <strong>{loading ? '—' : (stats?.total_runs ?? 0)}</strong>
        </article>
        <article className="product-stat">
          <span>Completed</span>
          <strong>{loading ? '—' : (stats?.completed ?? 0)}</strong>
        </article>
        <article className="product-stat">
          <span>Google Classroom sync</span>
          <strong className="sync-status-value">{loading ? '—' : syncStatus}</strong>
          <small>
            {sync?.last_sync ? new Date(sync.last_sync).toLocaleString() : 'No successful sync yet'}
          </small>
        </article>
      </section>

      <section className="product-card">
        <header className="product-card-head">
          <div>
            <p className="eyebrow">AUTOMATION ACTIVITY</p>
            <h2>Recent agent runs</h2>
          </div>
          <span className="product-pill">{runs.length}</span>
        </header>

        {loading ? (
          <div className="product-empty">Loading sync history…</div>
        ) : runs.length ? (
          <div className="product-list">
            {runs.map((run) => (
              <article className="activity-run" key={run.id}>
                <div className="product-row">
                  <span className="product-icon">
                    <Icon name="refresh" size={15} />
                  </span>
                  <span className="product-row-main">
                    <strong>{(run.trigger || 'Sync').replaceAll('_', ' ')}</strong>
                    <small>
                      {run.started_at ? new Date(run.started_at).toLocaleString() : 'Time unavailable'}
                      {run.duration_seconds != null
                        ? ` · ${Math.round(run.duration_seconds)} sec`
                        : ''}
                    </small>
                    <small>
                      {run.assignments_found ?? 0} assignments found · {run.changes_found ?? 0} changes ·{' '}
                      {run.notifications_sent ?? 0} notifications
                    </small>
                    {run.errors > 0 && (
                      <small className="run-error">
                        {run.error_details || `${run.errors} run errors`}
                      </small>
                    )}
                  </span>
                  <span className={`product-pill ${runTone(run.status)}`}>
                    {(run.status || 'unknown').toLowerCase()}
                  </span>
                  <button
                    type="button"
                    className="product-action secondary"
                    onClick={() => toggleEvents(run.id)}
                  >
                    {expandedRun === run.id ? 'Hide details' : 'View details'}
                  </button>
                </div>

                {expandedRun === run.id && (
                  <div className="run-event-list">
                    {runEvents[run.id] ? (
                      runEvents[run.id].length ? (
                        runEvents[run.id].map((event) => (
                          <div className="run-event" key={event.id}>
                            <span className={`product-pill ${runTone(event.status?.toUpperCase())}`}>
                              {event.status || event.event_type}
                            </span>
                            <span>
                              <strong>{event.message || event.source || 'Sync event'}</strong>
                              {event.created_at && (
                                <small>{new Date(event.created_at).toLocaleString()}</small>
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
          <div className="product-empty">
            <strong>No automation runs yet</strong>
            Run a Classroom sync to start recording background activity.
          </div>
        )}
      </section>

      <p className="product-note">
        This page reports recent agent runs and the latest Classroom sync status. Syncs run in the
        background after you start them.
      </p>
    </div>
  );
}
