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
**Scope:** `scp_54hq3qcbmc5m1jzv3cj86xepdh`

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

## Code to change

### `IssueService.list_issues` — `minimax/demo_project/issuehub/service.py`
Lines 22–45 · score 41.9

```python
def list_issues(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
    ) -> list[Issue]:
        """Return issues matching the supplied filters.

        Filters are combined with AND. The result is always ordered by id so
        that callers can rely on a stable response.
        """

        if priority is not None and priority not in ("low", "medium", "high"):
            raise InvalidPriority(priority)

        selected = self._issues
        if status is not None:
            selected = tuple(issue for issue in selected if issue.status == status)
        if priority is not None:
            selected = tuple(issue for issue in selected if issue.priority == priority)
        if assignee is not None:
            selected = tuple(issue for issue in selected if issue.assignee == assignee)
        return sorted(selected, key=lambda issue: issue.id)
```

### `make_handler` — `minimax/demo_project/issuehub/api.py`
Lines 22–59 · score 30.7

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
            priority = _first(query, "priority")
            assignee = _first(query, "assignee")
            try:
                issues = service.list_issues(status=status, priority=priority, assignee=assignee)
            except InvalidPriority:
                _json_response(
                    self,
                    400,
                    {"error": "invalid_priority", "allowed": ["low", "medium", "high"]},
                )
                return
            _json_response(self, 200, {"items": [issue.as_dict() for issue in issues], "total": len(issues)})

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    return Handler
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
Lines 14–15 · score 18.4

```python
class InvalidPriority(ValueError):
    """Raised when a caller asks for a priority outside the supported set."""
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

Status: **verified**

Completed: imported 30 material chunks into PowerContext; selected applicable specs, code symbols and tests; asked MiniMax to modify demo_project/issuehub; target tests pass after the change; regression tests pass after the change
Verification: `target: 4 failed before / 4 passed after; regression: 4 passed before and after`

## Source citations

- `SPEC-101.1` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_5eb379de3d1f49849d28deb933f7847c`, version `mem_ver_37f3126841394dedb0f4265a3b79dbda`)
- `SPEC-101.2` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_54bb54a2107e4ab7950a9b63166ad953`, version `mem_ver_2dfeda44cc074ae5bed36c484f8f1fb7`)
- `SPEC-101.3` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_9a364b9d880046ee90c289209b39715b`, version `mem_ver_3d01172b5dd448ca957d7f71006e4f86`)
- `SPEC-102.1` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_3d9097d85ee14a34b1b9e6c138615230`, version `mem_ver_c006a8f517914789ac00e20242570133`)
- `SPEC-102.2` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_078146baed314adfb0c4cf76f65320a8`, version `mem_ver_004f4399782e4d6abca96f5f8bc3abdc`)
- `SPEC-103.1` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_281338c3fd3d4496b2f144dd81226bdc`, version `mem_ver_b173205802fb44ac93c587b2d099e804`)
- `SPEC-103.2` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_02a97eafded4483899593c64e7066e29`, version `mem_ver_a53d6499f46e4d798755ecb15e2ad7df`)
- `SPEC-103.3` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_5e3a6a169f4347a98240504d89908a9f`, version `mem_ver_69bb953f7b5a4fe7b3914cee7f6ee983`)
- `CODE-service-IssueService-list_issues` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_45a0d006f5eb487991b0607409c39858`, version `mem_ver_c7a5b228d50c428e806442ea50c1768b`)
- `CODE-api-make_handler` → `minimax/demo_project/issuehub/api.py` (memory entry `mem_ent_e8853089134140e98c79e39801c530e0`, version `mem_ver_795774774b4a4ae9a81ed93ab5e05483`)
- `CODE-models-Issue` → `minimax/demo_project/issuehub/models.py` (memory entry `mem_ent_3a89e1379f1e4de3917a447e7941df08`, version `mem_ver_1c9fa52d554046c294d23487576ed297`)
- `CODE-service-InvalidPriority` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_97c41752eabf433297e5c00084a45190`, version `mem_ver_5e833bfb38f54a51990662a4d6c95f82`)
- `TEST-test_invalid_priority_returns_400` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_135b01c63b714682844411f657a13e02`, version `mem_ver_bd65e07c47dc4bd2a56536fa7f9a993a`)
- `TEST-test_priority_combines_with_status` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_7dda10d7217448cb98071d607f456fcc`, version `mem_ver_399ae580d3cb428689af82bb83caac79`)
- `TEST-test_filter_by_assignee_and_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_a2a3b52c59aa4cb896417cd3d4cfdcae`, version `mem_ver_1cf84a17de1c4b5a914bf85b25acbbea`)
- `TEST-test_filter_by_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_1e0d0ee8c96845529dd06acd5407c005`, version `mem_ver_26d384ac81a24dd8bfbfab536c925600`)
- `TEST-test_no_filters_returns_all_sorted` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_d428b1848a4144f0982c923ab5eeae4e`, version `mem_ver_301d2aea6e054d559f7ba6f019265eb6`)
- `TEST-test_status_filter_still_works` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_4b40c919bf524124b783bcffb8bb018b`, version `mem_ver_06431b380fc948e4a572785a0ba93073`)
