'use client';

import React, { useState, useRef, useCallback, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { UserButton } from "@clerk/nextjs";
import {
  Search,
  SlidersHorizontal,
  Plus,
  Pencil,
  MoreVertical,
  Paperclip,
  ArrowUp,
  ThumbsUp,
  ThumbsDown,
  RotateCw,
  Star,
  UploadCloud,
  FileText,
  FileSpreadsheet,
  FileJson,
  Link as LinkIcon,
  File,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Folder,
  X,
  ArrowRight,
  Database,
  Gauge,
  MessageSquare,
  AlertTriangle,
  Inbox,
  LogOut,
  Type,
  GitMerge,
  Sparkles,
  ShieldCheck,
  Quote,
  ChevronDown,
  ChevronRight,
  GraduationCap,
  Maximize2,
  Minimize2,
  ExternalLink,
  Info,
} from "lucide-react";

import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  getDocumentStatus,
  listConversations,
  createConversation,
  getConversation,
  updateConversationTitle,
  sendChat,
  getUsage,
  syncClassroom,
} from "@/app/lib/rag/services";

/* =====================================================================
   SHARED APP SHELL — Navigation & Plans
===================================================================== */

const NAV = [
  { id: "inbox", label: "Query Console", icon: Inbox },
  { id: "sources", label: "Knowledge Sources", icon: Database },
];

const PLANS = {
  free: {
    id: "free",
    name: "Unlimited",
    price: "$0",
    priceSub: "forever",
    queryLimit: Infinity,
    uploadLimit: Infinity,
    storageLimitBytes: 100 * 1024 * 1024 * 1024,
    seats: 1,
    features: ["Unlimited queries", "Unlimited indexed sources", "Unlimited storage", "1 seat"],
  },
  pro: {
    id: "pro",
    name: "Pro",
    price: "$0",
    priceSub: "included",
    queryLimit: Infinity,
    uploadLimit: Infinity,
    storageLimitBytes: 100 * 1024 * 1024 * 1024,
    seats: 10,
    features: [
      "Unlimited queries",
      "Unlimited indexed sources",
      "Unlimited storage",
      "Priority retrieval latency",
    ],
  },
};

const ICONS = {
  pdf: FileText,
  docx: FileText,
  csv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  xls: FileSpreadsheet,
  json: FileJson,
  url: LinkIcon,
  default: File,
};

function FileTypeIcon({ type, className = "w-3.5 h-3.5 text-stone-500" }) {
  const IconComponent = ICONS[type] || ICONS.default;
  return <IconComponent className={className} />;
}

const formatBytes = (b) => {
  if (!b || b <= 0) return "0 B";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
};

const STATUS_CONFIG = {
  completed: { label: "Indexed", icon: CheckCircle2, dot: "bg-emerald-500", text: "text-emerald-700" },
  indexed: { label: "Indexed", icon: CheckCircle2, dot: "bg-emerald-500", text: "text-emerald-700" },
  processing: { label: "Indexing", icon: Loader2, dot: "bg-amber-500", text: "text-amber-700", spin: true },
  uploaded: { label: "Indexing", icon: Loader2, dot: "bg-amber-500", text: "text-amber-700", spin: true },
  failed: { label: "Failed", icon: AlertCircle, dot: "bg-rose-500", text: "text-rose-700" },
  queued: { label: "Queued", icon: RotateCw, dot: "bg-stone-400", text: "text-stone-500" },
};

const CATEGORY_CONFIG = {
  slides: { label: "Lecture Slides", badge: "bg-amber-50 text-amber-700 border-amber-200" },
  labs: { label: "Lab Assignment", badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  coursework: { label: "Coursework", badge: "bg-blue-50 text-blue-700 border-blue-200" },
  syllabus: { label: "Syllabus", badge: "bg-purple-50 text-purple-700 border-purple-200" },
  handouts: { label: "Handout / Notes", badge: "bg-stone-100 text-stone-700 border-stone-200" },
  announcements: { label: "Announcement", badge: "bg-indigo-50 text-indigo-700 border-indigo-200" },
  user_upload: { label: "Uploaded File", badge: "bg-slate-100 text-slate-700 border-slate-200" },
};

function mapDocumentToFrontend(doc) {
  const ext = (doc.original_filename || "").split(".").pop().toLowerCase();
  let displayName = doc.clean_title || doc.original_filename || "Document";
  let courseName = doc.course_name;
  if (!courseName) {
    if (displayName.startsWith("[") && displayName.includes("]")) {
      courseName = displayName.slice(1, displayName.indexOf("]")).trim();
      displayName = displayName.slice(displayName.indexOf("]") + 1).trim();
    } else {
      courseName = "My Uploads";
    }
  } else if (displayName.startsWith("[") && displayName.includes("]")) {
    displayName = displayName.slice(displayName.indexOf("]") + 1).trim();
  }

  return {
    id: doc.id,
    name: displayName,
    fullName: doc.original_filename,
    course_id: doc.course_id || null,
    course_name: courseName,
    category: doc.category || "handouts",
    description: "",
    type: ext,
    size: doc.file_size,
    chunks: doc.chunk_count ?? null,
    collectionId: courseName,
    status: doc.status === "completed" ? "indexed" : doc.status,
    updated: formatRelativeTime(doc.updated_at || doc.created_at),
    created_at: doc.created_at,
    storage_url: doc.storage_url || null,
  };
}

function parseUtcDate(dateStr) {
  if (!dateStr) return null;
  const str = typeof dateStr === "string" && !dateStr.endsWith("Z") && !dateStr.includes("+") && !dateStr.slice(10).includes("-")
    ? `${dateStr}Z`
    : dateStr;
  const d = new Date(str);
  return isNaN(d.getTime()) ? new Date(dateStr) : d;
}

function formatRelativeTime(dateStr) {
  if (!dateStr) return "";
  const d = parseUtcDate(dateStr);
  if (!d || isNaN(d.getTime())) return "";
  const diff = Math.max(0, Date.now() - d.getTime());
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatConversationDate(dateStr) {
  if (!dateStr) return null;
  const d = parseUtcDate(dateStr);
  if (!d || isNaN(d.getTime())) return null;
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function PlanBadge({ plan, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 text-[12px] font-medium px-3 py-1.5 rounded-lg border border-indigo-200 bg-indigo-50/70 text-indigo-700 hover:bg-indigo-100 transition-colors shrink-0 cursor-pointer"
    >
      <Sparkles className="w-3.5 h-3.5 text-indigo-500" />
      <span>Unlimited Tier</span>
    </button>
  );
}

function UpgradeLockBar({ icon: Icon = MessageSquare, title, subtitle }) {
  return (
    <div className="flex items-center justify-between gap-3 bg-amber-50/90 border border-amber-200 rounded-xl px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
          <Icon className="w-4 h-4 text-amber-600" />
        </div>
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-amber-900 truncate">{title}</p>
          {subtitle && <p className="text-[12px] text-amber-700/80 truncate">{subtitle}</p>}
        </div>
      </div>
      <div className="shrink-0 text-[11.5px] font-medium bg-amber-100 text-amber-800 border border-amber-300 rounded-lg px-3 py-1.5 whitespace-nowrap">
        Demo Limit Reached
      </div>
    </div>
  );
}

function useMountedFade() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(raf);
  }, []);
  return mounted;
}

/* =====================================================================
   GLOBAL DOC SEARCH
===================================================================== */

function DocSearch({ files, onSelect }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [highlight, setHighlight] = useState(0);
  const wrapRef = useRef(null);
  const inputRef = useRef(null);

  const results = q.trim()
    ? files
        .filter(
          (f) =>
            f.name.toLowerCase().includes(q.trim().toLowerCase()) ||
            (f.description || "").toLowerCase().includes(q.trim().toLowerCase())
        )
        .slice(0, 6)
    : [];

  useEffect(() => {
    const onKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const onClickOutside = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const pick = (file) => {
    if (!file) return;
    onSelect(file);
    setQ("");
    setOpen(false);
  };

  const onKeyDown = (e) => {
    if (e.key === "Escape") return setOpen(false);
    if (!results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(results[highlight]);
    }
  };

  return (
    <div ref={wrapRef} className="relative w-full max-w-md">
      <div className="flex items-center gap-2 bg-stone-100 rounded-lg px-3 py-1.5 border border-transparent focus-within:bg-white focus-within:border-stone-200 focus-within:ring-2 focus-within:ring-indigo-400/30 transition-colors">
        <Search className="w-3.5 h-3.5 text-stone-400 shrink-0" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setHighlight(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search documents, then ask about one…"
          className="bg-transparent text-[13px] outline-none w-full placeholder:text-stone-400"
        />
        <kbd className="hidden sm:inline-flex shrink-0 items-center text-[10px] font-medium text-stone-400 bg-white border border-stone-200 rounded px-1.5 py-0.5">
          ⌘K
        </kbd>
      </div>

      {open && q.trim() && (
        <div className="absolute top-full left-0 right-0 mt-1.5 bg-white border border-stone-200 rounded-xl shadow-lg overflow-hidden z-30">
          {results.length === 0 ? (
            <div className="px-3 py-4 text-[12.5px] text-stone-400 text-center">No documents match "{q}"</div>
          ) : (
            results.map((f, i) => (
              <button
                key={f.id}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => pick(f)}
                className={`w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors cursor-pointer ${
                  i === highlight ? "bg-indigo-50" : "hover:bg-stone-50"
                }`}
              >
                <div className="w-6 h-6 rounded-md bg-stone-100 flex items-center justify-center shrink-0">
                  <FileTypeIcon type={f.type} className="w-3.5 h-3.5 text-stone-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] font-medium text-stone-800 truncate">{f.name}</p>
                  <p className="text-[11.5px] text-stone-400 truncate">
                    {f.description || f.collectionId || "Document"}
                  </p>
                </div>
                <span className={`text-[10.5px] font-medium shrink-0 ${i === highlight ? "text-indigo-600" : "text-stone-300"}`}>
                  Ask about this →
                </span>
              </button>
            ))
          )}
          <div className="px-3 py-2 border-t border-stone-100 text-[11px] text-stone-400 bg-stone-50">
            Opens a new conversation scoped to just this document
          </div>
        </div>
      )}
    </div>
  );
}

/* =====================================================================
   TOP BAR
===================================================================== */

function TopBar({ route, onRouteChange, plan, onOpenUsage, onLogout, files, onTagDoc }) {
  const btnRefs = useRef({});
  const [indicator, setIndicator] = useState(null);

  useEffect(() => {
    const el = btnRefs.current[route];
    if (el) setIndicator({ left: el.offsetLeft, width: el.offsetWidth });
  }, [route]);

  return (
    <div className="h-13 shrink-0 border-b border-stone-200 flex items-center justify-between gap-2 sm:gap-4 px-3 sm:px-4 bg-white/95 backdrop-blur-sm sticky top-0 z-20">
      <div className="flex items-center gap-2 sm:gap-3 shrink-0">
        <div className="flex items-center gap-1">
          <div className="w-6 h-6 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-xs">R</div>
          <span className="text-sm font-semibold text-stone-900 hidden sm:inline">RAG Assistant</span>
        </div>
        <div className="hidden sm:block h-4 w-px bg-stone-200" />

        <div className="relative flex items-center gap-1 shrink-0">
          {indicator && (
            <div
              className="absolute top-0 bottom-0 bg-stone-100 rounded-lg border border-stone-200 transition-all duration-200 ease-out pointer-events-none"
              style={{ left: indicator.left, width: indicator.width }}
            />
          )}
          {NAV.map((item) => {
            const Icon = item.icon;
            const active = route === item.id;
            return (
              <button
                key={item.id}
                ref={(el) => (btnRefs.current[item.id] = el)}
                onClick={() => onRouteChange(item.id)}
                className={`relative z-10 flex items-center gap-1.5 text-[12px] sm:text-[12.5px] font-medium px-2.5 sm:px-3 py-1.5 rounded-lg transition-colors cursor-pointer ${
                  active ? "text-stone-900" : "text-stone-500 hover:text-stone-700"
                }`}
              >
                <Icon className="w-3.5 h-3.5 shrink-0" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="hidden md:flex flex-1 justify-center min-w-0 max-w-sm">
        <DocSearch files={files} onSelect={onTagDoc} />
      </div>

      <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
        <PlanBadge plan={plan} onClick={onOpenUsage} />
        <div className="flex items-center gap-1.5 sm:gap-2 pl-1 border-l border-stone-200">
          <UserButton
            afterSignOutUrl="/sign-in"
            appearance={{
              elements: {
                avatarBox: "w-7 h-7",
              },
            }}
          />
          <button
            onClick={onLogout}
            title="Sign out"
            className="flex items-center gap-1 text-[12px] sm:text-[12.5px] font-medium p-1.5 sm:px-2.5 sm:py-1.5 rounded-lg text-stone-500 hover:text-stone-700 hover:bg-stone-100 transition-colors cursor-pointer"
          >
            <LogOut className="w-3.5 h-3.5 shrink-0" />
            <span className="hidden sm:inline">Sign out</span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* =====================================================================
   RAG CHAT CONSOLE
===================================================================== */

const STATUS = {
  amber: { dot: "bg-amber-400" },
  rose: { dot: "bg-rose-400" },
  emerald: { dot: "bg-emerald-400" },
  sky: { dot: "bg-sky-400" },
};

const PIPELINE_STAGES = [
  { id: "query", label: "Query analysis", icon: Search },
  { id: "vector", label: "Vector search", icon: Type },
  { id: "lexical", label: "Lexical search", icon: Type },
  { id: "fusion", label: "RRF fusion", icon: GitMerge },
  { id: "rerank", label: "Reranking", icon: Sparkles },
  { id: "grade", label: "Grading evidence", icon: ShieldCheck },
];

const CONFIDENCE_CONFIG = {
  grounded: { label: "Grounded", icon: ShieldCheck, className: "text-emerald-700 bg-emerald-50" },
  partial: { label: "Partially grounded", icon: AlertTriangle, className: "text-amber-700 bg-amber-50" },
  unsupported: { label: "Low confidence", icon: AlertCircle, className: "text-rose-700 bg-rose-50" },
};

function getConfidenceLevel(score) {
  if (score == null) return "unsupported";
  if (score >= 0.75) return "grounded";
  if (score >= 0.45) return "partial";
  return "unsupported";
}

function ConfidenceBadge({ confidence }) {
  const cfg = CONFIDENCE_CONFIG[confidence] || CONFIDENCE_CONFIG.grounded;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11.5px] font-medium px-2 py-1 rounded-full shrink-0 ${cfg.className}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

function AnswerText({ text, onCiteClick, activeCite }) {
  if (!text) return null;

  let processedText = text.replace(/\|\s*\|/g, "|\n|");
  processedText = processedText.replace(/\[(\d+)\]/g, "[$1](#cite-$1)");

  return (
    <div className="markdown-body text-[14px] text-stone-700 leading-relaxed overflow-x-auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto my-3 rounded-xl border border-stone-200/90 shadow-2xs">
              <table className="min-w-full divide-y divide-stone-200 text-[13px] bg-white" {...props} />
            </div>
          ),
          thead: ({ node, ...props }) => (
            <thead className="bg-stone-50/90 text-stone-700" {...props} />
          ),
          th: ({ node, ...props }) => (
            <th className="px-3.5 py-2.5 text-left text-[12px] font-semibold text-stone-800 uppercase tracking-wider border-b border-stone-200" {...props} />
          ),
          td: ({ node, ...props }) => (
            <td className="px-3.5 py-2 text-stone-600 border-b border-stone-100 align-top leading-normal" {...props} />
          ),
          ul: ({ node, ...props }) => (
            <ul className="list-disc pl-5 my-2 space-y-1 text-stone-700" {...props} />
          ),
          ol: ({ node, ...props }) => (
            <ol className="list-decimal pl-5 my-2 space-y-1 text-stone-700" {...props} />
          ),
          li: ({ node, ...props }) => (
            <li className="leading-relaxed pl-1" {...props} />
          ),
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) {
              const n = href.replace("#cite-", "");
              return (
                <button
                  type="button"
                  onClick={() => onCiteClick(n)}
                  className={`inline-flex items-center justify-center align-super text-[10px] font-semibold min-w-4 h-4 px-1 rounded mx-0.5 -translate-y-0.5 transition-colors cursor-pointer ${
                    activeCite === n
                      ? "bg-indigo-600 text-white shadow-xs"
                      : "bg-indigo-50 text-indigo-600 hover:bg-indigo-100"
                  }`}
                >
                  {children}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:text-indigo-700 underline font-medium">
                {children}
              </a>
            );
          },
        }}
      >
        {processedText}
      </ReactMarkdown>
    </div>
  );
}

function SourceCard({ source, active, onSelect }) {
  const ext = (source.file || "").split(".").pop().toLowerCase();
  const isMeaningfulScore = source.score != null && source.score > 0.05 && source.score < 0.999;

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left flex items-start gap-2.5 px-3 py-2.5 rounded-lg border transition-all cursor-pointer ${
        active
          ? "border-indigo-300 bg-indigo-50/70 ring-1 ring-indigo-200"
          : "border-stone-100 bg-white hover:bg-stone-50/80 hover:border-stone-200"
      }`}
    >
      <span
        className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 mt-0.5 text-[10px] font-semibold ${
          active ? "bg-indigo-600 text-white" : "bg-stone-100 text-stone-500"
        }`}
      >
        {source.n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <FileTypeIcon type={ext} className="w-3 h-3 text-stone-400 shrink-0" />
          <span className="text-[12.5px] font-medium text-stone-800 truncate">{source.file}</span>
          <span className="text-[11px] text-stone-400 shrink-0">· {source.loc}</span>
        </div>
        <p className="text-[12px] text-stone-500 mt-1 leading-snug line-clamp-2">
          <Quote className="w-2.5 h-2.5 inline mr-1 text-stone-300" />
          {source.snippet}
        </p>
        {isMeaningfulScore && (
          <div className="flex items-center gap-1.5 mt-1.5">
            <div className="flex-1 h-1 bg-stone-100 rounded-full overflow-hidden max-w-[80px]">
              <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${Math.round(source.score * 100)}%` }} />
            </div>
            <span className="text-[10.5px] text-stone-400 tabular-nums">{Math.round(source.score * 100)}% match</span>
          </div>
        )}
      </div>
    </button>
  );
}

function UserTurn({ text }) {
  return (
    <div className="py-3">
      <p className="text-[15px] font-medium text-stone-900 leading-snug">{text}</p>
    </div>
  );
}

function AssistantTurn({ turn, documents, onRegenerate, isLast, regenerateLocked }) {
  const [activeCite, setActiveCite] = useState(null);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const sources = (turn.sources || []).map((s, i) => {
    const doc = documents.find((d) => d.id === s.document_id);
    return {
      n: i + 1,
      file: doc ? doc.name : `Document #${s.document_id}`,
      loc: `p. ${s.page_number}`,
      snippet: s.content,
      score: s.score,
      document_id: s.document_id,
    };
  });

  const confidenceLevel = getConfidenceLevel(turn.confidence);

  return (
    <div className="py-4">
      {turn.abstained ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 mb-3">
          <div className="flex items-center gap-2 text-[13px] font-medium text-amber-800 mb-1">
            <AlertTriangle className="w-4 h-4" />
            Unable to answer
          </div>
          <p className="text-[12.5px] text-amber-700">
            {turn.abstention_reason || "The available documents don't contain enough information to answer this question."}
          </p>
          {turn.abstention_suggestion && (
            <p className="text-[12px] text-amber-600 mt-1">Suggestion: {turn.abstention_suggestion}</p>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between mb-2">
            <ConfidenceBadge confidence={confidenceLevel} />
          </div>
          <AnswerText
            text={turn.answer}
            onCiteClick={(n) => {
              setActiveCite(n);
              setSourcesOpen(true);
            }}
            activeCite={activeCite}
          />

          {sources.length > 0 && (
            <div className="mt-3">
              <button
                type="button"
                onClick={() => setSourcesOpen((prev) => !prev)}
                className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-stone-500 hover:text-stone-800 bg-stone-50 hover:bg-stone-100/90 border border-stone-200/80 rounded-md px-2.5 py-1 transition-all cursor-pointer select-none"
              >
                <FileText className="w-3.5 h-3.5 text-stone-400" />
                <span>{sources.length} {sources.length === 1 ? "source" : "sources"}</span>
                <ChevronDown className={`w-3 h-3 text-stone-400 transition-transform duration-200 ${sourcesOpen ? "rotate-180" : ""}`} />
              </button>

              {sourcesOpen && (
                <div className="mt-2.5 grid grid-cols-1 sm:grid-cols-2 gap-2 animate-in fade-in duration-200">
                  {sources.map((s) => (
                    <SourceCard
                      key={s.n}
                      source={s}
                      active={activeCite === String(s.n)}
                      onSelect={() => setActiveCite(String(s.n))}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={() => setFeedback(feedback === "up" ? null : "up")}
          className={`w-7 h-7 rounded-full flex items-center justify-center transition-colors cursor-pointer ${
            feedback === "up" ? "bg-emerald-50 text-emerald-600" : "hover:bg-stone-100 text-stone-400"
          }`}
          title="Helpful"
        >
          <ThumbsUp className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => setFeedback(feedback === "down" ? null : "down")}
          className={`w-7 h-7 rounded-full flex items-center justify-center transition-colors cursor-pointer ${
            feedback === "down" ? "bg-rose-50 text-rose-600" : "hover:bg-stone-100 text-stone-400"
          }`}
          title="Not helpful"
        >
          <ThumbsDown className="w-3.5 h-3.5" />
        </button>
        {isLast && !regenerateLocked && (
          <button
            onClick={onRegenerate}
            className="flex items-center gap-1.5 text-[12px] text-stone-400 hover:text-stone-600 ml-1 cursor-pointer"
          >
            <RotateCw className="w-3.5 h-3.5" />
            Regenerate
          </button>
        )}
      </div>
    </div>
  );
}

function PipelineRunning({ stageIndex }) {
  return (
    <div className="py-4">
      <div className="flex flex-wrap items-center gap-1">
        {PIPELINE_STAGES.map((s, i) => {
          const Icon = s.icon;
          const done = i < stageIndex;
          const active = i === stageIndex;
          return (
            <span key={s.id} className="flex items-center">
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-medium rounded-full px-2 py-1 border transition-colors ${
                  done
                    ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                    : active
                    ? "bg-indigo-50 border-indigo-200 text-indigo-700"
                    : "bg-white border-stone-200 text-stone-400"
                }`}
              >
                {active ? <Loader2 className="w-3 h-3 animate-spin" /> : done ? <CheckCircle2 className="w-3 h-3" /> : <Icon className="w-3 h-3" />}
                {s.label}
              </span>
              {i < PIPELINE_STAGES.length - 1 && <ArrowRight className="w-3 h-3 text-stone-300 mx-1" />}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function ChatRow({ chat, isActive, onClick }) {
  const dateStr = formatConversationDate(chat.updated_at || chat.created_at);
  const toneKey = chat.abstained
    ? "sky"
    : chat.confidence != null
    ? chat.confidence >= 0.75
      ? "emerald"
      : chat.confidence >= 0.45
      ? "amber"
      : "rose"
    : "sky";
  const tone = STATUS[toneKey] || STATUS.sky;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 border-b border-stone-100 transition-colors cursor-pointer ${
        isActive ? "bg-indigo-50/70" : "hover:bg-stone-50"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-[13.5px] font-medium text-stone-800 leading-snug line-clamp-2 flex items-center gap-1.5">
          {chat.document_ids && chat.document_ids.length > 0 && <FileText className="w-3 h-3 text-indigo-400 shrink-0" />}
          <span className="line-clamp-2">{chat.title}</span>
        </p>
        {isActive && (
          <div className="flex items-center gap-2 shrink-0 pt-0.5 text-stone-400">
            <Star className="w-3.5 h-3.5" />
            <MoreVertical className="w-3.5 h-3.5" />
          </div>
        )}
      </div>
      <div className="flex items-center gap-1.5 mt-1.5">
        <span className={`w-2 h-2 rounded-full ${tone.dot}`} />
        <span className="text-[12px] text-stone-500">
          {chat.document_ids && chat.document_ids.length > 0
            ? `${chat.document_ids.length} source${chat.document_ids.length === 1 ? "" : "s"}`
            : "All sources"}
        </span>
        {dateStr && <span className="text-[12px] text-stone-400 ml-auto">{dateStr}</span>}
      </div>
    </button>
  );
}

function DocumentPicker({ files, selectedIds, onToggle, onClear, onConfirm, onUpload, onUploadComplete, pickerRef }) {
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await onUpload(file);
      onUploadComplete?.();
    } catch {
      // Handled in parent
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div ref={pickerRef} className="absolute bottom-full left-0 mb-2 w-80 bg-white border border-stone-200 rounded-xl shadow-xl overflow-hidden z-50">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-stone-100">
        <span className="text-[13px] font-semibold text-stone-800">Select documents</span>
        <div className="flex items-center gap-1">
          <button onClick={onClear} className="text-[11.5px] text-stone-400 hover:text-stone-600 px-1.5 py-0.5 rounded hover:bg-stone-50 cursor-pointer">
            Clear
          </button>
          <button onClick={() => onConfirm()} className="text-[11.5px] text-indigo-600 hover:text-indigo-700 font-medium px-1.5 py-0.5 rounded hover:bg-indigo-50 cursor-pointer">
            Done
          </button>
        </div>
      </div>
      <div className="max-h-56 overflow-y-auto">
        {files.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <FileText className="w-8 h-8 text-stone-300 mx-auto mb-2" />
            <p className="text-[12.5px] text-stone-500 mb-3">No documents uploaded yet.</p>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-indigo-600 hover:text-indigo-700 disabled:opacity-50 cursor-pointer"
            >
              {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UploadCloud className="w-3.5 h-3.5" />}
              {uploading ? "Uploading…" : "Upload a document"}
            </button>
            <input ref={fileInputRef} type="file" accept=".pdf,.csv,.xlsx,.xls,.docx,.json" className="hidden" onChange={handleUpload} />
          </div>
        ) : (
          files.map((f) => {
            const selected = selectedIds.includes(f.id);
            return (
              <button
                key={f.id}
                onClick={() => onToggle(f.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors cursor-pointer ${
                  selected ? "bg-indigo-50/70" : "hover:bg-stone-50"
                }`}
              >
                <span
                  className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                    selected ? "bg-indigo-600 border-indigo-600" : "border-stone-300"
                  }`}
                >
                  {selected && <CheckCircle2 className="w-3 h-3 text-white" />}
                </span>
                <FileTypeIcon type={f.type} className="w-3.5 h-3.5 text-stone-400 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] text-stone-700 truncate">{f.name}</div>
                  <div className="text-[10.5px] text-stone-400 truncate">
                    {f.course_name || "General"} · {CATEGORY_CONFIG[f.category]?.label || "Document"}
                  </div>
                </div>
                <span className="text-[11px] text-stone-400 shrink-0">{f.status === "completed" ? "Indexed" : f.status}</span>
              </button>
            );
          })
        )}
      </div>
      {files.length > 0 && (
        <div className="px-3 py-2 border-t border-stone-100 flex items-center justify-between bg-stone-50/50">
          <span className="text-[11.5px] text-stone-400">
            {selectedIds.length} of {files.length} selected
          </span>
          <div className="flex items-center gap-2">
            <input ref={fileInputRef} type="file" accept=".pdf,.csv,.xlsx,.xls,.docx,.json" className="hidden" onChange={handleUpload} />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="text-[11.5px] text-stone-600 hover:text-stone-800 flex items-center gap-1 disabled:opacity-50 cursor-pointer font-medium"
            >
              {uploading ? <Loader2 className="w-3 h-3 animate-spin" /> : <UploadCloud className="w-3 h-3" />}
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function ChatInboxDashboard({
  plan,
  onUpgrade,
  pendingDocTag,
  onConsumePendingDocTag,
  files,
  usageData,
  refreshFiles,
  refreshUsage,
  onOpenSources,
}) {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [turnsById, setTurnsById] = useState({});
  const [input, setInput] = useState("");
  const [pipeline, setPipeline] = useState(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [loadingConversations, setLoadingConversations] = useState(true);
  const [search, setSearch] = useState("");
  const [scopedDocIds, setScopedDocIds] = useState([]);
  const [showDocPicker, setShowDocPicker] = useState(false);
  const [inlineUploading, setInlineUploading] = useState(false);
  const [mobileShowSidebar, setMobileShowSidebar] = useState(false);
  const scrollRef = useRef(null);
  const docPickerRef = useRef(null);
  const inlineFileInputRef = useRef(null);
  const mounted = useMountedFade();

  const activeChat = conversations.find((c) => c.id === activeId);
  const turns = turnsById[activeId] || [];
  const filtered = conversations.filter((c) => (c.title || "").toLowerCase().includes(search.toLowerCase()));

  useEffect(() => {
    let isSubscribed = true;
    const safetyTimer = setTimeout(() => {
      if (isSubscribed) setLoadingConversations(false);
    }, 3000);

    listConversations(0, 50)
      .then((res) => {
        if (!isSubscribed) return;
        const convs = res.conversations || [];
        setConversations(convs);
        if (convs.length > 0) {
          setActiveId((prev) => prev || convs[0].id);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (isSubscribed) setLoadingConversations(false);
        clearTimeout(safetyTimer);
      });

    return () => {
      isSubscribed = false;
      clearTimeout(safetyTimer);
    };
  }, []);

  useEffect(() => {
    if (!activeId) return;
    if (turnsById[activeId]) return;
    getConversation(activeId)
      .then((detail) => {
        const mapped = (detail.messages || []).flatMap((msg) => {
          if (msg.role === "user") return [{ role: "user", text: msg.content }];
          return [
            {
              role: "assistant",
              answer: msg.content,
              confidence: msg.confidence,
              abstained: msg.abstained,
              abstention_reason: msg.abstention_reason,
              sources: [],
              attempts: [{ query: "", sufficient: !msg.abstained }],
            },
          ];
        });
        setTurnsById((prev) => ({ ...prev, [activeId]: mapped }));
      })
      .catch(() => {});
  }, [activeId, turnsById]);

  useEffect(() => {
    if (!showDocPicker) return;
    const handleClick = (e) => {
      if (docPickerRef.current && !docPickerRef.current.contains(e.target)) {
        setShowDocPicker(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [showDocPicker]);

  const openChat = (id) => {
    setActiveId(id);
    setEditingTitle(false);
    setSearch("");
  };

  const addChat = async () => {
    try {
      const conv = await createConversation("New conversation");
      setConversations((prev) => [conv, ...prev]);
      setTurnsById((prev) => ({ ...prev, [conv.id]: [] }));
      openChat(conv.id);
    } catch {
      const localId = Date.now();
      const localConv = {
        id: localId,
        title: "New conversation",
        document_ids: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setConversations((prev) => [localConv, ...prev]);
      setTurnsById((prev) => ({ ...prev, [localId]: [] }));
      openChat(localId);
    }
  };

  const handleInlineUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setInlineUploading(true);
    try {
      await uploadDocument(file);
      await refreshFiles?.();
    } catch {
      // Handled in parent
    } finally {
      setInlineUploading(false);
      if (inlineFileInputRef.current) inlineFileInputRef.current.value = "";
    }
  };

  useEffect(() => {
    if (!pendingDocTag) return;
    let cancelled = false;
    (async () => {
      try {
        const title = `About ${pendingDocTag.name}`;
        const docIds = pendingDocTag.isCourse ? pendingDocTag.ids : [pendingDocTag.id];
        const conv = await createConversation(title, docIds);
        if (cancelled) return;
        setConversations((prev) => [conv, ...prev]);
        setTurnsById((prev) => ({ ...prev, [conv.id]: [] }));
        openChat(conv.id);
        if (docIds && docIds.length > 0) {
          setScopedDocIds(docIds);
        }
        onConsumePendingDocTag?.();
      } catch {
        // Handled silently
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pendingDocTag]);

  const startEditTitle = () => {
    setTitleDraft(activeChat?.title || "");
    setEditingTitle(true);
  };

  const commitTitle = async () => {
    setEditingTitle(false);
    const next = titleDraft.trim();
    if (!next || !activeId) return;
    try {
      await updateConversationTitle(activeId, next);
      setConversations((prev) => prev.map((c) => (c.id === activeId ? { ...c, title: next } : c)));
    } catch {
      // Handled silently
    }
  };

  const currentPlanCfg = PLANS[plan] || PLANS.free;
  const queryLimit = currentPlanCfg.queryLimit ?? Infinity;
  const queriesUsed =
    usageData?.queries_this_month ??
    Object.values(turnsById).reduce((sum, arr) => sum + arr.filter((t) => t.role === "user").length, 0);
  const queryLimitReached = false;

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, pipeline]);

  const submitQuery = async (queryText) => {
    const text = (queryText || input).trim();
    if (!text || pipeline || queryLimitReached) return;

    if (files.length === 0) {
      if (onOpenSources) onOpenSources();
      return;
    }

    setInput("");

    let targetChatId = activeId;
    if (!targetChatId) {
      try {
        const titleSnippet = text.length > 30 ? `${text.slice(0, 30)}…` : text;
        const newConv = await createConversation(titleSnippet);
        setConversations((prev) => [newConv, ...prev]);
        setTurnsById((prev) => ({ ...prev, [newConv.id]: [] }));
        targetChatId = newConv.id;
        setActiveId(targetChatId);
      } catch {
        const fallbackId = Date.now();
        const fallbackConv = {
          id: fallbackId,
          title: text.length > 30 ? `${text.slice(0, 30)}…` : text,
          document_ids: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        setConversations((prev) => [fallbackConv, ...prev]);
        setTurnsById((prev) => ({ ...prev, [fallbackId]: [] }));
        targetChatId = fallbackId;
        setActiveId(targetChatId);
      }
    }

    const userTurn = { role: "user", text };
    setTurnsById((prev) => ({ ...prev, [targetChatId]: [...(prev[targetChatId] || []), userTurn] }));

    let stage = 0;
    setPipeline({ stageIndex: 0 });
    const stageTimer = setInterval(() => {
      stage += 1;
      if (stage < PIPELINE_STAGES.length) {
        setPipeline({ stageIndex: stage });
      }
    }, 300);

    try {
      const docIds = scopedDocIds.length > 0 ? scopedDocIds : null;
      const result = await sendChat({
        query: text,
        conversation_id: targetChatId,
        document_ids: docIds,
      });

      clearInterval(stageTimer);
      setPipeline(null);

      const assistantTurn = {
        role: "assistant",
        answer: result.answer,
        sources: result.sources || [],
        confidence: result.confidence,
        abstained: result.abstained,
        abstention_reason: result.abstention_reason,
        abstention_suggestion: result.abstention_suggestion,
        query: text,
        attempts: [{ query: text, sufficient: !result.abstained }],
      };

      setTurnsById((prev) => ({ ...prev, [targetChatId]: [...(prev[targetChatId] || []), assistantTurn] }));
      setConversations((prev) =>
        prev.map((c) => (c.id === targetChatId ? { ...c, updated_at: new Date().toISOString() } : c))
      );
      if (refreshUsage) refreshUsage();
    } catch (err) {
      clearInterval(stageTimer);
      setPipeline(null);
      const errorTurn = {
        role: "assistant",
        answer: "Sorry, something went wrong while processing your question. Please try again.",
        sources: [],
        confidence: 0,
        abstained: true,
        abstention_reason: err?.message || "Request failed",
        query: text,
        attempts: [{ query: text, sufficient: false, reason: "Request failed" }],
      };
      setTurnsById((prev) => ({ ...prev, [targetChatId]: [...(prev[targetChatId] || []), errorTurn] }));
    }
  };

  const regenerate = async () => {
    if (pipeline || queryLimitReached || !activeId) return;
    const lastUser = [...turns].reverse().find((t) => t.role === "user");
    if (!lastUser) return;

    setTurnsById((prev) => ({ ...prev, [activeId]: prev[activeId].slice(0, -1) }));

    let stage = 0;
    setPipeline({ stageIndex: 0 });
    const stageTimer = setInterval(() => {
      stage += 1;
      if (stage < PIPELINE_STAGES.length) {
        setPipeline({ stageIndex: stage });
      }
    }, 300);

    try {
      const docIds = scopedDocIds.length > 0 ? scopedDocIds : null;
      const result = await sendChat({
        query: lastUser.text,
        conversation_id: activeId,
        document_ids: docIds,
      });

      clearInterval(stageTimer);
      setPipeline(null);

      const assistantTurn = {
        role: "assistant",
        answer: result.answer,
        sources: result.sources || [],
        confidence: result.confidence,
        abstained: result.abstained,
        abstention_reason: result.abstention_reason,
        abstention_suggestion: result.abstention_suggestion,
        query: lastUser.text,
        attempts: [{ query: lastUser.text, sufficient: !result.abstained }],
      };

      setTurnsById((prev) => ({ ...prev, [activeId]: [...prev[activeId], assistantTurn] }));
      if (refreshUsage) refreshUsage();
    } catch {
      clearInterval(stageTimer);
      setPipeline(null);
    }
  };

  return (
    <div className={`h-full w-full flex bg-white text-stone-900 transition-opacity duration-200 relative overflow-hidden ${mounted ? "opacity-100" : "opacity-0"}`}>
      {mobileShowSidebar && (
        <div
          onClick={() => setMobileShowSidebar(false)}
          className="fixed inset-0 bg-stone-900/40 backdrop-blur-xs z-30 md:hidden"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 w-[85vw] max-w-[300px] bg-stone-50 border-r border-stone-200 flex flex-col transition-transform duration-200 ease-out md:static md:w-[300px] md:translate-x-0 ${
          mobileShowSidebar ? "translate-x-0 shadow-2xl" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="flex items-center justify-between px-4 pt-4 pb-3">
          <h2 className="text-[15px] font-semibold tracking-tight">Conversations</h2>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => {
                addChat();
                setMobileShowSidebar(false);
              }}
              title="New chat"
              className="w-8 h-8 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white flex items-center justify-center transition-colors cursor-pointer shadow-xs"
            >
              <Plus className="w-4 h-4" />
            </button>
            <button
              onClick={() => setMobileShowSidebar(false)}
              className="md:hidden w-8 h-8 rounded-full hover:bg-stone-200/70 flex items-center justify-center text-stone-500 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="px-4 pb-3">
          <div className="flex items-center gap-2 bg-stone-200/60 rounded-lg px-3 py-2">
            <Search className="w-4 h-4 text-stone-400 shrink-0" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Find a query"
              className="bg-transparent text-[13px] outline-none w-full placeholder:text-stone-400"
            />
            <SlidersHorizontal className="w-4 h-4 text-stone-400 shrink-0" />
          </div>
        </div>

        <div className="px-4 pb-2 text-[12px] font-medium text-stone-400">History</div>

        <div className="flex-1 overflow-y-auto">
          {loadingConversations ? (
            <div className="px-4 py-8 text-center text-[12.5px] text-stone-400">
              <Loader2 className="w-4 h-4 animate-spin mx-auto mb-2 text-indigo-500" />
              Loading conversations…
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-[12.5px] text-stone-400">
              {files.length === 0 ? "No documents uploaded yet" : "No conversations yet"}
            </div>
          ) : (
            filtered.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                isActive={chat.id === activeId}
                onClick={() => {
                  openChat(chat.id);
                  setMobileShowSidebar(false);
                }}
              />
            ))
          )}
        </div>

        {plan === "free" && queryLimit !== Infinity && (
          <div className="px-4 py-3 border-t border-stone-200 bg-white">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] font-medium text-stone-400 uppercase tracking-wide">Monthly queries</span>
              <span className="text-[11px] text-stone-400 tabular-nums">
                {Math.min(queriesUsed, queryLimit)}/{queryLimit}
              </span>
            </div>
            <div className="w-full h-1.5 bg-stone-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${queryLimitReached ? "bg-rose-400" : "bg-indigo-500"}`}
                style={{ width: `${Math.min(100, (queriesUsed / queryLimit) * 100)}%` }}
              />
            </div>
          </div>
        )}
      </aside>

      <main className="flex-1 flex flex-col min-w-0 bg-white">
        <header className="flex items-center justify-between px-4 sm:px-8 pt-4 sm:pt-5 pb-3 sm:pb-4 border-b border-stone-100 gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <button
              onClick={() => setMobileShowSidebar(true)}
              className="md:hidden shrink-0 flex items-center gap-1.5 text-[12px] font-medium px-2.5 py-1.5 rounded-lg border border-stone-200 text-stone-700 bg-stone-50 hover:bg-stone-100 cursor-pointer"
            >
              <MessageSquare className="w-3.5 h-3.5 text-indigo-600" />
              <span>Chats</span>
            </button>
            {editingTitle ? (
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={commitTitle}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitTitle();
                  if (e.key === "Escape") setEditingTitle(false);
                }}
                className="text-[15px] sm:text-[17px] font-semibold text-stone-900 bg-stone-50 border border-indigo-300 rounded-md px-2 py-0.5 outline-none min-w-0 flex-1"
              />
            ) : (
              <>
                <h2 className="text-[15px] sm:text-[17px] font-semibold text-stone-900 truncate">
                  {activeChat?.title || (files.length === 0 ? "Knowledge Base Setup" : "RAG Query Console")}
                </h2>
                {activeChat && (
                  <button onClick={startEditTitle} title="Rename chat" className="text-stone-400 hover:text-stone-600 shrink-0 cursor-pointer">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                )}
              </>
            )}
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 sm:px-8">
          {files.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-12 sm:py-16 max-w-md mx-auto">
              <div className="w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center mb-4 shadow-xs">
                {inlineUploading ? (
                  <Loader2 className="w-7 h-7 text-indigo-600 animate-spin" />
                ) : (
                  <UploadCloud className="w-7 h-7 text-indigo-600" />
                )}
              </div>
              <h3 className="text-[17px] font-semibold text-stone-900">Upload your first document</h3>
              <p className="text-[13px] text-stone-500 mt-1.5 mb-6 leading-relaxed">
                RAG Assistant provides verifiable answers grounded in your own documents. Add a PDF, DOCX, CSV, Excel, or JSON file to start querying.
              </p>
              <div className="flex items-center gap-3">
                <button
                  onClick={onOpenSources}
                  className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white text-[13px] font-medium px-4 py-2.5 rounded-lg shadow-xs cursor-pointer transition-all"
                >
                  <Folder className="w-4 h-4" />
                  Go to Knowledge Sources
                </button>
                <button
                  onClick={() => inlineFileInputRef.current?.click()}
                  disabled={inlineUploading}
                  className="flex items-center gap-2 bg-stone-100 hover:bg-stone-200 text-stone-700 text-[13px] font-medium px-4 py-2.5 rounded-lg cursor-pointer transition-all disabled:opacity-50"
                >
                  <FileText className="w-4 h-4 text-stone-500" />
                  {inlineUploading ? "Uploading…" : "Browse File"}
                </button>
              </div>
              <input
                ref={inlineFileInputRef}
                type="file"
                accept=".pdf,.csv,.xlsx,.xls,.docx,.json"
                className="hidden"
                onChange={handleInlineUpload}
              />
            </div>
          ) : !activeId || turns.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-12 max-w-lg mx-auto">
              <div className="w-12 h-12 rounded-2xl bg-indigo-50 flex items-center justify-center mb-3">
                <Sparkles className="w-6 h-6 text-indigo-600" />
              </div>
              <h3 className="text-[17px] font-semibold text-stone-900">What would you like to know?</h3>
              <p className="text-[13px] text-stone-500 mt-1 mb-6">
                RAG Assistant is ready. Searching across <span className="font-semibold text-stone-700">{files.length} indexed document{files.length === 1 ? "" : "s"}</span>.
              </p>
              <div className="w-full space-y-2 text-left">
                <p className="text-[11.5px] font-medium text-stone-400 uppercase tracking-wide px-1">
                  Suggested Questions
                </p>
                {[
                  "Summarize the main points and key takeaways",
                  "What are the critical risks, obligations, or timelines?",
                  "Extract all important facts, metrics, and dates",
                ].map((suggestion, idx) => (
                  <button
                    key={idx}
                    onClick={() => {
                      submitQuery(suggestion);
                    }}
                    className="w-full flex items-center justify-between p-3 rounded-xl border border-stone-200/80 hover:border-indigo-300 hover:bg-indigo-50/40 text-[13px] text-stone-700 transition-all cursor-pointer group shadow-2xs"
                  >
                    <span>{suggestion}</span>
                    <ArrowRight className="w-3.5 h-3.5 text-stone-400 group-hover:text-indigo-600 group-hover:translate-x-0.5 transition-all" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="divide-y divide-stone-100 pb-6">
              {turns.map((t, i) =>
                t.role === "user" ? (
                  <UserTurn key={i} text={t.text} />
                ) : (
                  <AssistantTurn
                    key={i}
                    turn={t}
                    documents={files}
                    onRegenerate={regenerate}
                    isLast={i === turns.length - 1}
                    regenerateLocked={queryLimitReached}
                  />
                )
              )}
            </div>
          )}

          {pipeline && <PipelineRunning stageIndex={pipeline.stageIndex} />}
        </div>

        <div className="px-8 pb-6 pt-2 relative">
          {queryLimitReached ? (
            <UpgradeLockBar
              icon={MessageSquare}
              title={`You've used all ${queryLimit} free queries this month`}
              subtitle="Upgrade to Pro for unlimited queries across every collection."
              onUpgrade={onUpgrade}
            />
          ) : (
            <>
              {scopedDocIds.length > 0 && (
                <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                  <span className="text-[11.5px] text-stone-400">Scoped to:</span>
                  {scopedDocIds.map((id) => {
                    const doc = files.find((f) => f.id === id);
                    if (!doc) return null;
                    return (
                      <span key={id} className="inline-flex items-center gap-1 bg-indigo-50 text-indigo-700 text-[11.5px] font-medium px-2 py-0.5 rounded-full">
                        {doc.name}
                        <button
                          onClick={() => setScopedDocIds((prev) => prev.filter((d) => d !== id))}
                          className="hover:text-indigo-900 cursor-pointer"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    );
                  })}
                  <button onClick={() => setScopedDocIds([])} className="text-[11px] text-stone-400 hover:text-stone-600 ml-1 cursor-pointer">
                    Clear all
                  </button>
                </div>
              )}
              <div className="flex items-center gap-2 bg-stone-100 rounded-xl px-4 py-3 relative border border-stone-200/60 focus-within:border-stone-300 focus-within:bg-white transition-all shadow-xs">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && submitQuery()}
                  placeholder={
                    files.length === 0
                      ? "Upload a document to start asking questions…"
                      : pipeline
                      ? "Retrieving and synthesizing…"
                      : "Ask a question about your documents…"
                  }
                  disabled={!!pipeline}
                  className="bg-transparent text-[13.5px] outline-none w-full placeholder:text-stone-400 text-stone-900"
                />
                <button
                  type="button"
                  onClick={() => setShowDocPicker((v) => !v)}
                  className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-colors cursor-pointer ${
                    scopedDocIds.length > 0 ? "bg-indigo-100 text-indigo-600 hover:bg-indigo-200" : "hover:bg-stone-200 text-stone-500"
                  }`}
                  title={files.length === 0 ? "Upload documents" : "Filter documents"}
                >
                  <Paperclip className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={() => submitQuery()}
                  disabled={!!pipeline || !input.trim()}
                  className="w-8 h-8 rounded-full bg-stone-900 hover:bg-slate-800 disabled:opacity-40 flex items-center justify-center text-white shrink-0 cursor-pointer disabled:cursor-not-allowed transition-colors"
                >
                  <ArrowUp className="w-4 h-4" />
                </button>
                {showDocPicker && (
                  <DocumentPicker
                    pickerRef={docPickerRef}
                    files={files}
                    selectedIds={scopedDocIds}
                    onToggle={(id) =>
                      setScopedDocIds((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]))
                    }
                    onClear={() => setScopedDocIds([])}
                    onConfirm={() => setShowDocPicker(false)}
                    onUpload={uploadDocument}
                    onUploadComplete={refreshFiles}
                  />
                )}
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

/* =====================================================================
   RAG FILE MANAGER & USAGE
===================================================================== */

function StatusIndicator({ status }) {
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.queued;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12.5px] font-medium ${cfg.text}`}>
      {status === "processing" || status === "uploaded" ? (
        <Icon className={`w-3 h-3 ${cfg.spin ? "animate-spin" : ""}`} />
      ) : (
        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      )}
      {cfg.label}
    </span>
  );
}

function FileRow({ file, selected, onToggleSelect, onRetry, onRequestDelete, onChat }) {
  const catBadge = CATEGORY_CONFIG[file.category] || { label: "Document", badge: "bg-stone-50 text-stone-600 border-stone-200" };

  return (
    <>
      <div
        className={`hidden md:flex items-center gap-3 pl-4 pr-3 py-2.5 border-b border-stone-100 group transition-colors ${
          selected ? "bg-indigo-50/50" : "hover:bg-stone-50/80"
        }`}
      >
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(file.id)}
          className="w-3.5 h-3.5 rounded border-stone-300 text-indigo-600 focus:ring-indigo-400 cursor-pointer shrink-0"
        />

        <div className="w-6 h-6 rounded-md bg-stone-100 flex items-center justify-center shrink-0">
          <FileTypeIcon type={file.type} className="w-3.5 h-3.5 text-stone-500" />
        </div>

        <div className="flex-1 min-w-0 pr-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-[13px] font-medium text-stone-800 truncate" title={file.name}>
              {file.name}
            </span>
            {file.storage_url && (
              <a
                href={file.storage_url}
                target="_blank"
                rel="noreferrer"
                title="Open in Google Classroom / Drive"
                className="text-stone-400 hover:text-indigo-600 transition-colors shrink-0 p-0.5"
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
          {file.status === "failed" && file.error && <p className="text-[11px] text-rose-500 truncate">{file.error}</p>}
          {(file.status === "processing" || file.status === "uploaded") && (
            <div className="mt-0.5 h-[3px] w-28 bg-stone-100 rounded-full overflow-hidden">
              <div className="h-full bg-amber-400 rounded-full transition-all animate-pulse" style={{ width: `60%` }} />
            </div>
          )}
        </div>

        <div style={{ width: 130 }} className="shrink-0">
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${catBadge.badge}`}>
            {catBadge.label}
          </span>
        </div>

        <div style={{ width: 90 }} className="shrink-0">
          <StatusIndicator status={file.status} />
        </div>
        <div style={{ width: 85 }} className="shrink-0 text-[12px] text-stone-500 tabular-nums text-right">
          {formatBytes(file.size)}
        </div>
        <div style={{ width: 75 }} className="shrink-0 text-[11.5px] text-stone-400 text-right whitespace-nowrap">
          {file.updated}
        </div>

        <div style={{ width: 110 }} className="shrink-0 flex items-center justify-end gap-1">
          {file.status === "indexed" || file.status === "completed" ? (
            <button
              onClick={() => onChat(file)}
              title={`Chat about ${file.name}`}
              className="flex items-center gap-1 text-[11.5px] font-medium text-indigo-600 hover:bg-indigo-50 rounded-md px-2 py-1 whitespace-nowrap cursor-pointer transition-colors"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              Chat
            </button>
          ) : (
            <span style={{ width: 50 }} className="shrink-0" />
          )}
          <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            {file.status === "failed" && (
              <button
                onClick={() => onRetry(file.id)}
                title="Retry"
                className="w-6 h-6 rounded-md hover:bg-stone-200 flex items-center justify-center text-stone-500 cursor-pointer"
              >
                <RotateCw className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => onRequestDelete(file)}
              title="Remove"
              className="w-6 h-6 rounded-md hover:bg-rose-50 flex items-center justify-center text-stone-400 hover:text-rose-500 cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      <div
        className={`md:hidden flex flex-col p-3 border-b border-stone-100 transition-colors ${
          selected ? "bg-indigo-50/50" : "bg-white"
        }`}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <input
              type="checkbox"
              checked={selected}
              onChange={() => onToggleSelect(file.id)}
              className="w-4 h-4 rounded border-stone-300 text-indigo-600 focus:ring-indigo-400 cursor-pointer shrink-0"
            />
            <div className="w-7 h-7 rounded-md bg-stone-100 flex items-center justify-center shrink-0">
              <FileTypeIcon type={file.type} className="w-4 h-4 text-stone-600" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium text-stone-900 truncate">{file.name}</div>
              <span className={`inline-block mt-0.5 px-1.5 py-0.2 rounded text-[10.5px] font-medium border ${catBadge.badge}`}>
                {catBadge.label}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {(file.status === "indexed" || file.status === "completed") && (
              <button
                onClick={() => onChat(file)}
                className="flex items-center gap-1 text-[11.5px] font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-md px-2 py-1 cursor-pointer"
              >
                <MessageSquare className="w-3 h-3" />
                Chat
              </button>
            )}
            {file.status === "failed" && (
              <button
                onClick={() => onRetry(file.id)}
                className="w-7 h-7 rounded-md bg-stone-100 hover:bg-stone-200 flex items-center justify-center text-stone-600 cursor-pointer"
              >
                <RotateCw className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              onClick={() => onRequestDelete(file)}
              className="w-7 h-7 rounded-md hover:bg-rose-50 flex items-center justify-center text-stone-400 hover:text-rose-600 cursor-pointer"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between pl-6 text-[12px] text-stone-500">
          <StatusIndicator status={file.status} />
          <div className="flex items-center gap-2 text-stone-400 text-[11.5px]">
            <span>{formatBytes(file.size)}</span>
            <span>·</span>
            <span>{file.updated}</span>
          </div>
        </div>
      </div>
    </>
  );
}

function CourseGroupCard({
  group,
  selectedIds,
  onToggleSelect,
  onToggleCourseSelect,
  onRetry,
  onRequestDelete,
  onChat,
  onChatCourse,
  isExpanded,
  onToggleExpand,
}) {
  const { courseName, files, total, slidesCnt, labsCnt, asgCnt } = group;
  const isCourseSelected = files.length > 0 && files.every((f) => selectedIds.has(f.id));
  const hasSomeSelected = files.some((f) => selectedIds.has(f.id)) && !isCourseSelected;

  return (
    <div className="border border-stone-200 rounded-xl overflow-hidden bg-white mb-3.5 shadow-2xs transition-all">
      {/* Course Line Header */}
      <div className="flex items-center justify-between gap-3 px-3.5 sm:px-4 py-2.5 sm:py-3 bg-stone-50/90 border-b border-stone-100 hover:bg-stone-100/70 transition-colors">
        <div className="flex items-center gap-2.5 sm:gap-3 min-w-0 flex-1">
          <input
            type="checkbox"
            checked={isCourseSelected}
            ref={(el) => {
              if (el) el.indeterminate = hasSomeSelected;
            }}
            onChange={() => onToggleCourseSelect(courseName, files)}
            className="w-4 h-4 rounded border-stone-300 text-indigo-600 focus:ring-indigo-400 cursor-pointer shrink-0"
            title={`Select all files in ${courseName}`}
          />
          <button
            type="button"
            onClick={() => onToggleExpand(courseName)}
            className="flex items-center gap-2 sm:gap-2.5 min-w-0 flex-1 text-left cursor-pointer group"
          >
            <div className="w-7 h-7 rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-600 flex items-center justify-center shrink-0 group-hover:bg-indigo-100 transition-colors">
              <GraduationCap className="w-4 h-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                <span className="text-[13.5px] sm:text-[14px] font-semibold text-stone-900 group-hover:text-indigo-600 transition-colors truncate">
                  {courseName}
                </span>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-stone-200/70 text-stone-600 shrink-0">
                  {total} {total === 1 ? "file" : "files"}
                </span>
                {slidesCnt > 0 && (
                  <span className="text-[10.5px] font-medium px-1.5 sm:px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200/60 shrink-0">
                    {slidesCnt} {slidesCnt === 1 ? "Slide" : "Slides"}
                  </span>
                )}
                {labsCnt > 0 && (
                  <span className="text-[10.5px] font-medium px-1.5 sm:px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200/60 shrink-0">
                    {labsCnt} {labsCnt === 1 ? "Lab" : "Labs"}
                  </span>
                )}
                {asgCnt > 0 && (
                  <span className="text-[10.5px] font-medium px-1.5 sm:px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200/60 shrink-0">
                    {asgCnt} {asgCnt === 1 ? "Task" : "Tasks"}
                  </span>
                )}
              </div>
            </div>
          </button>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          <button
            type="button"
            onClick={() => onChatCourse(files, courseName)}
            title={`Start chat scoped to ${courseName}`}
            className="hidden sm:inline-flex items-center gap-1.5 text-[11.5px] font-medium text-indigo-600 hover:text-indigo-700 bg-white hover:bg-indigo-50/80 border border-indigo-200 rounded-lg px-2.5 py-1.5 transition-colors cursor-pointer"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Chat Course</span>
          </button>
          <button
            type="button"
            onClick={() => onToggleExpand(courseName)}
            title={isExpanded ? "Collapse course view" : "Maximize course to view all materials"}
            className="flex items-center gap-1 text-[11.5px] font-medium text-stone-600 hover:text-stone-900 bg-white hover:bg-stone-100 border border-stone-200 rounded-lg px-2.5 py-1.5 transition-colors cursor-pointer"
          >
            {isExpanded ? (
              <>
                <Minimize2 className="w-3.5 h-3.5 text-stone-500" />
                <span className="hidden md:inline">Collapse</span>
              </>
            ) : (
              <>
                <Maximize2 className="w-3.5 h-3.5 text-indigo-600" />
                <span className="hidden md:inline text-indigo-600 font-semibold">Maximize</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Expanded Course Materials Table */}
      {isExpanded && (
        <div>
          <div className="hidden md:flex items-center gap-3 pl-4 pr-3 py-1.5 bg-stone-50/40 text-[10.5px] font-medium text-stone-400 uppercase tracking-wide border-b border-stone-100">
            <div style={{ width: 14 }} className="shrink-0" />
            <div style={{ width: 24 }} className="shrink-0" />
            <div className="flex-1 min-w-0">Document & Material Title</div>
            <div style={{ width: 130 }} className="shrink-0">Category</div>
            <div style={{ width: 90 }} className="shrink-0">Status</div>
            <div style={{ width: 85 }} className="shrink-0 text-right">Size</div>
            <div style={{ width: 75 }} className="shrink-0 text-right">Updated</div>
            <div style={{ width: 110 }} className="shrink-0 text-right">Actions</div>
          </div>
          {files.map((file) => (
            <FileRow
              key={file.id}
              file={file}
              selected={selectedIds.has(file.id)}
              onToggleSelect={onToggleSelect}
              onRetry={onRetry}
              onRequestDelete={onRequestDelete}
              onChat={onChat}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DeleteConfirmModal({ target, onCancel, onConfirm }) {
  if (!target) return null;
  const isBulk = Array.isArray(target);
  const label = isBulk ? `${target.length} files` : `"${target.name}"`;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-xs px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5 border border-stone-200">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-full bg-rose-50 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-4 h-4 text-rose-500" />
          </div>
          <div>
            <h3 className="text-[14.5px] font-semibold text-stone-900">Delete {label}?</h3>
            <p className="text-[13px] text-stone-500 mt-1">
              This removes the {isBulk ? "files" : "file"} and every chunk indexed from {isBulk ? "them" : "it"} from the
              assistant's knowledge base. This action cannot be undone.
            </p>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 mt-5">
          <button
            onClick={onCancel}
            className="text-[13px] font-medium px-3 py-1.5 rounded-lg text-stone-600 hover:bg-stone-100 cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="text-[13px] font-medium px-3 py-1.5 rounded-lg bg-rose-600 text-white hover:bg-rose-700 cursor-pointer"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="border border-stone-200/80 rounded-xl px-4 py-3.5 bg-white shadow-xs">
      <div className="flex items-center gap-2 text-stone-400 mb-2">
        <Icon className="w-3.5 h-3.5" />
        <span className="text-[12px] font-medium">{label}</span>
      </div>
      <p className="text-[20px] font-semibold text-stone-900 leading-none">{value}</p>
      {sub && <p className="text-[12px] text-stone-400 mt-1.5">{sub}</p>}
    </div>
  );
}

function UsageView({ files, plan, usageData }) {
  const currentPlan = PLANS[plan] || PLANS.free;
  const storageLimitBytes = currentPlan.storageLimitBytes;
  const totalStorage = files.reduce((sum, f) => sum + (f.size || 0), 0);
  const totalChunks = usageData?.chunks_stored ?? files.reduce((sum, f) => sum + (f.chunks || 0), 0);
  const totalQueries = usageData?.queries_this_month ?? 0;
  const docsUploaded = usageData?.documents_uploaded ?? files.length;
  const queryQuota = usageData?.query_quota && usageData.query_quota > 0 ? usageData.query_quota : "Unlimited";
  const docQuota = usageData?.document_quota && usageData.document_quota > 0 ? usageData.document_quota : "Unlimited";
  const storagePct = storageLimitBytes ? Math.min(100, (totalStorage / storageLimitBytes) * 100) : 0;

  return (
    <div className="px-4 sm:px-8 py-5 sm:py-6 overflow-y-auto flex-1">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 mb-5 border border-indigo-100 rounded-xl px-4 py-3 bg-indigo-50/40">
        <div className="flex items-center gap-2 text-[13px]">
          <Sparkles className="w-4 h-4 text-indigo-600 shrink-0" />
          <span className="text-stone-700 font-medium">
            Active Tier <span className="text-stone-400 font-normal">· Unlimited Access</span>
          </span>
        </div>
        <div className="text-[12px] text-stone-600 font-medium bg-white border border-stone-200 rounded-md px-2.5 py-1 shrink-0">
          {totalQueries} queries used · Unlimited quota
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <SummaryCard
          icon={MessageSquare}
          label="Queries used"
          value={typeof queryQuota === "number" ? `${totalQueries} / ${queryQuota}` : `${totalQueries} (Unlimited)`}
          sub="live RAG generations"
        />
        <SummaryCard
          icon={Gauge}
          label="Indexed documents"
          value={typeof docQuota === "number" ? `${docsUploaded} / ${docQuota}` : `${docsUploaded} (Unlimited)`}
          sub="uploaded source files"
        />
        <SummaryCard
          icon={FileText}
          label="Chunks indexed"
          value={totalChunks.toLocaleString()}
          sub="vectorized chunks in DB"
        />
        <SummaryCard
          icon={Database}
          label="Storage used"
          value={formatBytes(totalStorage)}
          sub="Unlimited storage available"
        />
      </div>

      <div className="w-full h-2 bg-stone-100 rounded-full overflow-hidden mb-6">
        <div
          className="h-full rounded-full bg-indigo-500"
          style={{ width: "100%" }}
        />
      </div>

      <div className="rounded-xl border border-stone-200 bg-white p-4.5 text-[13px] text-stone-600 leading-relaxed shadow-2xs">
        <div className="flex items-center gap-2 font-semibold text-stone-900 mb-1.5">
          <Info className="w-4 h-4 text-indigo-600 shrink-0" />
          Unlimited RAG Assistant Architecture
        </div>
        <p className="text-stone-500 text-[12.5px] leading-relaxed">
          RAG Assistant is an enterprise hybrid search and verified document Q&A platform powered by pgvector dense retrieval, PostgreSQL full-text search, and cross-encoder reranking. Usage limits are removed with unlimited queries and document indexing available.
        </p>
      </div>
    </div>
  );
}

function RagFileManager({
  plan,
  onUpgrade,
  onDowngrade,
  view,
  setView,
  files,
  setFiles,
  onTagDoc,
  usageData,
  refreshFiles,
  refreshUsage,
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [isDragging, setIsDragging] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [syncingGcr, setSyncingGcr] = useState(false);
  const [expandedCourses, setExpandedCourses] = useState({});
  const pollingRef = useRef({});
  const inputRef = useRef(null);
  const mounted = useMountedFade();

  const handleSyncClassroom = async () => {
    setSyncingGcr(true);
    try {
      const res = await syncClassroom();
      if (refreshFiles) refreshFiles();
      if (refreshUsage) refreshUsage();
      const count = res?.total_materials ?? res?.synced_courses ?? 0;
      alert(`Google Classroom sync complete: ${count} materials updated.`);
    } catch (err) {
      console.error("GCR sync failed:", err);
      alert(err?.message || "Failed to sync Google Classroom. Please ensure your Google account is connected.");
    } finally {
      setSyncingGcr(false);
    }
  };

  const pollDocumentStatus = useCallback(
    (docId) => {
      if (pollingRef.current[docId]) return;
      pollingRef.current[docId] = true;

      let attempts = 0;
      const MAX_ATTEMPTS = 40;

      const poll = async () => {
        try {
          attempts++;
          const status = await getDocumentStatus(docId);
          const mappedStatus = status.status === "completed" ? "indexed" : status.status;
          setFiles((prev) =>
            prev.map((f) => (f.id === docId ? { ...f, status: mappedStatus, error: status.error_message } : f))
          );
          if ((mappedStatus === "processing" || mappedStatus === "uploaded") && attempts < MAX_ATTEMPTS) {
            setTimeout(poll, 1500);
          } else {
            const isTerminal = mappedStatus !== "processing" && mappedStatus !== "uploaded";
            if (attempts >= MAX_ATTEMPTS && (mappedStatus === "processing" || mappedStatus === "uploaded")) {
              setFiles((prev) =>
                prev.map((f) => (f.id === docId ? { ...f, status: "failed", error: "Processing timed out" } : f))
              );
            }
            delete pollingRef.current[docId];
            if (refreshUsage) refreshUsage();
            if (refreshFiles && isTerminal) refreshFiles();
          }
        } catch {
          delete pollingRef.current[docId];
        }
      };
      setTimeout(poll, 1500);
    },
    [setFiles, refreshUsage, refreshFiles]
  );

  useEffect(() => {
    files.forEach((f) => {
      if (f.status === "processing" || f.status === "uploaded") {
        pollDocumentStatus(f.id);
      }
    });
  }, [files, pollDocumentStatus]);

  const addFiles = useCallback(
    async (fileList) => {
      const selected = Array.from(fileList);
      if (selected.length === 0) return;

      const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB limit
      const validFiles = [];
      for (const file of selected) {
        if (file.size > MAX_FILE_SIZE) {
          alert(`"${file.name}" exceeds the 10 MB demo limit.`);
        } else {
          validFiles.push(file);
        }
      }
      if (validFiles.length === 0) return;

      setUploading(true);
      try {
        for (const file of validFiles) {
          const doc = await uploadDocument(file);
          const mapped = mapDocumentToFrontend(doc);
          mapped.progress = 0;
          setFiles((prev) => [mapped, ...prev.filter((f) => f.id !== doc.id)]);
          pollDocumentStatus(doc.id);
        }
        if (refreshUsage) refreshUsage();
        if (refreshFiles) refreshFiles();
      } catch (err) {
        console.error("Upload failed:", err);
        alert(err?.message || "Upload failed. Please check the backend server.");
      } finally {
        setUploading(false);
      }
    },
    [setFiles, pollDocumentStatus, refreshUsage, refreshFiles]
  );

  const onDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const onRetry = (id) => {
    setFiles((prev) => prev.map((f) => (f.id === id ? { ...f, status: "processing", progress: 0, error: null } : f)));
    pollDocumentStatus(id);
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = (visibleFiles) => {
    setSelectedIds((prev) => {
      const allSelected = visibleFiles.every((f) => prev.has(f.id));
      const next = new Set(prev);
      visibleFiles.forEach((f) => (allSelected ? next.delete(f.id) : next.add(f.id)));
      return next;
    });
  };

  const toggleCourseExpand = (courseName) => {
    setExpandedCourses((prev) => ({
      ...prev,
      [courseName]: !prev[courseName],
    }));
  };

  const toggleCourseSelect = (courseName, courseFiles) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allSelected = courseFiles.every((f) => prev.has(f.id));
      if (allSelected) {
        courseFiles.forEach((f) => next.delete(f.id));
      } else {
        courseFiles.forEach((f) => next.add(f.id));
      }
      return next;
    });
  };

  const setAllExpanded = (expandState) => {
    const updated = {};
    groupedCourses.forEach((g) => {
      updated[g.courseName] = expandState;
    });
    setExpandedCourses(updated);
  };

  const requestDelete = (fileOrFiles) => setDeleteTarget(fileOrFiles);
  const cancelDelete = () => setDeleteTarget(null);

  const confirmDelete = async () => {
    const ids = Array.isArray(deleteTarget) ? deleteTarget.map((f) => f.id) : [deleteTarget.id];
    try {
      await Promise.allSettled(ids.map((id) => deleteDocument(id)));
    } catch (err) {
      console.error("Delete failed:", err);
    } finally {
      setFiles((prev) => prev.filter((f) => !ids.includes(f.id)));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        ids.forEach((id) => next.delete(id));
        return next;
      });
      if (refreshUsage) refreshUsage();
      if (refreshFiles) refreshFiles();
      setDeleteTarget(null);
    }
  };

  const filtered = useMemo(() => {
    return files.filter((f) => {
      const q = query.trim().toLowerCase();
      const matchesQuery =
        !q ||
        (f.name && f.name.toLowerCase().includes(q)) ||
        (f.clean_title && f.clean_title.toLowerCase().includes(q)) ||
        (f.course_name && f.course_name.toLowerCase().includes(q)) ||
        (f.category && f.category.toLowerCase().includes(q));

      if (!matchesQuery) return false;

      if (statusFilter === "all") return true;
      if (["slides", "labs", "coursework", "syllabus", "handouts"].includes(statusFilter)) {
        return f.category === statusFilter;
      }
      return f.status === statusFilter;
    });
  }, [files, query, statusFilter]);

  const groupedCourses = useMemo(() => {
    const map = new Map();
    filtered.forEach((file) => {
      const course = file.course_name || "General Documents";
      if (!map.has(course)) {
        map.set(course, []);
      }
      map.get(course).push(file);
    });

    return Array.from(map.entries())
      .map(([courseName, courseFiles]) => ({
        courseName,
        files: courseFiles,
      }))
      .sort((a, b) => {
        if (a.courseName === "General Documents" || a.courseName === "My Uploads") return 1;
        if (b.courseName === "General Documents" || b.courseName === "My Uploads") return -1;
        return a.courseName.localeCompare(b.courseName);
      });
  }, [filtered]);

  const statusCounts = useMemo(() => {
    return files.reduce((acc, f) => {
      acc[f.status] = (acc[f.status] || 0) + 1;
      if (f.category) {
        acc[f.category] = (acc[f.category] || 0) + 1;
      }
      return acc;
    }, {});
  }, [files]);

  const uploadLimit = (PLANS[plan] || PLANS.free).uploadLimit;
  const uploadLimitReached = false;

  const FILTER_TABS = [
    { id: "all", label: "All Sources" },
    { id: "slides", label: "Slides" },
    { id: "labs", label: "Labs" },
    { id: "coursework", label: "Coursework" },
    { id: "handouts", label: "Handouts" },
    { id: "indexed", label: "Indexed" },
    { id: "processing", label: "Processing" },
  ];

  return (
    <div className={`h-full w-full bg-white text-stone-900 flex transition-opacity duration-200 ${mounted ? "opacity-100" : "opacity-0"}`}>
      <main className="flex-1 flex flex-col min-w-0 relative">
        <header className="px-4 sm:px-8 pt-5 sm:pt-6 pb-0 border-b border-stone-100 shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-[17px] sm:text-[18px] font-semibold tracking-tight">Knowledge Sources</h1>
              <p className="text-[12.5px] sm:text-[13px] text-stone-500 mt-0.5 mb-3 sm:mb-4">
                Google Classroom coursework, lecture slides, lab manuals, and uploaded documents indexed for verified retrieval.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-5">
            {[
              { id: "sources", label: "Sources" },
              { id: "usage", label: "Usage" },
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setView(t.id)}
                className={`text-[13.5px] font-medium pb-3 border-b-2 transition-colors cursor-pointer ${
                  view === t.id ? "border-stone-900 text-stone-900" : "border-transparent text-stone-400 hover:text-stone-600"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </header>

        {view === "usage" ? (
          <UsageView files={files} plan={plan} usageData={usageData} />
        ) : (
          <>
            <div className="px-4 sm:px-8 py-4 sm:py-5 shrink-0">
              {uploadLimitReached ? (
                <UpgradeLockBar
                  icon={UploadCloud}
                  title={`You've reached the ${uploadLimit}-source limit on the Demo tier`}
                  subtitle="Each demo account is provisioned with 5 indexed sources."
                />
              ) : (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={onDrop}
                  className={`rounded-xl border-2 border-dashed flex flex-col items-center justify-center py-6 sm:py-7 px-4 text-center transition-colors ${
                    isDragging ? "border-indigo-400 bg-indigo-50/60" : "border-stone-200 hover:border-stone-300"
                  }`}
                >
                  <input
                    ref={inputRef}
                    type="file"
                    multiple
                    accept=".pdf,.csv,.xlsx,.xls,.docx,.json,.pptx"
                    className="hidden"
                    onChange={(e) => e.target.files?.length && addFiles(e.target.files)}
                  />
                  <div className="w-10 h-10 sm:w-11 sm:h-11 rounded-full bg-indigo-50 flex items-center justify-center mb-3 shrink-0">
                    {uploading || syncingGcr ? (
                      <Loader2 className="w-5 h-5 text-indigo-500 animate-spin" />
                    ) : (
                      <UploadCloud className="w-5 h-5 text-indigo-500" />
                    )}
                  </div>
                  <p className="text-[13.5px] sm:text-[14px] font-medium text-stone-700">
                    {uploading
                      ? "Uploading and indexing files…"
                      : syncingGcr
                      ? "Fetching and indexing Google Classroom materials…"
                      : "Add materials or sync Google Classroom directly"}
                  </p>
                  <p className="text-[12px] sm:text-[12.5px] text-stone-400 mt-1 mb-3 sm:mb-4">
                    PDF, DOCX, PPTX, CSV, Excel, or JSON · synced automatically or uploaded locally
                  </p>

                  <div className="flex items-center gap-2.5 flex-wrap justify-center">
                    <button
                      type="button"
                      onClick={() => inputRef.current?.click()}
                      disabled={uploading || syncingGcr}
                      className="text-[12.5px] font-medium bg-stone-900 text-white rounded-lg px-3.5 py-1.5 hover:bg-stone-800 cursor-pointer disabled:opacity-50 transition-colors shadow-2xs"
                    >
                      Browse files
                    </button>
                    <button
                      type="button"
                      onClick={handleSyncClassroom}
                      disabled={uploading || syncingGcr}
                      className="inline-flex items-center gap-1.5 text-[12.5px] font-medium bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 rounded-lg px-3.5 py-1.5 cursor-pointer disabled:opacity-50 transition-colors shadow-2xs"
                    >
                      {syncingGcr ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <GraduationCap className="w-3.5 h-3.5 text-indigo-600" />
                      )}
                      <span>{syncingGcr ? "Syncing GCR…" : "Sync Google Classroom"}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="px-4 sm:px-8 pb-3 flex flex-wrap sm:flex-nowrap items-center justify-between gap-2 shrink-0">
              <div className="flex items-center gap-2 bg-stone-100 rounded-lg px-3 py-1.5 sm:py-2 flex-1 sm:w-64 min-w-[160px]">
                <Search className="w-4 h-4 text-stone-400 shrink-0" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search courses, slides, labs, docs…"
                  className="bg-transparent text-[13px] outline-none w-full placeholder:text-stone-400"
                />
              </div>

              <div className="flex items-center gap-2 overflow-x-auto max-w-full pb-1 sm:pb-0 shrink-0">
                <div className="flex items-center gap-1.5">
                  {FILTER_TABS.map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setStatusFilter(tab.id)}
                      className={`text-[12px] sm:text-[12.5px] font-medium px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-full border transition-colors cursor-pointer whitespace-nowrap ${
                        statusFilter === tab.id ? "bg-stone-900 text-white border-stone-900" : "border-stone-200 text-stone-500 hover:bg-stone-50"
                      }`}
                    >
                      {tab.label}
                      {tab.id !== "all" && statusCounts[tab.id] ? ` (${statusCounts[tab.id]})` : ""}
                    </button>
                  ))}
                </div>

                {groupedCourses.length > 0 && (
                  <div className="hidden sm:flex items-center gap-1 border-l border-stone-200 pl-2">
                    <button
                      type="button"
                      onClick={() => setAllExpanded(true)}
                      className="text-[11.5px] text-stone-500 hover:text-stone-800 px-2 py-1 rounded hover:bg-stone-100 cursor-pointer whitespace-nowrap font-medium"
                    >
                      Expand All
                    </button>
                    <span className="text-stone-300">·</span>
                    <button
                      type="button"
                      onClick={() => setAllExpanded(false)}
                      className="text-[11.5px] text-stone-500 hover:text-stone-800 px-2 py-1 rounded hover:bg-stone-100 cursor-pointer whitespace-nowrap font-medium"
                    >
                      Collapse All
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-4 sm:px-8 pb-24 relative">
              {groupedCourses.length === 0 ? (
                <div className="border border-stone-200 rounded-xl bg-white p-12 text-center text-[13px] text-stone-400">
                  {files.length === 0
                    ? "No files or Classroom materials available yet. Sync Google Classroom or upload files above."
                    : "No materials match this filter."}
                </div>
              ) : (
                groupedCourses.map(({ courseName, files: courseFiles }) => (
                  <CourseGroupCard
                    key={courseName}
                    courseName={courseName}
                    files={courseFiles}
                    isExpanded={query.trim().length > 0 ? true : !!expandedCourses[courseName]}
                    selectedIds={selectedIds}
                    onToggleExpand={toggleCourseExpand}
                    onToggleCourseSelect={toggleCourseSelect}
                    onToggleSelect={toggleSelect}
                    onRetry={onRetry}
                    onRequestDelete={requestDelete}
                    onChat={onTagDoc}
                    onChatCourse={(cFiles, cName) => {
                      if (onTagDoc && cFiles.length > 0) {
                        onTagDoc(cFiles[0]);
                      }
                    }}
                  />
                ))
              )}
            </div>

            {selectedIds.size > 0 && (
              <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-stone-900 text-white rounded-full pl-4 pr-2 py-2 flex items-center gap-3 shadow-xl z-10 animate-slide-up">
                <span className="text-[13px] font-medium">{selectedIds.size} selected</span>
                <button
                  type="button"
                  onClick={() => {
                    const selectedList = files.filter((f) => selectedIds.has(f.id));
                    if (selectedList.length > 0 && onTagDoc) {
                      onTagDoc(selectedList[0]);
                    }
                  }}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white text-[12px] font-medium px-3 py-1 rounded-full cursor-pointer transition-colors flex items-center gap-1.5 shadow-xs"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Chat Selected
                </button>
                <button
                  onClick={() => {
                    const toDelete = files.filter((f) => selectedIds.has(f.id));
                    requestDelete(toDelete);
                  }}
                  className="bg-rose-600 hover:bg-rose-700 text-white text-[12px] font-medium px-3 py-1 rounded-full cursor-pointer transition-colors flex items-center gap-1 shadow-xs"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Delete
                </button>
                <button
                  onClick={() => setSelectedIds(new Set())}
                  className="w-6 h-6 rounded-full hover:bg-white/20 flex items-center justify-center text-stone-300 cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </>
        )}
      </main>

      <DeleteConfirmModal target={deleteTarget} onCancel={cancelDelete} onConfirm={confirmDelete} />
    </div>
  );
}

/* =====================================================================
   MAIN DASHBOARD COMPONENT (EXPORTED)
===================================================================== */

export default function RagAssistantPage() {
  const [route, setRoute] = useState("inbox");
  const [plan, setPlan] = useState("free");
  const [sourcesView, setSourcesView] = useState("sources");
  const [files, setFiles] = useState([]);
  const [pendingDocTag, setPendingDocTag] = useState(null);
  const [usageData, setUsageData] = useState(null);
  const mounted = useMountedFade();

  const refreshFiles = useCallback(() => {
    listDocuments()
      .then((docs) => setFiles(docs.map(mapDocumentToFrontend)))
      .catch(() => {});
  }, []);

  const refreshUsage = useCallback(() => {
    getUsage()
      .then(setUsageData)
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshFiles();
    refreshUsage();
  }, [refreshFiles, refreshUsage]);

  const hasProcessingFiles = files.some(
    (f) => f.status === "processing" || f.status === "uploaded"
  );
  const pollingAttemptsRef = useRef(0);

  useEffect(() => {
    if (!hasProcessingFiles) {
      pollingAttemptsRef.current = 0;
      return;
    }
    if (pollingAttemptsRef.current >= 40) {
      pollingAttemptsRef.current = 0;
      return;
    }
    const interval = setInterval(() => {
      pollingAttemptsRef.current += 1;
      refreshFiles();
      refreshUsage();
    }, 3000);
    return () => clearInterval(interval);
  }, [hasProcessingFiles, refreshFiles, refreshUsage]);

  const goToRoute = (id) => {
    if (id === "sources") setSourcesView("sources");
    setRoute(id);
    refreshFiles();
    refreshUsage();
  };

  const upgrade = () => setPlan("pro");
  const downgrade = () => setPlan("free");

  const tagDocInChat = (file) => {
    setPendingDocTag({ ...file, taggedAt: Date.now() });
    setRoute("inbox");
  };

  return (
    <div
      className={`h-screen w-full flex flex-col bg-white text-stone-900 font-[system-ui] transition-opacity duration-300 ${
        mounted ? "opacity-100" : "opacity-0"
      }`}
    >
      <TopBar
        route={route}
        onRouteChange={goToRoute}
        plan={plan}
        onOpenUsage={() => {
          setSourcesView("usage");
          setRoute("sources");
          refreshUsage();
        }}
        onLogout={() => {
          // Sign out handled by Clerk UserButton
        }}
        files={files}
        onTagDoc={tagDocInChat}
      />

      <div className={`flex-1 min-h-0 ${route === "inbox" ? "" : "hidden"}`}>
        <ChatInboxDashboard
          plan={plan}
          onUpgrade={upgrade}
          pendingDocTag={pendingDocTag}
          onConsumePendingDocTag={() => setPendingDocTag(null)}
          files={files}
          usageData={usageData}
          refreshFiles={refreshFiles}
          refreshUsage={refreshUsage}
          onOpenSources={() => goToRoute("sources")}
        />
      </div>
      <div className={`flex-1 min-h-0 ${route === "sources" ? "" : "hidden"}`}>
        <RagFileManager
          plan={plan}
          onUpgrade={upgrade}
          onDowngrade={downgrade}
          view={sourcesView}
          setView={setSourcesView}
          files={files}
          setFiles={setFiles}
          onTagDoc={tagDocInChat}
          usageData={usageData}
          refreshFiles={refreshFiles}
          refreshUsage={refreshUsage}
        />
      </div>
    </div>
  );
}
