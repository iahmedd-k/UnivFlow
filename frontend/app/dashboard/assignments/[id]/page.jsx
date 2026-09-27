'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@clerk/nextjs';
import Link from 'next/link';
import { format } from 'date-fns';
import { api } from '@/app/lib/api';

export default function AssignmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { getToken } = useAuth();
  const assignmentId = params.id;
  const [assignment, setAssignment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [additionalFiles, setAdditionalFiles] = useState([]);
  const [turningIn, setTurningIn] = useState(false);
  const [solutionStatus, setSolutionStatus] = useState(null);
  const [solutionPolling, setSolutionPolling] = useState(false);
  const [activeTab, setActiveTab] = useState('details');

  useEffect(() => {
    const load = async () => {
      try {
        const token = await getToken();
        const [assignmentData, templatesData] = await Promise.all([
          api.getAssignments(null, token).then(list => list.find(a => a.id == assignmentId)),
          api.getAssignmentTemplates(token),
        ]);
        if (!assignmentData) throw new Error('Assignment not found');
        setAssignment(assignmentData);
        setTemplates(templatesData);
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [assignmentId, getToken]);

  useEffect(() => {
    if (!assignment) return;
    checkSolutionStatus();
  }, [assignment, getToken]);

  const checkSolutionStatus = async () => {
    try {
      const token = await getToken();
      const status = await api.getSolutionStatus(assignment.id, token);
      setSolutionStatus(status);
      if (status.status === 'generating') setSolutionPolling(true);
    } catch (e) {
      console.error('Failed to check solution status:', e);
    }
  };

  useEffect(() => {
    if (!solutionPolling) return;
    const interval = setInterval(checkSolutionStatus, 3000);
    return () => clearInterval(interval);
  }, [solutionPolling, assignment?.id, getToken]);

  const handleTurnIn = async () => {
    setTurningIn(true);
    try {
      const token = await getToken();
      await api.turnInAssignment(assignment.id, { template_id: selectedTemplateId, drive_file_ids: additionalFiles }, token);
      // Refresh assignment
      const list = await api.getAssignments(null, token);
      const updated = list.find(a => a.id == assignmentId);
      if (updated) setAssignment(updated);
    } catch (e) {
      alert('Turn-in failed: ' + e.message);
    } finally {
      setTurningIn(false);
    }
  };

  const handleGenerateSolution = async () => {
    try {
      const token = await getToken();
      await api.generateAssignmentSolution(assignment.id, { provider: 'groq', model: 'openai/gpt-oss-120b' }, token);
      setSolutionPolling(true);
      setSolutionStatus({ status: 'generating' });
    } catch (e) {
      alert('Failed: ' + e.message);
    }
  };

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;
  if (error) return <div className="text-red-600 p-4">Error: {error}</div>;
  if (!assignment) return <div className="p-8 text-center">Assignment not found</div>;

  const dueDate = assignment.due_at ? format(new Date(assignment.due_at), 'MMMM d, yyyy \'at\' h:mm a') : 'No deadline';
  const isOverdue = assignment.due_at && new Date(assignment.due_at) < new Date();
  const isSubmitted = assignment.submission_state === 'TURNED_IN' || assignment.submission_state === 'RETURNED';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link href="/dashboard/assignments" className="text-gray-400 hover:text-gray-600">←</Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{assignment.title}</h1>
            <p className="text-gray-500 mt-1">{assignment.course_name}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            isSubmitted ? 'bg-green-100 text-green-700' :
            isOverdue ? 'bg-red-100 text-red-700' :
            'bg-yellow-100 text-yellow-700'
          }`}>
            {isSubmitted ? 'Submitted' : isOverdue ? 'Overdue' : 'Pending'}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b bg-gray-50">
        {['details', 'materials', 'solution'].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? 'border-indigo-600 text-indigo-600 bg-white'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        {/* Details Tab */}
        {activeTab === 'details' && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Due Date</p>
                <p className={`font-medium ${isOverdue && !isSubmitted ? 'text-red-600' : 'text-gray-900'}`}>
                  {dueDate}
                  {isOverdue && !isSubmitted && <span className="ml-2 text-red-600 text-sm">(Overdue)</span>}
                </p>
              </div>
              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Work Type</p>
                <p className="font-medium text-gray-900">{assignment.work_type || 'ASSIGNMENT'}</p>
              </div>
              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Type</p>
                <p className="font-medium text-gray-900">{assignment.is_quiz ? 'Quiz' : 'Assignment'}</p>
              </div>
            </div>

            {assignment.description && (
              <div className="p-4 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500 mb-2">Description</p>
                <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
                  {assignment.description}
                </div>
              </div>
            )}

            {/* Turn-in Section */}
            {!isSubmitted && (
              <div className="border-t pt-6">
                <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  📤 Turn In Assignment
                </h3>

                <div className="space-y-3 mb-4">
                  <label className="block text-sm font-medium text-gray-700">Select Template</label>
                  {templates.length === 0 ? (
                    <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-yellow-800 text-sm">
                      No templates configured. Create one in <Link href="/dashboard/templates" className="underline">Templates</Link> page.
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {templates.map((t) => (
                        <label key={t.id} className={`flex items-center gap-3 p-3 border rounded-lg cursor-pointer transition-colors ${
                          selectedTemplateId === t.id
                            ? 'border-indigo-500 bg-indigo-50'
                            : 'border-gray-200 hover:border-indigo-300'
                        }`}>
                          <input
                            type="radio"
                            name="template"
                            value={t.id}
                            checked={selectedTemplateId === t.id}
                            onChange={() => setSelectedTemplateId(t.id)}
                            className="text-indigo-600"
                          />
                          <div className="flex-1">
                            <p className="font-medium text-gray-900">{t.name}</p>
                            <p className="text-sm text-gray-500">{t.description || 'No description'}</p>
                            {t.is_default && <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded">Default</span>}
                          </div>
                        </label>
                      ))}
                      <label className="flex items-center gap-3 p-3 border-2 border-dashed border-gray-300 rounded-lg cursor-pointer hover:border-indigo-400">
                        <input type="radio" name="template" value="" checked={!selectedTemplateId} onChange={() => setSelectedTemplateId(null)} className="text-indigo-600" />
                        <span className="text-gray-600">Create blank document (no template)</span>
                      </label>
                    </div>
                  )}
                </div>

                <div className="space-y-3 mb-4">
                  <label className="block text-sm font-medium text-gray-700">Additional Files (optional)</label>
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.doc,.docx,.txt,.py,.js,.ts,.jsx,.tsx,.zip"
                    onChange={(e) => setAdditionalFiles(Array.from(e.target.files).map(f => f.name))}
                    className="w-full px-4 py-2 border border-gray-300 rounded-lg text-sm"
                  />
                  {additionalFiles.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {additionalFiles.map((name, i) => (
                        <span key={i} className="px-2 py-1 bg-gray-100 text-gray-700 text-sm rounded flex items-center gap-1">
                          {name}
                          <button onClick={() => setAdditionalFiles(additionalFiles.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-500">✕</button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <button
                  onClick={handleTurnIn}
                  disabled={turningIn}
                  className="w-full py-3 px-4 bg-indigo-600 text-white font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {turningIn ? 'Submitting...' : 'Submit to Google Classroom'}
                </button>
              </div>
            )}

            {isSubmitted && (
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <div className="flex items-center gap-2 text-green-800">
                  <span>✅</span>
                  <span className="font-medium">Submitted to Google Classroom</span>
                </div>
                <p className="text-sm text-green-700 mt-1">Submission state: {assignment.submission_state}</p>
              </div>
            )}
          </div>
        )}

        {/* Materials Tab */}
        {activeTab === 'materials' && (
          <div className="space-y-4">
            {assignment.materials && assignment.materials.length > 0 ? (
              assignment.materials.map((m, i) => (
                <div key={i} className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
                  <div className="flex items-start gap-3">
                    <div className="p-2 bg-gray-100 rounded-lg">
                      {m.material_type === 'drive_file' ? '📄' : m.material_type === 'link' ? '🔗' : '📎'}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 truncate">{m.title || 'Untitled'}</p>
                      <p className="text-sm text-gray-500 capitalize">{m.material_type?.replace('_', ' ')}</p>
                      {m.url && (
                        <a href={m.url} target="_blank" rel="noopener noreferrer" className="text-sm text-indigo-600 hover:underline mt-1 inline-block">
                          Open in Google Classroom →
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="text-center py-12 text-gray-500">
                No materials attached to this assignment.
              </div>
            )}
          </div>
        )}

        {/* Solution Tab */}
        {activeTab === 'solution' && (
          <div className="space-y-4">
            {!solutionStatus || solutionStatus.status === 'not_started' ? (
              <div className="text-center py-12">
                <div className="text-6xl mb-4">🤖</div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">AI Solution Generator</h3>
                <p className="text-gray-500 mb-6">Generate a complete AI-powered solution for this assignment using Groq.</p>
                <button
                  onClick={handleGenerateSolution}
                  disabled={solutionPolling}
                  className="px-6 py-3 bg-gradient-to-r from-purple-600 to-pink-600 text-white font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                >
                  {solutionPolling ? 'Generating...' : 'Generate AI Solution'}
                </button>
              </div>
            ) : solutionStatus.status === 'generating' ? (
              <div className="text-center py-12">
                <div className="inline-block animate-spin text-4xl mb-4">⏳</div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Generating Solution...</h3>
                <p className="text-gray-500">This may take 30-60 seconds. Polling for completion...</p>
                <div className="w-64 mx-auto mt-4 h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div className="h-full bg-gradient-to-r from-purple-600 to-pink-600 animate-pulse" style={{ width: '100%' }} />
                </div>
              </div>
            ) : solutionStatus.status === 'completed' ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-gray-900">AI Solution</h3>
                  <span className="px-2 py-1 text-xs bg-green-100 text-green-700 rounded-full">Validated</span>
                </div>
                <div className="prose prose-sm max-w-none bg-gray-50 p-6 rounded-lg">
                  {solutionStatus.validated_content || solutionStatus.draft_content}
                </div>
                <div className="flex gap-2">
                  <button className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">Copy</button>
                  <button onClick={handleGenerateSolution} className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">Regenerate</button>
                </div>
              </div>
            ) : (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <h3 className="font-medium text-red-800 mb-2">Generation Failed</h3>
                <p className="text-sm text-red-700">{solutionStatus.validation_errors || 'Unknown error'}</p>
                <button onClick={handleGenerateSolution} className="mt-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">Retry</button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}