'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

/**
 * Turn-in tab: the student attaches the files THEY produced, picks a
 * cover/template if one applies, and submits to Google Classroom.
 */
export default function TurnInPanel({ assignment, onTurnIn }) {
  const { getToken } = useAuth();
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [submitted, setSubmitted] = useState(
    assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED'
  );
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleMinutesBefore, setScheduleMinutesBefore] = useState(60);
  const [savingSchedule, setSavingSchedule] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = getToken ? await getToken() : null;
        const data = await api.getAssignmentTemplates(token);
        if (!cancelled) {
          setTemplates(data || []);
          const def = data?.find((t) => t.is_default);
          if (def) setSelectedTemplateId(def.id);
        }
      } catch (e) {
        console.error('Failed to load templates:', e);
      }
    })();
    return () => { cancelled = true; };
  }, [getToken]);

  const handleFileChange = (e) => {
    const picked = Array.from(e.target.files || []);
    setFiles((prev) => [
      ...prev,
      ...picked.map((f) => ({
        name: f.name,
        size: (f.size / 1024).toFixed(1) + ' KB',
        fileObj: f,
      })),
    ]);
  };

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx));

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await onTurnIn(assignment.id, selectedTemplateId, files.map((f) => f.name), token);
      setSubmitted(true);
      setNotice('Assignment turned in successfully to Google Classroom!');
    } catch (e) {
      setError(e.message || 'Turn-in failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const saveSchedule = async () => {
    setSavingSchedule(true);
    setError(null);
    setNotice(null);
    try {
      const token = getToken ? await getToken() : null;
      await api.scheduleTurnIn(
        assignment.id,
        {
          enabled: scheduleEnabled,
          minutes_before_due: scheduleMinutesBefore,
          template_id: selectedTemplateId,
        },
        token
      );
      setNotice('Auto turn-in schedule saved successfully.');
    } catch (e) {
      setError(e.message || 'Could not save turn-in schedule.');
    } finally {
      setSavingSchedule(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.1fr) minmax(0, 1fr)', gap: 16 }}>
      {/* Left Column: Direct Deliverable Submission Studio */}
      <section className="product-card" style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <span className="eyebrow">FINAL SUBMISSION</span>
          <h3 style={{ margin: '3px 0 6px', fontSize: 15, fontWeight: 700, color: '#252837' }}>
            Submit to Google Classroom
          </h3>
          <p style={{ fontSize: 11, color: '#858998', lineHeight: 1.5, margin: 0 }}>
            Attach your completed coursework files and select a cover page template if required by your university.
          </p>
        </div>

        {/* Deliverables List */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#858998' }}>
            <span style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Attached Deliverables
            </span>
            <span>{files.length} {files.length === 1 ? 'file' : 'files'}</span>
          </div>

          {files.length === 0 ? (
            <div className="product-empty" style={{ padding: '24px 14px' }}>
              <strong>No files attached yet</strong>
              <span>Attach your code, report, or document deliverables below.</span>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 180, overflowY: 'auto' }}>
              {files.map((f, i) => (
                <div
                  key={i}
                  style={{
                    padding: '8px 12px',
                    background: '#fafafd',
                    border: '1px solid #ececf2',
                    borderRadius: 7,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 8,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    <Icon name="file" size={14}/>
                    <span style={{ fontSize: 11, fontWeight: 600, color: '#2c2f3b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {f.name}
                    </span>
                    <span style={{ fontSize: 10, color: '#858998' }}>({f.size})</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    style={{ background: 'none', border: 'none', color: '#858998', cursor: 'pointer', fontSize: 12, padding: 2 }}
                    aria-label={`Remove ${f.name}`}
                  >
                    <Icon name="close" size={13}/>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* File Picker Trigger */}
        <label className="product-action secondary" style={{ textAlign: 'center', cursor: 'pointer', display: 'block' }}>
          <span>+ Add deliverable files</span>
          <input type="file" multiple onChange={handleFileChange} style={{ display: 'none' }} />
        </label>

        {/* Cover Page Selector */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: '#696d7d', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Cover Page Template
          </label>
          <select
            value={selectedTemplateId || ''}
            onChange={(e) => setSelectedTemplateId(e.target.value ? Number(e.target.value) : null)}
            style={{
              height: 38,
              padding: '0 10px',
              border: '1px solid #e4e4eb',
              borderRadius: 8,
              background: '#fff',
              fontSize: 12,
              color: '#2c2f3b',
              outline: 'none',
              cursor: 'pointer',
            }}
          >
            <option value="">No cover template (Submit raw files)</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} {t.is_default ? '(Default)' : ''}
              </option>
            ))}
          </select>
        </div>

        {error && <div className="product-alert">{error}</div>}
        {notice && <div className="product-alert ok">{notice}</div>}

        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting || (files.length === 0 && !submitted)}
          className="primary-action"
          style={{ width: '100%', minHeight: 40, fontSize: 12, cursor: 'pointer' }}
        >
          {submitting ? (
            <span>Submitting to Google Classroom…</span>
          ) : submitted ? (
            <span><Icon name="checkCircle" size={14}/> Turned In to Classroom</span>
          ) : (
            <span><Icon name="upload" size={14}/> Turn In to Google Classroom</span>
          )}
        </button>

        {assignment.url && (
          <a
            href={assignment.url}
            target="_blank"
            rel="noreferrer"
            style={{ textAlign: 'center', fontSize: 11, color: '#6657d9', textDecoration: 'underline', marginTop: -4 }}
          >
            Open assignment in Google Classroom <Icon name="externalLink" size={13}/>
          </a>
        )}
      </section>

      {/* Right Column: Scheduled Auto-Submit Automation */}
      <section className="product-card" style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <span className="eyebrow">AUTOMATION</span>
          <h3 style={{ margin: '3px 0 6px', fontSize: 15, fontWeight: 700, color: '#252837' }}>
            Scheduled Auto Turn-In
          </h3>
          <p style={{ fontSize: 11, color: '#858998', lineHeight: 1.5, margin: 0 }}>
            Attach your work now and schedule Uniflow to turn in automatically before the deadline so you never miss a submission window.
          </p>
        </div>

        {/* Enable Automation Toggle */}
        <label
          style={{
            padding: '12px 14px',
            background: '#fafafd',
            border: '1px solid #ececf2',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
          }}
        >
          <div>
            <strong style={{ display: 'block', fontSize: 12, color: '#2c2f3b' }}>
              Enable Automatic Submission
            </strong>
            <small style={{ fontSize: 10, color: '#858998' }}>
              Submits attached files automatically prior to due date
            </small>
          </div>
          <input
            type="checkbox"
            checked={scheduleEnabled}
            onChange={(e) => setScheduleEnabled(e.target.checked)}
            style={{ width: 18, height: 18, accentColor: '#6657d9', cursor: 'pointer' }}
          />
        </label>

        {/* Offset Input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: '#696d7d' }}>
            Minutes Before Deadline
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <input
              type="number"
              min={5}
              max={1440}
              value={scheduleMinutesBefore}
              onChange={(e) => setScheduleMinutesBefore(parseInt(e.target.value, 10) || 60)}
              disabled={!scheduleEnabled}
              style={{
                width: 100,
                height: 38,
                padding: '0 10px',
                border: '1px solid #e4e4eb',
                borderRadius: 8,
                fontSize: 12,
                color: '#2c2f3b',
                background: '#fff',
                outline: 'none',
              }}
            />
            <span style={{ fontSize: 11, color: '#858998' }}>
              mins prior ({Math.round((scheduleMinutesBefore / 60) * 10) / 10} hours)
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={saveSchedule}
          disabled={files.length === 0 || savingSchedule}
          className="product-action secondary"
          style={{ width: '100%', minHeight: 38, fontSize: 11, cursor: 'pointer' }}
        >
          {savingSchedule ? 'Saving schedule…' : <><Icon name="save" size={14}/> Save Schedule Settings</>}
        </button>

        {files.length === 0 && (
          <p className="product-note" style={{ margin: 0 }}>
            Attach at least one deliverable file on the left before activating auto turn-in.
          </p>
        )}
      </section>
    </div>
  );
}
