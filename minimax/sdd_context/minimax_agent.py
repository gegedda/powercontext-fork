"""MiniMax coding step: send the selected context and apply the returned files."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

SYSTEM_PROMPT = """You are MiniMax, a careful coding agent working in an existing Python project.
You receive a task, the currently valid specifications, the relevant code symbols and the tests that must pass.
Return only one JSON object, with no Markdown fence and no commentary outside it:
{"summary": "one short paragraph", "files": [{"path": "demo_project/issuehub/service.py", "content": "full file text"}]}
Rules:
- Return complete replacement files, not diffs.
- Only change files under demo_project/issuehub/.
- Never change tests, specs or test expectations.
- Keep the existing public response schema and the single-issue endpoint unchanged.
- Implement exactly the requested filters and the invalid-priority 400 contract.
"""


def build_messages(context: dict[str, object], target_files: list[str] | None = None) -> list[dict[str, str]]:
    target_note = ""
    if target_files:
        target_note = (
            "\nReturn only this file in `files`: "
            + ", ".join(target_files)
            + ". The other file will be requested in a separate call; keep the interface consistent.\n"
        )
    user = f"""Task {context['task']['id']}: {context['task']['title']}

{context['task']['text']}

The following context was selected from the engineering material database. Use it as the source of truth.

{context['markdown']}

Return the complete updated file needed to implement this task.{target_note}
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def call_minimax(messages: list[dict[str, str]]) -> dict[str, object]:
    api_key = config.minimax_api_key()
    if not api_key:
        raise RuntimeError(
            "MINIMAX_API_KEY is not set. Put it in minimax/.env (see .env.example), or run with "
            "--offline to replay records/minimax_recorded.json."
        )
    payload = {
        "model": config.minimax_model(),
        "messages": messages,
        "temperature": 0,
        "max_tokens": int(os.environ.get("MINIMAX_MAX_TOKENS", "16384")),
    }
    request = urllib.request.Request(
        config.minimax_base_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = int(os.environ.get("MINIMAX_TIMEOUT", "300"))
    body = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured provider URL
                body = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"MiniMax HTTP {error.code}: {detail}") from error
        except TimeoutError:
            if attempt == 1:
                raise
    if body is None:
        raise RuntimeError("MiniMax returned no response body")
    content = _content_from_response(body)
    return {
        "provider": "MiniMax",
        "model": config.minimax_model(),
        "base_url": config.minimax_base_url(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "messages": messages,
        "response": content,
        "usage": body.get("usage", {}),
    }


def _content_from_response(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"MiniMax response has no choices: {json.dumps(body)[:500]}")
    message = choices[0].get("message", {})
    content = message.get("content", "")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("MiniMax returned empty content")
    return content


def parse_files(content: str) -> dict[str, object]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("MiniMax response is not a JSON object")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"MiniMax returned invalid JSON: {error}") from error
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("MiniMax response has no files")
    allowed = config.DEMO_DIR / "issuehub"
    validated: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).replace("\\", "/").lstrip("./")
        content_text = item.get("content")
        if not isinstance(content_text, str):
            continue
        normalized = raw_path
        if normalized.startswith("demo_project/"):
            normalized = "minimax/" + normalized
        target = (config.REPO_ROOT / normalized).resolve()
        if allowed.resolve() not in target.parents:
            raise RuntimeError(f"MiniMax tried to write outside demo_project/issuehub: {raw_path}")
        if target.suffix != ".py":
            raise RuntimeError(f"MiniMax can only write Python files: {raw_path}")
        validated.append({"path": normalized, "content": content_text})
    if not validated:
        raise RuntimeError("MiniMax returned no usable files")
    return {"summary": str(payload.get("summary", "")), "files": validated}


def apply_files(record: dict[str, object]) -> list[str]:
    written: list[str] = []
    for item in record["files"]:
        target = config.REPO_ROOT / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["content"], encoding="utf-8")
        written.append(item["path"])
    return written


def generate_files(context: dict[str, object]) -> dict[str, object]:
    """Ask MiniMax once per changed file to keep each JSON response bounded."""

    calls: list[dict[str, object]] = []
    by_path: dict[str, dict[str, str]] = {}
    for target in ("demo_project/issuehub/service.py", "demo_project/issuehub/api.py"):
        messages = build_messages(context, [target])
        raw = call_minimax(messages)
        try:
            parsed = parse_files(str(raw["response"]))
        except Exception:
            config.ensure_dirs()
            (config.RECORDS_DIR / "minimax_failed_response.txt").write_text(
                str(raw["response"]), encoding="utf-8"
            )
            raise
        calls.append({**raw, "summary": parsed["summary"], "files": parsed["files"]})
        for item in parsed["files"]:
            by_path[item["path"]] = item
    return {
        "provider": "MiniMax",
        "model": config.minimax_model(),
        "calls": calls,
        "files": list(by_path.values()),
        "summary": " ".join(str(call.get("summary", "")) for call in calls).strip(),
    }


def load_recorded() -> dict[str, object]:
    path = config.RECORDS_DIR / "minimax_recorded.json"
    if not path.is_file():
        raise RuntimeError(
            f"{path} is missing. Run the live MiniMax step once with MINIMAX_API_KEY set, then keep the record."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def write_record(record: dict[str, object]) -> Path:
    config.ensure_dirs()
    path = config.RECORDS_DIR / "minimax_run.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
