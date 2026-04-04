from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _runtime_root_candidates() -> list[Path]:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates = [executable_dir, *executable_dir.parents[:2]]
        return list(dict.fromkeys(candidates))

    return [Path(__file__).resolve().parent]


def _project_root() -> Path:
    for candidate in _runtime_root_candidates():
        if (candidate / "run.py").is_file():
            return candidate
    return _runtime_root_candidates()[0]


def _dotenv_path(root: Path) -> Path:
    for candidate in dict.fromkeys([root, *_runtime_root_candidates()]):
        env_path = candidate / ".env"
        if env_path.is_file():
            return env_path
    return root / ".env"


def main() -> int:
    root = _project_root()
    os.chdir(root)
    load_dotenv(_dotenv_path(root))

    run_module = importlib.import_module("run")
    asyncio.run(run_module.main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
