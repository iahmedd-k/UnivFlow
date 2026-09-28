'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';

const components = {
  code: ({ node, inline, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || '');
    return !inline ? (
      <pre {...props} style={{ 
        background: '#0f172a', 
        borderRadius: 8, 
        padding: '16px', 
        overflowX: 'auto',
        margin: '12px 0',
        fontSize: '12px',
        lineHeight: 1.5,
        border: '1px solid #1e293b',
      }}>
        <code className={className} style={{ color: '#e2e8f0', fontFamily: 'ui-monospace, monospace' }}>
          {String(children).replace(/\n$/, '')}
        </code>
      </pre>
    ) : (
      <code {...props} style={{ 
        background: '#f1f5f9', 
        padding: '2px 6px', 
        borderRadius: 4, 
        fontSize: '0.875em',
        fontFamily: 'ui-monospace, monospace',
        color: '#334155',
        border: '1px solid #e2e8f0',
      }}>
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }) => (
    <div {...props} style={{ margin: '12px 0' }}>
      {children}
    </div>
  ),
  p: ({ children, ...props }) => (
    <p {...props} style={{ margin: '8px 0', lineHeight: 1.6, color: '#334155' }}>
      {children}
    </p>
  ),
  h1: ({ children, ...props }) => <h1 {...props} style={{ fontSize: '1.5rem', fontWeight: 700, margin: '16px 0 8px', color: '#1e293b' }}>{children}</h1>,
  h2: ({ children, ...props }) => <h2 {...props} style={{ fontSize: '1.25rem', fontWeight: 600, margin: '14px 0 8px', color: '#1e293b' }}>{children}</h2>,
  h3: ({ children, ...props }) => <h3 {...props} style={{ fontSize: '1.125rem', fontWeight: 600, margin: '12px 0 6px', color: '#1e293b' }}>{children}</h3>,
  ul: ({ children, ...props }) => <ul {...props} style={{ margin: '8px 0', paddingLeft: '24px', lineHeight: 1.6 }}>{children}</ul>,
  ol: ({ children, ...props }) => <ol {...props} style={{ margin: '8px 0', paddingLeft: '24px', lineHeight: 1.6 }}>{children}</ol>,
  li: ({ children, ...props }) => <li {...props} style={{ margin: '4px 0' }}>{children}</li>,
  blockquote: ({ children, ...props }) => (
    <blockquote {...props} style={{ 
      borderLeft: '3px solid #6657d9', 
      paddingLeft: '12px', 
      margin: '12px 0', 
      color: '#64748b',
      fontStyle: 'italic',
      background: '#f8fafc',
      padding: '8px 12px',
      borderRadius: '0 8px 8px 0',
    }}>
      {children}
    </blockquote>
  ),
  table: ({ children, ...props }) => (
    <div style={{ overflowX: 'auto', margin: '12px 0' }}>
      <table {...props} style={{ 
        borderCollapse: 'collapse', 
        width: '100%', 
        fontSize: '0.875rem',
        border: '1px solid #e2e8f0',
        borderRadius: 8,
        overflow: 'hidden',
      }}>
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...props }) => (
    <th {...props} style={{ 
      border: '1px solid #e2e8f0', 
      padding: '8px 12px', 
      background: '#f8fafc', 
      fontWeight: 600,
      textAlign: 'left',
      color: '#1e293b',
    }}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td {...props} style={{ 
      border: '1px solid #e2e8f0', 
      padding: '8px 12px',
      color: '#334155',
    }}>
      {children}
    </td>
  ),
  tr: ({ children, index, ...props }) => (
    <tr {...props} style={{ 
      background: index % 2 === 0 ? '#ffffff' : '#f8fafc',
    }}>
      {children}
    </tr>
  ),
  strong: ({ children, ...props }) => <strong {...props} style={{ fontWeight: 600, color: '#1e293b' }}>{children}</strong>,
  em: ({ children, ...props }) => <em {...props} style={{ fontStyle: 'italic', color: '#334155' }}>{children}</em>,
  hr: ({ ...props }) => <hr {...props} style={{ border: 'none', borderTop: '1px solid #e2e8f0', margin: '16px 0' }} />,
  a: ({ href, children, ...props }) => (
    <a 
      href={href} 
      target="_blank" 
      rel="noopener noreferrer" 
      style={{ color: '#6657d9', textDecoration: 'underline', textUnderlineOffset: '2px' }}
      {...props}
    >
      {children}
    </a>
  ),
};

export default function MarkdownRenderer({ content, className = '' }) {
  if (!content) return null;

  return (
    <div className={className} style={{ fontSize: '0.875rem', color: '#334155' }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}