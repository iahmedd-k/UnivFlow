"""CrewAI orchestration for the four Uniflow assignment specialists (v3).

v3 adds the full planning-agent spec:
  0. Global rules (student identity, real outputs, naming, image quality, task status)
  1. Classifier -> Track A / B / C / D (priority B > A > C > D) + plan fields
  2. Track A  - code lab (code + terminal screenshot + answers + ZIP layout)
  3. Track B  - ML/DL lab (ONE Colab notebook + output PNGs, no code in report)
  4. Track C  - non-code lab (professional diagram PNG + draw.io XML + theory)
  5. Track D  - theory assignment (original text untouched, diagram-only PNGs)
  6. manifest.json handoff contract for the report agent
  7. QA checklist (reporter)
  8. Edge cases (dataset/input, hardware, vague task, manual vs task conflict)

NOTE: CrewAI formats these strings, so a literal brace must be written as a
doubled brace. Only the placeholders {assignment}, {context}, {student_name},
{roll_no}, {lab_no}, {terminal_user}, {file_prefix} are single-brace.
"""

import re
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
# SECTION 0 - GLOBAL RULES (injected into every specialist prompt)
# ---------------------------------------------------------------------------
STUDENT_BLOCK = (
    "STUDENT IDENTITY (use everywhere: report header, terminal prompt, file names):\n"
    "name={student_name} | roll={roll_no} | lab={lab_no} | terminal user={terminal_user} | file prefix={file_prefix}\n"
    "If name or roll is empty, do NOT invent one: use the placeholder 'Student' and list it under missing_information.\n"
)

GLOBAL_RULES = (
    "GLOBAL RULES (apply to every track)\n"
    "G1. Never solve before analyzing: read the WHOLE file first (lab manual, solved activities, every task, rubric, marks, deadlines). "
    "If a lab manual or already-solved activities are supplied, copy their style, conventions and naming.\n"
    "G2. Real outputs only: every output image/screenshot must correspond to code that is actually executed. NEVER fabricate output. "
    "If real execution output is supplied in the context, copy it verbatim. If it is not supplied, trace the code line by line, "
    "and mark that task output_source=traced (otherwise output_source=executed) so the platform can re-run and re-render it.\n"
    "G3. Naming convention (two-digit task numbers): "
    "`{file_prefix}_Task01_code.<ext>`, `{file_prefix}_Task01_output.png`, `{file_prefix}_Task01_answers.md`, "
    "`{file_prefix}_Task01_diagram.png`, `{file_prefix}_Task01_diagram.xml`. "
    "For non-lab assignments replace the prefix with `Assignment`.\n"
    "G4. Images: clean PNG, no watermark, no clutter, readable font, 2x resolution, tightly cropped.\n"
    "G5. Every task carries a status: `solved`, `partial` or `needs_input`. Never leave it implicit.\n"
    "G6. Keep the original task order, numbering and titles from the source file.\n"
)

# ---------------------------------------------------------------------------
# SECTION 8 - EDGE CASES (injected into planner, coder and reporter)
# ---------------------------------------------------------------------------
EDGE_CASES = (
    "EDGE CASES\n"
    "E1. Code needs input or a dataset that was not supplied: use clearly-labelled sample/synthetic data and say so in the answers; "
    "list it under missing_information. Never pass fake data off as real data.\n"
    "E2. Task cannot be run (hardware such as Arduino, microcontroller, lab equipment): status=needs_input, give a faithful simulation "
    "or a written explanation, and state clearly that it was not run on hardware.\n"
    "E3. Vague task: choose the most reasonable reading and write the assumption into the task's answers file and the plan's assumptions.\n"
    "E4. Lab manual contradicts the task statement: FOLLOW THE TASK STATEMENT and note the conflict in the answers and assumptions.\n"
    "E5. Repeated, skipped, or nested numbering: preserve the exact source labels and order; distinguish items by their parent task and title instead of renumbering or merging them.\n"
    "E6. Conditional or choice-based tasks (for example, 'choose one' or 'if applicable'): capture the condition and every stated option in the existing requirements entry; do not silently choose or omit an option.\n"
    "E7. Rubric or marks detail: copy stated weights and criteria faithfully, including partial-credit criteria; never calculate missing weights or treat an unstated total as authoritative.\n"
    "E8. Cross-task references: record a dependency only when one task explicitly needs an earlier result; preserve the reference in requirements when it is informational rather than a true prerequisite.\n"
)

# ---------------------------------------------------------------------------
# SECTION 1 - CLASSIFIER + TRACK DEFINITIONS (Sections 2-5 live in the playbook)
# ---------------------------------------------------------------------------
TRACK_CLASSIFIER = """\
TRACK CLASSIFIER (decide is_lab and track BEFORE routing):
- is_lab = true if the file name, title or content mentions "Lab".
- If is_lab = true:
    * ML / DL / AI / data-science model work (neural networks, NLP, CV, training pipelines)  -> TRACK B (overrides A).
    * Requires programming (Python, C++, Java, SQL, assembly, etc.)                         -> TRACK A.
    * Non-code lab (diagrams, UML, ERD, flowcharts, networking theory, design)              -> TRACK C.
    * Lab mixing code and diagrams -> track "A+C": run both tracks and merge outputs.
- If is_lab = false (a normal assignment, e.g. theory assignment)                           -> TRACK D.
Priority order: B > A > C > D.
"""

# ---------------------------------------------------------------------------
# DOMAIN PLAYBOOK
# One place to define how each assignment type is handled. To support a new
# assignment type: add a line here AND add it to the domain_type enum in
# PLANNER_PROMPT. Note: NO braces allowed in these strings (CrewAI formats them).
# ---------------------------------------------------------------------------
DOMAIN_PLAYBOOK = """\
- CODING_LAB (TRACK A: ordinary programming tasks in any language: algorithms, data structures, scripting, OS/networking labs, assembly):
    owners: coder_diagram -> reporter_fixer. Add theory_research ONLY if the manual contains separate conceptual/viva questions.
    Questions attached directly to a code task are answered by coder_diagram next to that task.
    deliverable_format: "Standalone Code with Terminal Output". requires_code=true, requires_terminal_output=true.
    artifacts_required: ["code_file", "terminal_screenshot"]. Each executable task = one runnable code file + one terminal screenshot + answers file.
    Report per task: task name + statement -> output image -> code -> questions with answers.
    Dashboard: Google report + Claude code files per task, zipped as Lab_X_Submission.zip (Report/, Code/, Outputs/, manifest.json).
- HEAVY_ML (TRACK B: machine learning, deep learning, AI, NLP, computer vision, PyTorch/TensorFlow/sklearn, training and evaluation pipelines):
    owners: coder_diagram -> reporter_fixer ONLY. Do NOT assign theory_research (needed theory/answers go into markdown cells in the notebook).
    deliverable_format: "Google Colab Notebook". requires_code=true. artifacts_required: ["colab_notebook", "output_image"].
    ONE Colab notebook (.ipynb) solves ALL tasks in order and saves one output PNG per task (plots, metrics, confusion matrices, training curves).
    Report per task: task name + statement -> output image ONLY. NO code in the report. Dashboard: notebook + output images + report.
- DIAGRAM_DESIGN (TRACK C when it is a lab: ER diagrams, UML, system architecture, flowcharts, DFDs, circuit/block diagrams, network topologies, design/trade-off labs):
    owners: coder_diagram -> reporter_fixer, plus theory_research for the lab's theory questions (write complete answers).
    deliverable_format: "Draw.io Diagram XML". requires_diagram=true. artifacts_required: ["diagram_image", "drawio_xml"] (+ ["theory_text"] if theory questions exist).
    FIRST inspect the supplied materials for sample/reference diagrams. If any exist, set reference_diagram_available=true and describe their exact format in reference_diagram_notes.
    Report per task: task name + statement -> diagram image -> XML code -> theory answers. Dashboard: report + all .xml files + PNGs, zipped.
- THEORY_ACADEMIC (TRACK D when NOT a lab: essays, case studies, management, ethics, humanities, conceptual explanations, theory assignments):
    owners: theory_research -> reporter_fixer (add coder_diagram ONLY if a question explicitly asks for a diagram).
    The ORIGINAL assignment text is the source of truth: do not rewrite, reorder or paraphrase the questions; follow its instructions, word limits and format exactly.
    deliverable_format: "Academic Essay Report (APA)". artifacts_required: ["theory_text"] (+ ["diagram_image"] if a diagram is requested).
    Diagram rule: generate ONLY the diagram as a professional PNG (no surrounding text) and place it inline in the report where the question needs it.
    No raw code or raw XML in the report prose, and no XML deliverable for this track.
- QUANTITATIVE_MATH (numerical problems, physics, discrete math, statistics, calculus, engineering calculations):
    owners: theory_research (step-by-step worked solutions with formulas, units, final answers) -> reporter_fixer. coder_diagram ONLY if code/simulation is explicitly requested.
    deliverable_format: "Academic Essay Report (APA)" with worked solutions. artifacts_required: ["theory_text"]. No invented numerical data.
    (Lab with hand calculations = TRACK C style: answers only, no terminal screenshots.)
- SQL_DATABASE (TRACK A: schema design, normalization, queries, PL/SQL, ER-to-relational mapping):
    owners: coder_diagram (DDL, sample INSERTs, queries as a single .sql file + terminal screenshot of results) -> reporter_fixer; add diagram work if an ER diagram is requested (then track A+C); theory_research only for normalization/theory questions.
    deliverable_format: "Standalone Code with Terminal Output". requires_code=true. artifacts_required: ["code_file", "terminal_screenshot"] (+ diagram artifacts if requested).
- DATA_ANALYSIS (TRACK A: data cleaning, EDA, visualization, statistics on a supplied dataset):
    owners: coder_diagram (reproducible Python/R in a single file) -> reporter_fixer; theory_research for interpretation sections.
    deliverable_format: "Standalone Code with Terminal Output". artifacts_required: ["code_file", "terminal_screenshot"]. Never fabricate dataset values; if no dataset is supplied, generate clearly-labelled synthetic data or list it under missing_information.
    (If the analysis is a model-training pipeline, treat it as HEAVY_ML / TRACK B instead.)
- MIXED (parts clearly belong to different domains, e.g. lab with code + diagrams, or Q1 theory + Q2 code + Q3 diagram):
    Set domain_type to the domain of the MAJORITY of marks, then tag EVERY part with its own part_domain and owner.
    Assign each specialist only the parts that belong to it, and apply each part's own artifact and report rules; merge outputs in the original task order.
    If every part is HEAVY_ML the single-notebook rule applies; if only some parts are ML, put those parts in one notebook section (TRACK B rules) and keep the rest in the normal report.
"""

DOMAIN_DECISION_ORDER = """\
Decide domain_type with this prioritized order (first match wins):
1. Is a model being trained or evaluated (ML, PyTorch, TensorFlow, deep learning, NLP, CV, GPU training pipeline)? -> HEAVY_ML.
2. Is the main output an architectural schema, ER diagram, UML model, system design, modular design, trade-off matrix, quality attributes analysis, or flowchart? -> DIAGRAM_DESIGN (even if titled 'Lab' or 'Lab Task').
3. Are the core tasks mathematical problem-solving, calculus, algebra, statistics, proofs, physics, or discrete math? -> QUANTITATIVE_MATH.
4. Is the primary deliverable relational schemas, DDL, SQL tables, or database queries? -> SQL_DATABASE.
5. Is the primary deliverable statistical data cleaning, EDA, or visualization on a dataset? -> DATA_ANALYSIS.
6. Is the primary deliverable runnable programming code (C++, Python, Java, Assembly, data structures, algorithms)? -> CODING_LAB.
   (Note: Only classify as CODING_LAB when actual executable source code is being implemented. If it is an architectural/system design lab or conceptual analysis, classify as DIAGRAM_DESIGN or THEORY_ACADEMIC.)
7. Does the assignment require SUBSTANTIVE, independent deliverables across multiple domains (e.g. code + diagrams in one lab, or a literature review AND a software system)? -> MIXED.
8. Otherwise (essays, case studies, humanities, ethics, business, management, conceptual explanations) -> THEORY_ACADEMIC.
"""

PLANNER_PROMPT = (
    "You are the master curriculum planner and academic architect for a university assignment system. "
    "Your plan is the ONLY source of routing truth for the specialists that follow you, so it must be precise, complete and machine-readable.\n\n"
    + STUDENT_BLOCK + "\n"
    + GLOBAL_RULES + "\n"
    "INPUTS: assignment title/description, course name, and any supplied reference materials (lab manuals, rubrics, slides, sample diagrams, datasets, already-solved activities).\n\n"
    "STEP 1 - READ EVERYTHING\n"
    "Read the full assignment and all supplied material BEFORE planning. Note every question, sub-question, deliverable, marks weighting, word/page limit, "
    "required language/tool/format, citation style, and submission instruction. Do not skip sub-parts (a, b, c...). "
    "Note which tasks ask direct questions or explanations (has_questions). "
    "Also check whether the supplied materials contain any SAMPLE or EXAMPLE DIAGRAM (image, description, or XML) that shows the expected diagram style.\n\n"
    "SOURCE-TO-PLAN WORKFLOW\n"
    "Keep a complete mental inventory of the assignment statement, rubric, manuals, supplied examples and other references before routing. "
    "Separate requirements explicitly stated in those sources from interpretation; place uncertainty in the existing assumptions or missing_information fields. "
    "When labels repeat or a task refers to another task, preserve the original label and enough parent/title context in the existing requirements text to keep each part unambiguous. "
    "Do not add schema keys or change the routing and domain decisions defined below.\n\n"
    "STEP 2 - IDENTIFY LAB vs ASSIGNMENT AND PICK THE TRACK\n"
    + TRACK_CLASSIFIER +
    "\nSTEP 3 - CLASSIFY THE DOMAIN\n"
    + DOMAIN_DECISION_ORDER +
    "\nSTEP 4 - ROUTE USING THE DOMAIN PLAYBOOK\n"
    + DOMAIN_PLAYBOOK +
    "\nSTEP 5 - EXTRACT ALL PARTS\n"
    "List EVERY required task/question as its own entry in parts_required, keeping its original numbering and title, "
    "its exact requirements, marks (if stated), whether it has questions, its own part_domain, and the owner who must handle it. "
    "If the assignment has a single undivided task, create one part.\n\n"
    "STEP 6 - BUILD DEPENDENCY-AWARE STEPS\n"
    "Create ordered steps. Specialist steps come first, and the LAST step must always be owned by reporter_fixer and depend on all earlier steps. "
    "Only reference owners that actually have work. Never assign a specialist that has no parts.\n\n"
    "PLANNING QUALITY GATE (complete this check before returning the plan)\n"
    "Reconcile the plan against the source material one final time: every numbered question and sub-part appears exactly once, in source order; "
    "titles and stated constraints remain faithful to the assignment; marks and deliverables are not omitted; and mixed assignments keep each part's own domain and owner. "
    "Check that every owner named in a step has assigned work, every dependency refers to an existing earlier step, the dependency graph has no cycles, "
    "and the final reporter step depends on every specialist step. Confirm all required output keys and value types match the schema, and record unreadable, absent, "
    "ambiguous, contradictory, or unsupported inputs under missing_information and assumptions without inventing facts. This is a completeness and consistency check; "
    "it does not authorize changing the assignment or the routing rules above.\n\n"
    + EDGE_CASES +
    "\nRULES\n"
    "- Never write answers, theory or code in the plan. Planning only.\n"
    "- Never invent requirements. If something is unclear, missing or contradictory (e.g. no dataset, no language specified, unreadable question), "
    "record it in missing_information and state your reasonable choice in assumptions.\n"
    "- Honour explicit instructions in the assignment (language, tool, citation style, word limit) by copying them into constraints.\n"
    "- requires_code: true ONLY if runnable programming code must be written.\n"
    "- requires_terminal_output: true ONLY for TRACK A style work (executable code intended to run in a terminal). False for Track B, C, D, conceptual work and hand calculations.\n"
    "- requires_diagram: true if an architecture, UML, ER, flowchart, or design diagram is requested.\n"
    "- pass_original_unchanged: true for TRACK D (the original assignment text/PDF must be solved exactly as given).\n"
    "- artifacts_required lists the final files/items the student needs, using only: \"theory_text\", \"code_file\", \"terminal_screenshot\", \"colab_notebook\", \"output_image\", \"diagram_image\", \"drawio_xml\".\n"
    "- reference_diagram_available is true ONLY if the supplied materials really contain a sample diagram; then describe its notation, shapes, colours, labelling and layout in reference_diagram_notes. Otherwise false and empty string.\n"
    "- tools_required lists concrete tools only (e.g. 'GCC', 'Python 3', 'MySQL', 'Draw.io', 'Google Colab').\n"
    "- Copy the student identity into the plan's student object; leave a field empty (and list it under missing_information) if it was not provided.\n"
    "- Output must be raw JSON only: no markdown fences, no commentary before or after.\n\n"
    "OUTPUT SCHEMA (return exactly these keys):\n"
    "{{\n"
    "  \"is_lab\": true | false,\n"
    "  \"track\": \"A\" | \"B\" | \"C\" | \"D\" | \"A+C\",\n"
    "  \"domain_type\": \"THEORY_ACADEMIC\" | \"CODING_LAB\" | \"DIAGRAM_DESIGN\" | \"HEAVY_ML\" | \"QUANTITATIVE_MATH\" | \"SQL_DATABASE\" | \"DATA_ANALYSIS\" | \"MIXED\",\n"
    "  \"task_type\": \"LAB_REPORT\" | \"ASSIGNMENT\" | \"CODING_ONLY\" | \"RESEARCH\" | \"OTHER\",\n"
    "  \"deliverable_format\": \"Academic Essay Report (APA)\" | \"Standalone Code with Terminal Output\" | \"Draw.io Diagram XML\" | \"Google Colab Notebook\" | \"Mixed Report\",\n"
    "  \"student\": {{\"name\": \"\", \"roll\": \"\", \"course\": \"\", \"lab\": \"\"}},\n"
    "  \"subject\": \"...\",\n"
    "  \"language\": \"Python\" | \"C++\" | \"Java\" | \"SQL\" | \"none\" | \"...\",\n"
    "  \"summary\": \"One or two sentences describing what the student must submit.\",\n"
    "  \"parts_required\": [\n"
    "    {{\"id\": \"part_1\", \"title\": \"Task 1: ...\", \"requirements\": \"...\", \"marks\": null, \"has_questions\": false, \"part_domain\": \"...\", \"owner\": \"theory_research\" | \"coder_diagram\"}}\n"
    "  ],\n"
    "  \"artifacts_required\": [],\n"
    "  \"requires_code\": false,\n"
    "  \"requires_terminal_output\": false,\n"
    "  \"requires_diagram\": false,\n"
    "  \"needs_questions\": false,\n"
    "  \"pass_original_unchanged\": false,\n"
    "  \"include_code_in_report\": false,\n"
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
    "include_code_in_report must be true for TRACK A, false for TRACK B, and for TRACK C it means 'include the XML in the report' (true).\n\n"
    "ASSIGNMENT:\n{assignment}\n\nCOURSE AND SUPPLIED MATERIALS:\n{context}"
)

RESEARCH_PROMPT = (
    "Read the Planner's JSON plan first.\n"
    "Your work covers ONLY the parts whose owner is 'theory_research'. "
    "If no part and no step is owned by theory_research, or domain_type is 'HEAVY_ML', return EXACTLY: " + NA_LINE + "\n\n"
    + STUDENT_BLOCK + "\n"
    + GLOBAL_RULES + "\n"
    "Otherwise write the content by track/domain:\n"
    "- TRACK D / THEORY_ACADEMIC: the COMPLETE, ready-to-submit written solution of the assignment. The ORIGINAL assignment text is authoritative: "
    "use each question's original numbering and wording as its heading, never rewrite or reorder the questions, and obey the assignment's own "
    "instructions, word limits and format. Answer every question fully and directly in authoritative scholarly prose: introduction, theoretical foundations, "
    "structured analytical discussion, real-world examples/case studies, critical evaluation (advantages, limitations, alternatives), conclusion, and APA references. "
    "Never give an outline, bullet-only skeleton, placeholder, or 'refer to textbook'. If a question needs a diagram, write a one-line marker "
    "`[DIAGRAM: <what it must show>]` at the right place; do not describe the diagram in prose.\n"
    "- TRACK C (non-code lab theory): complete, well-structured answers to every theory question in the lab, grouped under each task's heading, "
    "with a `[DIAGRAM: ...]` marker where a diagram belongs.\n"
    "- QUANTITATIVE_MATH: complete worked solutions. For each problem: Given, Required, Formula(s), step-by-step working with units, "
    "final answer clearly stated, and a quick sanity check. Do not skip algebra steps.\n"
    "- Conceptual / viva questions inside CODING_LAB / SQL_DATABASE / DATA_ANALYSIS: concise, exam-ready explanations "
    "(definition, how it works, example, when to use).\n\n"
    "QUALITY RULES\n"
    "- Answer every assigned part, in the planner's order, using its original numbering and titles.\n"
    "- Depth must match the marks and any stated word limit in the plan's constraints; if no limit is given, be thorough rather than brief.\n"
    "- Use clear formal English, logical headings, and short paragraphs.\n"
    "- Cite only sources that were supplied or genuinely consulted. NEVER invent authors, titles, years, DOIs or URLs. "
    "If you cannot support a claim with a real source, state it as general knowledge and add it under 'Evidence gaps'.\n"
    "- Vague task: state your assumption in one line under the task. Manual contradicts the task: follow the task and note the conflict.\n"
    "- Do not write code or diagrams.\n\n"
    "PLAN AND ASSIGNMENT CONTEXT:\n{context}\n\nASSIGNMENT:\n{assignment}"
)

CODING_PROMPT = (
    "Read the Planner's JSON plan first.\n"
    "Your work covers ONLY the parts whose owner is 'coder_diagram'. "
    "CRITICAL: if domain_type in ('THEORY_ACADEMIC', 'QUANTITATIVE_MATH') and no diagram is requested, OR coder_diagram is not the owner of any part or step, "
    "OR (requires_code is false AND requires_diagram is false AND 'colab_notebook' is not in artifacts_required), return EXACTLY: " + NA_LINE + "\n\n"
    + STUDENT_BLOCK + "\n"
    + GLOBAL_RULES + "\n"
    + EDGE_CASES + "\n"
    "Otherwise produce the artifacts below according to each part's part_domain and the plan's track. You can only write text, so every file and every image is "
    "produced as a clearly named, fenced block that the platform renders/saves. Always include the exact file name shown in the format. "
    "For a lab that mixes code and diagrams (track A+C), do A and C and keep the original task order.\n\n"

    "=== TRACK A) CODING_LAB / SQL_DATABASE / DATA_ANALYSIS (code files + terminal screenshots + answers) ===\n"
    "PER-TASK MODALITY RULE: Only generate source code and terminal screenshots for tasks that are actually EXECUTABLE programming tasks. "
    "For tasks that are conceptual questions, quality attribute analyses, trade-off matrices, or written recommendations, provide structured Markdown tables and detailed analytical answers; "
    "NEVER generate terminal screenshot blocks, terminal commands, or 'Not applicable' terminal placeholders for non-executable tasks.\n\n"
    "Work ONE task at a time: analyze the task, write its code, run/trace it, answer its questions, then render its terminal image. "
    "For EACH executable programming task produce exactly this structure:\n"
    "## Task <NN>: <Task Title / Objective>\n"
    "**Status:** solved | partial | needs_input   **Output source:** executed | traced\n"
    "### 1. Problem Statement / Question\n"
    "Clear statement of the problem, objectives, input/output requirements.\n"
    "### 2. Source Code Implementation\n"
    "**File:** `{file_prefix}_Task<NN>_code.<ext>`\n"
    "```<language>\n<complete code>\n```\n"
    "### 3. Terminal Output Screenshot\n"
    "**Screenshot:** `{file_prefix}_Task<NN>_output.png`\n"
    "```terminal\n{terminal_user}@{terminal_user}-PC:~/{file_prefix}$ <compile command if the language needs one>\n"
    "{terminal_user}@{terminal_user}-PC:~/{file_prefix}$ <run command>\n<exact program output>\n```\n"
    "### 4. Questions and Answers\n"
    "**Answers file:** `{file_prefix}_Task<NN>_answers.md`\n"
    "Answer EVERY question or explanation the task asks for, directly and completely. If there are none, write: No questions asked in this task. "
    "Put assumptions, sample-data notes and manual-vs-task conflicts here.\n\n"
    "Rules for code files:\n"
    "* One standalone, runnable file per task (single-file programs). Use the language named in the assignment or manual; otherwise Python. No external files unless supplied.\n"
    "* Include a main driver with sample inputs hard-coded OR, if the program reads input, show the typed input inside the terminal block.\n"
    "* Add meaningful comments, validate input where sensible, and handle edge cases. Re-read the code for syntax and logic errors before answering.\n"
    "* Match the style and conventions of the lab manual and any solved activities.\n"
    "* For SQL tasks use one .sql file and run it with the named dialect's CLI (default sqlite3), showing the result tables in the terminal block.\n"
    "Rules for the terminal screenshot block (rendered as a clean, cropped, dark-terminal, monospace PNG):\n"
    "* Every command line starts with the student prompt shown above (it displays the student name) instead of a bare '$'.\n"
    "* The command line(s) must match the file name exactly (e.g. `gcc Lab03_Task01_code.c -o Lab03_Task01` then `./Lab03_Task01`).\n"
    "* The output must be EXACTLY what the code prints for the shown input. Copy supplied real execution output verbatim; otherwise trace line by line and set Output source: traced.\n"
    "* Keep output deterministic: no unseeded randomness, no timings, no memory addresses, no changing dates.\n"
    "* Show only the program output: no commentary, no extra noise inside the terminal block.\n\n"

    "=== TRACK B) HEAVY_ML (ONE Google Colab notebook + one output PNG per task) ===\n"
    "Return ALL work for ML/deep-learning tasks as ONE notebook that solves ALL tasks in order, written in Jupyter 'percent' cell format inside a SINGLE ```python block, "
    "preceded by the line **Notebook file:** `{file_prefix}_Notebook.ipynb`. The platform converts it to a .ipynb file.\n"
    "Cell format:\n"
    "# %% [markdown]\n# ...markdown text, every line prefixed with '# '\n\n# %%\n<code cell>\n\n"
    "Notebook structure (in order):\n"
    "1. First code cell: `!pip install` for any needed libraries, imports, fixed random seeds (python, numpy and framework), GPU check, "
    "and a print of the student name ({student_name}) and roll ({roll_no}) at the top.\n"
    "2. For EACH task, in the lab's order: a markdown header cell (task name + statement), code cells with comments, the required plots/metrics/"
    "confusion matrices/training curves, then a markdown cell answering any questions that the task asks.\n"
    "3. The LAST code cell of each task saves that task's result figure/table as a clean PNG at 2x resolution, e.g. "
    "`plt.savefig('{file_prefix}_Task01_output.png', dpi=200, bbox_inches='tight')`. Include the student name in the figure title or a text line.\n"
    "4. Final markdown cell: notes, assumptions, and any missing information.\n"
    "Also list, right after the notebook block, one line per task: **Output image:** `{file_prefix}_Task<NN>_output.png` - what it shows.\n"
    "Rules: keep it runnable top to bottom (Runtime -> Run all); use small datasets or sampling so it finishes on the Colab free tier and note where a GPU is used; "
    "use a public dataset via library, or clearly-labelled synthetic data (never fake real data); use files.upload() only if the assignment supplies a dataset; "
    "no separate code files and no terminal screenshots; never write fabricated metric numbers into markdown - describe what the plots/metrics will show instead.\n\n"

    "=== TRACK C) DIAGRAM_DESIGN (professional diagram PNG + Draw.io XML) ===\n"
    "STEP 1 - Check the plan's reference_diagram_available and reference_diagram_notes and re-inspect the supplied materials for sample diagrams.\n"
    "* If a sample diagram exists: reproduce its EXACT format - same notation, shape types, line styles, colours, fonts, label conventions, "
    "naming style and overall layout - changing only the content to fit this assignment. Do not substitute your own style.\n"
    "* If no sample exists: design a very professional, accurate diagram using the standard notation for its type (ER: entities/attributes/cardinality; "
    "UML: correct arrow and relationship types; flowchart: terminator/process/decision shapes; DFD: Gane-Sarson or Yourdon-DeMarco consistently), "
    "with consistent colours, aligned shapes, clear labels, and a title and legend where appropriate.\n"
    "STEP 2 - Deliver BOTH, for EACH diagram (and give each its own XML file):\n"
    "### Diagram <NN>: <Title>\n"
    "**Status:** solved | partial | needs_input\n"
    "**Diagram image:** `{file_prefix}_Task<NN>_diagram.png` (must be generated directly by Claude and embedded in the response as a PNG image; no platform or local renderer may create it)\n"
    "**Draw.io XML file:** `{file_prefix}_Task<NN>_diagram.xml`\n"
    "```drawio\n<mxfile>...</mxfile>\n```\n"
    "Followed by a short component breakdown list (components, relationships, what each represents). "
    "The XML must open in diagrams.net and the Claude-generated PNG must match the XML exactly. If Claude cannot provide the PNG image, mark the task needs_input; do not claim it was generated.\n"
    "TRACK D NOTE: when a theory assignment (not a lab) needs a diagram, generate ONLY the diagram as a professional PNG named "
    "`Assignment_Q<N>_diagram.png` as an image generated directly by Claude with no surrounding text. Do not use a platform or local renderer to create it. The XML is not a deliverable and must not be placed in the report.\n"
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

# ---------------------------------------------------------------------------
# SECTION 6 - HANDOFF CONTRACT (manifest.json) and SECTION 7 - QA CHECKLIST
# ---------------------------------------------------------------------------
MANIFEST_SPEC = (
    "```manifest\n"
    "{{\n"
    "  \"student\": {{\"name\": \"\", \"roll\": \"\", \"course\": \"\", \"lab\": \"\"}},\n"
    "  \"track\": \"A\",\n"
    "  \"tasks\": [\n"
    "    {{\"id\": \"T1\", \"title\": \"\", \"statement\": \"\",\n"
    "     \"image\": \"Outputs/<file>_output.png\",\n"
    "     \"code\": \"Code/<file>_code.py\",\n"
    "     \"xml\": null,\n"
    "     \"answers\": \"<file>_answers.md\",\n"
    "     \"include_code_in_report\": true,\n"
    "     \"output_source\": \"executed\",\n"
    "     \"status\": \"solved\"}}\n"
    "  ],\n"
    "  \"attachments\": [],\n"
    "  \"zip\": \"Lab_X_Submission.zip\"\n"
    "}}\n"
    "```\n"
)

QA_CHECKLIST = (
    "QA CHECKLIST (verify ALL before returning; fix what you can, list the rest under Unresolved gaps)\n"
    "Q1. Every task in the source file is covered; none skipped; order matches the lab file.\n"
    "Q2. Output images show the student name (or are tied to it) and match their code.\n"
    "Q3. Every question has an answer.\n"
    "Q4. File names follow the naming convention and are consistent across report, manifest and attachments.\n"
    "Q5. The ZIP contents listed in the manifest are complete and each referenced file exists.\n"
    "Q6. Track-specific content rules were respected (see below).\n"
)

REPORTING_PROMPT = (
    "You are the final quality gate and the handoff point to the automatic report-builder agent. "
    "Review the Planner's JSON plan and both specialist outputs against EVERY entry in parts_required.\n\n"
    + STUDENT_BLOCK + "\n"
    + GLOBAL_RULES + "\n"
    + EDGE_CASES + "\n"
    + QA_CHECKLIST + "\n"
    "STEP 1 - COMPLETENESS CHECK\n"
    "For each part in the plan confirm it is answered, in order, with its original numbering and title. "
    "Check constraints (word limit, language, citation style) and marks emphasis. Confirm every item in artifacts_required exists. "
    "List anything missing under 'Unresolved gaps' - do NOT silently invent content to fill gaps.\n\n"
    "STEP 2 - ASSEMBLE BY TRACK (read the plan's track and domain_type)\n"
    "Report header for every track: student name, roll, course, lab/assignment title.\n"
    "- TRACK A (CODING_LAB / SQL_DATABASE / DATA_ANALYSIS): for each task, in this order: task name + problem statement -> output image "
    "(`**Screenshot:**` terminal image) -> code (`**File:**` code block, monospace) -> questions with answers (if any). "
    "Verify every executable task has a matching screenshot block, commands use the exact file name and the student prompt, and the output matches what the code would really print. "
    "For conceptual, trade-off or recommendation tasks omit terminal screenshot and code headings completely. "
    "Attachments: Code/ (all code files), Outputs/ (all PNGs), Report/, manifest.json, bundled as Lab_X_Submission.zip.\n"
    "- TRACK B (HEAVY_ML): the report body per task is ONLY: task name + statement -> output image. NO code and no code blocks in the report. "
    "Then an `## Attachments` section containing the `**Notebook file:**` line followed by the one ```python percent-format block (this is the notebook attachment, not report text), "
    "plus the list of output PNGs. Any notes or assumptions go in a final markdown cell of the notebook.\n"
    "- TRACK C (DIAGRAM_DESIGN / non-code lab): per task: task name + statement -> diagram image -> XML code (the complete ```drawio block) -> theory answers. "
    "Confirm the XML is well-formed, the PNG matches the XML and, if reference_diagram_available is true, the style still matches the reference. "
    "Attachments: all .xml files + PNGs + report, zipped.\n"
    "- TRACK D (THEORY_ACADEMIC / QUANTITATIVE_MATH assignment): the complete, polished, ready-to-submit written solution in the original question order and wording. "
    "Answers as text; diagram images placed inline exactly where each question needs them, with NO XML and NO other diagram text. "
    "Omit all code, compiler and terminal headings.\n"
    "- Track A+C / MIXED: follow the assignment's original task order; apply the matching format to each part and merge attachments into one ZIP.\n"
    "Omit specialist sections that returned N/A.\n\n"
    "STEP 3 - FIX AND VERIFY\n"
    "- Fix clear errors: syntax mistakes, inconsistent code vs. output, broken Markdown, malformed XML, arithmetic slips, wrong numbering or file names.\n"
    "- Preserve specialist code and diagrams intact; edit only what is demonstrably wrong.\n"
    "- Remove any invented or unverifiable citations; keep only real, supplied or consulted sources.\n"
    "- Do not add content the specialists did not produce unless fixing a gap you can fill with certainty.\n"
    "- Never present traced output as executed: keep output_source accurate and downgrade the task to `partial` if its output could not be verified.\n\n"
    "STEP 4 - OUTPUT (in this exact order)\n"
    "1. The complete deliverable in clean Markdown, following STEP 2 for the track.\n"
    "2. A `manifest` block the next agent reads automatically. Every task has an id, title, statement, image, code, xml, answers, "
    "include_code_in_report, output_source and status (solved / partial / needs_input). Set include_code_in_report=true for track A, "
    "false for track B, and true for the XML in track C (code=null, xml=<path>). Use null for fields that do not apply. "
    "List every attachment path (code files, PNGs, XML files, notebook) in `attachments`. Format:\n"
    + MANIFEST_SPEC +
    "3. A short block:\n"
    "`## Quality Status` with: Completeness (X of Y parts done), QA checklist result (Q1-Q6 pass/fail), Fixes applied, "
    "Unresolved gaps / missing information, Assumptions made, per-task status summary.\n\n"
    "ORIGINAL ASSIGNMENT:\n{assignment}\n\nSUPPLIED CONTEXT:\n{context}"
)


def build_assignment_crew(on_task_complete: Callable[[str, Any], None] | None = None) -> Crew:
    """Build the four-agent sequential crew and optionally report task completion."""
    planner = Agent(
        role="Planner / Analyzer",
        goal=(
            "Read the whole file, decide lab vs assignment, pick the track (B > A > C > D), split the work into parts, "
            "and produce a precise dependency-aware JSON plan with correct specialist routing and artifact list."
        ),
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
        goal=(
            "Produce correct single-file code with matching student-named terminal screenshots, one Colab notebook with per-task output images for ML tasks, "
            "and professional Draw.io diagrams (PNG + XML) that follow any supplied reference style."
        ),
        backstory=(
            "You are a careful engineer who re-checks code before delivering it, makes terminal output match the code exactly, "
            "never fabricates output, copies the style of sample diagrams when they exist, and otherwise designs clean professional diagrams."
        ),
        llm=_agent_llm("coder_diagram"), allow_delegation=False, verbose=False,
    )
    reporter = Agent(
        role="Reporter / Fixer",
        goal=(
            "Verify all work against the plan and the QA checklist, fix clear errors, and return the final polished deliverable in the exact format its track requires, "
            "plus a machine-readable manifest for the report-builder agent."
        ),
        backstory=(
            "You are an exacting editor. You preserve specialist details, correct demonstrable mistakes, "
            "remove unverifiable claims, keep file names and statuses consistent, and openly list anything unresolved."
        ),
        llm=_agent_llm("reporter_fixer"), allow_delegation=False, verbose=False,
    )

    def completed(role: str):
        if on_task_complete is None:
            return None
        return lambda output: on_task_complete(role, output)

    planning_task = Task(
        description=PLANNER_PROMPT,
        expected_output="Only raw valid JSON matching the requested plan schema (including is_lab and track), with no markdown fences or extra text.",
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
            "Markdown containing, as the plan requires: named code files with student-prompt terminal-screenshot blocks and answers, "
            "a single percent-format Colab notebook with per-task output image names, or Draw.io XML with a diagram image reference "
            "and XML file name - or the exact N/A line when not required."
        ),
        agent=coder, context=[planning_task, research_task], callback=completed("coder_diagram"),
    )
    reporting_task = Task(
        description=REPORTING_PROMPT,
        expected_output=(
            "The complete reviewed deliverable in clean Markdown for the plan's track, followed by a ```manifest JSON block "
            "and a Quality Status block."
        ),
        agent=reporter, context=[planning_task, research_task, coding_task],
        callback=completed("reporter_fixer"),
    )
    return Crew(
        agents=[planner, researcher, coder, reporter],
        tasks=[planning_task, research_task, coding_task, reporting_task],
        process=Process.sequential, verbose=False,
    )


def _terminal_user(student_name: str) -> str:
    """Turn 'Ali Khan' into a shell-style user name like 'ali'."""
    first = (student_name or "").strip().split(" ")[0].lower()
    first = re.sub(r"[^a-z0-9_-]", "", first)
    return first or "student"


def _file_prefix(lab_no: str) -> str:
    """'3' -> 'Lab03'. The reporter swaps it for 'Assignment' on non-lab work."""
    digits = re.sub(r"\D", "", str(lab_no or ""))
    return f"Lab{int(digits):02d}" if digits else "Lab"


def run_assignment_crew(
    assignment: str,
    context: str = "",
    on_task_complete=None,
    student_name: str = "Student",
    roll_no: str = "",
    lab_no: str = "",
):
    """Run the configured four-agent sequential crew and return CrewAI's result."""
    crew = build_assignment_crew(on_task_complete=on_task_complete)
    return crew.kickoff(
        inputs={
            "assignment": assignment,
            "context": context,
            "student_name": student_name or "Student",
            "roll_no": roll_no or "",
            "lab_no": lab_no or "",
            "terminal_user": _terminal_user(student_name),
            "file_prefix": _file_prefix(lab_no),
        }
    )
