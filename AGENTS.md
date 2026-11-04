# Workspace Agent Guidelines

## 1. Git Rules
- **No Push Without Permission**: NEVER execute `git push` or publish commits to remote repositories without explicit user permission. Always keep changes local until requested.

## 2. Page & Feature Verification
- **Mandatory Local Rendering & Access**: For every page changed or feature updated, actively access and render the page locally (via browser subagent or local HTTP/render check) to verify:
  - **Frontend**: Check for runtime errors, undefined variables, console errors, or broken rendering in Next.js / React.
  - **Backend**: Inspect `uvicorn` backend logs, verify API responses, and ensure zero unhandled exceptions or 500 errors.
- Never consider a feature complete without verifying both frontend and backend functionality.

## 3. Playwright Testing
- **Do not run Playwright or browser automation for testing or verification unless the user explicitly asks for it in the current request.**
- Use non-browser checks instead, such as focused tests, lint, builds, and plain HTTP/API health checks. Do not claim visual or browser-runtime verification when it was not requested.
