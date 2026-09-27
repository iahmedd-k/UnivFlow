'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import AssignmentCard from './AssignmentCard';

const statusFilters = ['all', 'missing', 'assignments', 'quizzes', 'open', 'submitted'];

export default function AssignmentsPage() {
  const { getToken } = useAuth();
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const data = await api.getAssignments(filter === 'all' ? null : filter, token);
        setAssignments(data);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [getToken, filter]);

  const handleTurnIn = async (assignmentId) => {
    // Navigation happens via link, this is for any additional handling
    console.log('Turn in clicked for', assignmentId);
  };

  const handleGenerateSolution = async (assignmentId) => {
    // Navigation happens via link
    console.log('Generate solution clicked for', assignmentId);
  };

  const filteredAssignments = assignments;

  if (loading) return <div className="flex items-center justify-center h-64">Loading assignments...</div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Assignments</h1>
          <p className="text-gray-500 mt-1">Manage, review, and track course deliverables</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {statusFilters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? 'bg-indigo-600 text-white'
                : 'bg-white text-gray-600 hover:bg-gray-100 border border-gray-200'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Assignments List */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {filteredAssignments.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            No assignments found for this filter.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {filteredAssignments.map((assignment) => (
              <AssignmentCard
                key={assignment.id}
                assignment={assignment}
                onTurnIn={handleTurnIn}
                onGenerateSolution={handleGenerateSolution}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}