'use client';

import { useState } from 'react';
import { useAuth } from '@clerk/nextjs';
import { api } from '@/app/lib/api';
import ExecutionConsole from '@/app/dashboard/ExecutionConsole';
import Icon from '@/app/dashboard/Icon';

const SAMPLE_CODE = {
  python: `print("Hello Ahmed")
print(2 + 3)

# Fibonacci sequence
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        print(a, end=' ')
        a, b = b, a + b

fibonacci(10)`,
  javascript: `console.log("Hello Ahmed");
console.log(2 + 3);

// Fibonacci sequence
function fibonacci(n) {
    let a = 0, b = 1;
    for (let i = 0; i < n; i++) {
        process.stdout.write(a + " ");
        [a, b] = [b, a + b];
    }
}

fibonacci(10);`,
  typescript: `console.log("Hello Ahmed");
console.log(2 + 3);

// Fibonacci sequence
function fibonacci(n: number): void {
    let a = 0, b = 1;
    for (let i = 0; i < n; i++) {
        process.stdout.write(a + " ");
        [a, b] = [b, a + b];
    }
}

fibonacci(10);`,
  cpp: `#include <iostream>

int main() {
    std::cout << "Hello Ahmed" << std::endl;
    std::cout << 2 + 3 << std::endl;

    // Fibonacci sequence
    int a = 0, b = 1;
    for (int i = 0; i < 10; i++) {
        std::cout << a << " ";
        int temp = a + b;
        a = b;
        b = temp;
    }
    std::cout << std::endl;
    return 0;
}`,
  java: `public class Main {
    public static void main(String[] args) {
        System.out.println("Hello Ahmed");
        System.out.println(2 + 3);

        // Fibonacci sequence
        int a = 0, b = 1;
        for (int i = 0; i < 10; i++) {
            System.out.print(a + " ");
            int temp = a + b;
            a = b;
            b = temp;
        }
        System.out.println();
    }
}`,
  go: `package main

import "fmt"

func main() {
    fmt.Println("Hello Ahmed")
    fmt.Println(2 + 3)

    // Fibonacci sequence
    a, b := 0, 1
    for i := 0; i < 10; i++ {
        fmt.Print(a, " ")
        a, b = b, a + b
    }
    fmt.Println()
}`,
  assembly: `section .data
    hello db "Hello Ahmed", 10, 0
    hello_len equ $ - hello

section .text
    global _start

_start:
    ; Write "Hello Ahmed"
    mov eax, 4
    mov ebx, 1
    mov ecx, hello
    mov edx, hello_len
    int 0x80

    ; Exit
    mov eax, 1
    xor ebx, ebx
    int 0x80`,
  sqlite: `-- Create table
CREATE TABLE students (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER
);

-- Insert data
INSERT INTO students (name, age) VALUES ('Ahmed', 22);
INSERT INTO students (name, age) VALUES ('Ali', 20);
INSERT INTO students (name, age) VALUES ('Sara', 23);

-- Query
SELECT * FROM students;`,
  mysql: `-- Create table
CREATE TABLE IF NOT EXISTS students (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    age INT
);

-- Insert data
INSERT INTO students (name, age) VALUES ('Ahmed', 22);
INSERT INTO students (name, age) VALUES ('Ali', 20);

-- Query
SELECT * FROM students;`,
  mongodb: `{
  "operation": "insert_many",
  "collection": "students",
  "documents": [
    { "name": "Ahmed", "age": 22, "major": "Computer Science" },
    { "name": "Ali", "age": 20, "major": "Mathematics" },
    { "name": "Sara", "age": 23, "major": "Physics" }
  ]
}`,
};

const LANGUAGES = [
  { id: 'python', name: 'Python', category: 'programming' },
  { id: 'javascript', name: 'JavaScript', category: 'programming' },
  { id: 'typescript', name: 'TypeScript', category: 'programming' },
  { id: 'cpp', name: 'C++', category: 'programming' },
  { id: 'java', name: 'Java', category: 'programming' },
  { id: 'go', name: 'Go', category: 'programming' },
  { id: 'assembly', name: 'Assembly (NASM)', category: 'programming' },
  { id: 'sqlite', name: 'SQLite', category: 'database' },
  { id: 'mysql', name: 'MySQL', category: 'database' },
  { id: 'mongodb', name: 'MongoDB', category: 'database' },
];

export default function ExecutionDemo() {
  const { getToken } = useAuth();
  const [selectedLanguage, setSelectedLanguage] = useState('python');
  const [code, setCode] = useState(SAMPLE_CODE.python);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showCode, setShowCode] = useState(true);
  const [compact, setCompact] = useState(false);

  const handleLanguageChange = (lang: string) => {
    setSelectedLanguage(lang);
    setCode(SAMPLE_CODE[lang as keyof typeof SAMPLE_CODE] || '');
    setResult(null);
    setError('');
  };

  const handleExecute = async () => {
    if (!code.trim()) {
      setError('Please enter some code to execute');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const token = getToken ? await getToken() : null;
      const response = await api.executeCode({
        language: selectedLanguage,
        code,
        max_attempts: 1,
      }, token);
      setResult(response);
    } catch (err: any) {
      setError(err.message || 'Execution failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1000px', margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: '#1e293b', marginBottom: 8 }}>
          Execution Console Demo
        </h1>
        <p style={{ color: '#64748b', fontSize: 14 }}>
          Test the multi-language execution console with Piston and database backends
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 24 }}>
        {/* Sidebar */}
        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, padding: 16, height: 'fit-content' }}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
              Language
            </label>
            <select
              value={selectedLanguage}
              onChange={(e) => handleLanguageChange(e.target.value)}
              style={{ width: '100%', padding: '10px 12px', border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13, background: '#ffffff', color: '#1e293b', cursor: 'pointer' }}
            >
              {LANGUAGES.map((lang) => (
                <option key={lang.id} value={lang.id}>{lang.name}</option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#334155', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={showCode}
                onChange={(e) => setShowCode(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#6657d9' }}
              />
              Show Source Code
            </label>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#334155', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={compact}
                onChange={(e) => setCompact(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#6657d9' }}
              />
              Compact Mode
            </label>
          </div>

          <button
            onClick={handleExecute}
            disabled={loading || !code.trim()}
            style={{
              width: '100%',
              padding: '12px 16px',
              background: loading ? '#94a3b8' : '#6657d9',
              color: '#ffffff',
              border: 'none',
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}
          >
            {loading ? (
              <>
                <span style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid #ffffff', borderTopColor: 'transparent', animation: 'spin 1s linear infinite' }} />
                Executing...
              </>
            ) : (
              <>
                <Icon name="play" size={16} />
                Run Code
              </>
            )}
          </button>

          {error && (
            <div style={{ marginTop: 12, padding: '10px 12px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#dc2626', fontSize: 12 }}>
              <strong>Error:</strong> {error}
            </div>
          )}
        </div>

        {/* Code Editor & Console */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Code Editor */}
          <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '12px 16px', background: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name="code" size={16} style={{ color: '#64748b' }} />
                <strong style={{ fontSize: 12, color: '#334155' }}>Source Code</strong>
                <span style={{ fontSize: 10, padding: '2px 6px', background: '#e2e8f0', color: '#475569', borderRadius: 4, textTransform: 'uppercase' }}>
                  {selectedLanguage}
                </span>
              </div>
              <span style={{ fontSize: 10, color: '#94a3b8' }}>{code.split('\n').length} lines</span>
            </div>
            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              style={{
                width: '100%',
                minHeight: 300,
                padding: '16px',
                border: 'none',
                outline: 'none',
                fontFamily: 'ui-monospace, monospace',
                fontSize: 13,
                lineHeight: 1.6,
                color: '#1e293b',
                background: '#ffffff',
                resize: 'vertical',
              }}
              placeholder="Enter code to execute..."
              spellCheck={false}
            />
          </div>

          {/* Execution Console */}
          <ExecutionConsole
            result={result}
            code={showCode ? code : undefined}
            showCode={showCode}
            compact={compact}
          />
        </div>
      </div>

      <style jsx>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}