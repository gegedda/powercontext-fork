---
id: SPEC-101
title: Issue list priority and assignee filters
status: active
applies_to: issuehub
version: 2
tags: [api, filter, priority, assignee, issues]
---
## SPEC-101.1 Request parameters

`GET /issues` accepts two optional query parameters in addition to the existing
`status` parameter:

- `priority`: one of `low`, `medium`, `high`.
- `assignee`: an exact assignee name.

All supplied filters are combined with AND. Omitting a filter must not exclude
any issue on account of that filter.

## SPEC-101.2 Ordering and response shape

The response remains `{"items": [...], "total": N}`. `items` is always ordered
by ascending `id`. Each item keeps the existing fields `id`, `title`, `status`,
`priority`, `assignee`.

## SPEC-101.3 Combination examples

- `?priority=high` returns issues 1 and 4.
- `?assignee=alice&priority=high` returns issue 1.
- `?status=open&priority=low` returns issue 2.
