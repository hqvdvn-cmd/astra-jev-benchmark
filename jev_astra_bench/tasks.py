from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from .model import TaskSpec


def load_manifest(path: Path) -> list[TaskSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks: list[TaskSpec] = []
    for item in data["tasks"]:
        fixture = (path.parent / item["fixture_dir"]).resolve()
        tasks.append(
            TaskSpec(
                task_id=item["task_id"],
                kind=item["kind"],
                prompt=item["prompt"],
                fixture_dir=fixture,
                verifier=item["verifier"],
                browser_profile=item.get("browser_profile"),
                allowed_files=tuple(item.get("allowed_files", ())),
                requirements=tuple(item.get("requirements", ())),
                review_changed_lines_above=item.get("review_changed_lines_above"),
            )
        )
    return tasks


def copy_fixture(task: TaskSpec, repeat: int, root: Path | None = None) -> Path:
    base = root or Path(tempfile.mkdtemp(prefix=f"jev-astra-{task.task_id}-{repeat}-"))
    workspace = base / "workspace"
    shutil.copytree(task.fixture_dir, workspace)
    return workspace
