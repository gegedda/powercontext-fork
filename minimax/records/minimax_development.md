# MiniMax development record

- **Provider**: MiniMax
- **API**: `POST https://api.minimaxi.com/v1/chat/completions` (OpenAI-compatible)
- **Model**: `MiniMax-M3.1-Flash`
- **Runs**: `2026-10-28T11:49:56Z` and `2026-10-28T11:50:17Z`
- **Raw record**: [`minimax_run.json`](minimax_run.json) — full request messages, final content, usage; no private reasoning content is stored.

## 1. Task given to MiniMax

`TASK-001` — add `priority` and `assignee` filters to `GET /issues`, return HTTP 400
`invalid_priority` for unknown priorities, combine filters with the existing
`status` filter, and preserve the existing response shape and behaviour.

The task text and the selected context were sent as the user message; the system
message required a single JSON object with complete replacement files and forbade
changing tests/specs.

## 2. Context supplied

The context was produced by `python -m sdd_context --db sqlite context` from the
PowerContext Memory store and written to [`context.json`](context.json):

- **Specs (9 sections from 3 active documents)**:
  `SPEC-101.1`, `SPEC-101.2`, `SPEC-101.3`,
  `SPEC-102.1`, `SPEC-102.2`,
  `SPEC-103.1`, `SPEC-103.2`, `SPEC-103.3`, `SPEC-103.4`.
  The superseded `SPEC-090` was explicitly excluded.
- **Code**: `IssueService.list_issues`, `make_handler`, `Issue`, `InvalidPriority`.
- **Tests**: the 4 target tests and `test_no_filters_returns_all_sorted`,
  `test_status_filter_still_works`.
- **State**: `not_started` before the run.

The code in this context is the **before** snapshot, not the already-finished
implementation, because `demo` restores `snapshots/before` before ingesting.

## 3. Calls

Two calls were used, one per file, so each JSON response stays bounded and the
model can focus on one interface:

| Call | Requested file | Prompt tokens | Completion tokens | Reasoning tokens | Final content chars |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | `demo_project/issuehub/service.py` | 3,994 | 5,781 | 5,355 | 1,771 |
| 2 | `demo_project/issuehub/api.py` | 3,994 | 1,693 | 999 | 3,028 |

Both calls returned valid JSON. The model preserved `IssueService()` with no
arguments, kept `DEFAULT_ISSUES`, added `ALLOWED_PRIORITIES`, and returned the
required 400 body.

## 4. Applied result

- `minimax/demo_project/issuehub/service.py`
- `minimax/demo_project/issuehub/api.py`

The model's final code is the committed after snapshot; the diff is
[`code.diff`](code.diff).

Tests run after applying the response:

- `tests/test_issue_filters.py`: 4 passed, 0 failed.
- `tests/test_regressions.py`: 4 passed, 0 failed.

## 5. Traceability

| Item | File |
| --- | --- |
| Task + context sent to MiniMax | `context.json`, `context.md`, `minimax_run.json` |
| Model final answer | `minimax_run.json` (`calls[].response`) |
| Applied diff | `code.diff` |
| Before test failure | `before_target.log`, `before_regression.log` |
| After test pass | `after_target.log`, `after_regression.log` |
| State reuse | `state_reuse.json`, `powercontext_state.md` |

The recorded response can be replayed with `python -m sdd_context demo --offline`
([`minimax_recorded.json`](minimax_recorded.json)) without another online call.
