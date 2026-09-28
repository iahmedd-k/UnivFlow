'use client';

import { useState } from 'react';
import Icon from '@/app/dashboard/Icon';
import { format, isValid, formatDistanceToNow } from 'date-fns';
import TutorPanel from './TutorPanel';
import ReviewPanel from './ReviewPanel';
import TurnInPanel from './TurnInPanel';
import SolutionPanel from './SolutionPanel';

const TABS = [
  { id: 'overview', label: 'Overview & Rubric', icon: 'clipboard' },
  { id: 'tutor', label: 'AI Tutor', icon: 'lightbulb' },
  { id: 'solver', label: 'Solver & Report', icon: 'code' },
  { id: 'review', label: 'Pre-Submit Review', icon: 'search' },
  { id: 'turnin', label: 'Turn In', icon: 'upload' },
];

export default function AssignmentDetailModal({ assignment, initialTab = 'overview', onClose, onTurnIn }) {
  const [tab, setTab] = useState(TABS.some((t) => t.id === initialTab) ? initialTab : 'overview');

  const due = assignment.due_at ? new Date(assignment.due_at) : null;
  const hasValidDue = due && isValid(due);
  const dueDate = hasValidDue ? format(due, "MMMM d, yyyy 'at' h:mm a") : 'No deadline';
  const isOverdue = hasValidDue && due < new Date();
  const isSubmitted = assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED';
  const isQuiz = Boolean(assignment.is_quiz);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/60 backdrop-blur-xs animate-fade-in"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-3xl shadow-2xl max-w-5xl w-full max-h-[92vh] overflow-hidden flex flex-col border border-[#ececf2]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={assignment.title}
      >
        {/* Modal Topbar */}
        <div className="px-6 py-4.5 border-b border-[#ececf2] bg-white flex items-center justify-between gap-4">
          <div className="flex items-center gap-3.5 min-w-0">
            <div className={`w-11 h-11 shrink-0 rounded-2xl flex items-center justify-center text-xl border ${
              isQuiz ? 'bg-amber-50 border-amber-200 text-amber-600' : 'bg-[#f4f2ff] border-[#e4dffe] text-[#6657d9]'
            }`}>
              <Icon name={isQuiz ? 'clipboard' : 'book'} size={20}/>
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] font-semibold text-[#6657d9] bg-[#f5f3ff] px-2 py-0.5 rounded-md border border-[#ece7ff]">
                  {assignment.course_name}
                </span>
                {isSubmitted ? (
                  <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
                    <Icon name="check" size={12}/> Submitted
                  </span>
                ) : isOverdue ? (
                  <span className="text-[11px] font-semibold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-md border border-rose-200">
                    <Icon name="alert" size={12}/> Overdue
                  </span>
                ) : (
                  <span className="text-[11px] font-semibold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                    <Icon name="clock" size={12}/> Open
                  </span>
                )}
              </div>
              <h2 className="text-base sm:text-lg font-bold text-[#1e293b] leading-tight truncate mt-1">
                {assignment.title}
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {assignment.url && (
              <a
                href={assignment.url}
                target="_blank"
                rel="noreferrer"
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 bg-[#f8fafc] hover:bg-[#f1f5f9] text-[#475569] hover:text-[#1e293b] rounded-xl border border-[#e2e8f0] text-xs font-semibold transition-colors"
                title="Open in Google Classroom"
              >
                <span>Classroom</span>
                <Icon name="externalLink" size={13}/>
              </a>
            )}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-[#f8fafc] hover:bg-[#f1f5f9] flex items-center justify-center text-[#64748b] hover:text-[#1e293b] transition-colors border border-[#e2e8f0]"
              aria-label="Close modal"
            >
              <Icon name="close" size={15}/>
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <nav
          className="flex border-b border-[#ececf2] px-4 sm:px-6 bg-[#fafafd] overflow-x-auto scrollbar-none gap-1 sm:gap-2"
          aria-label="Assignment sections"
        >
          {TABS.map((t) => {
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`py-3 px-3 sm:px-4 text-xs sm:text-sm font-semibold border-b-2 transition-all flex items-center gap-1.5 whitespace-nowrap ${
                  isActive
                    ? 'border-[#6657d9] text-[#6657d9] bg-white rounded-t-xl'
                    : 'border-transparent text-[#64748b] hover:text-[#1e293b] hover:bg-white/60'
                }`}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon name={t.icon} size={15}/>
                <span>{t.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab Content Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 bg-[#fbfbfe]">
          {tab === 'overview' && (
            <OverviewTab
              assignment={assignment}
              dueDate={dueDate}
              isOverdue={isOverdue}
              isSubmitted={isSubmitted}
              onSwitchTab={setTab}
            />
          )}
          {tab === 'tutor' && <TutorPanel assignment={assignment} />}
          {tab === 'solver' && <SolutionPanel assignment={assignment} />}
          {tab === 'review' && <ReviewPanel assignment={assignment} />}
          {tab === 'turnin' && <TurnInPanel assignment={assignment} onTurnIn={onTurnIn} />}
        </div>
      </div>
    </div>
  );
}

function OverviewTab({ assignment, dueDate, isOverdue, isSubmitted, onSwitchTab }) {
  const due = assignment.due_at ? new Date(assignment.due_at) : null;
  const materials = assignment.materials || [];

  return (
    <div className="space-y-6">
      {/* Overview Quick Stats Card */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
        <div className="bg-white p-4 rounded-2xl border border-[#ebebf0] shadow-2xs">
          <span className="text-[11px] font-semibold text-[#858998] uppercase tracking-wider block">Course & Type</span>
          <p className="text-sm font-bold text-[#1e293b] mt-1 truncate">{assignment.course_name}</p>
          <span className="text-xs text-[#64748b] capitalize mt-0.5 block">
            {assignment.work_type ? assignment.work_type.replace('_', ' ') : 'Coursework Assignment'}
          </span>
        </div>

        <div className="bg-white p-4 rounded-2xl border border-[#ebebf0] shadow-2xs">
          <span className="text-[11px] font-semibold text-[#858998] uppercase tracking-wider block">Due Date</span>
          <p className="text-sm font-bold text-[#1e293b] mt-1">{dueDate}</p>
          {due && isValid(due) && (
            <span className={`text-xs font-semibold mt-0.5 block ${isOverdue ? 'text-rose-600' : 'text-[#6657d9]'}`}>
              {isOverdue ? `Expired ${formatDistanceToNow(due)} ago` : `Due in ${formatDistanceToNow(due)}`}
            </span>
          )}
        </div>

        <div className="bg-white p-4 rounded-2xl border border-[#ebebf0] shadow-2xs">
          <span className="text-[11px] font-semibold text-[#858998] uppercase tracking-wider block">Submission State</span>
          <p className="text-sm font-bold text-[#1e293b] mt-1 capitalize">
            {isSubmitted ? 'Turned In' : isOverdue ? 'Overdue' : 'Pending Submission'}
          </p>
          <span className="text-xs text-[#64748b] mt-0.5 block">
            {assignment.max_points ? `${assignment.max_points} Maximum Points` : 'Graded Coursework'}
          </span>
        </div>
      </div>

      {/* Instructions & Prompt Box */}
      <div className="bg-white rounded-2xl border border-[#ebebf0] shadow-2xs p-5 sm:p-6 space-y-3">
        <div className="flex items-center justify-between border-b border-[#f1f1f4] pb-3">
          <div className="flex items-center gap-2">
            <Icon name="file" size={16}/>
            <h3 className="text-xs font-bold text-[#475569] uppercase tracking-wider">Assignment Instructions & Description</h3>
          </div>
          {assignment.url && (
            <a
              href={assignment.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-semibold text-[#6657d9] hover:underline flex items-center gap-1"
            >
              Classroom Post <Icon name="externalLink" size={13}/>
            </a>
          )}
        </div>

        {assignment.description ? (
          <div className="prose prose-sm max-w-none text-[#334155] whitespace-pre-wrap text-xs sm:text-sm leading-relaxed bg-[#fafafd] p-4 sm:p-5 rounded-xl border border-[#ececf2]">
            {assignment.description}
          </div>
        ) : (
          <div className="text-center py-8 text-xs text-[#858998] bg-[#fafafd] rounded-xl border border-dashed border-[#ececf2]">
            No text instructions provided for this coursework post.
          </div>
        )}
      </div>

      {/* Materials & References Section */}
      <div className="bg-white rounded-2xl border border-[#ebebf0] shadow-2xs p-5 sm:p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-[#f1f1f4] pb-3">
          <div className="flex items-center gap-2">
            <Icon name="paperclip" size={16}/>
            <h3 className="text-xs font-bold text-[#475569] uppercase tracking-wider">Course Materials & Reference Files</h3>
          </div>
          <span className="text-xs font-semibold text-[#6657d9] bg-[#f5f3ff] px-2.5 py-0.5 rounded-full border border-[#ece7ff]">
            {materials.length} {materials.length === 1 ? 'Attachment' : 'Attachments'}
          </span>
        </div>

        {materials.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {materials.map((m, idx) => (
              <a
                key={idx}
                href={m.url || '#'}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-3 p-3.5 rounded-xl border border-[#ececf2] bg-[#fafafd] hover:bg-[#f5f3ff] hover:border-[#d9d2fa] transition-all group"
              >
                <div className="w-10 h-10 rounded-xl bg-white border border-[#ececf2] flex items-center justify-center text-xl shrink-0 group-hover:border-[#c9c2f0]">
                  <Icon name={m.material_type === 'drive_file' ? 'file' : m.material_type === 'link' ? 'link' : 'paperclip'} size={17}/>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-[#1e293b] truncate group-hover:text-[#6657d9] transition-colors">
                    {m.title || 'Attachment'}
                  </p>
                  <p className="text-[11px] text-[#858998] capitalize mt-0.5">
                    {m.material_type?.replace('_', ' ') || 'Reference File'} · Click to open <Icon name="externalLink" size={11}/>
                  </p>
                </div>
              </a>
            ))}
          </div>
        ) : (
          <div className="text-center py-6 text-xs text-[#858998] bg-[#fafafd] rounded-xl border border-dashed border-[#ececf2]">
            No attachments or external links attached to this coursework post.
          </div>
        )}
      </div>

      {/* Quick Navigation Action Hub */}
      <div className="bg-gradient-to-r from-[#f7f5ff] to-[#eef2ff] p-5 rounded-2xl border border-[#e4dffe] flex flex-col sm:flex-row items-center justify-between gap-4">
        <div>
          <h4 className="text-xs font-bold uppercase tracking-wider text-[#5142c1]">Next Steps with Uniflow</h4>
          <p className="text-xs text-[#6b678c] mt-0.5">
            Use AI assistance, sandbox code verification, and direct Classroom turn-in.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap shrink-0">
          <button
            type="button"
            onClick={() => onSwitchTab('tutor')}
            className="px-3.5 py-2 bg-white hover:bg-gray-50 text-[#5142c1] font-bold text-xs rounded-xl border border-[#d6d0fb] shadow-2xs transition-all flex items-center gap-1.5"
          >
            <Icon name="lightbulb" size={15}/>
            <span>Ask AI Tutor</span>
          </button>
          <button
            type="button"
            onClick={() => onSwitchTab('solver')}
            className="px-3.5 py-2 bg-[#6657d9] hover:bg-[#5748c9] text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
          >
            <Icon name="code" size={15}/>
            <span>Run AI Solver</span>
          </button>
          <button
            type="button"
            onClick={() => onSwitchTab('turnin')}
            className="px-3.5 py-2 bg-[#1e293b] hover:bg-[#0f172a] text-white font-bold text-xs rounded-xl shadow-sm transition-all flex items-center gap-1.5"
          >
            <Icon name="upload" size={15}/>
            <span>Turn In</span>
          </button>
        </div>
      </div>
    </div>
  );
}
