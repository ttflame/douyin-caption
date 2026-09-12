# Architecture Baseline

Version: 0.2
Date: 2026-09-13

## System shape

```text
Vue 3 browser client
  -> FastAPI REST API
       -> PostgreSQL (business records)
       -> Redis (member AI-call lock and login rate limits)
       -> OpenAI-compatible provider selected by the member
```

The browser never calls a model provider directly. Provider credentials are encrypted by the API and are decrypted only for the duration of an outbound request.

## Backend boundaries

- `app/core`: configuration, database session, security primitives, shared errors. Main-agent owned.
- `app/modules/identity`: authentication, members, and personal provider settings with model names.
- `app/modules/tasks`: rewriting tasks, creative settings, presets, versions, locked fragments, finalization and export.
- `app/modules/ai`: provider adapter, prompt assembly, structured outputs, workflow operations and deterministic validation.
- `app/api`: root router composition. Main-agent owned.
- `alembic`: schema migrations. Main-agent owned.

Modules may depend on `app/core`. The AI module may consume task-domain DTOs but must not write task tables directly. Cross-module state changes go through application services.

## Frontend boundaries

- `src/shared`: design tokens, reusable controls, API client, common types.
- `src/features/auth`: login and session.
- `src/features/settings`: member provider settings.
- `src/features/admin`: member and model administration.
- `src/features/tasks`: task list, creation, creative settings and presets.
- `src/features/workbench`: analysis, optimization selection, editing, locking, revisions and finalization.

Suggestion selection is a local draft, isolated in `sessionStorage` by member, task and analysis.
Checkbox and note edits do not write to the API. The three suggestion-based actions submit one
immutable full snapshot. A successful `202` clears the draft; failures and authentication expiry
preserve it. Login expiry stores a validated internal return route and never silently resubmits.

## Task state machine

```text
draft
  -> analyzing -> analysis_ready
  -> suggesting -> suggestions_ready
  -> generating -> editing
  -> editing <-> revising
  -> finalized

Any non-final state -> archived
archived -> previous state
```

Rules:

- A task has exactly one first draft.
- Another independent first draft requires a new task.
- Revision versions are immutable and form a parent-child tree. A revision may modify the current text or regenerate from the original text and the latest accepted optimization suggestions.
- A finalized version remains immutable; further work creates a child revision.
- At most one AI call per member may be active.
- Failed calls restore the last stable task state and may be retried idempotently.
- AI operations and request parameters are persisted in PostgreSQL or SQLite before HTTP `202` is
  returned. `AiQueueWorker` runs for the API process lifespan, reads FIFO queue entries by member,
  and uses independent database sessions for execution. Page navigation or browser closure has no
  effect on accepted work. Queued entries are rediscovered after a process restart.
- For suggestion-based operations, snapshot validation, decision persistence, task-state transition
  and queue creation share one transaction. `request_payload` is the worker's source of truth. The
  single-item suggestion `PATCH` remains only as a compatibility API.
- A Redis member lease and conditional queued-to-running update prevent competing API workers from
  executing the same entry. A partial unique index prevents multiple active operations per document.
  Document mutation guards include queued operations, keeping their input resources stable.
- Graceful shutdown marks interrupted running work cancelled. After a hard process exit, stale
  running operations are marked failed after the recovery threshold; users explicitly retry them
  to avoid automatic duplicate provider charges. Queued work then continues.
- Provider requests use each member's response deadline (240 seconds by default, up to 600).
  The Redis lease lasts 660 seconds and stale recovery starts after 720 seconds, leaving time
  for request cancellation and result persistence. Queue waiting does not consume the provider timeout.
- A global Pinia queue store polls while signed in (1.5 seconds while active, 5 seconds when idle).
  The right-bottom task center survives route changes and offers status, elapsed time, queued
  cancellation, retry and result navigation. Results refresh only the matching document; stale
  requests and responses from a previous login are ignored. Polling has no overall queue deadline.

## Security invariants

- Every member-owned query includes the authenticated member identifier.
- Administrators manage accounts but cannot use product APIs to read member content.
- Provider API keys use authenticated encryption at rest and never appear in responses or logs.
- Disabled members cannot authenticate or start work.
- Each AI call uses the model name saved in the authenticated member's provider settings.
- Provider URLs are revalidated before outbound use and must resolve only to public addresses;
  production additionally requires HTTPS and network-level egress controls.
- Login attempts are rate-limited in Redis by IP, username and their combination.
- Request IDs are validated or generated at the API boundary, returned to the browser, saved on AI
  operations and included in submission and worker logs. Sanitized client events use a strict,
  authenticated, size-limited and rate-limited endpoint.

## Shared-file ownership

During parallel work, only the main conversation edits root configuration, dependency manifests, lock files, `app/core`, `app/api`, Alembic migrations and shared API contracts. Child conversations edit only their assigned module directories.
