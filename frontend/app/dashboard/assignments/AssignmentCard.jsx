import Link from 'next/link';
import { format } from 'date-fns';

function getStatusBadge(status, submissionState) {
  if (submissionState === 'TURNED_IN' || submissionState === 'RETURNED') {
    return <span className="px-2 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full">Submitted</span>;
  }
  if (submissionState === 'DRAFT') {
    return <span className="px-2 py-1 text-xs font-medium bg-blue-100 text-blue-700 rounded-full">Draft</span>;
  }
  switch (status) {
    case 'PENDING':
      return <span className="px-2 py-1 text-xs font-medium bg-yellow-100 text-yellow-700 rounded-full">Pending</span>;
    case 'OVERDUE':
      return <span className="px-2 py-1 text-xs font-medium bg-red-100 text-red-700 rounded-full">Overdue</span>;
    case 'APPROVED':
      return <span className="px-2 py-1 text-xs font-medium bg-green-100 text-green-700 rounded-full">Approved</span>;
    case 'DRAFT':
      return <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded-full">Draft</span>;
    default:
      return <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded-full">{status}</span>;
  }
}

function isOverdue(dueAt) {
  if (!dueAt) return false;
  return new Date(dueAt) < new Date();
}

export default function AssignmentCard({ assignment, onTurnIn, onGenerateSolution }) {
  const dueDate = assignment.due_at ? format(new Date(assignment.due_at), 'MMM d, yyyy HH:mm') : 'No deadline';
  const overdue = isOverdue(assignment.due_at);
  const isSubmitted = assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED';
  const hasNoDeadline = !assignment.due_at;

  return (
    <Link
      href={`/dashboard/assignments/${assignment.id}`}
      className="block px-6 py-4 hover:bg-gray-50 transition-colors flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-3">
          <div className={`p-2 rounded-lg ${assignment.is_quiz ? 'bg-purple-100' : 'bg-indigo-100'}`}>
            {assignment.is_quiz ? '❓' : '📝'}
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold text-gray-900 truncate">{assignment.title}</h3>
            <p className="text-sm text-gray-500 mt-1">{assignment.course_name}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 mt-3 text-sm">
          <span className="flex items-center gap-1 text-gray-500">
            📅 {dueDate}
            {overdue && !hasNoDeadline && !isSubmitted && (
              <span className="text-red-600 font-medium">(Overdue)</span>
            )}
          </span>
          {assignment.work_type && <span className="text-gray-400">•</span>}
          {assignment.work_type && <span className="text-gray-500">{assignment.work_type}</span>}
        </div>
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 sm:ml-4">
        {getStatusBadge(assignment.status, assignment.submission_state)}

        {!isSubmitted && !hasNoDeadline && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onTurnIn(assignment.id);
            }}
            className="px-3 py-1.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Turn In
          </button>
        )}

        {!isSubmitted && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onGenerateSolution(assignment.id);
            }}
            className="px-3 py-1.5 text-sm font-medium bg-gradient-to-r from-purple-600 to-pink-600 text-white rounded-lg hover:opacity-90 transition-opacity"
          >
            🤖 AI Solution
          </button>
        )}

        {isSubmitted && (
          <span className="px-3 py-1.5 text-sm font-medium bg-green-100 text-green-700 rounded-lg">
            Submitted
          </span>
        )}

        <span className="text-gray-300 ml-auto sm:ml-0">→</span>
      </div>
    </Link>
  );
}