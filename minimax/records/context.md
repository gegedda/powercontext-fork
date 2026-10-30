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

**Backend:** seekdb  
**Scope:** `scp_376mvwhs4rw8nxtfg5m2bjwg8g`

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

- `SPEC-101.1` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_85ff973eebfe477cbb75264bb7d626c2`, version `art_85ff973eebfe477cbb75264bb7d626c2@1`)
- `SPEC-101.2` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_0376780a887f41f7affda67e22ff098e`, version `art_0376780a887f41f7affda67e22ff098e@1`)
- `SPEC-101.3` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `art_3bd2a9a955464dcfa1903c4c6283741a`, version `art_3bd2a9a955464dcfa1903c4c6283741a@1`)
- `SPEC-102.1` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `art_0503e9ad167b41ec9b00ba0e18d6288d`, version `art_0503e9ad167b41ec9b00ba0e18d6288d@1`)
- `SPEC-102.2` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `art_86ec49910e374c1ea1fa8ee719788376`, version `art_86ec49910e374c1ea1fa8ee719788376@1`)
- `SPEC-103.1` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_56818d836d0141e58815fe2291431395`, version `art_56818d836d0141e58815fe2291431395@1`)
- `SPEC-103.2` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_f295eae1f8cd47129e653cdada71695c`, version `art_f295eae1f8cd47129e653cdada71695c@1`)
- `SPEC-103.3` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_61c2b8eb1b5b4ce28398f009e255f951`, version `art_61c2b8eb1b5b4ce28398f009e255f951@1`)
- `SPEC-103.4` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `art_aa92ee1a0a3e44f6b2bc7f3b5a9acc4a`, version `art_aa92ee1a0a3e44f6b2bc7f3b5a9acc4a@1`)
- `CODE-service-IssueService-list_issues` → `minimax/demo_project/issuehub/service.py` (memory entry `art_959723305bb44b95a3e73a00be6f4c10`, version `art_959723305bb44b95a3e73a00be6f4c10@1`)
- `CODE-models-Issue` → `minimax/demo_project/issuehub/models.py` (memory entry `art_c9380f957cae480b8e2e5570292f28fc`, version `art_c9380f957cae480b8e2e5570292f28fc@1`)
- `CODE-service-InvalidPriority` → `minimax/demo_project/issuehub/service.py` (memory entry `art_ea59dc71c81546cdbbecaeddcb527aa1`, version `art_ea59dc71c81546cdbbecaeddcb527aa1@1`)
- `CODE-api-make_handler` → `minimax/demo_project/issuehub/api.py` (memory entry `art_06d914e584ca407686991fed45c92b9b`, version `art_06d914e584ca407686991fed45c92b9b@1`)
- `TEST-test_invalid_priority_returns_400` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_65899ef44adc4a00a69e6ba5cb372bad`, version `art_65899ef44adc4a00a69e6ba5cb372bad@1`)
- `TEST-test_priority_combines_with_status` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_69cc2ea4d6dc44e7b63847aa5f9f7722`, version `art_69cc2ea4d6dc44e7b63847aa5f9f7722@1`)
- `TEST-test_filter_by_assignee_and_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_2ceb379f4a8e44c693d8be1a1078caae`, version `art_2ceb379f4a8e44c693d8be1a1078caae@1`)
- `TEST-test_filter_by_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `art_4fe0a4eb45974aca80f9b063ac1c709f`, version `art_4fe0a4eb45974aca80f9b063ac1c709f@1`)
- `TEST-test_no_filters_returns_all_sorted` → `minimax/demo_project/tests/test_regressions.py` (memory entry `art_43e0370859294b77885e80edca0b4b03`, version `art_43e0370859294b77885e80edca0b4b03@1`)
- `TEST-test_status_filter_still_works` → `minimax/demo_project/tests/test_regressions.py` (memory entry `art_16a99db011a64310a9e759c8dd7210d5`, version `art_16a99db011a64310a9e759c8dd7210d5@1`)
