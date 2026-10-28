"""Test helpers shared by the demo API tests."""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import urlopen


def get_json(base: str, path: str) -> tuple[int, dict[str, object]]:
    try:
        with urlopen(base + path, timeout=5) as response:  # noqa: S310 - loopback test server
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))
