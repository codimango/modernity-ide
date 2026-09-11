#!/usr/bin/env python3
"""Run the hovercraft through the shared hash-locked mesh cycle runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


SHARED_RUNNER = Path(__file__).resolve().parents[1] / "03-off-road-truck" / "run-cycle.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("round3_mesh_cycle_runner", SHARED_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared mesh cycle runner: {SHARED_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    runner = _load_runner()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not any(
        argument == "--config" or argument.startswith("--config=")
        for argument in arguments
    ):
        arguments.extend(("--config", str(Path(__file__).with_name("cycle.json"))))
    return runner.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
