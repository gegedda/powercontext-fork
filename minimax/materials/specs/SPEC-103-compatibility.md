---
id: SPEC-103
title: Backward compatibility of the issue list API
status: active
applies_to: issuehub
version: 2
tags: [compatibility, regression, default, status]
---
## SPEC-103.1 Existing callers keep working

A request without filters returns every issue, ordered by id. The existing
`status` filter continues to return only issues with the requested status.

## SPEC-103.2 No response schema change

The JSON field names and value types are unchanged. New filters must not add
fields, rename fields, or change the meaning of `total`.

## SPEC-103.3 Single-issue endpoint

`GET /issues/{id}` and its 404 behaviour for unknown ids are unaffected.

## SPEC-103.4 Service construction

`IssueService()` without arguments must keep using `DEFAULT_ISSUES`. The test
fixture and existing callers construct the service this way; the optional
`issues` argument remains available for injection in unit tests. A change that
makes `issues` required is a regression.
