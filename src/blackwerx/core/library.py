"""Block library persistence: global store + per-project blocks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .block import Block

if sys.platform == "win32":
    GLOBAL_LIBRARY_PATH = (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "blackwerx" / "library.json"
    )
else:
    GLOBAL_LIBRARY_PATH = (
        Path.home() / ".local" / "share" / "blackwerx" / "library.json"
    )


class Library:
    """Global block library stored as JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else GLOBAL_LIBRARY_PATH
        self.blocks: dict[str, Block] = {}
        self.load()

    def load(self):
        self.blocks = {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for bid, bd in data.get("blocks", {}).items():
            b = Block.from_dict(bd)
            self.blocks[b.id] = b

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"format": "bwlib", "version": 1,
                "blocks": {bid: b.to_dict() for bid, b in self.blocks.items()}}
        self.path.write_text(json.dumps(data, indent=2))

    def add(self, block: Block):
        self.blocks[block.id] = block
        self.save()

    def remove(self, block_id: str):
        self.blocks.pop(block_id, None)
        self.save()

    def get(self, block_id: str) -> Block | None:
        return self.blocks.get(block_id)

    def all(self) -> list[Block]:
        return sorted(self.blocks.values(), key=lambda b: b.name.lower())
