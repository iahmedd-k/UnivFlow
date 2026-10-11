'use client';

import { useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import DiagramViewer from '@/app/dashboard/DiagramViewer';
import Icon from '@/app/dashboard/Icon';

const SAMPLE_DIAGRAMS = {
  flowchart: `flowchart TD
    User --> Frontend
    Frontend --> API
    API --> Auth
    API --> Agent
    Agent --> LLM
    Agent --> Database
    Agent --> ExternalAPIs
    Database --> PostgreSQL
    ExternalAPIs --> Google
    ExternalAPIs --> GitHub`,
  sequence: `sequenceDiagram
    actor User
    participant Frontend
    participant API
    participant Agent
    participant Piston

    User->>Frontend: Request execution
    Frontend->>API: Submit code
    API->>Agent: Execute code
    Agent->>Piston: Execute program
    Piston-->>Agent: Execution result
    Agent-->>API: Normalized result
    API-->>Frontend: Result
    Frontend-->>User: Display output`,
  class: `classDiagram
    class User {
        +int id
        +string name
        +string email
        +login()
        +logout()
    }

    class Assignment {
        +int id
        +string title
        +string description
        +datetime due_date
        +submit()
    }

    class Solution {
        +int id
        +string code
        +string language
        +execute()
    }

    User "1" --> "*" Assignment
    Assignment "1" --> "*" Solution`,
  er: `erDiagram
    USER ||--o{ ASSIGNMENT : creates
    USER ||--o{ SUBMISSION : submits
    ASSIGNMENT ||--o{ SUBMISSION : receives
    ASSIGNMENT ||--o{ SOLUTION : generates
    SOLUTION ||--o{ EXECUTION_RESULT : produces

    USER {
        int id PK
        string name
        string email
    }

    ASSIGNMENT {
        int id PK
        int user_id FK
        string title
        datetime due_date
    }

    SUBMISSION {
        int id PK
        int user_id FK
        int assignment_id FK
        string status
    }

    SOLUTION {
        int id PK
        int assignment_id FK
        string code
        string language
    }`,
  state: `stateDiagram-v2
    [*] --> Pending
    Pending --> Processing : Start
    Processing --> Completed : Success
    Processing --> Failed : Error
    Failed --> Processing : Retry
    Completed --> [*]
    Failed --> [*] : Max retries`,
  gantt: `gantt
    title Uniflow Development Timeline
    dateFormat YYYY-MM-DD

    section Backend
    Core API       :done, api1, 2026-09-01, 10d
    Auth System    :done, auth1, after api1, 5d
    Code Execution :active, exec1, after auth1, 7d
    Diagram Gen    :diagram1, after exec1, 5d

    section Frontend
    Dashboard      :done, dash1, 2026-09-05, 8d
    Assignment UI  :dash2, after dash1, 5d
    Diagram Viewer :viewer1, after diagram1, 3d

    section Testing
    Unit Tests     :test1, after exec1, 3d
    Integration    :test2, after viewer1, 3d`,
  mindmap: `mindmap
  root((Uniflow))
    Agent
      Code Execution
      Database
      Diagram Gen
    Frontend
      Dashboard
      Assignments
      Classroom
    Backend
      FastAPI
      PostgreSQL
      Redis
    Integrations
      Google
      GitHub
      Piston
      Kroki`,
  c4context: `flowchart TB
    subgraph System [Uniflow System]
      Agent[AI Agent]
      API[FastAPI Backend]
      DB[(PostgreSQL)]
      Piston[Piston Code Runner]
      Kroki[Kroki Diagram Renderer]
    end

    User((User))
    Google((Google OAuth))
    LLM((Groq LLM))

    User --> Agent
    User --> API
    API --> Agent
    Agent --> LLM
    Agent --> Piston
    Agent --> Kroki
    Agent --> DB
    API --> Google
    API --> DB`,
};

const DIAGRAM_TYPES = [
  { id: 'flowchart', name: 'Flowchart', description: 'System architecture, workflows, processes' },
  { id: 'sequence', name: 'Sequence Diagram', description: 'API flows, interactions, protocols' },
  { id: 'class', name: 'Class Diagram', description: 'Object-oriented structures, relationships' },
  { id: 'er', name: 'ER Diagram', description: 'Database schemas, relationships' },
  { id: 'state', name: 'State Diagram', description: 'Lifecycle, state transitions' },
  { id: 'gantt', name: 'Gantt Chart', description: 'Project timelines, schedules' },
  { id: 'mindmap', name: 'Mindmap', description: 'Concepts, brainstorming, hierarchies' },
  { id: 'c4context', name: 'C4 Context', description: 'System context, high-level architecture' },
];

export default function DiagramDemo() {
  const { getToken } = useAuth();
  const [selectedType, setSelectedType] = useState('flowchart');
  const [source, setSource] = useState(SAMPLE_DIAGRAMS.flowchart);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showSource, setShowSource] = useState(true);
  const [compact, setCompact] = useState(false);
  const [outputFormat, setOutputFormat] = useState('svg');

  const handleTypeChange = (type) => {
    setSelectedType(type);
    setSource(SAMPLE_DIAGRAMS[type] || '');
    setResult(null);
    setError('');
  };

  const handleGenerate = async () => {
    if (!source.trim()) {
      setError('Please enter diagram source');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const token = getToken ? await getToken() : null;
      const response = await api.generateDiagram({
        diagram_type: 'mermaid',
        diagram_kind: selectedType,
        source,
        output_format: outputFormat,
        max_attempts: 2,
      }, token);
      setResult(response);
    } catch (err) {
      setError(err.message || 'Generation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1100px', margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#1e293b', marginBottom: 8 }}>
          Diagram Generation Demo
        </h1>
        <p style={{ color: '#64748b', fontSize: 14 }}>
          Generate diagrams using Mermaid + Kroki. Supports flowcharts, sequence diagrams, class diagrams, ER diagrams, state diagrams, Gantt charts, mindmaps, and C4 context diagrams.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 24 }}>
        {/* Sidebar */}
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, height: 'fit-content' }}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Diagram Type
            </label>
            <select
              value={selectedType}
              onChange={(e) => handleTypeChange(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, background: '#ffffff', color: '#1e293b', cursor: 'pointer' }}
            >
              {DIAGRAM_TYPES.map((t) => (
                <option key={t.id} value={t.id} title={t.description}>{t.name}</option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Output Format
            </label>
            <select
              value={outputFormat}
              onChange={(e) => setOutputFormat(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, background: '#ffffff', color: '#1e293b', cursor: 'pointer' }}
            >
              <option value="svg">SVG (Vector)</option>
              <option value="png">PNG (Raster)</option>
              <option value="pdf">PDF</option>
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#334155', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={showSource}
                onChange={(e) => setShowSource(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#6657d9' }}
              />
              Show Source
            </label>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#334155', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={compact}
                onChange={(e) => setCompact(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#6657d9' }}
              />
              Compact Mode
            </label>
          </div>

          <button
            onClick={handleGenerate}
            disabled={loading || !source.trim()}
            style={{
              width: '100%',
              padding: '12px 16px',
              background: loading ? '#94a3b8' : '#6657d9',
              color: '#ffffff',
              border: 'none',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            {loading ? (
              <>
                <span style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid #ffffff', borderTopColor: 'transparent', animation: 'spin 1s linear infinite' }} />
                Generating...
              </>
            ) : (
              <>
                <Icon name="image" size={16} />
                Generate Diagram
              </>
            )}
          </button>

          {error && (
            <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 12 }}>
              <strong>Error:</strong> {error}
            </div>
          )}
        </div>

        {/* Editor & Viewer */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Source Editor */}
          <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name="code" size={16} style={{ color: '#64748b' }} />
                <strong style={{ fontSize: 12, color: '#334155' }}>Mermaid Source</strong>
                <span style={{ fontSize: 10, padding: '2px 6px', background: '#e2e8f0', color: '#475569', borderRadius: 4, textTransform: 'uppercase' }}>
                  mermaid
                </span>
              </div>
              <span style={{ fontSize: 10, color: '#94a3b8' }}>{source.split('\n').length} lines</span>
            </div>
            <textarea
              value={source}
              onChange={(e) => setSource(e.target.value)}
              style={{
                width: '100%',
                minHeight: 300,
                padding: '16px',
                border: 'none',
                outline: 'none',
                fontFamily: 'ui-monospace, monospace',
                fontSize: 13,
                lineHeight: 1.6,
                color: '#1e293b',
                background: '#ffffff',
                resize: 'vertical',
              }}
              placeholder="Enter Mermaid diagram source..."
              spellCheck={false}
            />
          </div>

          {/* Diagram Viewer */}
          <DiagramViewer
            result={result}
            showSource={showSource}
            compact={compact}
          />
        </div>
      </div>

      <style jsx>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}