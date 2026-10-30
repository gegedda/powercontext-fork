# Development context — TASK-001

**Task:** Add priority and assignee filters to the issue list

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

**Backend:** sqlite  
**Scope:** `scp_43amt0e8z1etnsygv0xnw17p5c`

## Applicable specifications

### SPEC-101.1 — SPEC-101.1 Request parameters
Source: `minimax/materials/specs/SPEC-101-issue-filters.md` lines 9–17  
Status: active · score 53.0

## SPEC-101.1 Request parameters
`GET /issues` accepts two optional query parameters in addition to the existing
`status` parameter:

- `priority`: one of `low`, `medium`, `high`.
- `assignee`: an exact assignee name.

All supplied filters are combined with AND. Omitting a filter must not exclude
any issue on account of that filter.

### SPEC-101.2 — SPEC-101.2 Ordering and response shape
Source: `minimax/materials/specs/SPEC-101-issue-filters.md` lines 20–23  
Status: active · score 46.0

## SPEC-101.2 Ordering and response shape
The response remains `{"items": [...], "total": N}`. `items` is always ordered
by ascending `id`. Each item keeps the existing fields `id`, `title`, `status`,
`priority`, `assignee`.

### SPEC-101.3 — SPEC-101.3 Combination examples
Source: `minimax/materials/specs/SPEC-101-issue-filters.md` lines 26–29  
Status: active · score 38.0

## SPEC-101.3 Combination examples
- `?priority=high` returns issues 1 and 4.
- `?assignee=alice&priority=high` returns issue 1.
- `?status=open&priority=low` returns issue 2.

### SPEC-102.1 — SPEC-102.1 Reject unknown priorities
Source: `minimax/materials/specs/SPEC-102-invalid-priority.md` lines 9–11  
Status: active · score 52.5

## SPEC-102.1 Reject unknown priorities
A `priority` value outside `low`, `medium`, `high` is a client error. The
service must not silently return an unfiltered list.

### SPEC-102.2 — SPEC-102.2 Error contract
Source: `minimax/materials/specs/SPEC-102-invalid-priority.md` lines 14–22  
Status: active · score 45.5

## SPEC-102.2 Error contract
The response is HTTP 400 with this JSON body:

```json
{"error": "invalid_priority", "allowed": ["low", "medium", "high"]}
```

The error must be raised before filtering so that an invalid request never
looks like a successful empty result.

### SPEC-103.1 — SPEC-103.1 Existing callers keep working
Source: `minimax/materials/specs/SPEC-103-compatibility.md` lines 9–11  
Status: active · score 47.5

## SPEC-103.1 Existing callers keep working
A request without filters returns every issue, ordered by id. The existing
`status` filter continues to return only issues with the requested status.

### SPEC-103.2 — SPEC-103.2 No response schema change
Source: `minimax/materials/specs/SPEC-103-compatibility.md` lines 14–16  
Status: active · score 51.0

## SPEC-103.2 No response schema change
The JSON field names and value types are unchanged. New filters must not add
fields, rename fields, or change the meaning of `total`.

### SPEC-103.3 — SPEC-103.3 Single-issue endpoint
Source: `minimax/materials/specs/SPEC-103-compatibility.md` lines 19–20  
Status: active · score 44.5

## SPEC-103.3 Single-issue endpoint
`GET /issues/{id}` and its 404 behaviour for unknown ids are unaffected.

### SPEC-103.4 — SPEC-103.4 Service construction
Source: `minimax/materials/specs/SPEC-103-compatibility.md` lines 23–27  
Status: active · score 37.0

## SPEC-103.4 Service construction
`IssueService()` without arguments must keep using `DEFAULT_ISSUES`. The test
fixture and existing callers construct the service this way; the optional
`issues` argument remains available for injection in unit tests. A change that
makes `issues` required is a regression.

## Code to change

### `IssueService.list_issues` — `minimax/demo_project/issuehub/service.py`
Lines 18–24 · score 28.4

```python
def list_issues(self, *, status: str | None = None) -> list[Issue]:
        """Return issues matching the status filter, ordered by id."""

        selected = self._issues
        if status is not None:
            selected = tuple(issue for issue in selected if issue.status == status)
        return sorted(selected, key=lambda issue: issue.id)
```

### `Issue` — `minimax/demo_project/issuehub/models.py`
Lines 12–26 · score 20.4

```python
class Issue:
    id: int
    title: str
    status: str = "open"
    priority: str = "medium"
    assignee: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
        }
```

### `InvalidPriority` — `minimax/demo_project/issuehub/service.py`
Lines 10–11 · score 18.4

```python
class InvalidPriority(ValueError):
    """Reserved for the TASK-001 validation path; unused in this baseline."""
```

### `make_handler` — `minimax/demo_project/issuehub/api.py`
Lines 22–49 · score 17.2

```python
def make_handler(service: IssueService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            parsed = urlparse(self.path)
            if parsed.path == "/issues":
                self._list_issues(parsed.query)
                return
            if parsed.path.startswith("/issues/"):
                suffix = parsed.path.removeprefix("/issues/")
                if suffix.isdigit():
                    issue = service.get_issue(int(suffix))
                    if issue is None:
                        _json_response(self, 404, {"error": "not_found"})
                    else:
                        _json_response(self, 200, issue.as_dict())
                    return
            _json_response(self, 404, {"error": "not_found"})

        def _list_issues(self, raw_query: str) -> None:
            query = parse_qs(raw_query, keep_blank_values=False)
            status = _first(query, "status")
            issues = service.list_issues(status=status)
            _json_response(self, 200, {"items": [issue.as_dict() for issue in issues], "total": len(issues)})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler
```

## Verification tests

- `test_invalid_priority_returns_400` (target, test) — `minimax/demo_project/tests/test_issue_filters.py` lines 30–34
- `test_priority_combines_with_status` (target, test) — `minimax/demo_project/tests/test_issue_filters.py` lines 23–27
- `test_filter_by_assignee_and_priority` (target, test) — `minimax/demo_project/tests/test_issue_filters.py` lines 16–20
- `test_filter_by_priority` (target, test) — `minimax/demo_project/tests/test_issue_filters.py` lines 8–13
- `test_no_filters_returns_all_sorted` (regression, test) — `minimax/demo_project/tests/test_regressions.py` lines 8–13
- `test_status_filter_still_works` (regression, test) — `minimax/demo_project/tests/test_regressions.py` lines 16–20

Run: `python -m pytest demo_project/tests -q`

## Persisted task state

Status: **not_started**


## Source citations

- `SPEC-101.1` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_43b5eaf679dd4d65b99fcd9a7599d489`, version `art_43b5eaf679dd4d65b99fcd9a7599d489@1`)
- `SPEC-101.2` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_b90094b9fa744714a212d5e34cc9c17c`, version `art_b90094b9fa744714a212d5e34cc9c17c@1`)
- `SPEC-101.3` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_6b55eba1a9e54630b34482a4b46287b5`, version `art_6b55eba1a9e54630b34482a4b46287b5@1`)
- `SPEC-102.1` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `art_bc6240e98c9043d4bd7915508a0c5cbc`, version `art_bc6240e98c9043d4bd7915508a0c5cbc@1`)
- `SPEC-102.2` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `art_6edec3a01f2c4bf8af5318ca74795fee`, version `art_6edec3a01f2c4bf8af5318ca74795fee@1`)
- `SPEC-103.1` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_ac42432ab6694cff8ed0d2796366c7c2`, version `art_ac42432ab6694cff8ed0d2796366c7c2@1`)
- `SPEC-103.2` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_3d8f569789aa4189aeca4e5d046664a8`, version `art_3d8f569789aa4189aeca4e5d046664a8@1`)
- `SPEC-103.3` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_1d5871489d564beaacd22b1524aac950`, version `art_1d5871489d564beaacd22b1524aac950@1`)
- `SPEC-103.4` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_cd78731e42bc405b89ac3287feed0f61`, version `art_cd78731e42bc405b89ac3287feed0f61@1`)
- `CODE-service-IssueService-list_issues` → `minimax/demo_project/issuehub/service.py` (memory entry `art_68046eabfb204cd78886a40c38eedec8`, version `art_68046eabfb204cd78886a40c38eedec8@1`)
- `CODE-models-Issue` → `minimax/demo_project/issuehub/models.py` (memory entry `art_4717d19a8a484fd2a25b4b65b1a53d33`, version `art_4717d19a8a484fd2a25b4b65b1a53d33@1`)
- `CODE-service-InvalidPriority` → `minimax/demo_project/issuehub/service.py` (memory entry `art_4921ec78917747db95d7f5dc2d9cdda5`, version `art_4921ec78917747db95d7f5dc2d9cdda5@1`)
- `CODE-api-make_handler` → `minimax/demo_project/issuehub/api.py` (memory entry `art_b5ab826ed23948d3b967fb5d73a962c9`, version `art_b5ab826ed23948d3b967fb5d73a962c9@1`)
- `TEST-test_invalid_priority_returns_400` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_c8f0ecf4084145d4819e48205c23abca`, version `art_c8f0ecf4084145d4819e48205c23abca@1`)
- `TEST-test_priority_combines_with_status` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_86fa634c3ac94b1994f7fe9378959088`, version `art_86fa634c3ac94b1994f7fe9378959088@1`)
- `TEST-test_filter_by_assignee_and_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_a4e10bf84d81437798a952346558be24`, version `art_a4e10bf84d81437798a952346558be24@1`)
- `TEST-test_filter_by_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_63cc2ab78fe64959b12f6b4c0d31690e`, version `art_63cc2ab78fe64959b12f6b4c0d31690e@1`)
- `TEST-test_no_filters_returns_all_sorted` → `minimax/demo_project/tests/test_regressions.py` (memory entry `art_b1a46528dc214999847d03c5dec63bee`, version `art_b1a46528dc214999847d03c5dec63bee@1`)
- `TEST-test_status_filter_still_works` → `minimax/demo_project/tests/test_regressions.py` (memory entry `art_1e33a18aa59c4cf8b7ae8bd614dcd228`, version `art_1e33a18aa59c4cf8b7ae8bd614dcd228@1`)
