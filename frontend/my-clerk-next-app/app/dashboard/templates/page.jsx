'use client';

import { useEffect, useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';

export default function TemplatesPage() {
  const { getToken } = useAuth();
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [driveDocs, setDriveDocs] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    google_doc_id: '',
    google_drive_file_id: '',
    is_default: false,
  });

  useEffect(() => {
    loadTemplates();
  }, [getToken]);

  const loadTemplates = async () => {
    try {
      const token = await getToken();
      const data = await api.getAssignmentTemplates(token);
      setTemplates(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchDrive = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const token = await getToken();
      const data = await api.listDriveDocsForTemplates(searchQuery, token);
      setDriveDocs(data);
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
    setDriveDocs([]);
    setSearchQuery('');
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!formData.name || !formData.google_doc_id) {
      alert('Name and Google Doc ID are required');
      return;
    }
    setCreating(true);
    try {
      const token = await getToken();
      await api.createAssignmentTemplate(formData, token);
      setShowCreate(false);
      setFormData({ name: '', description: '', google_doc_id: '', google_drive_file_id: '', is_default: false });
      setSelectedDoc(null);
      loadTemplates();
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
    if (!confirm('Delete this template?')) return;
    try {
      const token = await getToken();
      await api.deleteAssignmentTemplate(templateId, token);
      loadTemplates();
    } catch (e) {
      alert('Failed to delete: ' + e.message);
    }
  };

  if (loading) return <div className="flex items-center justify-center h-64">Loading...</div>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Assignment Templates</h1>
          <p className="text-gray-500 mt-1">Manage Google Doc templates for student turn-ins</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + Create Template
        </button>
      </div>

      {/* Templates List */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        {templates.length === 0 ? (
          <div className="p-12 text-center">
            <div className="text-4xl mb-4">📋</div>
            <h3 className="text-lg font-medium text-gray-900 mb-2">No templates yet</h3>
            <p className="text-gray-500 mb-6">Create your first template from a Google Doc</p>
            <button
              onClick={() => setShowCreate(true)}
              className="px-6 py-3 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
            >
              Create Template
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {templates.map((t) => (
              <div key={t.id} className="px-6 py-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div className="flex items-start gap-4">
                  <div className="p-3 bg-indigo-100 rounded-lg">📋</div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-gray-900">{t.name}</h3>
                      {t.is_default && (
                        <span className="px-2 py-0.5 text-xs bg-indigo-100 text-indigo-700 rounded">Default</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500 mt-1">{t.description || 'No description'}</p>
                    <p className="text-xs text-gray-400 mt-1">Doc ID: {t.google_doc_id}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {!t.is_default && (
                    <button
                      onClick={() => handleSetDefault(t.id)}
                      className="px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                    >
                      Set Default
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(t.id)}
                    className="px-3 py-1.5 text-sm bg-red-50 text-red-600 rounded-lg hover:bg-red-100"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create Template Modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={() => setShowCreate(false)}>
          <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b sticky top-0 bg-white z-10">
              <h2 className="text-lg font-semibold">Create Template</h2>
              <button onClick={() => setShowCreate(false)} className="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            <form onSubmit={handleCreate} className="p-6 space-y-4">
              {/* Search Drive */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Search Google Drive for Docs</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSearchDrive()}
                    placeholder="Search for a Google Doc..."
                    className="flex-1 px-4 py-2 border border-gray-300 rounded-lg"
                  />
                  <button
                    type="button"
                    onClick={handleSearchDrive}
                    disabled={searching}
                    className="px-4 py-2 bg-indigo-600 text-white rounded-lg disabled:opacity-50"
                  >
                    {searching ? 'Searching...' : 'Search'}
                  </button>
                </div>

                {driveDocs.length > 0 && (
                  <div className="mt-3 max-h-64 overflow-y-auto border border-gray-200 rounded-lg">
                    {driveDocs.map((doc) => (
                      <button
                        key={doc.id}
                        type="button"
                        onClick={() => handleSelectDoc(doc)}
                        className="w-full px-4 py-3 text-left hover:bg-gray-50 border-t border-gray-100 first:border-0 flex items-center gap-3"
                      >
                        <span className="text-lg">📄</span>
                        <div className="flex-1 text-left">
                          <p className="font-medium text-gray-900 truncate">{doc.name}</p>
                          <p className="text-xs text-gray-500">Modified: {doc.modifiedTime ? new Date(doc.modifiedTime).toLocaleDateString() : 'Unknown'}</p>
                        </div>
                        <span className="text-green-600 text-sm">Select</span>
                      </button>
                    ))}
                  </div>
                )}

                {selectedDoc && (
                  <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
                    <div>
                      <p className="font-medium text-green-800">Selected: {selectedDoc.name}</p>
                      <p className="text-sm text-green-700">Doc ID: {selectedDoc.id}</p>
                    </div>
                    <button type="button" onClick={() => setSelectedDoc(null)} className="text-green-600 hover:text-green-800">Change</button>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Template Name *</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({...formData, name: e.target.value})}
                  placeholder="e.g., Lab Report Template"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({...formData, description: e.target.value})}
                  placeholder="Optional description..."
                  rows={3}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg"
                />
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="is_default"
                  checked={formData.is_default}
                  onChange={(e) => setFormData({...formData, is_default: e.target.checked})}
                  className="text-indigo-600"
                />
                <label htmlFor="is_default" className="text-sm text-gray-700">Set as default template</label>
              </div>

              <div className="flex justify-end gap-3 pt-4">
                <button type="button" onClick={() => setShowCreate(false)} className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50">
                  Cancel
                </button>
                <button type="submit" disabled={creating} className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50">
                  {creating ? 'Creating...' : 'Create Template'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}