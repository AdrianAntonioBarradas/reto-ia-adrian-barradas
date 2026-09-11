"""Checksum the canonical corpus.

The corpus is the one thing the agent treats as true, so a change to it should be as
visible as a change to code. The manifest records a SHA-256 per source file; a test
compares it against what is on disk and fails the build if they diverge.

What this buys, concretely:

* **Deterministic rebuilds.** The chunk index is derived, so "which corpus produced
  these numbers?" has an answer that is not "whatever was checked out that day".
* **Poisoning becomes loud.** An edit to the corpus that slips through review changes
  a checksum. Without this, the only signal is the agent quietly asserting something
  new, which is the failure mode that matters least when caught late.

    uv run python -m scripts.manifest --write     # regenerate after a corpus change
    uv run python -m scripts.manifest --check     # what the test does
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "data" / "canonical"
MANIFEST = ROOT / "data" / "manifests" / "canonical.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, Any]:
    files = sorted(CANONICAL.glob("*.yaml"))
    entries = {p.name: {"sha256": digest(p), "bytes": p.stat().st_size} for p in files}
    # A digest over the per-file digests: one value that identifies the whole corpus,
    # so a report or a stored evaluation result can name the corpus it ran against.
    combined = hashlib.sha256(
        "".join(f"{name}:{e['sha256']}" for name, e in entries.items()).encode()
    ).hexdigest()
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus_sha256": combined,
        "file_count": len(entries),
        "files": entries,
    }


def load() -> dict[str, Any] | None:
    if not MANIFEST.is_file():
        return None
    data: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return data


def differences(current: dict[str, Any], recorded: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    cur, rec = current["files"], recorded.get("files", {})
    for name in sorted(set(cur) | set(rec)):
        if name not in rec:
            problems.append(f"{name}: present on disk, absent from the manifest")
        elif name not in cur:
            problems.append(f"{name}: recorded in the manifest, absent on disk")
        elif cur[name]["sha256"] != rec[name]["sha256"]:
            problems.append(f"{name}: content changed since the manifest was written")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()

    current = build()

    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(
            json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {MANIFEST.relative_to(ROOT)}")
        print(f"  {current['file_count']} files, corpus {current['corpus_sha256'][:16]}…")
        return 0

    recorded = load()
    if recorded is None:
        print("no manifest: run `uv run python -m scripts.manifest --write`")
        return 1
    problems = differences(current, recorded)
    if problems:
        print("corpus does not match the manifest:")
        for p in problems:
            print(f"  - {p}")
        print("\nIf the change was intended, regenerate with --write and commit both.")
        return 1
    print(
        f"corpus matches the manifest ({current['file_count']} files, "
        f"{current['corpus_sha256'][:16]}…)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
