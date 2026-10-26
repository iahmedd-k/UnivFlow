'use client';

import Link from 'next/link';
import { format, isValid, formatDistanceToNow } from 'date-fns';
import Icon from '@/app/dashboard/Icon';

function getStatus(assignment) {
  const state = assignment.submission_state;
  if (state === 'TURNED_IN' || state === 'RETURNED') {
    return { label: 'Submitted', className: 'bg-[#eaf7f1] text-[#438a71]' };
  }
  if (state === 'DRAFT') {
    return { label: 'Draft', className: 'bg-[#f1f1f6] text-[#6e7281]' };
  }
  if (assignment.due_at && new Date(assignment.due_at) < new Date()) {
    return { label: 'Overdue', className: 'bg-[#fff0f0] text-[#b15252]' };
  }
  if (assignment.status === 'APPROVED') {
    return { label: 'Approved', className: 'bg-[#eaf7f1] text-[#438a71]' };
  }
  return { label: 'Upcoming', className: 'bg-[#fff4e4] text-[#a87936]' };
}

export default function AssignmentCard({ assignment, onOpen, viewMode = 'grid' }) {
  const date = assignment.due_at ? new Date(assignment.due_at) : null;
  const hasValidDate = date && isValid(date);
  const dueDateStr = hasValidDate ? format(date, 'MMM d, yyyy · h:mm a') : 'No deadline';
  const relativeStr = hasValidDate
    ? date < new Date()
      ? `${formatDistanceToNow(date)} ago`
      : `in ${formatDistanceToNow(date)}`
    : null;
  const status = getStatus(assignment);
  const isQuiz = Boolean(assignment.is_quiz);
  const materialsCount = assignment.materials?.length || 0;
  const targetHref = `/dashboard/assignments/${assignment.id}`;

  if (viewMode === 'list') {
    return (
      <Link
        href={targetHref}
        className="group flex min-h-[60px] items-center gap-3 border-b border-border-light px-4 py-3 text-inherit no-underline last:border-b-0 hover:bg-surface-secondary"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-light text-violet">
          <Icon name={isQuiz ? 'clipboard' : 'book'} size={16}/>
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <strong className="truncate text-sm font-semibold text-heading">
            {assignment.title || 'Untitled assignment'}
          </strong>
          <small className="text-xs font-normal text-muted">
            {assignment.course_name || 'Course'}
            {assignment.work_type ? ` · ${assignment.work_type.replace('_', ' ')}` : ''}
          </small>
        </span>
        <span className="whitespace-nowrap text-right text-xs font-normal text-muted max-sm:hidden tabular-nums">
          Due {dueDateStr}
          {relativeStr && (
            <span className={`block text-xs font-semibold tabular-nums ${status.label === 'Overdue' ? 'text-danger' : 'text-violet'}`}>
              {relativeStr}
            </span>
          )}
        </span>
        <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}>
          {status.label}
        </span>
        <span className="ml-2 inline-flex shrink-0 items-center whitespace-nowrap text-xs font-medium text-violet max-sm:hidden">
          Open <Icon name="arrowUpRight" size={13}/>
        </span>
      </Link>
    );
  }

  return (
    <Link
      href={targetHref}
      className="group flex flex-col justify-between rounded-xl border border-border bg-surface p-4 sm:p-5 text-inherit transition-all duration-150 hover:-translate-y-px hover:border-border-hover hover:shadow-md"
    >
      <div>
        <div className="mb-3 flex items-center justify-between gap-2">
          <span className="max-w-[65%] truncate rounded-md border border-violet-light bg-violet-light/60 px-2 py-0.5 text-xs font-medium text-violet">
            {assignment.course_name || 'Course'}
          </span>
          <span className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}>
            {status.label}
          </span>
        </div>

        <div className="mb-2.5 flex items-start gap-2.5">
          <span className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-xs ${isQuiz ? 'bg-warning-bg text-warning' : 'bg-violet-light text-violet'}`}>
            <Icon name={isQuiz ? 'clipboard' : 'file'} size={15}/>
          </span>
          <span className="min-w-0 flex-1">
            <span className="line-clamp-2 text-sm font-semibold leading-snug text-heading">
              {assignment.title || 'Untitled assignment'}
            </span>
            <span className="mt-1 block text-xs font-medium uppercase tracking-wider text-label">
              {assignment.work_type ? assignment.work_type.replace('_', ' ') : isQuiz ? 'Quiz' : 'Assignment'}
            </span>
          </span>
        </div>
      </div>

      <div className="mt-3.5 border-t border-border-light pt-3">
        <div className="mb-2 flex items-center justify-between gap-2 text-xs text-muted">
          <span className="inline-flex min-w-0 items-center gap-1.5 tabular-nums">
            <Icon name="clock" size={13}/>
            <span className="truncate">{dueDateStr}</span>
          </span>
          {relativeStr && (
            <span className={`shrink-0 text-xs font-semibold tabular-nums ${status.label === 'Overdue' ? 'text-danger' : 'text-violet'}`}>
              {relativeStr}
            </span>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-xs text-subtle">
          <span className="inline-flex min-w-0 items-center gap-1.5 truncate">
            {materialsCount > 0 && <Icon name="paperclip" size={12}/>}
            {materialsCount > 0 ? `${materialsCount} ${materialsCount === 1 ? 'attachment' : 'attachments'}` : 'No attachments'}
          </span>
          <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-violet">
            Open Page <Icon name="arrowUpRight" size={13}/>
          </span>
        </div>
      </div>
    </Link>
  );
}
