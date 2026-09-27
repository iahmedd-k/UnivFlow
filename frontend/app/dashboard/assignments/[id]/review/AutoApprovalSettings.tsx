"use client";

import { useState, useEffect } from "react";

interface AutoApprovalConfig {
  enabled: boolean;
  min_confidence: number;
  allowed_task_types: string[];
  max_grade_percentage: number;
  notify_before_submit: boolean;
  notify_minutes_before: number;
  excluded_courses: string[];
  excluded_keywords: string[];
  require_manual_for: {
    group_work: boolean;
    presentations: boolean;
    peer_review: boolean;
  };
}

interface AutoApprovalSettingsProps {
  config: AutoApprovalConfig;
  onUpdate: (config: AutoApprovalConfig) => void;
}

const TASK_TYPES = [
  "ESSAY", "CODE", "MATH", "REPORT", 
  "PRESENTATION", "DATA_ANALYSIS", "RESEARCH", "OTHER"
];

export default function AutoApprovalSettings({ config, onUpdate }: AutoApprovalSettingsProps) {
  const [localConfig, setLocalConfig] = useState<AutoApprovalConfig>(config);
  const [expanded, setExpanded] = useState(false);
  const [newExcludedCourse, setNewExcludedCourse] = useState("");
  const [newExcludedKeyword, setNewExcludedKeyword] = useState("");

  useEffect(() => {
    setLocalConfig(config);
  }, [config]);

  const updateConfig = (updates: Partial<AutoApprovalConfig>) => {
    const newConfig = { ...localConfig, ...updates };
    setLocalConfig(newConfig);
    onUpdate(newConfig);
  };

  const toggleTaskType = (taskType: string) => {
    const newTypes = localConfig.allowed_task_types.includes(taskType)
      ? localConfig.allowed_task_types.filter(t => t !== taskType)
      : [...localConfig.allowed_task_types, taskType];
    updateConfig({ allowed_task_types: newTypes });
  };

  const addExcludedCourse = () => {
    if (newExcludedCourse.trim()) {
      updateConfig({ 
        excluded_courses: [...localConfig.excluded_courses, newExcludedCourse.trim().toUpperCase()] 
      });
      setNewExcludedCourse("");
    }
  };

  const removeExcludedCourse = (course: string) => {
    updateConfig({ 
      excluded_courses: localConfig.excluded_courses.filter(c => c !== course) 
    });
  };

  const addExcludedKeyword = () => {
    if (newExcludedKeyword.trim()) {
      updateConfig({ 
        excluded_keywords: [...localConfig.excluded_keywords, newExcludedKeyword.trim().toLowerCase()] 
      });
      setNewExcludedKeyword("");
    }
  };

  const removeExcludedKeyword = (keyword: string) => {
    updateConfig({ 
      excluded_keywords: localConfig.excluded_keywords.filter(k => k !== keyword) 
    });
  };

  return (
    <details className="group border border-gray-200 rounded-lg bg-white overflow-hidden">
      <summary className="flex items-center gap-3 p-4 cursor-pointer list-none bg-gray-50 border-b border-gray-200">
        <svg className="w-5 h-5 text-gray-500 group-open:rotate-180 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
        <span className="font-medium text-gray-900">⚙️ Auto-Approval Settings</span>
        <span className={`ml-auto px-2 py-1 text-xs font-medium rounded-full ${
          localConfig.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800"
        }`}>
          {localConfig.enabled ? "Enabled" : "Disabled"}
        </span>
      </summary>

      <div className="p-4 space-y-6">
        {/* Master Toggle */}
        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
          <div>
            <p className="font-medium text-gray-900">Enable Auto-Approval</p>
            <p className="text-sm text-gray-500">
              Automatically submit assignments when confidence threshold is met
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={localConfig.enabled}
              onChange={(e) => updateConfig({ enabled: e.target.checked })}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
          </label>
        </div>

        {/* Confidence Threshold */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Minimum Confidence Threshold: <span className="font-normal">{Math.round(localConfig.min_confidence * 100)}%</span>
          </label>
          <input
            type="range"
            min="50"
            max="99"
            value={Math.round(localConfig.min_confidence * 100)}
            onChange={(e) => updateConfig({ min_confidence: parseInt(e.target.value) / 100 })}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <p className="text-xs text-gray-500 mt-1">
            Only auto-submit when AI confidence exceeds this threshold. Higher = safer but fewer auto-submissions.
          </p>
        </div>

        {/* Allowed Task Types */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Allowed Task Types for Auto-Approval</label>
          <div className="flex flex-wrap gap-2">
            {TASK_TYPES.map((type) => (
              <label key={type} className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-sm cursor-pointer transition-colors ${
                localConfig.allowed_task_types.includes(type)
                  ? "bg-blue-100 text-blue-800 border border-blue-300"
                  : "bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200"
              }`}>
                <input
                  type="checkbox"
                  checked={localConfig.allowed_task_types.includes(type)}
                  onChange={() => toggleTaskType(type)}
                  className="sr-only"
                />
                {type}
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            Select which assignment types can be auto-approved. Code and Math are typically safer.
          </p>
        </div>

        {/* Max Grade Percentage */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Max Grade Weight: <span className="font-normal">{localConfig.max_grade_percentage}%</span>
          </label>
          <input
            type="range"
            min="0"
            max="100"
            value={localConfig.max_grade_percentage}
            onChange={(e) => updateConfig({ max_grade_percentage: parseInt(e.target.value) })}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <p className="text-xs text-gray-500 mt-1">
            Don't auto-approve assignments worth more than this percentage of the course grade.
          </p>
        </div>

        {/* Notification Settings */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={localConfig.notify_before_submit}
                onChange={(e) => updateConfig({ notify_before_submit: e.target.checked })}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700">Notify me before auto-submitting</span>
            </label>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700">Notify minutes before: </label>
            <input
              type="number"
              min="1"
              max="60"
              value={localConfig.notify_minutes_before}
              onChange={(e) => updateConfig({ notify_minutes_before: parseInt(e.target.value) || 5 })}
              className="mt-1 w-24 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Excluded Courses */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Excluded Courses (never auto-approve)</label>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={newExcludedCourse}
              onChange={(e) => setNewExcludedCourse(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addExcludedCourse()}
              placeholder="e.g., CS499, CAPSTONE"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={addExcludedCourse}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
            >
              Add
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {localConfig.excluded_courses.map((course) => (
              <span key={course} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 text-gray-700 rounded-full text-sm">
                {course}
                <button
                  onClick={() => removeExcludedCourse(course)}
                  className="text-gray-400 hover:text-red-500"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>

        {/* Excluded Keywords */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Excluded Keywords in Title</label>
          <div className="flex gap-2 mb-2">
            <input
              type="text"
              value={newExcludedKeyword}
              onChange={(e) => setNewExcludedKeyword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addExcludedKeyword()}
              placeholder="e.g., final, thesis, capstone"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              onClick={addExcludedKeyword}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
            >
              Add
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {localConfig.excluded_keywords.map((keyword) => (
              <span key={keyword} className="inline-flex items-center gap-1 px-2 py-1 bg-yellow-50 text-yellow-800 rounded-full text-sm border border-yellow-200">
                {keyword}
                <button
                  onClick={() => removeExcludedKeyword(keyword)}
                  className="text-yellow-500 hover:text-red-500"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>

        {/* Require Manual For */}
        <div className="border-t border-gray-200 pt-4">
          <h4 className="font-medium text-gray-900 mb-3">Always Require Manual Approval For:</h4>
          <div className="space-y-2">
            {Object.entries(localConfig.require_manual_for).map(([key, value]) => (
              <label key={key} className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={value}
                  onChange={(e) => updateConfig({ 
                    require_manual_for: { ...localConfig.require_manual_for, [key]: e.target.checked } 
                  })}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700 capitalize">{key.replace("_", " ")}</span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </details>
  );
}