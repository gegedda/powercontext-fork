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
**Scope:** `scp_12n36wy81y9nd5bf54ksxc7788`

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

- `SPEC-101.1` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_b0472e96440f49aca3dd0037f85854fa`, version `mem_ver_d69d54db01dc433e8e04b558f12bb52a`)
- `SPEC-101.2` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_abe0dc7abd684d9c85b03899735435e9`, version `mem_ver_9862bef427b24b23b4c814e758874282`)
- `SPEC-101.3` → `minimax/materials/specs/SPEC-101-issue-filters.md` (memory entry `mem_ent_a1ff95ff99434983bab3bcc978741c83`, version `mem_ver_4b5bc3fd3d2f47009c219a24b5e0edd5`)
- `SPEC-102.1` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_8c191807552c4a34bae92e4e8f4720b7`, version `mem_ver_a90490b6cb934e078bb2e01eef35c0a9`)
- `SPEC-102.2` → `minimax/materials/specs/SPEC-102-invalid-priority.md` (memory entry `mem_ent_4dcf69bfd8cc456ab5b3240379d9f809`, version `mem_ver_2722951b7f2947cda53a7bfa362eb8ba`)
- `SPEC-103.1` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_1393510e224f408ab7addf03c98d7f04`, version `mem_ver_aff3aa59ba1a4388b6b8802257149060`)
- `SPEC-103.2` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_ebf37dd6b84b43d58a8c18693555d89d`, version `mem_ver_bbb5acdb65bc42a4ac2192758a457068`)
- `SPEC-103.3` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_4a1c16d1d0e74015ad5f909a175f555f`, version `mem_ver_46f30bf7e32d4f87b111da0c1739154f`)
- `SPEC-103.4` → `minimax/materials/specs/SPEC-103-compatibility.md` (memory entry `mem_ent_e0d5c6b252564f699187e28d3bbda87c`, version `mem_ver_96860adfcb9040cba867a7173df27a5e`)
- `CODE-service-IssueService-list_issues` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_ee44142a71a240f5b2c87f86e6ebd02b`, version `mem_ver_28f5d156eed14b12b4355546e0c6155e`)
- `CODE-models-Issue` → `minimax/demo_project/issuehub/models.py` (memory entry `mem_ent_6bcb5cb4b768411b8540196ad7f7ff69`, version `mem_ver_1515e55110b44cb7be7ca8e7f382ce52`)
- `CODE-service-InvalidPriority` → `minimax/demo_project/issuehub/service.py` (memory entry `mem_ent_c0caebb2f72f40759515e89996bb33ef`, version `mem_ver_9f990ec96d7749d7a5c69998059f5285`)
- `CODE-api-make_handler` → `minimax/demo_project/issuehub/api.py` (memory entry `mem_ent_9fb5a08298654beead9841943844a9ce`, version `mem_ver_a837537e8d354e46a4a6b60487f7c5b9`)
- `TEST-test_invalid_priority_returns_400` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_437db886865e45639964b21b4ecabd45`, version `mem_ver_9d77f890e5724663b683c44edc560a3e`)
- `TEST-test_priority_combines_with_status` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_e4cfbcf8c2f94d3dae589ecc0d399e8e`, version `mem_ver_02639d535f2b433c84d5f48a03dccd84`)
- `TEST-test_filter_by_assignee_and_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_744e786258744f2bbb47b5467912f932`, version `mem_ver_a20e422b12a547eaa77d273deb8d52aa`)
- `TEST-test_filter_by_priority` → `minimax/demo_project/tests/test_issue_filters.py` (memory entry `mem_ent_3ac84a6e047d41febec0a86e1ff9ed91`, version `mem_ver_3b2e0c7692984df7838109f98fb4f818`)
- `TEST-test_no_filters_returns_all_sorted` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_7b43a8274feb40fbb6b9e6c409ed5f3d`, version `mem_ver_421ecec747b142f48a599b853b970c11`)
- `TEST-test_status_filter_still_works` → `minimax/demo_project/tests/test_regressions.py` (memory entry `mem_ent_62e9124e708b42049c4b698d609c9320`, version `mem_ver_203bd7a58ebd48d7ae4c136ae92c9ea2`)
