'use client';

import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  Download,
  ExternalLink,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  Layers,
  Image as ImageIcon,
  ArrowRight,
  RefreshCw,
} from 'lucide-react';
import { api } from '@/app/lib/api';

const detectPlatform = (url) => {
  if (!url) return null;
  const lower = url.toLowerCase();
  if (lower.includes('chatgpt.com') || lower.includes('openai.com')) {
    return { id: 'chatgpt', name: 'ChatGPT', color: 'emerald', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200' };
  }
  if (lower.includes('claude.ai')) {
    return { id: 'claude', name: 'Claude AI', color: 'amber', bg: 'bg-amber-50 text-amber-800 border-amber-200' };
  }
  if (lower.includes('gemini.google.com') || lower.includes('g.co/gemini')) {
    return { id: 'gemini', name: 'Google Gemini', color: 'blue', bg: 'bg-blue-50 text-blue-700 border-blue-200' };
  }
  return { id: 'generic', name: 'Web AI Chat', color: 'indigo', bg: 'bg-indigo-50 text-indigo-700 border-indigo-200' };
};

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 KB';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
};

export default function WebChatImportModal({ isOpen, onClose, onExportSuccess, onViewLibrary }) {
  const [url, setUrl] = useState('');
  const [customTitle, setCustomTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [stepIndex, setStepIndex] = useState(0);

  const platform = detectPlatform(url);
  const isPublic = url && (url.includes('/share/') || url.includes('g.co/gemini/share'));

  // Multi-step progress animation while processing
  useEffect(() => {
    let timer;
    if (loading) {
      setStepIndex(0);
      timer = setInterval(() => {
        setStepIndex((prev) => (prev < 3 ? prev + 1 : prev));
      }, 3500);
    } else {
      setStepIndex(0);
    }
    return () => clearInterval(timer);
  }, [loading]);

  if (!isOpen) return null;

  const handleReset = () => {
    setUrl('');
    setCustomTitle('');
    setError('');
    setResult(null);
    setLoading(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;

    setError('');
    setResult(null);
    setLoading(true);

    try {
      const response = await api.exportWebChatToPdf({
        url: url.trim(),
        custom_title: customTitle.trim() || null,
      });

      const data = response?.data || response;
      if (!data || !data.id) {
        throw new Error(response?.message || 'Failed to export chat.');
      }

      setResult(data);
      if (onExportSuccess) {
        onExportSuccess(data);
      }
    } catch (err) {
      const msg = err?.message || 'Failed to generate PDF. Please ensure the link is public or companion cookies are synced.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!result) return;
    try {
      await api.downloadExportedChat(result.id, `${result.title || 'chat'}.pdf`);
    } catch (err) {
      setError('Download failed. You can also download it from the Library drawer.');
    }
  };

  const progressSteps = [
    'Launching headless Chromium browser...',
    'Scrolling 100% of conversation history (bottom to top)...',
    'Rendering Mermaid diagrams, math formulas & visual assets...',
    'Enforcing page breaks & compiling high-res A4 PDF...',
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-stone-900/50 backdrop-blur-xs transition-opacity animate-in fade-in duration-200">
      <div
        className="bg-white rounded-2xl shadow-2xl border border-stone-200 w-full max-w-lg overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-stone-100 bg-linear-to-r from-stone-50 via-white to-stone-50">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shadow-2xs">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-[16px] font-semibold text-stone-900">Export Web Chat to PDF</h3>
              <p className="text-[12px] text-stone-500">ChatGPT, Claude, or Google Gemini full chat export</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg text-stone-400 hover:text-stone-700 hover:bg-stone-100 flex items-center justify-center transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6">
          {!result ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-[13px] font-medium text-stone-700 mb-1.5">
                  Chat URL / Public Share Link <span className="text-red-500">*</span>
                </label>
                <div className="relative">
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    disabled={loading}
                    placeholder="https://chatgpt.com/share/... or https://claude.ai/share/..."
                    required
                    className="w-full text-[13px] px-3.5 py-2.5 rounded-xl border border-stone-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all placeholder:text-stone-400 disabled:bg-stone-50"
                  />
                  {platform && (
                    <span
                      className={`absolute right-2.5 top-2.5 px-2 py-0.5 rounded-md text-[11px] font-medium border ${platform.bg}`}
                    >
                      {platform.name}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between mt-1.5 text-[11px] text-stone-500">
                  <span>
                    {isPublic
                      ? '✓ Public share link detected (Zero login needed)'
                      : url
                      ? 'Direct chat link (Uses companion session key if private)'
                      : 'Tip: Create a share link in ChatGPT / Claude for instant conversion'}
                  </span>
                </div>
              </div>

              <div>
                <label className="block text-[13px] font-medium text-stone-700 mb-1.5">
                  Custom Title <span className="text-stone-400 text-[11px] font-normal">(Optional)</span>
                </label>
                <input
                  type="text"
                  value={customTitle}
                  onChange={(e) => setCustomTitle(e.target.value)}
                  disabled={loading}
                  placeholder="e.g. CS50 Algorithm Explanations"
                  className="w-full text-[13px] px-3.5 py-2 rounded-xl border border-stone-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all placeholder:text-stone-400 disabled:bg-stone-50"
                />
              </div>

              {error && (
                <div className="p-3.5 rounded-xl bg-red-50 border border-red-200 flex items-start gap-2.5 text-red-700 text-[12.5px]">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-600" />
                  <div className="leading-snug">{error}</div>
                </div>
              )}

              {loading && (
                <div className="p-4 rounded-xl bg-indigo-50/60 border border-indigo-100 space-y-3">
                  <div className="flex items-center gap-2.5 text-indigo-900 font-medium text-[13px]">
                    <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
                    <span>Processing Conversation History...</span>
                  </div>
                  <div className="space-y-1.5 text-[12px] text-stone-600 pl-6">
                    {progressSteps.map((step, idx) => (
                      <div
                        key={idx}
                        className={`transition-all duration-300 ${
                          idx === stepIndex
                            ? 'text-indigo-700 font-medium'
                            : idx < stepIndex
                            ? 'text-stone-400 line-through'
                            : 'text-stone-300'
                        }`}
                      >
                        • {step}
                      </div>
                    ))}
                  </div>
                  <div className="w-full bg-indigo-100 h-1.5 rounded-full overflow-hidden">
                    <div
                      className="bg-indigo-600 h-full rounded-full transition-all duration-500 ease-out"
                      style={{ width: `${((stepIndex + 1) / progressSteps.length) * 100}%` }}
                    />
                  </div>
                </div>
              )}

              <div className="flex items-center justify-end gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={loading}
                  className="px-4 py-2 text-[13px] font-medium text-stone-600 hover:text-stone-900 hover:bg-stone-100 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !url.trim()}
                  className="px-5 py-2 text-[13px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-xl shadow-xs transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Generating PDF...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      <span>Generate PDF</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          ) : (
            /* Success State */
            <div className="space-y-5 animate-in fade-in zoom-in-95 duration-200">
              <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 flex items-start gap-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <h4 className="text-[14px] font-semibold text-emerald-900">PDF Ready for Download!</h4>
                  <p className="text-[12px] text-emerald-700">
                    100% of conversation history and visual assets have been compiled into an academic A4 document.
                  </p>
                </div>
              </div>

              {/* Chat details card */}
              <div className="p-4 rounded-xl border border-stone-200 bg-stone-50/50 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <FileText className="w-5 h-5 text-indigo-600 shrink-0" />
                    <span className="text-[14px] font-semibold text-stone-900 line-clamp-1">
                      {result.title || 'Exported Chat'}
                    </span>
                  </div>
                  <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-stone-200/70 text-stone-700 uppercase">
                    {result.source_platform}
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-2 border-t border-stone-200/60 text-center">
                  <div className="p-2 rounded-lg bg-white border border-stone-100">
                    <div className="text-[11px] text-stone-400">Turns</div>
                    <div className="text-[13px] font-bold text-stone-800">{result.turn_count || 0}</div>
                  </div>
                  <div className="p-2 rounded-lg bg-white border border-stone-100">
                    <div className="text-[11px] text-stone-400">File Size</div>
                    <div className="text-[13px] font-bold text-stone-800">
                      {formatBytes(result.file_size_bytes)}
                    </div>
                  </div>
                  <div className="p-2 rounded-lg bg-white border border-stone-100">
                    <div className="text-[11px] text-stone-400">Visuals</div>
                    <div className="text-[13px] font-bold text-stone-800 flex items-center justify-center gap-1">
                      {result.has_images && <ImageIcon className="w-3.5 h-3.5 text-blue-500" title="Images" />}
                      {result.has_diagrams && <Layers className="w-3.5 h-3.5 text-purple-500" title="Diagrams" />}
                      {!result.has_images && !result.has_diagrams && <span>Text</span>}
                    </div>
                  </div>
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex flex-col gap-2 pt-1">
                <button
                  type="button"
                  onClick={handleDownload}
                  className="w-full py-2.5 px-4 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-[13px] flex items-center justify-center gap-2 shadow-xs transition-colors cursor-pointer"
                >
                  <Download className="w-4 h-4" />
                  <span>Download PDF Document</span>
                </button>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleReset}
                    className="flex-1 py-2 px-3 rounded-xl border border-stone-200 text-stone-700 hover:bg-stone-100 font-medium text-[12.5px] flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                  >
                    <RefreshCw className="w-3.5 h-3.5 text-stone-500" />
                    <span>Export Another</span>
                  </button>
                  {onViewLibrary && (
                    <button
                      type="button"
                      onClick={() => {
                        onClose();
                        onViewLibrary();
                      }}
                      className="flex-1 py-2 px-3 rounded-xl border border-stone-200 text-stone-700 hover:bg-stone-100 font-medium text-[12.5px] flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <span>View Library</span>
                      <ArrowRight className="w-3.5 h-3.5 text-stone-500" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

