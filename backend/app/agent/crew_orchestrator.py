"""CrewAI orchestration for the four Uniflow assignment specialists (improved prompts, v2)."""

from collections.abc import Callable
from typing import Any

from crewai import Agent, Crew, LLM, Process, Task

from app.agent.model_registry import get_agent_models
from app.core.config import settings


AGENT_ORDER = ("planner", "theory_research", "coder_diagram", "reporter_fixer")

NA_LINE = "N/A — not required for this task."


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


# ---------------------------------------------------------------------------
# DOMAIN PLAYBOOK
# One place to define how each assignment type is handled. To support a new
# assignment type: add a line here AND add it to the domain_type enum in
# PLANNER_PROMPT. Note: NO braces allowed in these strings (CrewAI formats them).
# ---------------------------------------------------------------------------
DOMAIN_PLAYBOOK = """\
- THEORY_ACADEMIC (essays, case studies, management, business plans, ethics, humanities, conceptual explanations, non-coding research, theoretical proofs):
    owners: theory_research -> reporter_fixer. coder_diagram is FORBIDDEN.
    deliverable_format: "Academic Essay Report (APA)". artifacts_required: ["theory_text"].
    The final result must be the FULL, ready-to-submit written solution of every question. No code, no terminal output, no outlines.
- CODING_LAB (ordinary programming tasks in any language: algorithms, data structures, scripting, OS/networking labs, assembly; each task normally runs from a single source file):
    owners: coder_diagram -> reporter_fixer. Add theory_research ONLY if the manual contains separate conceptual/viva questions.
    deliverable_format: "Standalone Code with Terminal Output". requires_code=true, requires_terminal_output=true.
    artifacts_required: ["code_file", "terminal_screenshot"]. Each task = one runnable code file + one terminal output screenshot of that file running.
- DIAGRAM_DESIGN (ER diagrams, UML, system architecture, flowcharts, DFDs, circuit/block diagrams, network topologies):
    owners: coder_diagram -> reporter_fixer (+ theory_research only if a written explanation is explicitly requested).
    deliverable_format: "Draw.io Diagram XML". requires_diagram=true. artifacts_required: ["diagram_image", "drawio_xml"].
    FIRST inspect the supplied materials for sample/reference diagrams. If any exist, set reference_diagram_available=true and describe their exact format in reference_diagram_notes.
- HEAVY_ML (machine learning, deep learning, PyTorch/TensorFlow/sklearn, model training and evaluation pipelines):
    owners: coder_diagram -> reporter_fixer ONLY. Do NOT assign theory_research (any needed theory goes into markdown cells inside the notebook).
    deliverable_format: "Google Colab Notebook". requires_code=true. artifacts_required: ["colab_notebook"].
    The ONLY deliverable is ONE single Google Colab notebook file (.ipynb). No separate report, code files or screenshots.
- QUANTITATIVE_MATH (numerical problems, physics, discrete math, statistics, calculus, engineering calculations):
    owners: theory_research (step-by-step worked solutions with formulas, units, final answers) -> reporter_fixer. coder_diagram ONLY if code/simulation is explicitly requested.
    deliverable_format: "Academic Essay Report (APA)" with worked solutions. artifacts_required: ["theory_text"]. No invented numerical data.
- SQL_DATABASE (schema design, normalization, queries, PL/SQL, ER-to-relational mapping):
    owners: coder_diagram (DDL, sample INSERTs, queries as a single .sql file + terminal screenshot of results) -> reporter_fixer; add diagram work if an ER diagram is requested; theory_research only for normalization/theory questions.
    deliverable_format: "Standalone Code with Terminal Output". requires_code=true. artifacts_required: ["code_file", "terminal_screenshot"] (+ diagram artifacts if requested).
- DATA_ANALYSIS (data cleaning, EDA, visualization, statistics on a supplied dataset):
    owners: coder_diagram (reproducible Python/R in a single file) -> reporter_fixer; theory_research for interpretation sections.
    deliverable_format: "Standalone Code with Terminal Output". artifacts_required: ["code_file", "terminal_screenshot"]. Never fabricate dataset values; if no dataset is supplied, generate clearly-labelled synthetic data or list it under missing_information.
    (If the analysis is a model-training pipeline, treat it as HEAVY_ML instead.)
- MIXED (parts clearly belong to different domains, e.g. Q1 theory + Q2 code + Q3 diagram):
    Set domain_type to the domain of the MAJORITY of marks, then tag EVERY part with its own part_domain and owner.
    Assign each specialist only the parts that belong to it, and apply each part's own artifact rules.
    If every part is HEAVY_ML the single-notebook rule applies; if only some parts are ML, put those parts in one notebook section and keep the rest in the normal report.
"""

DOMAIN_DECISION_ORDER = """\
Decide domain_type with this prioritized order (first match wins):
1. Is a model being trained or evaluated (PyTorch, TensorFlow, deep learning, GPU training pipeline)? -> HEAVY_ML.
2. Is the main output an architectural schema, ER diagram, UML model, or flowchart? -> DIAGRAM_DESIGN.
3. Are the core tasks mathematical problem-solving, calculus, algebra, statistics, proofs, physics, or discrete math? -> QUANTITATIVE_MATH.
4. Is the primary deliverable relational schemas, DDL, SQL tables, or database queries? -> SQL_DATABASE.
5. Is the primary deliverable statistical data cleaning, EDA, or visualization on a dataset? -> DATA_ANALYSIS.
6. Is the primary deliverable runnable programming code (C++, Python, Java, Assembly, algorithms, lab tasks)? -> CODING_LAB.
   (Note: If a coding lab includes brief conceptual or viva questions, classify it as CODING_LAB, not MIXED.)
7. Does the assignment require SUBSTANTIVE, independent deliverables across multiple domains (e.g. both a multi-page literature review AND a full software system)? -> MIXED.
8. Otherwise (essays, case studies, humanities, ethics, business, management, conceptual explanations) -> THEORY_ACADEMIC.
"""

PLANNER_PROMPT = (
    "You are the master curriculum planner and academic architect for a university assignment system. "
    "Your plan is the ONLY source of routing truth for the specialists that follow you, so it must be precise, complete and machine-readable.\n\n"
    "INPUTS: assignment title/description, course name, and any supplied reference materials (lab manuals, rubrics, slides, sample diagrams, datasets).\n\n"
    "STEP 1 - READ EVERYTHING\n"
    "Read the full assignment and all supplied material. Note every question, sub-question, deliverable, marks weighting, word/page limit, "
    "required language/tool/format, citation style, and submission instruction. Do not skip sub-parts (a, b, c...). "
    "Also check whether the supplied materials contain any SAMPLE or EXAMPLE DIAGRAM (image, description, or XML) that shows the expected diagram style.\n\n"
    "STEP 2 - CLASSIFY\n"
    + DOMAIN_DECISION_ORDER +
    "\nSTEP 3 - ROUTE USING THE DOMAIN PLAYBOOK\n"
    + DOMAIN_PLAYBOOK +
    "\nSTEP 4 - EXTRACT ALL PARTS\n"
    "List EVERY required task/question as its own entry in parts_required, keeping its original numbering and title, "
    "its exact requirements, marks (if stated), its own part_domain, and the owner who must handle it. "
    "If the assignment has a single undivided task, create one part.\n\n"
    "STEP 5 - BUILD DEPENDENCY-AWARE STEPS\n"
    "Create ordered steps. Specialist steps come first, and the LAST step must always be owned by reporter_fixer and depend on all earlier steps. "
    "Only reference owners that actually have work. Never assign a specialist that has no parts.\n\n"
    "RULES\n"
    "- Never write answers, theory or code in the plan. Planning only.\n"
    "- Never invent requirements. If something is unclear, missing or contradictory (e.g. no dataset, no language specified, unreadable question), "
    "record it in missing_information and state your reasonable choice in assumptions.\n"
    "- Honour explicit instructions in the assignment (language, tool, citation style, word limit) by copying them into constraints.\n"
    "- requires_code / requires_terminal_output / requires_diagram must be true if ANY part needs them.\n"
    "- artifacts_required lists the final files/items the student needs, using only: \"theory_text\", \"code_file\", \"terminal_screenshot\", \"colab_notebook\", \"diagram_image\", \"drawio_xml\".\n"
    "- reference_diagram_available is true ONLY if the supplied materials really contain a sample diagram; then describe its notation, shapes, colours, labelling and layout in reference_diagram_notes. Otherwise false and empty string.\n"
    "- tools_required lists concrete tools only (e.g. 'GCC', 'Python 3', 'MySQL', 'Draw.io', 'Google Colab').\n"
    "- Output must be raw JSON only: no markdown fences, no commentary before or after.\n\n"
    "OUTPUT SCHEMA (return exactly these keys):\n"
    "{{\n"
    "  \"domain_type\": \"THEORY_ACADEMIC\" | \"CODING_LAB\" | \"DIAGRAM_DESIGN\" | \"HEAVY_ML\" | \"QUANTITATIVE_MATH\" | \"SQL_DATABASE\" | \"DATA_ANALYSIS\" | \"MIXED\",\n"
    "  \"task_type\": \"LAB_REPORT\" | \"ASSIGNMENT\" | \"CODING_ONLY\" | \"RESEARCH\" | \"OTHER\",\n"
    "  \"deliverable_format\": \"Academic Essay Report (APA)\" | \"Standalone Code with Terminal Output\" | \"Draw.io Diagram XML\" | \"Google Colab Notebook\" | \"Mixed Report\",\n"
    "  \"subject\": \"...\",\n"
    "  \"summary\": \"One or two sentences describing what the student must submit.\",\n"
    "  \"parts_required\": [\n"
    "    {{\"id\": \"part_1\", \"title\": \"Task 1: ...\", \"requirements\": \"...\", \"marks\": null, \"part_domain\": \"...\", \"owner\": \"theory_research\" | \"coder_diagram\"}}\n"
    "  ],\n"
    "  \"artifacts_required\": [],\n"
    "  \"requires_code\": false,\n"
    "  \"requires_terminal_output\": false,\n"
    "  \"requires_diagram\": false,\n"
    "  \"reference_diagram_available\": false,\n"
    "  \"reference_diagram_notes\": \"\",\n"
    "  \"constraints\": [],\n"
    "  \"assumptions\": [],\n"
    "  \"missing_information\": [],\n"
    "  \"tools_required\": [],\n"
    "  \"steps\": [\n"
    "    {{\"id\": \"step_1\", \"owner\": \"theory_research\" | \"coder_diagram\" | \"reporter_fixer\", \"description\": \"...\", \"depends_on\": []}}\n"
    "  ]\n"
    "}}\n\n"
    "ASSIGNMENT:\n{assignment}\n\nCOURSE AND SUPPLIED MATERIALS:\n{context}"
)

RESEARCH_PROMPT = (
    "Read the Planner's JSON plan first.\n"
    "Your work covers ONLY the parts whose owner is 'theory_research'. "
    "If no part and no step is owned by theory_research, or domain_type is 'HEAVY_ML', return EXACTLY: " + NA_LINE + "\n\n"
    "Otherwise write the content by domain:\n"
    "- THEORY_ACADEMIC: the COMPLETE, ready-to-submit written solution of the assignment. Answer every assigned question fully and directly in "
    "authoritative scholarly prose: introduction, theoretical foundations, structured analytical discussion, real-world examples/case studies, "
    "critical evaluation (advantages, limitations, alternatives), conclusion, and APA references. Each question gets its own numbered heading "
    "and a full answer - never an outline, bullet-only skeleton, placeholder, or 'refer to textbook'.\n"
    "- QUANTITATIVE_MATH: complete worked solutions. For each problem: Given, Required, Formula(s), step-by-step working with units, "
    "final answer clearly stated, and a quick sanity check. Do not skip algebra steps.\n"
    "- Conceptual questions inside CODING_LAB / SQL_DATABASE / DATA_ANALYSIS: concise, exam-ready explanations "
    "(definition, how it works, example, when to use).\n\n"
    "QUALITY RULES\n"
    "- Answer every assigned part, in the planner's order, using its original numbering and titles.\n"
    "- Depth must match the marks and any stated word limit in the plan's constraints; if no limit is given, be thorough rather than brief.\n"
    "- Use clear formal English, logical headings, and short paragraphs.\n"
    "- Cite only sources that were supplied or genuinely consulted. NEVER invent authors, titles, years, DOIs or URLs. "
    "If you cannot support a claim with a real source, state it as general knowledge and add it under 'Evidence gaps'.\n"
    "- Do not write code or diagrams.\n\n"
    "PLAN AND ASSIGNMENT CONTEXT:\n{context}\n\nASSIGNMENT:\n{assignment}"
)

CODING_PROMPT = (
    "Read the Planner's JSON plan first.\n"
    "Your work covers ONLY the parts whose owner is 'coder_diagram'. "
    "CRITICAL: if domain_type in ('THEORY_ACADEMIC', 'QUANTITATIVE_MATH'), OR coder_diagram is not the owner of any part or step, "
    "OR (requires_code is false AND requires_diagram is false AND 'colab_notebook' is not in artifacts_required), return EXACTLY: " + NA_LINE + "\n\n"
    "Otherwise produce the artifacts below according to each part's part_domain. You can only write text, so every file and every image is "
    "produced as a clearly named, fenced block that the platform renders/saves. Always include the exact file name shown in the format.\n\n"

    "=== A) CODING_LAB / SQL_DATABASE / DATA_ANALYSIS (code files + terminal screenshots) ===\n"
    "For EACH task produce exactly this structure:\n"
    "## Task <N>: <Task Title / Objective>\n"
    "### 1. Problem Statement / Question\n"
    "Clear statement of the problem, objectives, input/output requirements.\n"
    "### 2. Source Code Implementation\n"
    "**File:** `task<N>_<short_name>.<ext>`\n"
    "```<language>\n<complete code>\n```\n"
    "### 3. Terminal Output Screenshot\n"
    "**Screenshot:** `task<N>_<short_name>_output.png`\n"
    "```terminal\n$ <compile command if the language needs one>\n$ <run command>\n<exact program output>\n```\n"
    "Rules for code files:\n"
    "* One standalone, runnable file per task (single-file programs). Use the language named in the assignment; otherwise Python. No external files unless supplied.\n"
    "* Include a main driver with sample inputs hard-coded OR, if the program reads input, show the typed input inside the terminal block.\n"
    "* Add meaningful comments, validate input where sensible, and handle edge cases. Re-read the code for syntax and logic errors before answering.\n"
    "* For SQL tasks use one .sql file and run it with the named dialect's CLI (default sqlite3), showing the result tables in the terminal block.\n"
    "Rules for the terminal screenshot block:\n"
    "* The command line(s) must match the file name exactly (e.g. `$ gcc task1_sum.c -o task1_sum` then `$ ./task1_sum`).\n"
    "* The output must be EXACTLY what the code prints for the shown input: trace the code carefully line by line. "
    "If real execution output is supplied in the context, copy it verbatim instead of tracing.\n"
    "* Keep output deterministic: no unseeded randomness, no timings, no memory addresses, no dates/usernames that change.\n"
    "* Do not add commentary inside the terminal block; it is rendered as an image of a real terminal session.\n\n"

    "=== B) HEAVY_ML (ONE single Google Colab notebook) ===\n"
    "Return ALL work for ML/deep-learning parts as ONE notebook, written in Jupyter 'percent' cell format inside a SINGLE ```python block, "
    "preceded by the line **Notebook file:** `<assignment_short_name>.ipynb`. The platform converts it to a .ipynb file.\n"
    "Cell format:\n"
    "# %% [markdown]\n# ...markdown text, every line prefixed with '# '\n\n# %%\n<code cell>\n\n"
    "Notebook structure (in order): title and problem statement; setup (`!pip install` only if needed, imports, random seeds, GPU check); "
    "dataset loading (public dataset via library, or clearly-labelled synthetic data; never fake real data); preprocessing; model definition; "
    "training; evaluation (metrics + plots); results interpretation; conclusion. Add short markdown cells that explain the theory/answers to any questions.\n"
    "Rules: it must run top-to-bottom in Google Colab with no local files (use files.upload() only if the assignment supplies a dataset); "
    "no separate code files, no terminal screenshots, no extra report outside the notebook; never write fabricated metric numbers into markdown - "
    "describe what the plots/metrics will show instead.\n\n"

    "=== C) DIAGRAM_DESIGN (Draw.io diagram image + XML) ===\n"
    "STEP 1 - Check the plan's reference_diagram_available and reference_diagram_notes and re-inspect the supplied materials for sample diagrams.\n"
    "* If a sample diagram exists: reproduce its EXACT format - same notation, shape types, line styles, colours, fonts, label conventions, "
    "naming style and overall layout - changing only the content to fit this assignment. Do not substitute your own style.\n"
    "* If no sample exists: design a professional, accurate diagram using the standard notation for its type (ER: entities/attributes/cardinality; "
    "UML: correct arrow and relationship types; flowchart: terminator/process/decision shapes; DFD: Gane-Sarson or Yourdon-DeMarco consistently).\n"
    "STEP 2 - Deliver BOTH, for each diagram:\n"
    "### Diagram <N>: <Title>\n"
    "**Diagram image:** `diagram<N>_<short_name>.png` (rendered by the platform from the XML below)\n"
    "**Draw.io XML:**\n"
    "```drawio\n<mxfile>...</mxfile>\n```\n"
    "Followed by a short component breakdown list (components, relationships, what each represents).\n"
    "Diagram quality rules:\n"
    "* NEVER output a single empty or giant plain rectangle. Break architectures into subsystem cards inside a container.\n"
    "* Compact cards: width=\"220\" height=\"90\", rounded=1;arcSize=10;\n"
    "* Rich card text: value=\"&lt;b&gt;Card Name&lt;/b&gt;&lt;hr style='margin:4px 0; border:0; border-top:1px solid ...'/&gt;&bull; Responsibility 1&lt;br/&gt;&bull; Responsibility 2\"\n"
    "* Default semantic colours (only when no reference diagram dictates the style):\n"
    "  - Request / Queue / API Layer: Amber (fillColor=#FEF3C7;strokeColor=#D97706;fontColor=#92400E;)\n"
    "  - Controller / Strategy / Logic: Indigo (fillColor=#EEF2FF;strokeColor=#4F46E5;fontColor=#1E1B4B;)\n"
    "  - Hardware / Worker / Execution: Emerald (fillColor=#ECFDF5;strokeColor=#059669;fontColor=#064E3B;)\n"
    "  - Containers / Boundaries: Slate (fillColor=#F8FAFC;strokeColor=#CBD5E1;fontColor=#475569;dashed=1;)\n"
    "* Connectors: edgeStyle=orthogonalEdgeStyle;rounded=1;strokeColor=#4F46E5;strokeWidth=2;endArrow=classic;endFill=1;\n"
    "* Every mxCell needs a unique id and a valid parent; every edge must reference existing source/target ids; XML must be well-formed, "
    "with no overlapping shapes, no crossing lines where avoidable, and all text readable.\n"
    "* The diagram must be complete and accurate to the assignment text: every required entity/class/process/relationship appears and is labelled.\n\n"
    "General: do not write theory essays; only brief explanations of how each artifact works.\n\n"
    "ASSIGNMENT AND SUPPLIED MATERIALS:\n{assignment}\n{context}"
)

REPORTING_PROMPT = (
    "You are the final quality gate. Review the Planner's JSON plan and both specialist outputs against EVERY entry in parts_required.\n\n"
    "STEP 1 - COMPLETENESS CHECK\n"
    "For each part in the plan confirm it is answered, in order, with its original numbering and title. "
    "Check constraints (word limit, language, citation style) and marks emphasis. Confirm every item in artifacts_required exists. "
    "List anything missing under 'Unresolved gaps' - do NOT silently invent content to fill gaps.\n\n"
    "STEP 2 - ASSEMBLE BY domain_type\n"
    "- THEORY_ACADEMIC / QUANTITATIVE_MATH: the complete, polished, ready-to-submit written solution - Title, Executive Summary, "
    "every question answered in full under its own numbered heading, Real-World Applications, Conclusion, References. "
    "Omit all code, compiler and terminal headings.\n"
    "- CODING_LAB / SQL_DATABASE / DATA_ANALYSIS: for each task keep Problem Statement -> `**File:**` code block -> `**Screenshot:**` terminal block. "
    "Verify that every code file has a matching terminal screenshot block, that the commands use the exact file name, and that the output "
    "matches what the code would really print. Keep code blocks and file/screenshot name lines intact.\n"
    "- DIAGRAM_DESIGN: keep, for each diagram, the `**Diagram image:**` line, the complete ```drawio XML block and the component breakdown. "
    "Confirm the XML is well-formed and (if reference_diagram_available is true) that the style still matches the reference.\n"
    "- HEAVY_ML: return ONLY the single notebook - the `**Notebook file:**` line followed by the one ```python percent-format block. "
    "No report, no extra files, no Quality Status outside it; put any notes or assumptions in a final markdown cell of the notebook.\n"
    "- MIXED: follow the assignment's original part order; apply the matching format to each part.\n"
    "Omit specialist sections that returned N/A.\n\n"
    "STEP 3 - FIX AND VERIFY\n"
    "- Fix clear errors: syntax mistakes, inconsistent code vs. output, broken Markdown, malformed XML, arithmetic slips, wrong numbering.\n"
    "- Preserve specialist code and diagrams intact; edit only what is demonstrably wrong.\n"
    "- Remove any invented or unverifiable citations; keep only real, supplied or consulted sources.\n"
    "- Do not add content the specialists did not produce unless fixing a gap you can fill with certainty.\n\n"
    "STEP 4 - OUTPUT\n"
    "Return the complete deliverable in clean Markdown, then (except for HEAVY_ML) a short block:\n"
    "`## Quality Status` with: Completeness (X of Y parts done), Fixes applied, Unresolved gaps / missing information, Assumptions made.\n\n"
    "ORIGINAL ASSIGNMENT:\n{assignment}\n\nSUPPLIED CONTEXT:\n{context}"
)


def build_assignment_crew(on_task_complete: Callable[[str, Any], None] | None = None) -> Crew:
    """Build the four-agent sequential crew and optionally report task completion."""
    planner = Agent(
        role="Planner / Analyzer",
        goal="Classify the assignment, split it into parts, and produce a precise dependency-aware JSON plan with correct specialist routing and artifact list.",
        backstory=(
            "You are a senior academic coordinator who reads university assignments of every kind - essays, labs, "
            "diagrams, ML, math, databases - and identifies exactly what must be delivered. You never answer the "
            "assignment yourself and you flag anything unclear instead of guessing."
        ),
        llm=_agent_llm("planner"), allow_delegation=False, verbose=False,
    )
    researcher = Agent(
        role="Theory / Research Specialist",
        goal="Write complete, accurate theory solutions and worked answers for the assigned parts using only supplied or genuinely consulted evidence.",
        backstory=(
            "You write clear, full-length university-level solutions and step-by-step workings, mark evidence gaps openly, "
            "and never invent citations, statistics or sources."
        ),
        llm=_agent_llm("theory_research"), allow_delegation=False, verbose=False,
    )
    coder = Agent(
        role="Coder / Diagram Specialist",
        goal="Produce correct single-file code with matching terminal screenshots, a single Colab notebook for ML tasks, and Draw.io diagrams (image + XML) that follow any supplied reference style.",
        backstory=(
            "You are a careful engineer who re-checks code before delivering it, makes terminal output match the code exactly, "
            "copies the style of sample diagrams when they exist, and otherwise designs clean professional diagrams."
        ),
        llm=_agent_llm("coder_diagram"), allow_delegation=False, verbose=False,
    )
    reporter = Agent(
        role="Reporter / Fixer",
        goal="Verify all work against the plan, fix clear errors, and return the final polished deliverable in the exact format its domain requires.",
        backstory=(
            "You are an exacting editor. You preserve specialist details, correct demonstrable mistakes, "
            "remove unverifiable claims and openly list anything unresolved."
        ),
        llm=_agent_llm("reporter_fixer"), allow_delegation=False, verbose=False,
    )

    def completed(role: str):
        if on_task_complete is None:
            return None
        return lambda output: on_task_complete(role, output)

    planning_task = Task(
        description=PLANNER_PROMPT,
        expected_output="Only raw valid JSON matching the requested plan schema, with no markdown fences or extra text.",
        agent=planner, callback=completed("planner"),
    )
    research_task = Task(
        description=RESEARCH_PROMPT,
        expected_output="A complete Markdown written solution for the assigned parts, or the exact N/A line when not required.",
        agent=researcher, context=[planning_task], callback=completed("theory_research"),
    )
    coding_task = Task(
        description=CODING_PROMPT,
        expected_output=(
            "Markdown containing, as the plan requires: named code files with matching terminal-screenshot blocks, "
            "a single percent-format Colab notebook, or Draw.io XML with a diagram image reference - or the exact N/A line when not required."
        ),
        agent=coder, context=[planning_task, research_task], callback=completed("coder_diagram"),
    )
    reporting_task = Task(
        description=REPORTING_PROMPT,
        expected_output="The complete reviewed deliverable in clean Markdown (for HEAVY_ML only the single notebook), followed by a Quality Status block where applicable.",
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