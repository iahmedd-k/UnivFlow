'use client';

import { useCallback, useEffect, useState } from 'react';
import { useAuth, useUser } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import Icon from '@/app/dashboard/Icon';

const TEMPLATE_PLACEHOLDERS = [
  { tag: '{{STUDENT_NAME}}', label: 'Student Name', sample: 'Ahmed Khan', desc: 'Full name of the student' },
  { tag: '{{ROLL_NO}}', label: 'Roll Number / ID', sample: '210982', desc: 'University Roll number or Student ID' },
  { tag: '{{CLASS}}', label: 'Class / Section', sample: 'BS CS - Section 4A', desc: 'Degree program, semester or class section' },
  { tag: '{{SUBJECT_NAME}}', label: 'Subject Name', sample: 'Artificial Intelligence & Neural Networks', desc: 'Course title / Subject' },
  { tag: '{{COURSE_CODE}}', label: 'Course Code', sample: 'CS-401', desc: 'Official course code' },
  { tag: '{{ASSIGNMENT_TITLE}}', label: 'Assignment / Report', sample: 'Lab Report 04 - NLP Transformers', desc: 'Assignment or lab report title' },
  { tag: '{{INSTRUCTOR_NAME}}', label: 'Instructor / Professor', sample: 'Dr. Muhammad Tariq', desc: 'Faculty instructor or supervisor' },
  { tag: '{{SUBMISSION_DATE}}', label: 'Submission Date', sample: 'September 27, 2026', desc: 'Formatted submission timestamp' },
  { tag: '{{UNIVERSITY_NAME}}', label: 'University Name', sample: 'AIR UNIVERSITY, ISLAMABAD', desc: 'University / institution name' },
  { tag: '{{SOLUTION_CONTENT}}', label: 'Report / Solution Body', sample: 'Auto-generated assignment answer & analysis', desc: 'Main report findings, methodology, and solutions' },
];

export default function TemplatesPage() {
  const { getToken } = useAuth();
  const { user } = useUser();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [copiedTag, setCopiedTag] = useState(null);

  // Search & Form
  const [driveDocs, setDriveDocs] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [docUrlInput, setDocUrlInput] = useState('');
  const [searching, setSearching] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);

  const [formData, setFormData] = useState({
    name: '', description: '', google_doc_id: '', google_drive_file_id: '', is_default: false,
  });

  // Simulator preview data
  const [previewData, setPreviewData] = useState({
    studentName: user?.fullName || 'Ahmed Khan',
    rollNo: '210982',
    className: 'BS CS - Section A',
    subjectName: 'Distributed Systems & Cloud Computing',
    assignmentTitle: 'Assignment 02 - Microservices Architecture',
    instructorName: 'Prof. Dr. Kashif Munir',
    universityName: 'AIR UNIVERSITY, ISLAMABAD',
    submissionDate: new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
    solutionSnippet: '1. Executive Summary & Architecture Overview\n\nThis report presents the distributed consensus mechanism, load balancing metrics, and microservice decoupling strategy implemented for the university capstone project...',
  });

  const loadTemplates = useCallback(async () => {
    try {
      const token = await getToken();
      const data = await api.getAssignmentTemplates(token);
      setTemplates(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  const extractDocIdFromUrl = (urlOrId) => {
    if (!urlOrId) return '';
    const trimmed = urlOrId.trim();
    // Check if full Google Doc URL
    const match = trimmed.match(/\/d\/([a-zA-Z0-9-_]+)/);
    if (match && match[1]) {
      return match[1];
    }
    return trimmed;
  };

  const handleUrlInputChange = (val) => {
    setDocUrlInput(val);
    const docId = extractDocIdFromUrl(val);
    if (docId) {
      setFormData((prev) => ({
        ...prev,
        google_doc_id: docId,
        google_drive_file_id: docId,
      }));
    }
  };

  const handleSearchDrive = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const token = await getToken();
      const data = await api.listDriveDocsForTemplates(searchQuery, token);
      setDriveDocs(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setSearching(false);
    }
  };

  const handleSelectDoc = (doc) => {
    setSelectedDoc(doc);
    setFormData({
      ...formData,
      name: doc.name,
      google_doc_id: doc.id,
      google_drive_file_id: doc.id,
    });
    setDocUrlInput(`https://docs.google.com/document/d/${doc.id}/edit`);
    setDriveDocs([]);
    setSearchQuery('');
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    const docId = extractDocIdFromUrl(formData.google_doc_id || docUrlInput);
    if (!formData.name || !docId) {
      alert('Template Name and a valid Google Doc ID or URL are required.');
      return;
    }
    setCreating(true);
    try {
      const token = await getToken();
      await api.createAssignmentTemplate(
        {
          ...formData,
          google_doc_id: docId,
          google_drive_file_id: docId,
        },
        token
      );
      setShowCreate(false);
      setFormData({
        name: '',
        description: '',
        google_doc_id: '',
        google_drive_file_id: '',
        is_default: false,
      });
      setDocUrlInput('');
      setSelectedDoc(null);
      await loadTemplates();
    } catch (e) {
      alert('Failed to create template: ' + e.message);
    } finally {
      setCreating(false);
    }
  };

  const handleSetDefault = async (templateId) => {
    try {
      const token = await getToken();
      await api.setDefaultTemplate(templateId, token);
      loadTemplates();
    } catch (e) {
      alert('Failed to set default: ' + e.message);
    }
  };

  const handleDelete = async (templateId) => {
    if (!confirm('Are you sure you want to remove this template?')) return;
    try {
      const token = await getToken();
      await api.deleteAssignmentTemplate(templateId, token);
      loadTemplates();
    } catch (e) {
      alert('Failed to delete: ' + e.message);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopiedTag(text);
    setTimeout(() => setCopiedTag(null), 2000);
  };

  const loadAirUniversityPreset = () => {
    const createStarter = async () => {
      setCreating(true); setError(null);
      try {
        const token = await getToken();
        await api.createStarterAssignmentTemplate(token);
        setShowCreate(false);
        await loadTemplates();
      } catch (e) { setError(e.message || 'Could not create the starter report template.'); }
      finally { setCreating(false); }
    };
    createStarter();
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-80 space-y-3">
        <div className="w-10 h-10 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin"></div>
        <p className="text-gray-500 font-medium">Loading templates...</p>
      </div>
    );
  }

  const defaultTemplate = templates.find((t) => t.is_default) || templates[0];

  return (
    <div className="max-w-7xl mx-auto space-y-8 pb-12">
      {/* Top Banner Header */}
      <div className="bg-gradient-to-r from-indigo-900 via-indigo-800 to-blue-900 rounded-3xl p-8 text-white shadow-xl relative overflow-hidden">
        <div className="absolute right-0 top-0 bottom-0 w-1/3 bg-white/5 skew-x-12 pointer-events-none transform translate-x-12"></div>
        <div className="relative z-10 flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 bg-indigo-500/30 rounded-full text-indigo-200 text-xs font-semibold backdrop-blur-sm border border-indigo-400/30">
              <Icon name="graduation" size={16}/>
              <span>Report & Assignment Cover Engine</span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight">Google Docs Report Templates</h1>
            <p className="text-indigo-200 text-sm md:text-base leading-relaxed">
              Choose the cover page used for AI-generated assignment reports. Uniflow copies the document and fills the supported fields before adding the solution.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => setShowPreviewModal(true)}
              className="px-4 py-2.5 bg-white/10 hover:bg-white/20 text-white font-medium rounded-xl backdrop-blur-sm border border-white/20 transition-all flex items-center gap-2 shadow-sm text-sm"
            >
              <Icon name="eye" size={15}/>
              <span>Preview Live Fill</span>
            </button>
            <button
              onClick={() => {
                setFormData({
                  name: '',
                  description: '',
                  google_doc_id: '',
                  google_drive_file_id: '',
                  is_default: false,
                });
                setDocUrlInput('');
                setShowCreate(true);
              }}
              className="px-5 py-2.5 bg-indigo-500 hover:bg-indigo-400 text-white font-semibold rounded-xl shadow-lg hover:shadow-indigo-500/30 transition-all flex items-center gap-2 text-sm"
            >
              <Icon name="fileAdd" size={15}/>
              <span>Add New Template</span>
            </button>
          </div>
        </div>
      </div>

      {/* Featured Primary Template Card */}
      <div className="bg-white rounded-2xl border border-gray-200/80 shadow-sm p-6 hover:shadow-md transition-shadow">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6 pb-6 border-b border-gray-100">
          <div className="flex items-start gap-4">
            <div className="w-14 h-14 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-3xl shadow-inner shrink-0">
              <Icon name="file" size={19}/>
            </div>
            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <h2 className="text-xl font-bold text-gray-900">
                  {defaultTemplate ? defaultTemplate.name : 'No report template yet'}
                </h2>
                {defaultTemplate && <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-100 text-emerald-800 rounded-full border border-emerald-200 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Active Default Template
                </span>}
              </div>
              <p className="text-gray-600 text-sm mt-1">
                {defaultTemplate?.description || 'Create an editable report cover in your connected Google Drive to get started.'}
              </p>
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 font-mono">
                {defaultTemplate && <span>Doc ID: {defaultTemplate.google_doc_id}</span>}
                <span className="text-gray-300">•</span>
                <span className="text-gray-500">Private to your Google Drive</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {defaultTemplate && <a
              href={`https://docs.google.com/document/d/${defaultTemplate.google_doc_id}/edit`}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-gray-50 hover:bg-gray-100 text-gray-700 font-medium rounded-xl border border-gray-200 transition-colors flex items-center gap-2 text-sm"
            >
              <Icon name="link" size={15}/>
              <span>Open in Google Docs</span>
            </a>}
            <button
              onClick={() => setShowPreviewModal(true)}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl shadow-sm transition-colors flex items-center gap-2 text-sm"
            >
              <Icon name="sparkles" size={15}/>
              <span>Test Auto-Fill</span>
            </button>
          </div>
        </div>

        {/* Visual Template Structure Blueprint */}
        <div className="mt-6">
          <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3">Cover Page Layout Preview</h3>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-gray-50/70 p-4 rounded-xl border border-gray-200/60 text-xs">
            <div className="p-3 bg-white rounded-lg border border-gray-200 shadow-2xs space-y-1">
              <span className="font-semibold text-indigo-700 block">1. Header</span>
              <p className="text-gray-800 font-medium">SUBJECT Name</p>
              <p className="text-gray-500">Assignment No.</p>
            </div>
            <div className="p-3 bg-white rounded-lg border border-gray-200 shadow-2xs space-y-1">
              <span className="font-semibold text-indigo-700 block">2. Student Details</span>
              <p className="text-gray-800 font-medium">Submitted by: {'{{STUDENT_NAME}}'}</p>
              <p className="text-gray-500">Roll No: {'{{ROLL_NO}}'}</p>
              <p className="text-gray-500">CLASS: {'{{CLASS}}'}</p>
            </div>
            <div className="p-3 bg-white rounded-lg border border-gray-200 shadow-2xs space-y-1">
              <span className="font-semibold text-indigo-700 block">3. Faculty Details</span>
              <p className="text-gray-800 font-medium">Submitted to: {'{{INSTRUCTOR_NAME}}'}</p>
              <p className="text-gray-500">Dated: {'{{SUBMISSION_DATE}}'}</p>
            </div>
            <div className="p-3 bg-white rounded-lg border border-gray-200 shadow-2xs space-y-1">
              <span className="font-semibold text-indigo-700 block">4. Institution & Body</span>
              <p className="text-gray-800 font-medium">AIR UNIVERSITY, ISLAMABAD</p>
              <p className="text-gray-500">{'{{SOLUTION_CONTENT}}'}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Dynamic Placeholder Reference Guide */}
      <div className="bg-white rounded-2xl border border-gray-200/80 shadow-sm p-6 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <div>
            <h3 className="text-lg font-bold text-gray-900">Supported Template Variables</h3>
            <p className="text-sm text-gray-500">
              Click a tag to copy it into your Google Doc. The AI export fills student name, email, course, assignment, instructor, date, and report content. Roll number, degree program, and university are not currently collected, so those tags remain blank.
            </p>
          </div>
          {copiedTag && (
            <span className="animate-pulse rounded-full border border-brand-border bg-brand-bg px-3 py-1.5 text-xs font-semibold text-brand-hover">
              <Icon name="check" size={13}/> Copied {copiedTag}
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 pt-2">
          {TEMPLATE_PLACEHOLDERS.map((ph) => (
            <button
              key={ph.tag}
              onClick={() => copyToClipboard(ph.tag)}
              className="p-3.5 bg-gray-50/80 hover:bg-indigo-50/50 hover:border-indigo-200 rounded-xl border border-gray-200/80 text-left transition-all group flex flex-col justify-between"
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <code className="font-mono font-bold text-indigo-700 text-xs bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100 group-hover:bg-indigo-100 transition-colors">
                  {ph.tag}
                </code>
                <span className="text-xs text-gray-400 group-hover:text-indigo-600 transition-colors font-medium">Copy</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-800">{ph.label}</p>
                <p className="text-2xs text-gray-500 mt-0.5">{ph.desc}</p>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Available Templates Catalog */}
      <div className="bg-white rounded-2xl border border-gray-200/80 shadow-sm overflow-hidden">
        <div className="p-6 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-gray-900">All Registered Templates</h3>
            <p className="text-sm text-gray-500">Manage custom Google Doc templates configured for your account.</p>
          </div>
          <button
            onClick={loadAirUniversityPreset}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors border border-indigo-200"
          >
            {creating ? 'Creating…' : '+ Create starter report template'}
          </button>
        </div>

        {templates.length === 0 ? (
          <div className="p-12 text-center space-y-4">
            <div className="text-indigo-600"><Icon name="files" size={34}/></div>
            <h4 className="text-base font-semibold text-gray-900">No templates found</h4>
            <p className="text-sm text-gray-500 max-w-sm mx-auto">
              Create a starter report in your connected Drive or register an existing Google Doc.
            </p>
            <button
              onClick={loadAirUniversityPreset}
              className="px-5 py-2.5 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 transition-colors shadow-sm"
            >
              {creating ? 'Creating…' : 'Create starter report template'}
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {templates.map((t) => (
              <div
                key={t.id}
                className="p-5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 hover:bg-gray-50/60 transition-colors"
              >
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl bg-indigo-100/60 border border-indigo-200 flex items-center justify-center text-xl shrink-0 mt-0.5">
                    <Icon name="files" size={19}/>
                  </div>
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h4 className="font-semibold text-gray-900 text-base">{t.name}</h4>
                      {t.is_default && (
                        <span className="px-2 py-0.5 text-2xs font-bold uppercase tracking-wide bg-indigo-100 text-indigo-800 rounded-md">
                          Default
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{t.description || 'No description provided'}</p>
                    <div className="flex items-center gap-3 text-2xs text-gray-400 font-mono">
                      <span>Doc ID: {t.google_doc_id}</span>
                      <a
                        href={`https://docs.google.com/document/d/${t.google_doc_id}/edit`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-indigo-600 hover:underline"
                      >
                        View Google Doc <Icon name="externalLink" size={12}/>
                      </a>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {!t.is_default && (
                    <button
                      onClick={() => handleSetDefault(t.id)}
                      className="px-3 py-1.5 text-xs font-medium bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors"
                    >
                      Make Default
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(t.id)}
                    className="px-3 py-1.5 text-xs font-medium bg-red-50 hover:bg-red-100 text-red-600 rounded-lg transition-colors"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add / Create Template Modal */}
      {showCreate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs"
          onClick={() => setShowCreate(false)}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl max-w-xl w-full max-h-[90vh] overflow-y-auto border border-gray-100"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-5 border-b sticky top-0 bg-white z-10">
              <div className="flex items-center gap-2">
                <Icon name="fileAdd" size={17}/>
                <h2 className="text-lg font-bold text-gray-900">Add Google Doc Template</h2>
              </div>
              <button
                onClick={() => setShowCreate(false)}
                className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center text-gray-400 hover:text-gray-600 transition-colors"
              >
                <Icon name="close" size={15}/>
              </button>
            </div>

            <form onSubmit={handleCreate} className="p-6 space-y-5">
              {/* Presets Button */}
              <div className="p-3 bg-indigo-50/60 rounded-xl border border-indigo-100 flex items-center justify-between">
                <div>
                  <p className="text-xs font-bold text-indigo-900">Create a starter report document</p>
                  <p className="text-2xs text-indigo-700">Creates a real editable template in your Google Drive.</p>
                </div>
                <button
                  type="button"
                  onClick={loadAirUniversityPreset}
                  className="px-2.5 py-1 text-xs font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
                >
                  Create
                </button>
              </div>

              {/* Paste Google Doc URL or ID */}
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-700 mb-1.5">
                  Google Doc URL or Document ID *
                </label>
                <input
                  type="text"
                  value={docUrlInput || formData.google_doc_id}
                  onChange={(e) => handleUrlInputChange(e.target.value)}
                  placeholder="https://docs.google.com/document/d/10Le2mgUnelQtxh8.../edit"
                  className="w-full px-3.5 py-2.5 border border-gray-300 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                  required
                />
                <p className="text-2xs text-gray-400 mt-1">
                  Make sure the Google Doc sharing is set to &ldquo;Anyone with the link can view&rdquo;.
                </p>
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-700 mb-1.5">
                  Template Name *
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g., Air University Report Template"
                  className="w-full px-3.5 py-2.5 border border-gray-300 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-700 mb-1.5">
                  Description
                </label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Brief description of this template layout..."
                  rows={2}
                  className="w-full px-3.5 py-2.5 border border-gray-300 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Search Google Drive Option */}
              <div className="pt-2 border-t border-gray-100">
                <label className="block text-xs font-bold uppercase tracking-wider text-gray-700 mb-1.5">
                  Or Search From Connected Google Drive
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), handleSearchDrive())}
                    placeholder="Search docs in your Drive..."
                    className="flex-1 px-3.5 py-2 border border-gray-300 rounded-xl text-sm"
                  />
                  <button
                    type="button"
                    onClick={handleSearchDrive}
                    disabled={searching}
                    className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 font-medium rounded-xl text-xs disabled:opacity-50"
                  >
                    {searching ? 'Searching...' : 'Search Drive'}
                  </button>
                </div>

                {driveDocs.length > 0 && (
                  <div className="mt-2 max-h-40 overflow-y-auto border border-gray-200 rounded-xl divide-y divide-gray-100">
                    {driveDocs.map((doc) => (
                      <button
                        key={doc.id}
                        type="button"
                        onClick={() => handleSelectDoc(doc)}
                        className="w-full px-3 py-2 text-left hover:bg-indigo-50 flex items-center justify-between text-xs"
                      >
                        <span className="font-medium text-gray-800 truncate">{doc.name}</span>
                        <span className="text-indigo-600 shrink-0 font-semibold ml-2">Select</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="is_default_check"
                  checked={formData.is_default}
                  onChange={(e) => setFormData({ ...formData, is_default: e.target.checked })}
                  className="w-4 h-4 text-indigo-600 rounded border-gray-300 focus:ring-indigo-500"
                />
                <label htmlFor="is_default_check" className="text-xs font-medium text-gray-700">
                  Set as default template for automatic report generation
                </label>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="px-4 py-2.5 border border-gray-300 text-gray-700 font-medium rounded-xl hover:bg-gray-50 text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl text-sm shadow-sm disabled:opacity-50"
                >
                  {creating ? 'Saving...' : 'Save Template'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Live Fill Simulator Modal */}
      {showPreviewModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs"
          onClick={() => setShowPreviewModal(false)}
        >
          <div
            className="bg-white rounded-3xl shadow-2xl max-w-4xl w-full max-h-[92vh] overflow-hidden border border-gray-200 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-5 border-b border-gray-100 flex items-center justify-between bg-gray-50/60">
              <div className="flex items-center gap-2">
              <Icon name="sparkles" size={17}/>
                <div>
                  <h3 className="font-bold text-gray-900 text-base">Live Template Auto-Fill Simulator</h3>
                  <p className="text-2xs text-gray-500">
                    Preview sample data only. The live report uses the connected profile and assignment details available to Uniflow.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowPreviewModal(false)}
                className="w-8 h-8 rounded-full hover:bg-gray-200 flex items-center justify-center text-gray-400 hover:text-gray-600"
              >
                <Icon name="close" size={15}/>
              </button>
            </div>

            {/* Modal Body: Two Columns */}
            <div className="flex-1 overflow-y-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Left Column: Student & Course Inputs */}
              <div className="lg:col-span-5 space-y-3.5 bg-gray-50/60 p-4 rounded-2xl border border-gray-200/80">
                <h4 className="text-xs font-bold uppercase tracking-wider text-gray-700">User & Subject Parameters</h4>

                <div>
                  <label className="block text-2xs font-semibold text-gray-600 mb-1">Student Full Name</label>
                  <input
                    type="text"
                    value={previewData.studentName}
                    onChange={(e) => setPreviewData({ ...previewData, studentName: e.target.value })}
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-2xs font-semibold text-gray-600 mb-1">Roll No / ID</label>
                    <input
                      type="text"
                      value={previewData.rollNo}
                      onChange={(e) => setPreviewData({ ...previewData, rollNo: e.target.value })}
                      className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-2xs font-semibold text-gray-600 mb-1">Class / Section</label>
                    <input
                      type="text"
                      value={previewData.className}
                      onChange={(e) => setPreviewData({ ...previewData, className: e.target.value })}
                      className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-2xs font-semibold text-gray-600 mb-1">Subject / Course Name</label>
                  <input
                    type="text"
                    value={previewData.subjectName}
                    onChange={(e) => setPreviewData({ ...previewData, subjectName: e.target.value })}
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                  />
                </div>

                <div>
                  <label className="block text-2xs font-semibold text-gray-600 mb-1">Assignment / Report Title</label>
                  <input
                    type="text"
                    value={previewData.assignmentTitle}
                    onChange={(e) => setPreviewData({ ...previewData, assignmentTitle: e.target.value })}
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                  />
                </div>

                <div>
                  <label className="block text-2xs font-semibold text-gray-600 mb-1">Instructor / Professor</label>
                  <input
                    type="text"
                    value={previewData.instructorName}
                    onChange={(e) => setPreviewData({ ...previewData, instructorName: e.target.value })}
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                  />
                </div>

                <div>
                  <label className="block text-2xs font-semibold text-gray-600 mb-1">University Name</label>
                  <input
                    type="text"
                    value={previewData.universityName}
                    onChange={(e) => setPreviewData({ ...previewData, universityName: e.target.value })}
                    className="w-full px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-lg"
                  />
                </div>
              </div>

              {/* Right Column: Realistic Document Preview */}
              <div className="lg:col-span-7 bg-white border border-gray-300 rounded-2xl p-8 shadow-inner font-serif text-center space-y-6 select-none relative">
                <div className="absolute top-3 right-3 text-2xs font-sans font-semibold bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                  Doc Preview
                </div>

                {/* Subject Title */}
                <div className="space-y-1 pt-4">
                  <h2 className="text-xl font-bold text-gray-900 tracking-wide">{previewData.subjectName}</h2>
                  <p className="text-base font-semibold text-gray-700">{previewData.assignmentTitle}</p>
                </div>

                {/* University Emblem Placeholder / Visual */}
                <div className="w-24 h-24 mx-auto rounded-full bg-gradient-to-tr from-indigo-900 to-blue-800 flex items-center justify-center text-white text-3xl shadow-md border-4 border-indigo-100">
                  <Icon name="school" size={34} strokeWidth={1.5}/>
                </div>

                {/* Student Details */}
                <div className="space-y-1">
                  <h3 className="text-sm font-bold underline text-gray-900 uppercase">Submitted by:</h3>
                  <p className="text-base font-bold text-indigo-950">{previewData.studentName}</p>
                  <p className="text-sm text-gray-700">Roll No: <span className="font-semibold">{previewData.rollNo}</span></p>
                  <p className="text-sm text-gray-700">CLASS: <span className="font-semibold">{previewData.className}</span></p>
                </div>

                {/* Faculty Details */}
                <div className="space-y-1 pt-2">
                  <h3 className="text-sm font-bold underline text-gray-900 uppercase">Submitted to:</h3>
                  <p className="text-sm font-medium italic text-gray-800">{previewData.instructorName}</p>
                  <p className="text-xs text-gray-600">Dated: {previewData.submissionDate}</p>
                </div>

                {/* University Bottom */}
                <div className="pt-4 border-t border-gray-200">
                  <p className="text-xs font-bold tracking-widest text-gray-900 uppercase">{previewData.universityName}</p>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-4 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
              <span className="text-2xs text-gray-500">
                  The AI solver copies the selected default document into Google Drive when export is enabled.
              </span>
              <div className="flex items-center gap-3">
                {defaultTemplate && <a href={`https://docs.google.com/document/d/${defaultTemplate.google_doc_id}/edit`} target="_blank" rel="noreferrer" className="px-4 py-2 text-xs font-medium text-indigo-600 hover:text-indigo-800 inline-flex items-center gap-1">Open report template <Icon name="externalLink" size={12}/></a>}
                <button
                  onClick={() => setShowPreviewModal(false)}
                  className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl text-xs"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
