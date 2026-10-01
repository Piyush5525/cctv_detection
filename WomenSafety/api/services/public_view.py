"""Fix pass item 7: API output never carries absolute server paths.

Stored incident JSON keeps absolute evidence paths (the notification service
and scripts open those files directly). Everything that leaves the API goes
through public_view(), which rewrites any string under the evidence root or
the project root to a relative path (forward slashes).
"""
from __future__ import annotations

from pathlib import Path

from api.core.config import settings

_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


def _prefixes() -> list[str]:
    out = []
    for root in (Path(settings.EVIDENCE_ROOT_V2), _PROJECT_ROOT):
        for form in (str(root), str(root.resolve())):
            for variant in (form, form.replace("\\", "/")):
                if variant not in out:
                    out.append(variant)
    return sorted(out, key=len, reverse=True)


def _scrub_str(value: str, prefixes: list[str]) -> str:
    for prefix in prefixes:
        if value.startswith(prefix):
            return value[len(prefix):].lstrip("\\/").replace("\\", "/")
        if prefix in value:
            value = value.replace(prefix, "")
    return value


def public_view(obj):
    prefixes = _prefixes()

    def walk(x):
        if isinstance(x, str):
            return _scrub_str(x, prefixes)
        if isinstance(x, list):
            return [walk(i) for i in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x
    return walk(obj)
