# Douyin Caption frontend

Vue 3 + TypeScript + Vite client for the Douyin spoken-script rewriting workspace.

## Commands

Run these commands from the repository root:

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend exec -- playwright test
```

The Playwright tests use simulated API responses and do not call a real model. The
frontend expects the backend API at `http://127.0.0.1:8000` by default; override it in
`frontend/.env.development.local` when needed. Local environment files and generated
build/test output are intentionally ignored by Git.
