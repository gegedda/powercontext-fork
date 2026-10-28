---
id: SPEC-102
title: Invalid priority is a client error
status: active
applies_to: issuehub
version: 2
tags: [api, validation, priority, error, 400]
---
## SPEC-102.1 Reject unknown priorities

A `priority` value outside `low`, `medium`, `high` is a client error. The
service must not silently return an unfiltered list.

## SPEC-102.2 Error contract

The response is HTTP 400 with this JSON body:

```json
{"error": "invalid_priority", "allowed": ["low", "medium", "high"]}
```

The error must be raised before filtering so that an invalid request never
looks like a successful empty result.
