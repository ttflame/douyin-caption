# REST API Contract

Version: 0.1  
Base path: `/api/v1`

Resource identifiers are UUID strings; provider `model_id` is a model name. All timestamps are UTC ISO 8601 strings. Error responses use:

```json
{
  "error": {
    "code": "stable_machine_code",
    "message": "Human-readable message",
    "details": {}
  }
}
```

## Authentication and identity

- `POST /auth/login`: username and password -> access token and current member.
- `GET /auth/me`: current member.
- `POST /auth/change-password`: current password and new password.
- `GET /admin/members`: administrator-only member list without content data.
- `POST /admin/members`: administrator creates a member.
- `PATCH /admin/members/{member_id}`: administrator changes display name or active state.
- `GET /settings/provider`: masked provider settings.
- `PUT /settings/provider`: replace API key, base URL, manually entered `model_id` (a model name, trimmed, 1-150 characters), and `timeout_seconds` (integer, 10-600, defaults to 240).
- `PATCH /settings/provider`: update only `timeout_seconds` on the current member's saved connection, without resubmitting credentials; other fields are rejected.
- `DELETE /settings/provider`: delete provider settings.
- `POST /settings/provider/test`: test the saved or supplied connection without logging credentials.

Provider responses return `model_id` as the actual provider model name. Connection tests accept an
optional model name override with the same validation as saving. The model catalog endpoint has been removed.
Provider responses also include `timeout_seconds`. Connection tests accept an optional timeout
override, otherwise using the saved value or 240 seconds. The timeout bounds the entire outbound
request; connect, write, and pool waits retain shorter limits of 10, 30, and 10 seconds.

## Creative presets

- `GET /presets`: current member's presets.
- `POST /presets`: create a preset.
- `PATCH /presets/{preset_id}`: rename or update a preset.
- `DELETE /presets/{preset_id}`: delete a preset.

## Rewriting tasks

- `GET /tasks`: current member's tasks, with search, state and archive filters.
- `POST /tasks`: create a draft task from source text and creative settings.
- `GET /tasks/{task_id}`: task detail owned by the current member.
- `PATCH /tasks/{task_id}`: update a draft or rename a task.
- `POST /tasks/{task_id}/copy`: create an independent task by copying source and settings.
- `POST /tasks/{task_id}/archive`: archive a task.
- `POST /tasks/{task_id}/restore`: restore an archived task.

## AI workflow

Successful operation submission returns HTTP `202` with a persisted `AiOperation` in `queued`
status. Responses include `task_id`, `task_name`, `kind`, `created_at`, nullable `started_at` and
`completed_at`, and optional `resource_type` / `resource_id`. Mutating submissions accept an
`Idempotency-Key` header. A backend worker executes each member's queue in submission order,
independently of the submitting request and browser connection. Different members may run concurrently.

- `POST /tasks/{task_id}/analysis`: analyze or re-analyze source text; accepts an empty object.
- `PATCH /tasks/{task_id}/analysis/{analysis_id}`: save member corrections.
- `GET /tasks/{task_id}/analysis/{analysis_id}`: read one owned analysis.
- `GET /tasks/{task_id}/analyses`: list owned analysis history and selected state.
- `POST /tasks/{task_id}/suggestions`: create 5-8 suggestions from a selected analysis.
- `PATCH /tasks/{task_id}/suggestions/{suggestion_id}`: accept, reject or annotate one suggestion.
- `GET /tasks/{task_id}/suggestions`: read suggestions for the selected analysis, or filter with
  `analysis_id`.
- `POST /tasks/{task_id}/first-draft`: generate the task's only first draft.
- `POST /tasks/{task_id}/revisions`: create a full-text or selected-range revision from a parent version.
- `GET /operations/{operation_id}`: poll operation state and safe error information.
- `GET /operations`: all queued/running operations and the latest 30 finished operations owned by the current member.
- `POST /operations/{operation_id}/cancel`: cancel a queued operation; returns `409` if execution has started or finished.
- `POST /operations/{operation_id}/retry`: submit saved inputs as a new queue entry for a failed/cancelled operation, returning `202`; accepts `Idempotency-Key`.

Only one queued/running operation is allowed per document. Content mutations and archival are
blocked while work is queued/running; source text, selected suggestions and version references remain
stable until execution finishes. A retry uses the saved request parameters with the document's
current valid state. Historical non-analysis operations without saved inputs must be resubmitted
from the workbench. The member's current provider settings are loaded when execution begins.

Analysis sends only the system instruction `根据原文整理出来一个文案结构，逐条分析` and a user
message containing the original text, without creative settings or a response schema. New analysis
payloads have the shape `{ "content": "model response text" }`. Historical seven-module payloads
remain readable. Suggestions derived from text analysis use `analysis_issue_ids: ["analysis"]`;
historical structured analyses continue to use their stored issue identifiers.

An idempotency key is scoped to member, task and operation kind and is bound to a canonical request
body hash. Reusing it with different request parameters returns `409`. At most one provider call may
run per member. If Redis coordination is unavailable, the worker leaves operations queued and does
not call the provider. A failed operation does not prevent the next queued document from running.

## Versions and locked fragments

- `GET /tasks/{task_id}/versions`: version tree.
- `GET /tasks/{task_id}/versions/{version_id}`: one version and its provenance.
- `POST /tasks/{task_id}/versions/{version_id}/manual-edit`: save edited text as a child version.
- `POST /tasks/{task_id}/versions/compare`: deterministic text diff for two owned versions.
- `POST /tasks/{task_id}/versions/{version_id}/locks`: lock an exact selected fragment.
- `GET /tasks/{task_id}/locks`: list all active task-level locked fragments.
- `DELETE /tasks/{task_id}/locks/{lock_id}`: remove a lock.
- `POST /tasks/{task_id}/versions/{version_id}/finalize`: mark a current final version.
- `GET /tasks/{task_id}/export?format=txt|md`: export the current final version.

## Core DTO rules

- `CreativeSettings` contains target character count plus persona, audience, language style, content structure, output specification and hard constraints.
- Source text is limited to 20,000 characters.
- `Analysis` contains the seven fixed modules defined in the product requirements.
- `Suggestion` has priority `primary` or `optional` and references an analysis issue.
- `Version.kind` is `first_draft`, `ai_revision` or `manual_edit`.
- `Revision.scope` is `full` or `selection`.
- Repeated suggestions generation preserves accepted records, IDs and member notes and replaces only unselected suggestions in the chosen analysis. When all suggestions are accepted, the operation fails before calling the provider.
- Locked fragments preserve exact text, punctuation and repeated occurrence counts. Position and relative order may change with the article structure. Offsets count Unicode code points.
- Revisions that violate preservation constraints fail with `locked_text_changed` and do not create a version. Manual edits that change locked text return `409`; unlock the affected text before editing it.
