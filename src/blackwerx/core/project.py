""".bwpx project file load/save."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Pattern

BWpx_SUFFIX = ".bwpx"


def save_project(pattern: Pattern, path: str | Path):
    path = Path(path)
    if path.suffix != BWpx_SUFFIX:
        path = path.with_suffix(BWpx_SUFFIX)
    path.write_text(json.dumps(pattern.to_dict(), indent=2))
    return path


def load_project(path: str | Path) -> Pattern:
    data = json.loads(Path(path).read_text())
    if data.get("format") != "bwpx":
        raise ValueError(f"not a Black-Werx project file: {path}")
    return Pattern.from_dict(data)
