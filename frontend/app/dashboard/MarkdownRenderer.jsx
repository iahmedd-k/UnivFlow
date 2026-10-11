'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

const components = {
  code: ({ inline, className, children, ...props }) => (
    inline ? (
      <code {...props} className={`rounded border border-line bg-paper px-1.5 py-0.5 font-mono text-[0.9em] text-ink ${className || ''}`}>
        {children}
      </code>
    ) : (
      <code {...props} className={`block min-w-0 font-mono text-sm leading-6 text-slate-100 ${className || ''}`}>
        {String(children).replace(/\n$/, '')}
      </code>
    )
  ),
  pre: ({ children, ...props }) => (
    <pre {...props} className="my-3 overflow-x-auto rounded-lg border border-slate-700 bg-slate-900 p-4 text-sm leading-6 text-slate-100">
      {children}
    </pre>
  ),
  p: ({ children, ...props }) => <p {...props} className="my-2 leading-6 text-slate-700">{children}</p>,
  h1: ({ children, ...props }) => <h1 {...props} className="my-4 text-2xl font-bold tracking-tight text-ink">{children}</h1>,
  h2: ({ children, ...props }) => <h2 {...props} className="my-3 text-xl font-semibold tracking-tight text-ink">{children}</h2>,
  h3: ({ children, ...props }) => <h3 {...props} className="my-3 text-lg font-semibold text-ink">{children}</h3>,
  ul: ({ children, ...props }) => <ul {...props} className="my-2 list-disc space-y-1 pl-6 leading-6 text-slate-700">{children}</ul>,
  ol: ({ children, ...props }) => <ol {...props} className="my-2 list-decimal space-y-1 pl-6 leading-6 text-slate-700">{children}</ol>,
  li: ({ children, ...props }) => <li {...props} className="pl-1">{children}</li>,
  blockquote: ({ children, ...props }) => (
    <blockquote {...props} className="my-3 rounded-r-lg border-l-4 border-violet bg-violet-light/60 px-4 py-3 italic text-muted">
      {children}
    </blockquote>
  ),
  table: ({ children, ...props }) => (
    <div className="my-3 overflow-x-auto">
      <table {...props} className="w-full border-collapse border border-line text-sm">
        {children}
      </table>
    </div>
  ),
  th: ({ children, ...props }) => <th {...props} className="border border-line bg-paper px-3 py-2 text-left font-semibold text-ink">{children}</th>,
  td: ({ children, ...props }) => <td {...props} className="border border-line px-3 py-2 text-slate-700 even:bg-paper">{children}</td>,
  tr: ({ children, ...props }) => <tr {...props} className="even:bg-paper">{children}</tr>,
  strong: ({ children, ...props }) => <strong {...props} className="font-semibold text-ink">{children}</strong>,
  em: ({ children, ...props }) => <em {...props} className="text-slate-700">{children}</em>,
  hr: ({ ...props }) => <hr {...props} className="my-4 border-0 border-t border-line" />,
  a: ({ href, children, ...props }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium text-violet underline decoration-violet/40 underline-offset-2 hover:text-violet-dark" {...props}>
      {children}
    </a>
  ),
};

export default function MarkdownRenderer({ content, className = '' }) {
  if (!content) return null;

  return (
    <div className={`min-w-0 text-sm text-slate-700 ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
