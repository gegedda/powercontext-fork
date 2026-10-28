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
**Scope:** `scp_45mdmzyvg2mnsf5h0gxn9g2qsw`

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

Status: **verified**

Completed: imported 30 material chunks into PowerContext; selected applicable specs, code symbols and tests; asked MiniMax to modify demo_project/issuehub; target tests pass after the change; regression tests pass after the change
Verification: `target: 4 failed before / 4 passed after; regression: 4 passed before and after`

## Source citations

- `SPEC-101.1` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_dc539d9cfc9a41e79c5a9ddc54e46380`, version `mem_ver_a98f6ef771da4b55a1a81d4cae59a49e`)
- `SPEC-101.2` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_21d1f4e3808b416aabd01bc1fea567c1`, version `mem_ver_91fe8ff1aa6c4aea94d6459da2d9c047`)
- `SPEC-101.3` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_fadaa90fe4e94ba1852b8c4cc319183f`, version `mem_ver_94eb0dba76c4481bb8ea35ad85365192`)
- `SPEC-102.1` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_c36b33b61d364489a7369ed57d79d469`, version `mem_ver_27abeb574d7049ae8a12c5635e8987c7`)
- `SPEC-102.2` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_5f60bab600dd48a1895351ad20962974`, version `mem_ver_533cfe5ef2744b1592d8d6efc399b4da`)
- `SPEC-103.1` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_f8781826dc24478b9c8ccd38072a6c7a`, version `mem_ver_f65ca54eb6344d13bc6dab66505c39ea`)
- `SPEC-103.2` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_910e08f815434030a9bbb42ab24e8b8d`, version `mem_ver_e290a0cefd444027b8571372d905e87c`)
- `SPEC-103.3` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_c75af3bb1e8e4bd6bab6090723b81f96`, version `mem_ver_d0bd7ff9671e4eb89c44765b85c17a41`)
- `SPEC-103.4` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_302a10c5730c422da73ca873f2ab897c`, version `mem_ver_774b31db0c424c138d6d19d06dfba601`)
- `CODE-service-IssueService-list_issues` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_2d60e859923a4e0bb220d8306ce0ff65`, version `mem_ver_2a668e2fdb864008a9aa226829265194`)
- `CODE-models-Issue` → `minimax/demo_project/issuehub/models.py` (memory entry `mem_ent_a1cdb45c64004200b836f688d584a702`, version `mem_ver_782de1a388614f479d1a568fcf8802e5`)
- `CODE-service-InvalidPriority` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_8eacf1d263274d0fb29b775d9ba8ed68`, version `mem_ver_eeb1bc2884a148cba1b80481a1a8b0fe`)
- `CODE-api-make_handler` → `minimax/demo_project/issuehub/api.py` (memory entry `mem_ent_db29811615314324bfd887c40ec90199`, version `mem_ver_5d7766ee9a7b4c40b8c112736ba6676a`)
- `TEST-test_invalid_priority_returns_400` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_583111a6f96f45109fd02feed93fa9da`, version `mem_ver_3dac6d37a50e446f99b56fc81ebe8fb9`)
- `TEST-test_priority_combines_with_status` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_a90256d14c2e43b7b8394a450b6f5630`, version `mem_ver_4e108963bfda472886dbce9bcfa53ae6`)
- `TEST-test_filter_by_assignee_and_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_2a028789be904be196b3bf9e36ec49a8`, version `mem_ver_53942553ce3a46bf9d860e1f892a9db2`)
- `TEST-test_filter_by_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_6c4b65c439ab481cb355e322ae06076f`, version `mem_ver_c335c00ce17e418582d60ef26acffd80`)
- `TEST-test_no_filters_returns_all_sorted` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_6a34e1a615a2470cb5e786e79f093e65`, version `mem_ver_6c1c08e7d5ac49c08f8426169b92c86b`)
- `TEST-test_status_filter_still_works` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_4c189aa0b9664cd5847f074e0b1bada7`, version `mem_ver_dc7d3f50c2c548118296db1be6ffb4f9`)
