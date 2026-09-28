'use client';

import Link from 'next/link';
import { format, isValid, formatDistanceToNow } from 'date-fns';
import Icon from '@/app/dashboard/Icon';

function getStatus(assignment) {
  const state = assignment.submission_state;
  if (state === 'TURNED_IN' || state === 'RETURNED') {
    return { label: 'Submitted', pillClass: 'product-pill success' };
  }
  if (state === 'DRAFT') {
    return { label: 'Draft', pillClass: 'product-pill' };
  }
  if (assignment.due_at && new Date(assignment.due_at) < new Date()) {
    return { label: 'Overdue', pillClass: 'product-pill error' };
  }
  if (assignment.status === 'APPROVED') {
    return { label: 'Approved', pillClass: 'product-pill success' };
  }
  return { label: 'Upcoming', pillClass: 'product-pill warning' };
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
        className="product-row group"
        style={{ textDecoration: 'none', display: 'flex', alignItems: 'center' }}
      >
        <span className="product-icon" aria-hidden="true" style={{ width: 32, height: 32, flex: '0 0 32px' }}>
          <Icon name={isQuiz ? 'clipboard' : 'book'} size={16}/>
        </span>
        <div className="product-row-main">
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <strong style={{ fontSize: 13, color: '#2c2f3c' }}>
              {assignment.title || 'Untitled assignment'}
            </strong>
          </div>
          <small style={{ color: '#858998', fontSize: 11 }}>
            {assignment.course_name || 'Course'}
            {assignment.work_type ? ` · ${assignment.work_type.replace('_', ' ')}` : ''}
          </small>
        </div>
        <span className="product-row-meta" style={{ fontSize: 11, color: '#858998', textAlign: 'right' }}>
          Due {dueDateStr}
          {relativeStr && (
            <span style={{ display: 'block', fontSize: 10, color: status.label === 'Overdue' ? '#b34d4d' : '#6657d9' }}>
              {relativeStr}
            </span>
          )}
        </span>
        <span className={status.pillClass}>{status.label}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#6657d9', marginLeft: 8, whiteSpace: 'nowrap' }}>
          Open <Icon name="arrowUpRight" size={13}/>
        </span>
      </Link>
    );
  }

  // Grid Mode (Rich Surface Card)
  return (
    <Link
      href={targetHref}
      className="surface-card group"
      style={{
        padding: '18px 20px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        transition: 'all 0.15s ease',
        borderRadius: 11,
        textDecoration: 'none',
        color: 'inherit',
      }}
    >
      <div>
        {/* Top bar: Course Pill & Status Badge */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: '#5b4cc6',
              background: '#f4f1ff',
              border: '1px solid #e6e1fb',
              borderRadius: 6,
              padding: '2px 8px',
              maxWidth: '65%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {assignment.course_name || 'Course'}
          </span>
          <span className={status.pillClass} style={{ flexShrink: 0 }}>
            {status.label}
          </span>
        </div>

        {/* Title and Icon */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, marginBottom: 10 }}>
          <span
            style={{
              width: 26,
              height: 26,
              flex: '0 0 26px',
              borderRadius: 7,
              background: isQuiz ? '#fff3e8' : '#f0edff',
              color: isQuiz ? '#d88752' : '#6657d9',
              display: 'grid',
              placeItems: 'center',
              fontSize: 13,
              marginTop: 1,
            }}
          >
            <Icon name={isQuiz ? 'clipboard' : 'file'} size={15}/>
          </span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <h3
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: '#2c2f3b',
                lineHeight: 1.4,
                margin: 0,
                overflow: 'hidden',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
              }}
            >
              {assignment.title || 'Untitled assignment'}
            </h3>
            <span style={{ display: 'block', fontSize: 10, fontWeight: 500, color: '#9a9cab', marginTop: 3, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              {assignment.work_type ? assignment.work_type.replace('_', ' ') : isQuiz ? 'Quiz' : 'Assignment'}
            </span>
          </div>
        </div>
      </div>

      {/* Footer Area: Due Date & Action */}
      <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #f2f2f5' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: '#858998', marginBottom: 8 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <Icon name="clock" size={13}/>
            <span>{dueDateStr}</span>
          </span>
          {relativeStr && (
            <span style={{ fontSize: 10, fontWeight: 600, color: status.label === 'Overdue' ? '#b34d4d' : '#6657d9' }}>
              {relativeStr}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 10, color: '#9a9cab' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>{materialsCount > 0 && <Icon name="paperclip" size={12}/>} {materialsCount > 0 ? `${materialsCount} ${materialsCount === 1 ? 'attachment' : 'attachments'}` : 'No attachments'}</span>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#6657d9', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            Open Page <Icon name="arrowUpRight" size={13}/>
          </span>
        </div>
      </div>
    </Link>
  );
}
