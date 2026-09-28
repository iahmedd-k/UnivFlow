'use client';

import { useMemo } from 'react';
import Icon from '@/app/dashboard/Icon';

export interface ExecutionResult {
  success: boolean;
  execution_id: string;
  execution_type: string;
  language: string;
  stdout: string;
  stderr: string;
  output: string;
  exit_code: number | null;
  signal: string | null;
  timed_out: boolean;
  execution_time: number;
  attempt: number;
  error_type: string | null;
  error_message: string | null;
  columns?: string[];
  rows?: any[][];
  affected_rows?: number;
  database_type?: string;
  database_name?: string;
}

interface ExecutionConsoleProps {
  result: ExecutionResult | null;
  code?: string;
  showCode?: boolean;
  compact?: boolean;
}

const STATUS_CONFIG = {
  success: { label: '✓ Success', color: '#10b981', bg: '#ecfdf5', border: '#10b98133', icon: 'checkCircle' },
  error: { label: '✗ Error', color: '#ef4444', bg: '#fef2f2', border: '#ef444433', icon: 'alertCircle' },
  timeout: { label: '⏱ Timeout', color: '#f59e0b', bg: '#fffbeb', border: '#f59e0b33', icon: 'clock' },
  unsupported_language: { label: '⚠ Unsupported', color: '#6b7280', bg: '#f9fafb', border: '#9ca3af33', icon: 'alertTriangle' },
  backend_unavailable: { label: '⚠ Backend Unavailable', color: '#ef4444', bg: '#fef2f2', border: '#ef444433', icon: 'serverOff' },
  limit_exceeded: { label: '⚠ Limit Exceeded', color: '#f59e0b', bg: '#fffbeb', border: '#f59e0b33', icon: 'alertTriangle' },
} as const;

const LANGUAGE_COLORS: Record<string, string> = {
  python: '#3776ab',
  javascript: '#f7df1e',
  typescript: '#3178c6',
  c: '#a8b9cc',
  cpp: '#00599c',
  java: '#ed8b00',
  go: '#00add8',
  assembly: '#6e4c13',
  sqlite: '#003b57',
  mysql: '#4479a1',
  mongodb: '#47a248',
};

function formatTime(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatExitCode(code: number | null, signal: string | null): string {
  if (signal) return `Signal: ${signal}`;
  if (code === null) return 'N/A';
  return `Exit code: ${code}`;
}

function StatusBadge({ status }: { status: keyof typeof STATUS_CONFIG }) {
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
      <Icon name={config.icon as any} size={12} />
      {config.label}
    </span>
  );
}

function InfoRow({ label, value, icon, monospace = false }: { 
  label: string; 
  value: string; 
  icon?: string; 
  monospace?: boolean 
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
      {icon && <Icon name={icon as any} size={14} style={{ color: '#64748b', flexShrink: 0 }} />}
      <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500, minWidth: 100 }}>{label}</span>
      <span style={{ fontSize: 11, color: '#1e293b', fontFamily: monospace ? 'ui-monospace, monospace' : 'inherit', wordBreak: 'break-all' }}>
        {value}
      </span>
    </div>
  );
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  return (
    <div style={{ borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden', background: '#0f172a' }}>
      <div style={{ padding: '8px 12px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#94a3b8', fontSize: 11, fontFamily: 'monospace' }}>
          {language}
        </span>
      </div>
      <pre style={{ margin: 0, padding: '12px 14px', color: '#e2e8f0', fontSize: 11, lineHeight: 1.6, overflowX: 'auto', maxHeight: 200, fontFamily: 'ui-monospace, monospace' }}>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function OutputSection({ label, content, color, emptyMessage }: { 
  label: string; 
  content: string; 
  color: string; 
  emptyMessage: string 
}) {
  const hasContent = content && content.trim().length > 0;
  
  return (
    <div style={{ borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden', background: '#0b0f19' }}>
      <div style={{ padding: '8px 12px', background: '#161f30', borderBottom: '1px solid #232d42', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: color, fontSize: 11, fontFamily: 'monospace', fontWeight: 600 }}>{label}</span>
      </div>
      {hasContent ? (
        <pre style={{ margin: 0, padding: '12px 14px', color, fontSize: 11, lineHeight: 1.5, fontFamily: 'ui-monospace, monospace', maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {content}
        </pre>
      ) : (
        <div style={{ padding: '12px 14px', color: '#64748b', fontSize: 11, fontStyle: 'italic' }}>
          {emptyMessage}
        </div>
      )}
    </div>
  );
}

function DatabaseResultsTable({ columns, rows }: { columns: string[]; rows: any[][] }) {
  if (!columns.length || !rows.length) return null;

  return (
    <div style={{ borderRadius: 8, border: '1px solid #e2e8f0', overflow: 'hidden', background: '#ffffff' }}>
      <div style={{ padding: '8px 12px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ color: '#334155', fontSize: 11, fontWeight: 600 }}>Query Results</span>
        <span style={{ color: '#64748b', fontSize: 10 }}>{rows.length} row{rows.length !== 1 ? 's' : ''}</span>
      </div>
      <div style={{ overflowX: 'auto', maxHeight: 300 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              {columns.map((col, i) => (
                <th key={i} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#334155', borderBottom: '1px solid #e2e8f0', whiteSpace: 'nowrap' }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex} style={{ background: rowIndex % 2 === 0 ? '#ffffff' : '#f8fafc' }}>
                {row.map((cell, colIndex) => (
                  <td key={colIndex} style={{ padding: '6px 12px', color: '#1e293b', borderBottom: '1px solid #f1f5f9', fontFamily: 'ui-monospace, monospace', fontSize: 10, whiteSpace: 'nowrap', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {cell === null ? <span style={{ color: '#94a3b8', fontStyle: 'italic' }}>NULL</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ExecutionConsole({ result, code, showCode = true, compact = false }: ExecutionConsoleProps) {
  if (!result) {
    return (
      <div style={{ padding: 20, textAlign: 'center', color: '#94a3b8', fontSize: 13 }}>
        <Icon name="terminal" size={32} style={{ marginBottom: 8, opacity: 0.5 }} />
        <p>No execution result to display</p>
      </div>
    );
  }

  const isDatabase = result.execution_type === 'database';
  const statusKey = result.success ? 'success' : (result.status || 'error') as keyof typeof STATUS_CONFIG;
  const languageColor = LANGUAGE_COLORS[result.language] || '#6657d9';

  const metadata = useMemo(() => [
    { label: 'Language', value: result.language.toUpperCase(), icon: 'code' },
    { label: 'Execution Time', value: formatTime(result.execution_time * 1000), icon: 'clock' },
    { label: 'Attempt', value: String(result.attempt), icon: 'gitBranch' },
    { label: formatExitCode(result.exit_code, result.signal), value: '', icon: 'terminal' },
    { label: result.timed_out ? 'Status' : '', value: result.timed_out ? 'Timed Out' : '', icon: 'alertTriangle' },
  ].filter(m => m.value), [result]);

  const databaseMetadata = useMemo(() => [
    { label: 'Database', value: result.database_type?.toUpperCase() || 'Unknown', icon: 'database' },
    { label: 'Database Name', value: result.database_name || 'N/A', icon: 'file' },
    { label: 'Execution Time', value: formatTime(result.execution_time * 1000), icon: 'clock' },
    { label: 'Columns', value: String(result.columns?.length || 0), icon: 'list' },
    { label: 'Rows Returned', value: String(result.rows?.length || 0), icon: 'table' },
    { label: 'Affected Rows', value: String(result.affected_rows || 0), icon: 'edit' },
  ].filter(m => m.value), [result]);

  if (compact) {
    return (
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden', background: '#ffffff' }}>
        <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ width: 28, height: 28, borderRadius: 8, background: `${languageColor}22`, color: languageColor, display: 'grid', placeItems: 'center', fontSize: 12, fontWeight: 700 }}>
              <Icon name="terminal" size={14} />
            </span>
            <div>
              <strong style={{ display: 'block', fontSize: 12, color: '#1e293b' }}>{result.language}</strong>
              <StatusBadge status={statusKey} />
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: '#64748b' }}>
            <span>⏱ {formatTime(result.execution_time * 1000)}</span>
            <span>#{result.attempt}</span>
            {result.exit_code !== null && <span>Exit: {result.exit_code}</span>}
          </div>
        </div>
        
        {(code && showCode) && (
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #e2e8f0' }}>
            <CodeBlock code={code} language={result.language} />
          </div>
        )}
        
        <div style={{ padding: '12px 16px' }}>
          {isDatabase ? (
            <>
              {result.stdout && <OutputSection label="STDOUT" content={result.stdout} color="#34d399" emptyMessage="No output" />}
              {result.stderr && <OutputSection label="STDERR" content={result.stderr} color="#f87171" emptyMessage="No errors" />}
              <DatabaseResultsTable columns={result.columns || []} rows={result.rows || []} />
            </>
          ) : (
            <>
              {result.stdout && <OutputSection label="STDOUT" content={result.stdout} color="#34d399" emptyMessage="No output" />}
              {result.stderr && <OutputSection label="STDERR" content={result.stderr} color="#f87171" emptyMessage="No errors" />}
              {(result.output && result.output !== result.stdout) && (
                <OutputSection label="OUTPUT" content={result.output} color="#60a5fa" emptyMessage="No combined output" />
              )}
            </>
          )}
        </div>
        
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
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${languageColor}15`, color: languageColor, display: 'grid', placeItems: 'center' }}>
            <Icon name={isDatabase ? 'database' : 'terminal'} size={20} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <strong style={{ fontSize: 14, color: '#1e293b' }}>{result.language.toUpperCase()}</strong>
              <StatusBadge status={statusKey} />
            </div>
            <span style={{ fontSize: 11, color: '#64748b' }}>Execution ID: {result.execution_id}</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 11, color: '#64748b' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="clock" size={12} /> {formatTime(result.execution_time * 1000)}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Icon name="gitBranch" size={12} /> Attempt {result.attempt}
          </span>
          {result.exit_code !== null && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'monospace' }}>
              <Icon name="terminal" size={12} /> Exit {result.exit_code}
            </span>
          )}
        </div>
      </div>

      {/* Code Section */}
      {(code && showCode) && (
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e2e8f0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Icon name="code" size={14} style={{ color: '#64748b' }} />
            <strong style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Source Code</strong>
          </div>
          <CodeBlock code={code} language={result.language} />
        </div>
      )}

      {/* Metadata Grid */}
      <div style={{ padding: '16px 20px', background: '#fafafa', borderBottom: '1px solid #e2e8f0' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          {(isDatabase ? databaseMetadata : metadata).map((item, index) => (
            <InfoRow key={index} {...item} monospace={item.label.includes('Exit') || item.label.includes('Signal')} />
          ))}
        </div>
      </div>

      {/* Output Sections */}
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {isDatabase ? (
          <>
            {result.stdout && <OutputSection label="STDOUT" content={result.stdout} color="#34d399" emptyMessage="No output" />}
            {result.stderr && <OutputSection label="STDERR" content={result.stderr} color="#f87171" emptyMessage="No errors" />}
            <DatabaseResultsTable columns={result.columns || []} rows={result.rows || []} />
          </>
        ) : (
          <>
            {result.stdout && <OutputSection label="STDOUT" content={result.stdout} color="#34d399" emptyMessage="No output" />}
            {result.stderr && <OutputSection label="STDERR" content={result.stderr} color="#f87171" emptyMessage="No errors" />}
            {(result.output && result.output !== result.stdout) && (
              <OutputSection label="COMBINED OUTPUT" content={result.output} color="#60a5fa" emptyMessage="No combined output" />
            )}
          </>
        )}
      </div>

      {/* Error Details */}
      {result.error_message && (
        <div style={{ padding: '16px 20px', background: '#fef2f2', borderTop: '1px solid #fecaca' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, color: '#dc2626', fontSize: 12 }}>
            <Icon name="alertCircle" size={16} style={{ marginTop: 2, flexShrink: 0 }} />
            <div>
              <strong style={{ display: 'block', marginBottom: 4 }}>{result.error_type || 'Execution Error'}</strong>
              <span style={{ wordBreak: 'break-word' }}>{result.error_message}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}