# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Run the best-of-N content foundry, with an offline dry-run mode."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import foundry_loop, preference  # type: ignore[import-not-found]  # noqa: E402


@dataclass
class _DryVerdict:
    decision: str

    def to_dict(self) -> dict:
        checks = []
        if self.decision == "accept":
            checks.append(
                {
                    "name": "synthetic_acceptance",
                    "passed": True,
                    "severity": "hard",
                    "evidence": "offline dry-run acceptance",
                }
            )
        elif self.decision == "reject":
            checks.append(
                {
                    "name": "synthetic_rejection",
                    "passed": False,
                    "severity": "hard",
                    "evidence": "offline dry-run rejection",
                }
            )
        return {"decision": self.decision, "checks": checks}

    def reasons(self) -> list[str]:
        return ["offline dry-run rejection"] if self.decision == "reject" else []


class _DryVerifier:
    def check(self, problem: dict) -> _DryVerdict:
        decisions = ("accept", "reject", "escalate")
        return _DryVerdict(decisions[problem["_foundry_seed"] % len(decisions)])


def _dry_run(
    topic: str, n: int, *, category: str | None = None
) -> foundry_loop.SlotResult:
    category = category or "mechanics"
    sequence = iter(range(max(0, n)))

    def generate(slot: dict) -> dict:
        index = next(sequence)
        return {
            "id": f"dry-{index + 1}",
            "topic": slot["topic"],
            "blueprint_category": slot["blueprint_category"],
            "stem": f"Offline candidate {index + 1}",
            "choices": ["A", "B", "C", "D", "E"],
            "key": "A",
            "source_ref": (
                f"synthetic://foundry/{slot['blueprint_category']}/{index + 1}"
            ),
        }

    return foundry_loop.run_slot(
        {"topic": topic, "blueprint_category": category},
        generate_fn=generate,
        verifier=_DryVerifier(),
        n=n,
    )


def _summary(result: foundry_loop.SlotResult, pairs: list[dict], category: str) -> dict:
    summary = foundry_loop.summarize_runs([result])
    summary["blueprint_category"] = category
    summary["preferences"] = preference.summarize_pairs(pairs)
    return summary


def _effective_n(requested_n: int, verifier_accuracy: float) -> int:
    return min(requested_n, foundry_loop.max_n_for_accuracy(verifier_accuracy))


def _validate_run_id(run_id: str) -> None:
    if (
        not run_id.strip()
        or Path(run_id).name != run_id
        or run_id in {".", ".."}
        or "\\" in run_id
    ):
        raise ValueError("run ID must be a non-empty directory name")


def _write_result(
    out: str,
    run_id: str,
    result: foundry_loop.SlotResult,
    slot: dict,
    *,
    synthetic: bool = False,
) -> Path:
    """Persist a complete run through a temporary sibling directory."""
    _validate_run_id(run_id)
    out_dir = Path(out)
    run_dir = out_dir / run_id
    if run_dir.exists():
        raise ValueError(f"foundry run directory already exists: {run_dir}")

    pairs = preference.pairs_from_slot(
        slot,
        result,
        run_id=run_id,
        synthetic=synthetic,
    )
    payloads = {
        "accepted.json": result.accepted,
        "rejected.json": result.rejected,
        "escalated.json": result.escalated,
        "summary.json": _summary(
            result,
            pairs,
            slot["blueprint_category"],
        ),
    }
    rendered = {
        filename: json.dumps(payload, indent=2, allow_nan=False) + "\n"
        for filename, payload in payloads.items()
    }

    temporary: Path | None = None
    lock_path = out_dir / f".{run_id}.lock"
    lock_fd: int | None = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as error:
            raise ValueError(
                f"foundry run publication lock already exists: {lock_path}"
            ) from error
        os.write(lock_fd, f"pid={os.getpid()}\n".encode())
        if run_dir.exists():
            raise ValueError(f"foundry run directory already exists: {run_dir}")
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{run_id}.", suffix=".tmp", dir=out_dir)
        )
        for filename, content in rendered.items():
            (temporary / filename).write_text(content, encoding="utf-8")
        written = preference.write_jsonl(str(temporary / "preferences.jsonl"), pairs)
        if written != len(pairs):
            raise ValueError(
                f"preference count mismatch: generated {len(pairs)}, wrote {written}"
            )
        if run_dir.exists():
            raise ValueError(f"foundry run directory already exists: {run_dir}")
        os.rename(temporary, run_dir)
        temporary = None
    except OSError as error:
        raise ValueError(
            f"could not persist foundry run {run_id!r}: {error}"
        ) from error
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    return run_dir


def _self_check() -> int:
    result = _dry_run("classical_mechanics", 3)
    assert [len(result.accepted), len(result.rejected), len(result.escalated)] == [
        1,
        1,
        1,
    ]
    assert result.accepted[0]["correct"] == "A"
    print(f"[ok] foundry self-check passed; yield={result.yield_rate:.3f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the best-of-N content foundry.")
    parser.add_argument("--dry-run", action="store_true", help="use offline fakes")
    parser.add_argument(
        "--n", type=int, default=8, help="requested candidates per slot"
    )
    parser.add_argument(
        "--verifier-accuracy",
        type=float,
        default=0.8,
        help=(
            "calibrated verifier accuracy used to cap N "
            "(default: 0.8, which caps N at 6)"
        ),
    )
    parser.add_argument("--topic", default="classical_mechanics")
    parser.add_argument(
        "--category",
        default="mechanics",
        help="locked blueprint category for the slot (default: mechanics)",
    )
    parser.add_argument("--out", default="content/run/foundry")
    parser.add_argument(
        "--run",
        help=(
            "new run directory name under --out "
            "(default: current UTC timestamp with microseconds)"
        ),
    )
    parser.add_argument(
        "--self-check", action="store_true", help="run an offline smoke and exit"
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="request comparative selection (deferred to Phase 2.1)",
    )
    args = parser.parse_args()

    if args.compare:
        print(
            "--compare is deferred to Phase 2.1; continuing without it", file=sys.stderr
        )
    if args.self_check:
        return _self_check()
    if not args.dry_run:
        parser.error("online generation is not available yet; use --dry-run")
    if args.n < 0:
        parser.error("--n must be non-negative")
    if not 0.0 <= args.verifier_accuracy <= 1.0:
        parser.error("--verifier-accuracy must be between 0 and 1")

    effective_n = _effective_n(args.n, args.verifier_accuracy)
    category = args.category
    if category not in preference.BLUEPRINT_CATEGORIES:
        parser.error(
            "blueprint category must be one of: "
            + ", ".join(sorted(preference.BLUEPRINT_CATEGORIES))
        )
    result = _dry_run(args.topic, effective_n, category=category)
    run_id = args.run or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        run_dir = _write_result(
            args.out,
            run_id,
            result,
            {"topic": args.topic, "blueprint_category": category},
            synthetic=True,
        )
    except ValueError as error:
        parser.error(str(error))
    print(
        f"requested_n={args.n}; effective_n={effective_n}; "
        f"yield={result.yield_rate:.3f}; wrote {run_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
