from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import fields
from pathlib import Path

BENCHMARK_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(BENCHMARK_ROOT))

from jev_astra_bench.cli import write_report
from jev_astra_bench.model import AttemptRecord, PassRecord


_GROUP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FORBIDDEN_TEXT = (
    re.compile(r"apikey_", re.IGNORECASE),
    re.compile(r"TYPESAFE_API_KEY", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]"),
    re.compile(r"\\\\[^\\]+\\[^\\]+"),
)
_LOCAL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/][^\s\"']+|\\\\[^\\\s]+\\[^\s\"']+")
_CREDENTIAL = re.compile(r"apikey_[A-Za-z0-9_-]+|TYPESAFE_API_KEY", re.IGNORECASE)
_ATTEMPT_FIELDS = {item.name for item in fields(AttemptRecord)}
_PASS_FIELDS = {item.name for item in fields(PassRecord)}


def _parse_input(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--input must use NAME=PATH")
    name, raw_path = value.split("=", 1)
    if not _GROUP_NAME.fullmatch(name):
        raise argparse.ArgumentTypeError("input name must contain lowercase letters, digits, or hyphens")
    path = Path(raw_path)
    if not path.is_dir() or not (path / "attempts.jsonl").is_file():
        raise argparse.ArgumentTypeError(f"input does not contain attempts.jsonl: {path}")
    return name, path


def _read_records(path: Path) -> list[AttemptRecord]:
    records: list[AttemptRecord] = []
    for line in (path / "attempts.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("attempt record must be an object")
        clean = {
            key: _scrub_value(value)
            for key, value in raw.items()
            if key in _ATTEMPT_FIELDS
        }
        clean["passes"] = [
            {
                key: _scrub_value(value)
                for key, value in item.items()
                if key in _PASS_FIELDS
            }
            for item in clean.get("passes", [])
            if isinstance(item, dict)
        ]
        records.append(AttemptRecord.from_public_dict(clean))
    return sorted(records, key=lambda item: (item.task_id, item.mode, item.repeat))


def _scrub_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _scrub_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    if isinstance(value, str):
        value = _CREDENTIAL.sub("[redacted]", value)
        return _LOCAL_PATH.sub("[local path redacted]", value)
    return value


def _safe_json(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    for pattern in _FORBIDDEN_TEXT:
        if pattern.search(text):
            raise ValueError(f"evidence contains forbidden text matched by {pattern.pattern}")
    return text


def _write_attempts(records: list[AttemptRecord], path: Path) -> None:
    lines = [_safe_json(record.to_public_dict()) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_evidence(
    inputs: list[tuple[str, Path]],
    output: Path,
    date: str,
    source_commit: str,
    replace: bool = False,
) -> dict[str, object]:
    existing_files = list(output.rglob("*")) if output.exists() else []
    existing_files = [path for path in existing_files if path.is_file()]
    if existing_files and not replace:
        raise ValueError(f"output directory already contains files: {output}")
    if existing_files and replace and not (output / "manifest.json").is_file():
        raise ValueError(f"replace requires an existing evidence manifest: {output}")
    output.mkdir(parents=True, exist_ok=True)
    all_records: list[AttemptRecord] = []
    groups: dict[str, int] = {}
    artifacts: list[Path] = []

    for name, source in inputs:
        records = _read_records(source)
        group = output / name
        group.mkdir(exist_ok=True)
        attempts_path = group / "attempts.jsonl"
        report_path = group / "report.json"
        _write_attempts(records, attempts_path)
        write_report(records, report_path)
        _safe_json(json.loads(report_path.read_text(encoding="utf-8")))
        groups[name] = len(records)
        all_records.extend(records)
        artifacts.extend((attempts_path, report_path))

    all_records.sort(key=lambda item: (item.task_id, item.mode, item.repeat))
    combined_report = output / "combined-report.json"
    write_report(all_records, combined_report)
    _safe_json(json.loads(combined_report.read_text(encoding="utf-8")))
    artifacts.append(combined_report)

    manifest = {
        "schema_version": 1,
        "date": date,
        "source_commit": source_commit,
        "records": len(all_records),
        "groups": groups,
        "sha256": {
            path.relative_to(output).as_posix(): _sha256(path)
            for path in sorted(artifacts, key=lambda item: item.as_posix())
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="export-evidence")
    parser.add_argument("--input", action="append", type=_parse_input, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--replace", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = export_evidence(args.input, args.output, args.date, args.source_commit, args.replace)
    print(f"EVIDENCE_EXPORT_OK records={manifest['records']} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
