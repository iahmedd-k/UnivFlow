import { NextRequest, NextResponse } from "next/server";

// Mock data for development - replace with actual backend call
const mockReviewData = {
  assignment: {
    id: "assign_123",
    title: "Implement Dijkstra's Algorithm",
    description: "Implement Dijkstra's shortest path algorithm in Python. The algorithm should find the shortest path between two nodes in a weighted graph. Include proper error handling and documentation.",
    course_code: "CS301",
    course_name: "Algorithms and Data Structures",
    due_date: "2026-02-15T23:59:00Z",
    status: "READY_FOR_APPROVAL",
  },
  requirements: {
    task_type: "CODE",
    requirements: [
      {
        id: "req_1",
        description: "Implement Dijkstra's algorithm with O((V+E) log V) complexity using a priority queue",
        type: "CODING",
        priority: "HIGH",
        deliverable: "CODE_FILE",
        constraints: {
          language: "Python",
          libraries: ["heapq"],
          file_types: [".py"],
          complexity: "O((V+E) log V)",
        },
        rubric_criteria: [
          { criterion: "Correctness", weight: 40, description: "Algorithm produces correct shortest paths" },
          { criterion: "Time Complexity", weight: 25, description: "Meets O((V+E) log V) requirement" },
          { criterion: "Code Quality", weight: 20, description: "Clean, documented, follows PEP 8" },
          { criterion: "Error Handling", weight: 15, description: "Handles edge cases gracefully" },
        ],
        depends_on: [],
      },
      {
        id: "req_2",
        description: "Write a test suite with at least 5 test cases covering various graph types",
        type: "CODING",
        priority: "MEDIUM",
        deliverable: "CODE_FILE",
        constraints: {
          language: "Python",
          libraries: ["unittest", "pytest"],
          file_types: [".py"],
        },
        rubric_criteria: [
          { criterion: "Coverage", weight: 50, description: "Tests cover normal, edge, and error cases" },
          { criterion: "Quality", weight: 50, description: "Tests are well-structured and readable" },
        ],
        depends_on: ["req_1"],
      },
      {
        id: "req_3",
        description: "Document the implementation with docstrings and a README",
        type: "FORMATTING",
        priority: "LOW",
        deliverable: "DOCUMENT",
        constraints: {
          format: "Markdown",
          required_sections: ["Usage", "Complexity Analysis", "Examples"],
        },
        rubric_criteria: [
          { criterion: "Completeness", weight: 60, description: "All required sections present" },
          { criterion: "Clarity", weight: 40, description: "Documentation is clear and helpful" },
        ],
        depends_on: ["req_1"],
      },
    ],
    deliverables: [
      { name: "dijkstra.py", type: "CODE_FILE", required: true, description: "Main implementation" },
      { name: "test_dijkstra.py", type: "CODE_FILE", required: true, description: "Test suite" },
      { name: "README.md", type: "DOCUMENT", required: false, description: "Documentation" },
    ],
    submission_format: "GOOGLE_DOC",
    confidence: 0.92,
  },
  generated_solution: {
    files: [
      {
        name: "dijkstra.py",
        content: `import heapq
from typing import Dict, List, Optional, Tuple


def dijkstra(graph: Dict[str, Dict[str, float]], start: str, end: str) -> Optional[Tuple[List[str], float]]:
    """
    Find the shortest path between start and end nodes using Dijkstra's algorithm.
    
    Args:
        graph: Adjacency list representation {node: {neighbor: weight}}
        start: Starting node
        end: Target node
    
    Returns:
        Tuple of (path as list of nodes, total distance) or None if no path exists
    
    Time Complexity: O((V + E) log V) where V = vertices, E = edges
    Space Complexity: O(V)
    """
    if start not in graph or end not in graph:
        raise ValueError("Start or end node not in graph")
    
    # Priority queue: (distance, node, path)
    pq = [(0, start, [start])]
    visited = set()
    distances = {start: 0}
    
    while pq:
        current_dist, current_node, path = heapq.heappop(pq)
        
        if current_node in visited:
            continue
        visited.add(current_node)
        
        if current_node == end:
            return path, current_dist
        
        for neighbor, weight in graph[current_node].items():
            if neighbor in visited:
                continue
            
            new_dist = current_dist + weight
            if neighbor not in distances or new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor, path + [neighbor]))
    
    return None  # No path found


def build_graph(edges: List[Tuple[str, str, float]]) -> Dict[str, Dict[str, float]]:
    """Build adjacency list from edge list."""
    graph = {}
    for u, v, w in edges:
        if u not in graph:
            graph[u] = {}
        if v not in graph:
            graph[v] = {}
        graph[u][v] = w
        graph[v][u] = w  # Undirected
    return graph


if __name__ == "__main__":
    # Example usage
    edges = [
        ("A", "B", 4), ("A", "C", 2),
        ("B", "C", 1), ("B", "D", 5),
        ("C", "D", 8), ("C", "E", 10),
        ("D", "E", 2), ("D", "F", 6),
        ("E", "F", 2)
    ]
    
    graph = build_graph(edges)
    result = dijkstra(graph, "A", "F")
    
    if result:
        path, distance = result
        print(f"Shortest path: {' -> '.join(path)}")
        print(f"Total distance: {distance}")
    else:
        print("No path found")`,
        mime_type: "text/x-python",
        size_bytes: 2048,
        requirement_ids: ["req_1"],
      },
      {
        name: "test_dijkstra.py",
        content: `import unittest
from dijkstra import dijkstra, build_graph


class TestDijkstra(unittest.TestCase):
    
    def setUp(self):
        self.edges = [
            ("A", "B", 4), ("A", "C", 2),
            ("B", "C", 1), ("B", "D", 5),
            ("C", "D", 8), ("C", "E", 10),
            ("D", "E", 2), ("D", "F", 6),
            ("E", "F", 2)
        ]
        self.graph = build_graph(self.edges)
    
    def test_basic_path(self):
        """Test basic shortest path finding."""
        result = dijkstra(self.graph, "A", "F")
        self.assertIsNotNone(result)
        path, dist = result
        self.assertEqual(path, ["A", "C", "B", "D", "E", "F"])
        self.assertEqual(dist, 12)
    
    def test_same_node(self):
        """Test path from node to itself."""
        result = dijkstra(self.graph, "A", "A")
        self.assertIsNotNone(result)
        path, dist = result
        self.assertEqual(path, ["A"])
        self.assertEqual(dist, 0)
    
    def test_no_path(self):
        """Test disconnected graph."""
        graph = {"A": {"B": 1}, "C": {"D": 1}}
        result = dijkstra(graph, "A", "C")
        self.assertIsNone(result)
    
    def test_invalid_start(self):
        """Test invalid start node."""
        with self.assertRaises(ValueError):
            dijkstra(self.graph, "X", "A")
    
    def test_invalid_end(self):
        """Test invalid end node."""
        with self.assertRaises(ValueError):
            dijkstra(self.graph, "A", "X")
    
    def test_single_edge(self):
        """Test graph with single edge."""
        graph = {"A": {"B": 5}, "B": {"A": 5}}
        result = dijkstra(graph, "A", "B")
        self.assertIsNotNone(result)
        path, dist = result
        self.assertEqual(path, ["A", "B"])
        self.assertEqual(dist, 5)


if __name__ == "__main__":
    unittest.main()`,
        mime_type: "text/x-python",
        size_bytes: 1536,
        requirement_ids: ["req_2"],
      },
      {
        name: "README.md",
        content: `# Dijkstra's Algorithm Implementation

## Overview
This project implements Dijkstra's shortest path algorithm in Python with O((V+E) log V) time complexity using a priority queue (heapq).

## Files
- \`dijkstra.py\` - Main implementation
- \`test_dijkstra.py\` - Comprehensive test suite

## Usage

\`\`\`python
from dijkstra import dijkstra, build_graph

# Define edges as (node1, node2, weight)
edges = [
    ("A", "B", 4),
    ("A", "C", 2),
    ("B", "C", 1),
    # ... more edges
]

graph = build_graph(edges)
path, distance = dijkstra(graph, "A", "F")

if path:
    print(f"Path: {' -> '.join(path)}")
    print(f"Distance: {distance}")
\`\`\`

## Complexity Analysis

| Operation | Time Complexity | Space Complexity |
|-----------|-----------------|------------------|
| Dijkstra | O((V + E) log V) | O(V) |
| Build Graph | O(E) | O(V + E) |

Where V = number of vertices, E = number of edges.

## Algorithm Details

The implementation uses a min-priority queue (heapq) to efficiently extract the vertex with minimum distance. Each vertex is processed once, and each edge is relaxed at most once.

### Key Features:
- ✅ Handles weighted, undirected graphs
- ✅ Proper error handling for invalid nodes
- ✅ Returns both path and total distance
- ✅ Comprehensive test coverage
- ✅ Clean, documented code following PEP 8

## Running Tests

\`\`\`bash
python -m pytest test_dijkstra.py -v
# or
python test_dijkstra.py
\`\`\``,
        mime_type: "text/markdown",
        size_bytes: 2048,
        requirement_ids: ["req_3"],
      },
    ],
    content: {
      "req_1": {
        "content": "// Dijkstra implementation...",
        "type": "code",
        "language": "python",
      },
      "req_2": {
        "content": "// Test suite...",
        "type": "code",
        "language": "python",
      },
      "req_3": {
        "content": "# README...",
        "type": "document",
        "format": "markdown",
      },
    },
    confidence: 0.92,
    requirements_met: ["req_1", "req_2", "req_3"],
    requirements_partial: [],
    requirements_failed: [],
    reviewer_feedback: "All requirements met with high confidence. Code is clean, well-documented, and includes comprehensive tests. The implementation correctly achieves O((V+E) log V) complexity using heapq. Documentation covers usage, complexity analysis, and examples.",
  },
  google_doc: {
    doc_id: "1abc123def456",
    url: "https://docs.google.com/document/d/1abc123def456/edit",
    drive_file_id: "1xyz789uvw000",
    title: "Implement Dijkstra's Algorithm - John Doe - CS301 - 2026-01-27",
    created_at: "2026-01-27T10:30:00Z",
    editable_url: "https://docs.google.com/document/d/1abc123def456/edit?usp=sharing",
  },
  confidence_score: 0.92,
  ai_reasoning: `The assignment asks for implementing Dijkstra's algorithm in Python with specific complexity requirements. 

Analysis:
1. Task Type: CODE - Clear programming assignment
2. Primary Requirement: Implement Dijkstra with O((V+E) log V) using priority queue
3. Secondary: Test suite with 5+ test cases
3. Tertiary: Documentation in Markdown

The solution uses Python's heapq module which provides O(log V) priority queue operations, achieving the required complexity. The implementation handles:
- Standard shortest path computation
- Edge cases (same node, disconnected graph, invalid nodes)
- Proper error handling with descriptive messages
- Clean code structure with type hints and docstrings

Tests cover:
- Basic path finding
- Same node (distance 0)
- Disconnected graphs
- Invalid start/end nodes
- Single edge graphs

Documentation follows the required sections: Usage, Complexity Analysis, Examples.

Confidence: 92% - All requirements clearly addressed with production-quality code.`,
  can_auto_approve: true,
  auto_approval_reason: null,
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  
  // In production: call backend API
  // const res = await fetch(`${process.env.BACKEND_URL}/assignments/${id}/review`);
  // const data = await res.json();
  
  // For now return mock data
  return NextResponse.json(mockReviewData);
}