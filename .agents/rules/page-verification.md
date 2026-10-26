# Page and Feature Verification Rules

- **Mandatory Local Access & Rendering Verification**:
  - Whenever changes are made to a page or a feature is updated or introduced, you **must actively access or render the page locally**.
  - Use the browser subagent or headless verification to inspect the rendered page, capture console logs, and check for any runtime React/Next.js/Turbopack errors or broken UI states.
- **Dual-Side Error Detection (Frontend & Backend)**:
  - **Frontend**: Check for uncaught runtime exceptions, undefined variable references, failed imports, or broken component rendering.
  - **Backend**: Inspect the running backend server logs (`uvicorn`), test the endpoints triggered by the page/feature, and ensure no 500 internal server errors, unhandled exceptions, or database query failures occur.
- **Definition of Done**:
  - A task involving UI pages or backend APIs is NOT complete until both sides have been tested and verified locally without errors.
