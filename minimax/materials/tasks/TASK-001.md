---
id: TASK-001
title: Add priority and assignee filters to the issue list
project: issuehub
kind: task
---
Add optional `priority` and `assignee` filters to `GET /issues`.

Requirements:

- `priority` accepts `low`, `medium`, `high`; unknown values return HTTP 400
  with `{"error": "invalid_priority", "allowed": ["low", "medium", "high"]}`.
- `assignee` matches exactly.
- Filters combine with each other and with the existing `status` filter using
  AND.
- No filters must keep returning all six issues ordered by id.
- Do not change the response schema or the single-issue endpoint.

The change must be verified with the target tests for the new filters and the
regression tests for existing behaviour.
