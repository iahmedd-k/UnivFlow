"""CrewAI orchestration for the four Uniflow assignment specialists."""

from collections.abc import Callable
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task

from app.agent.model_registry import get_agent_models
from app.core.config import settings


AGENT_ORDER = ("planner", "theory_research", "coder_diagram", "reporter_fixer")


def _agent_llm(role: str) -> LLM:
    models = get_agent_models()
    model = models[role]
    provider = model.provider
    model_name = model.model
    api_key = settings.groq_api_key if provider == "groq" else settings.gemini_api_key

    # Resilience: if one provider key is missing, fall back to the available provider
    if not api_key:
        if provider == "groq" and settings.gemini_api_key:
            provider = "gemini"
            model_name = "gemini-2.0-flash"
            api_key = settings.gemini_api_key
        elif provider == "gemini" and settings.groq_api_key:
            provider = "groq"
            model_name = "llama-3.3-70b-versatile"
            api_key = settings.groq_api_key
        else:
            key_name = "GROQ_API_KEY or GEMINI_API_KEY"
            raise ValueError(f"{key_name} is required to create the {role} agent.")

    provider_model = f"{provider}/{model_name}"
    token_limit = {"max_tokens": 8192} if provider == "groq" else {"max_output_tokens": 8192}
    return LLM(model=provider_model, api_key=api_key, **token_limit)


def build_assignment_crew(on_task_complete: Callable[[str, Any], None] | None = None) -> Crew:
    """Build the four-agent sequential crew and optionally report task completion."""
    planner = Agent(
        role="Planner / Analyzer",
        goal="Classify the assignment and produce a dependency-aware structured plan.",
        backstory="You analyze university assignments and identify their required deliverables precisely.",
        llm=_agent_llm("planner"), allow_delegation=False, verbose=False,
    )
    researcher = Agent(
        role="Theory / Research Specialist",
        goal="Explain requested course concepts using only supplied or actually consulted evidence.",
        backstory="You write clear university-level theory, mark evidence gaps, and never invent citations.",
        llm=_agent_llm("theory_research"), allow_delegation=False, verbose=False,
    )
    coder = Agent(
        role="Coder / Diagram Specialist",
        goal="Produce requested runnable code, SQL, and syntactically sound diagram source.",
        backstory="You are a careful engineer who distinguishes generated artifacts from executed results.",
        llm=_agent_llm("coder_diagram"), allow_delegation=False, verbose=False,
    )
    reporter = Agent(
        role="Reporter / Fixer",
        goal="Check all work against the plan and return the requested polished deliverable.",
        backstory="You preserve accurate specialist details, fix clear errors, and expose unresolved gaps.",
        llm=_agent_llm("reporter_fixer"), allow_delegation=False, verbose=False,
    )

    def completed(role: str):
        if on_task_complete is None:
            return None
        return lambda output: on_task_complete(role, output)

    planning_task = Task(
        description=(
            "Analyze the assignment, supplied materials, and course context. Use exactly one task_type: "
            "LAB_REPORT, ASSIGNMENT, CODING_ONLY, RESEARCH, or OTHER. Return ONLY valid JSON with this "
            "shape: {{\"task_type\": \"LAB_REPORT\", "
            "\"subject\": \"...\", \"summary\": \"...\", \"parts_required\": [], "
            "\"constraints\": [], \"assumptions\": [], \"missing_information\": [], "
            "\"tools_required\": [], \"steps\": []}}. "
            "Each step must have id, owner (theory_research, coder_diagram, or reporter_fixer), "
            "description, and depends_on. Identify which specialists are needed. Do not write theory, "
            "the final answer, or code in this plan. If requirements are unclear, record an assumption.\n\n"
            "ASSIGNMENT:\n{assignment}\n\nCOURSE AND SUPPLIED MATERIALS:\n{context}"
        ),
        expected_output="Only valid JSON matching the requested plan schema.", agent=planner,
        callback=completed("planner"),
    )
    research_task = Task(
        description=(
            "Follow the Planner's plan. Write only the theory and research sections that are required. "
            "Structure explanations logically: introduction, definitions, operation or architecture, "
            "example, advantages and disadvantages, and summary as relevant. Use clear formal English. "
            "Use a Pakistani example "
            "when it naturally fits. Follow the requested length and citation style. Cite only sources "
            "actually supplied or consulted; do not invent citations or claim web research. If theory is "
            "not required, return exactly: N/A — not required for this task.\n\nPLAN AND ASSIGNMENT CONTEXT:\n{context}"
        ),
        expected_output="A clean Markdown theory/research brief, or the exact N/A line when not required.",
        agent=researcher, context=[planning_task], callback=completed("theory_research"),
    )
    coding_task = Task(
        description=(
            "Follow the Planner's plan. Produce only the technical artifacts required by the assignment.\n"
            "For each required task or exercise, structure the output strictly as:\n"
            "1. Heading: `## Task <N>: <Task Title / Objective>`\n"
            "2. `### 1. Problem Statement / Question`: Clear statement of the problem, architectural objectives, and input/output requirements.\n"
            "3. `### 2. Source Code Implementation` (or `### 2. Architecture & Visual Diagram Specification` for diagram tasks):\n"
            "   - FOR PROGRAMMING/SQL: Complete, standalone, runnable code in a language block (e.g. ```cpp, ```python, ```sql).\n"
            "   - FOR ARCHITECTURE / SYSTEM DESIGN / DIAGRAMS: Use valid Draw.io XML (```xml <mxfile>...</mxfile> ```) OR valid Mermaid (```mermaid ... ```).\n"
            "   CRITICAL DIAGRAM QUALITY RULES:\n"
            "   * NEVER generate a single empty or plain giant rectangle. Break monolithic architectures into internal subsystem cards inside a container.\n"
            "   * Modern compact card geometry: width=\"220\" height=\"90\" with rounded corners (rounded=1;arcSize=10;).\n"
            "   * Rich HTML formatting for cards: value=\"&lt;b&gt;Card Name&lt;/b&gt;&lt;hr style='margin:4px 0; border:0; border-top:1px solid ...'/&gt;&bull; Responsibility 1&lt;br/&gt;&bull; Responsibility 2\"\n"
            "   * Diverse semantic color palettes:\n"
            "     - Request / Queue / API Layer: Amber (fillColor=#FEF3C7;strokeColor=#D97706;fontColor=#92400E;)\n"
            "     - Controller / Strategy / Logic: Indigo (fillColor=#EEF2FF;strokeColor=#4F46E5;fontColor=#1E1B4B;)\n"
            "     - Hardware / Worker / Execution: Emerald (fillColor=#ECFDF5;strokeColor=#059669;fontColor=#064E3B;)\n"
            "     - Containers / Subsystem Boundaries: Slate (fillColor=#F8FAFC;strokeColor=#CBD5E1;fontColor=#475569;dashed=1;)\n"
            "   * Orthogonal rounded connectors: edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#4F46E5;strokeWidth=2;endArrow=classic;endFill=1;\n"
            "4. `### 3. Expected Output / Component Breakdown & Verification`: Structured markdown tables detailing component roles, cohesion/coupling ratings, or terminal test verification outputs.\n"
            "   CRITICAL CODE & RUNNER RULES:\n"
            "   * All programming and assembly code MUST be fully standalone and runnable with main test execution drivers and print routines (standard print / INT 21h syscalls) displaying sample inputs and verified results to stdout.\n"
            "   * In terminal outputs and execution evidence, capture ONLY the terminal execution window (command + stdout). Never repeat the task source code in the terminal capture.\n"
            "   * If the output is long, it must be captured in full without truncation (splitting into multi-part images Part 1 and Part 2 if needed).\n"
            "Do not invent APIs or execution output. State whether artifacts were actually executed only when an execution tool was called.\n"
            "If code or diagrams are not required, return exactly: N/A — not required for this task.\n\n"
            "ASSIGNMENT AND SUPPLIED MATERIALS:\n{assignment}\n{context}"
        ),
        expected_output="Structured Markdown technical artifacts following the 3-part task structure with publication-grade code and Draw.io XML / Mermaid blocks, or the exact N/A line when not required.",
        agent=coder, context=[planning_task, research_task], callback=completed("coder_diagram"),
    )
    reporting_task = Task(
        description=(
            "Review the Planner output and both specialist outputs against every required part. "
            "Ensure the final deliverable is structured with professional academic quality:\n"
            "- For coding/lab tasks: Each task MUST contain the Question/Problem Statement first, the Source Code second, and the Expected Output & Verification third.\n"
            "- For theoretical tasks: Exhaustive structured sections with Executive Summary, Theoretical Analysis, and APA citations.\n"
            "Mark sections N/A only when the plan confirms they are not required; state any missing required material clearly. "
            "Correct clear errors, preserve code and diagrams intact, and prepare the final requested deliverable. "
            "Do not fabricate execution output, references, or document links. Return clean Markdown with a short quality status.\n\n"
            "ORIGINAL ASSIGNMENT:\n{assignment}\n\nSUPPLIED CONTEXT:\n{context}"
        ),
        expected_output="The complete reviewed deliverable in clean Markdown, followed by a brief quality status.",
        agent=reporter, context=[planning_task, research_task, coding_task],
        callback=completed("reporter_fixer"),
    )
    return Crew(
        agents=[planner, researcher, coder, reporter],
        tasks=[planning_task, research_task, coding_task, reporting_task],
        process=Process.sequential, verbose=False,
    )


def run_assignment_crew(assignment: str, context: str = "", on_task_complete=None):
    """Run the configured four-agent sequential crew and return CrewAI's result."""
    crew = build_assignment_crew(on_task_complete=on_task_complete)
    return crew.kickoff(inputs={"assignment": assignment, "context": context})
