from __future__ import annotations

import json
from typing import Any
from urllib.request import urlopen  # stdlib to keep this simple


def fetch_public_json(url: str, timeout: int = 20) -> list[dict[str, Any]]:
    """Tiny helper for optional public JSON fallback."""
    with urlopen(url, timeout=timeout) as r:  # nosec - used for read-only public JSON
        payload = json.loads(r.read().decode("utf-8"))
    if isinstance(payload, list):
        return payload  # type: ignore[return-value]
    return []  # conservative
