"""Load a client's specs (take, reshape, crosswalks) and resolve {placeholders}."""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def _resolve(value, variables: dict):
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [_resolve(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, variables) for k, v in value.items()}
    return value


class ClientSpecs:
    def __init__(self, client_dir: str | Path, take_id: str | None = None):
        """take_id selects clients/<client>/takes/<take_id>.yaml (each take has its own date and file names);
        without it, or when it names the default take, clients/<client>/take.yaml is used."""
        self.dir = Path(client_dir)
        take_file = self.dir / "take.yaml"
        if take_id and (self.dir / "takes" / f"{take_id}.yaml").exists():
            take_file = self.dir / "takes" / f"{take_id}.yaml"
        self.take = yaml.safe_load(take_file.read_text(encoding="utf-8"))
        if take_id and self.take.get("take_id") != take_id:
            raise ValueError(f"no take file for '{take_id}': add {self.dir / 'takes' / (take_id + '.yaml')}")
        self.vars = {k: self.take[k] for k in ("client", "take_id", "take_date", "conversion_date") if k in self.take}
        self.reshapes = []
        for p in sorted((self.dir / "reshape").glob("*.yaml")):
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            if spec.get("kind") == "reshape":
                spec["_path"] = str(p)
                self.reshapes.append(_resolve(spec, self.vars))
        self.crosswalks = {}
        for p in sorted((self.dir / "crosswalks").glob("*.yaml")):
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            if spec.get("kind") == "crosswalk":
                self.crosswalks[spec["id"]] = spec

    @property
    def client(self) -> str:
        return self.take["client"]

    @property
    def take_id(self) -> str:
        return self.take["take_id"]

    def file_reshapes(self, landing: str | Path) -> list[dict]:
        """Reshape specs whose source is a file of this take (the others describe legacy SQL logic)."""
        landing = Path(landing)
        return [s for s in self.reshapes if (landing / s["source"]["file"]).exists()]
