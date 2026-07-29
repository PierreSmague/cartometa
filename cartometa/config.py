from __future__ import annotations
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "defaults.toml"


@dataclass(frozen=True)
class Config:
    data: dict[str, Any]

    def get(self, dotted_key: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config(path: Path | None = None) -> Config:
    with open(path or DEFAULT_CONFIG, "rb") as handle:
        return Config(tomllib.load(handle))
