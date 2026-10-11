'use client';

import { useState, useMemo } from 'react';
import Icon from '@/app/dashboard/Icon';

const STATUS_CONFIG = {
  success: { label: '✓ Rendered', color: '#10b981', bg: '#ecfdf5', border: '#10b98133', icon: 'checkCircle' },
  error: { label: '✗ Error', color: '#ef4444', bg: '#fef2f2', border: '#ef444433', icon: 'alertCircle' },
  timeout: { label: '⏱ Timeout', color: '#f59e0b', bg: '#fffbeb', border: '#f59e0b33', icon: 'clock' },
  size_limit: { label: '⚠ Size Limit', color: '#f59e0b', bg: '#fffbeb', border: '#f59e0b33', icon: 'alertTriangle' },
  unsupported_type: { label: '⚠ Unsupported', color: '#6b7280', bg: '#f9fafb', border: '#9ca3af33', icon: 'alertTriangle' },
  render_error: { label: '⚠ Render Error', color: '#ef4444', bg: '#fef2f2', border: '#ef444433', icon: 'alertCircle' },
  backend_unavailable: { label: '⚠ Backend Unavailable', color: '#ef4444', bg: '#fef2f2', border: '#ef444433', icon: 'serverOff' },
};

const TYPE_COLORS = {
  mermaid: '#6657d9',
  plantuml: '#e67e22',
  graphviz: '#27ae60',
  d2: '#8e44ad',
  erd: '#2c3e50',
  bpmn: '#e74c3c',
  excalidraw: '#3498db',
  vega: '#9b59b6',
  'vega-lite': '#9b59b6',
  wavedrom: '#1abc9c',
  structurizr: '#34495e',
  wireviz: '#f39c12',
};

const KIND_ICONS = {
  flowchart: 'gitBranch',
  sequence: 'arrowRightLeft',
  class: 'code',
  er: 'database',
  state: 'activity',
  gantt: 'calendar',
  pie: 'pieChart',
  gitgraph: 'gitBranch',
  journey: 'map',
  requirement: 'clipboard',
  c4context: 'globe',
  c4container: 'server',
  c4component: 'puzzle',
  c4code: 'code',
  timeline: 'clock',
  quadrant: 'grid',
  mindmap: 'brain',
  sankey: 'chart',
  block: 'square',
  packet: 'package',
};

function formatTime(ms) {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function StatusBadge({ status }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.error;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        background: config.bg,
        color: config.color,
        border: `1px solid ${config.border}`,
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      <Icon name={config.icon} size={12} />
      {config.label}
    </span>
  );
}

function InfoRow({ label, value, icon, monospace = false }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
      {icon && <Icon name={icon} size={14} style={{ color: '#64748b', flexShrink: 0 }} />}
      <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500, minWidth: 100 }}>{label}</span>
      <span style={{ fontSize: 11, color: '#1e293b', fontFamily: monospace ? 'ui-monospace, monospace' : 'inherit', wordBreak: 'break-all' }}>
        {value}
      </span>
    </div>
  );
}

function SourceCode({ source, language }) {
  return (
    <div style={{ borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden', background: '#0f172a' }}>
      <div style={{ padding: '8px 12px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#94a3b8', fontSize: 11, fontFamily: 'monospace' }}>
          {language} source
        </span>
      </div>
      <pre style={{ margin: 0, padding: '12px 14px', color: '#e2e8f0', fontSize: 11, lineHeight: 1.6, overflowX: 'auto', maxHeight: 300, fontFamily: 'ui-monospace, monospace' }}>
        <code>{source}</code>
      </pre>
    </div>
  );
}

export default function DiagramViewer({ result, showSource = true, compact = false }) {
  if (!result) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
        <Icon name="image" size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
        <p>No diagram to display</p>
      </div>
    );
  }

  const statusKey = result.success ? 'success' : (result.status || 'error');
  const typeColor = TYPE_COLORS[result.diagram_type] || '#6657d9';
  const kindIcon = KIND_ICONS[result.diagram_kind] || 'image';

  const metadata = [
    { label: 'Type', value: result.diagram_type, icon: 'layers' },
    { label: 'Kind', value: result.diagram_kind, icon: kindIcon },
    { label: 'Format', value: (result.output_format || '').toUpperCase(), icon: 'file' },
    { label: 'Render Time', value: formatTime((result.execution_time || 0) * 1000), icon: 'clock' },
    { label: 'Attempt', value: String(result.attempt || 1), icon: 'gitBranch' },
  ].filter(m => m.value);

  if (compact) {
    return (
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden', background: '#ffffff' }}>
        <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 28, height: 28, borderRadius: 8, background: `${typeColor}15`, color: typeColor, display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 700 }}>
              <Icon name={kindIcon} size={14} />
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 12, color: '#1e293b' }}>{result.diagram_kind}</strong>
              <StatusBadge status={statusKey} />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: '#64748b' }}>
            <span>⏱ {formatTime(result.execution_time * 1000)}</span>
            <span>#{result.attempt}</span>
            <span>{result.output_format.toUpperCase()}</span>
          </div>
        </div>

        {result.content_base64 && (
          <div style={{ padding: '12px 16px', textAlign: 'center', background: '#fafafa' }}>
            <img
              src={`data:${result.content_type || `image/${result.output_format}`};base64,${result.content_base64}`}
              alt="Diagram"
              style={{ maxWidth: '100%', height: 'auto', borderRadius: 4, border: '1px solid #e2e8f0', boxShadow: '0 2px 8px rgba(0,0,0,0.05)' }}
            />
          </div>
        )}

        {result.error_message && (
          <div style={{ padding: '12px 16px', background: '#fef2f2', borderTop: '1px solid #fecaca' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#dc2626', fontSize: 11 }}>
              <Icon name="alertCircle" size={14} />
              <strong>{result.error_type || 'Error'}:</strong> {result.error_message}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', background: '#ffffff' }}>
      {/* Header */}
      <div style={{ padding: '16px 20px', background: '#fafafa', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${typeColor}15`, color: typeColor, display: 'grid', placeItems: 'center' }}>
            <Icon name={kindIcon} size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <strong style={{ fontSize: 14, color: '#1e293b' }}>{result.diagram_kind.charAt(0).toUpperCase() + result.diagram_kind.slice(1)} Diagram</strong>
              <StatusBadge status={statusKey} />
            </div>
            <span style={{ fontSize: 11, color: '#64748b' }}>Diagram ID: {result.diagram_id}</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 11, color: '#64748b' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="layers" size={12} /> {result.diagram_type}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="file" size={12} /> {result.output_format.toUpperCase()}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="clock" size={12} /> {formatTime(result.execution_time * 1000)}
          </span>
        </div>
      </div>

      {/* Rendered Diagram */}
      {result.content_base64 && (
        <div style={{ padding: '20px', textAlign: 'center', background: '#fafafa', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ display: 'inline-block', maxWidth: '100%' }}>
            <img
              src={`data:${result.content_type || `image/${result.output_format}`};base64,${result.content_base64}`}
              alt="Generated diagram"
              style={{
                maxWidth: '100%',
                height: 'auto',
                borderRadius: 8,
                border: '1px solid #e2e8f0',
                boxShadow: '0 4px 16px rgba(0,0,0,0.08)',
                background: '#ffffff',
              }}
            />
          </div>
        </div>
      )}

      {/* Source Code */}
      {showSource && result.source && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Icon name="code" size={14} style={{ color: '#64748b' }} />
            <strong style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {result.diagram_type} Source
            </strong>
            <span style={{ fontSize: 10, padding: '2px 6px', background: '#e2e8f0', color: '#475569', borderRadius: 4, textTransform: 'uppercase' }}>
              {result.diagram_type}
            </span>
          </div>
          <SourceCode source={result.source} language={result.diagram_type} />
        </div>
      )}

      {/* Metadata Grid */}
      <div style={{ padding: '16px 20px', background: '#fafafa', borderBottom: '1px solid #e2e8f0' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          {metadata.map((item, index) => (
            <InfoRow key={index} {...item} />
          ))}
        </div>
      </div>

      {/* Error Details */}
      {result.error_message && (
        <div style={{ padding: '16px 20px', background: '#fef2f2', borderTop: '1px solid #fecaca' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, color: '#dc2626', fontSize: 12 }}>
            <Icon name="alertCircle" size={16} style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <strong style={{ display: 'block', marginBottom: 4 }}>{result.error_type || 'Render Error'}</strong>
              <span style={{ wordBreak: 'break-word' }}>{result.error_message}</span>
            </div>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!result.content_base64 && !result.error_message && result.success && (
        <div style={{ padding: '40px 20px', textAlign: 'center', color: '#94a3b8' }}>
          <Icon name="image" size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
          <p>Diagram rendered but no content returned</p>
        </div>
      )}
    </div>
  );
}