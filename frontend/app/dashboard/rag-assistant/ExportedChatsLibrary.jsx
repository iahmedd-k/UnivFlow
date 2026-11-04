'use client';

import React, { useState, useEffect } from 'react';
import {
  Download,
  Trash2,
  Pencil,
  Check,
  X,
  ExternalLink,
  Sparkles,
  Search,
  FileText,
  Image as ImageIcon,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  FolderOpen,
} from 'lucide-react';
import { api } from '@/app/lib/api';

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 KB';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

const PLATFORM_CONFIG = {
  chatgpt: { name: 'ChatGPT', badge: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  claude: { name: 'Claude', badge: 'bg-amber-50 text-amber-800 border-amber-200' },
  gemini: { name: 'Gemini', badge: 'bg-blue-50 text-blue-700 border-blue-200' },
  generic: { name: 'Web Chat', badge: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
};

export default function ExportedChatsLibrary({ onOpenImportModal }) {
  const [chats, setChats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [downloadingId, setDownloadingId] = useState(null);
  const [openingDriveId, setOpeningDriveId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [driveError, setDriveError] = useState('');

  const fetchChats = async () => {
    setLoading(true);
    try {
      const res = await api.getExportedChats();
      const list = res?.data?.items || res?.items || [];
      setChats(list);
    } catch (err) {
      console.error('Failed to load exported chats:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchChats();
  }, []);

  const handleStartEdit = (chat) => {
    setEditingId(chat.id);
    setEditTitle(chat.title);
  };

  const handleSaveEdit = async (chatId) => {
    if (!editTitle.trim()) return;
    try {
      await api.updateExportedChat(chatId, { title: editTitle.trim() });
      setChats((prev) =>
        prev.map((c) => (c.id === chatId ? { ...c, title: editTitle.trim() } : c))
      );
      setEditingId(null);
    } catch (err) {
      console.error('Failed to update title:', err);
    }
  };

  const handleDelete = async (chatId) => {
    if (!confirm('Are you sure you want to delete this exported PDF?')) return;
    setDeletingId(chatId);
    try {
      await api.deleteExportedChat(chatId);
      setChats((prev) => prev.filter((c) => c.id !== chatId));
    } catch (err) {
      console.error('Failed to delete exported chat:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const handleDownload = async (chat) => {
    setDownloadingId(chat.id);
    try {
      await api.downloadExportedChat(chat.id, `${chat.title || 'chat'}.pdf`);
    } catch (err) {
      console.error('Failed to download chat PDF:', err);
    } finally {
      setDownloadingId(null);
    }
  };

  const handleOpenInDrive = async (chat) => {
    setDriveError('');
    setOpeningDriveId(chat.id);
    try {
      const response = await api.openExportedChatInDrive(chat.id);
      const updatedChat = response?.data || response;
      const driveUrl = updatedChat?.google_drive_url || chat.google_drive_url;
      if (!driveUrl) throw new Error('Google Drive did not return a link for this PDF.');
      setChats((prev) => prev.map((item) => (item.id === chat.id ? { ...item, ...updatedChat } : item)));
      window.open(driveUrl, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setDriveError(err?.message || 'Could not open this PDF in Google Drive.');
    } finally {
      setOpeningDriveId(null);
    }
  };

  const filteredChats = chats.filter((c) => {
    if (!search.trim()) return true;
    const term = search.toLowerCase();
    return (
      (c.title || '').toLowerCase().includes(term) ||
      (c.source_platform || '').toLowerCase().includes(term)
    );
  });

  return (
    <div className="flex-1 flex flex-col h-full bg-white overflow-hidden">
      {/* Header Bar */}
      <div className="p-4 sm:p-6 border-b border-stone-200 bg-stone-50/50 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-stone-900 tracking-tight">Exported AI Chats</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
              {chats.length} {chats.length === 1 ? 'PDF' : 'PDFs'}
            </span>
          </div>
          <p className="text-[13px] text-stone-500 mt-1">
            Complete conversations from ChatGPT, Claude, and Gemini formatted for academic study
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={fetchChats}
            disabled={loading}
            title="Refresh library"
            className="p-2 rounded-xl border border-stone-200 text-stone-600 hover:text-stone-900 hover:bg-stone-100 transition-colors cursor-pointer disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>

          <button
            onClick={onOpenImportModal}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-[13px] font-medium shadow-xs transition-colors cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Export Web Chat</span>
          </button>
        </div>
      </div>

      {/* Search and Filter */}
      <div className="px-4 sm:px-6 py-3 border-b border-stone-100 flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-stone-400 absolute left-3 top-2.5" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search exported chats by title or platform..."
            className="w-full pl-9 pr-3 py-1.5 text-[13px] rounded-lg border border-stone-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 placeholder:text-stone-400"
          />
        </div>
      </div>

      {driveError && (
        <div role="alert" className="mx-4 sm:mx-6 mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700">
          {driveError}
        </div>
      )}

      {/* Content Grid */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {loading && chats.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-stone-400">
            <Loader2 className="w-8 h-8 animate-spin text-indigo-600 mb-2" />
            <p className="text-[13px]">Loading exported conversations...</p>
          </div>
        ) : filteredChats.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-72 text-center p-6 border-2 border-dashed border-stone-200 rounded-2xl max-w-lg mx-auto my-8">
            <div className="w-12 h-12 rounded-2xl bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center mb-3 shadow-2xs">
              <Sparkles className="w-6 h-6" />
            </div>
            <h3 className="text-[15px] font-semibold text-stone-900 mb-1">
              {search ? 'No matching chats found' : 'No Exported Chats Yet'}
            </h3>
            <p className="text-[13px] text-stone-500 max-w-sm mb-4">
              {search
                ? `No exports matched "${search}". Try searching for something else.`
                : 'Turn long, laggy ChatGPT, Claude, or Gemini chats into clean, printable A4 PDFs with 100% of messages and diagrams captured.'}
            </p>
            {!search && (
              <button
                onClick={onOpenImportModal}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-[13px] font-medium shadow-xs transition-colors cursor-pointer"
              >
                <Plus className="w-4 h-4" />
                <span>Import First Chat</span>
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredChats.map((chat) => {
              const platformConfig =
                PLATFORM_CONFIG[chat.source_platform?.toLowerCase()] || PLATFORM_CONFIG.generic;
              const isEditing = editingId === chat.id;

              return (
                <div
                  key={chat.id}
                  className="rounded-2xl border border-stone-200 bg-white hover:border-indigo-200 hover:shadow-md transition-all p-4.5 flex flex-col justify-between group"
                >
                  {/* Top: Platform & Actions */}
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2.5">
                      <span
                        className={`px-2 py-0.5 rounded-md text-[11px] font-semibold border ${platformConfig.badge}`}
                      >
                        {platformConfig.name}
                      </span>
                      <div className="flex items-center gap-1 opacity-70 group-hover:opacity-100 transition-opacity">
                        <a
                          href={chat.source_url}
                          target="_blank"
                          rel="noreferrer"
                          title="Open original conversation"
                          className="p-1 rounded-lg hover:bg-stone-100 text-stone-400 hover:text-stone-700 transition-colors"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                        <button
                          onClick={() => handleStartEdit(chat)}
                          title="Rename title"
                          className="p-1 rounded-lg hover:bg-stone-100 text-stone-400 hover:text-stone-700 transition-colors cursor-pointer"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(chat.id)}
                          disabled={deletingId === chat.id}
                          title="Delete PDF"
                          className="p-1 rounded-lg hover:bg-red-50 text-stone-400 hover:text-red-600 transition-colors cursor-pointer"
                        >
                          {deletingId === chat.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Title */}
                    {isEditing ? (
                      <div className="flex items-center gap-1.5 mb-2">
                        <input
                          type="text"
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="flex-1 text-[13px] px-2 py-1 rounded-lg border border-indigo-300 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveEdit(chat.id);
                            if (e.key === 'Escape') setEditingId(null);
                          }}
                        />
                        <button
                          onClick={() => handleSaveEdit(chat.id)}
                          className="p-1 text-emerald-600 hover:bg-emerald-50 rounded-md cursor-pointer"
                        >
                          <Check className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="p-1 text-stone-400 hover:bg-stone-100 rounded-md cursor-pointer"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <h4
                        className="text-[14px] font-semibold text-stone-900 leading-snug line-clamp-2 mb-2"
                        title={chat.title}
                      >
                        {chat.title}
                      </h4>
                    )}

                    {/* Metadata pills */}
                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-stone-500 mb-4">
                      <span className="font-medium text-stone-700">{chat.turn_count || 0} turns</span>
                      <span>•</span>
                      <span>{formatBytes(chat.file_size_bytes)}</span>
                      <span>•</span>
                      <span>{formatDate(chat.created_at)}</span>

                      {(chat.has_images || chat.has_diagrams) && (
                        <div className="flex items-center gap-1 ml-auto">
                          {chat.has_images && (
                            <ImageIcon className="w-3 h-3 text-blue-500" title="Includes images" />
                          )}
                          {chat.has_diagrams && (
                            <Layers className="w-3 h-3 text-purple-500" title="Includes diagrams" />
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => handleOpenInDrive(chat)}
                      disabled={openingDriveId === chat.id}
                      className="py-2 px-3 rounded-xl border border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-600 hover:text-white text-[12.5px] font-medium flex items-center justify-center gap-2 transition-colors cursor-pointer disabled:opacity-50"
                    >
                      {openingDriveId === chat.id ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Opening...</span></>
                      ) : (
                        <><FolderOpen className="w-3.5 h-3.5" /><span>Open in Drive</span></>
                      )}
                    </button>
                    <button
                      onClick={() => handleDownload(chat)}
                      disabled={downloadingId === chat.id}
                      className="py-2 px-3 rounded-xl bg-stone-100 hover:bg-stone-900 text-stone-700 hover:text-white text-[12.5px] font-medium flex items-center justify-center gap-2 transition-colors cursor-pointer disabled:opacity-50"
                    >
                      {downloadingId === chat.id ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /><span>Downloading...</span></>
                      ) : (
                        <><Download className="w-3.5 h-3.5" /><span>Download</span></>
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

