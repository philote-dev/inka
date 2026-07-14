"""Run the best-of-N content foundry, with an offline dry-run mode."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import _ai_path  # noqa: E402

_ai_path.add_ai_core()

from pgrep.ai import foundry_loop  # type: ignore[import-not-found]  # noqa: E402


@dataclass
class _DryVerdict:
    decision: str

    def to_dict(self) -> dict:
        return {"decision": self.decision, "checks": []}

    def reasons(self) -> list[str]:
        return ["offline dry-run rejection"] if self.decision == "reject" else []


class _DryVerifier:
    def check(self, problem: dict) -> _DryVerdict:
        decisions = ("accept", "reject", "escalate")
        return _DryVerdict(decisions[problem["_foundry_seed"] % len(decisions)])


def _dry_run(topic: str, n: int) -> foundry_loop.SlotResult:
    sequence = iter(range(max(0, n)))

    def generate(slot: dict) -> dict:
        index = next(sequence)
        return {
            "id": f"dry-{index + 1}",
            "topic": slot["topic"],
            "stem": f"Offline candidate {index + 1}",
            "choices": ["A", "B", "C", "D", "E"],
            "key": "A",
        }

    return foundry_loop.run_slot(
        {"topic": topic},
        generate_fn=generate,
        verifier=_DryVerifier(),
        n=n,
    )


def _payload(result: foundry_loop.SlotResult) -> dict:
    return {
        "accepted": result.accepted,
        "rejected": result.rejected,
        "escalated": result.escalated,
        "yield_rate": result.yield_rate,
    }


def _write_result(out: str, topic: str, result: foundry_loop.SlotResult) -> Path:
    output_dir = Path(out)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{topic}.json"
    output_path.write_text(json.dumps(_payload(result), indent=2) + "\n")
    return output_path


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
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--topic", default="classical_mechanics")
    parser.add_argument("--out", default="content/run/foundry")
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
        print("--compare is deferred to Phase 2.1; continuing without it", file=sys.stderr)
    if args.self_check:
        return _self_check()
    if not args.dry_run:
        parser.error("online generation is not available yet; use --dry-run")
    if args.n < 0:
        parser.error("--n must be non-negative")

    result = _dry_run(args.topic, args.n)
    output_path = _write_result(args.out, args.topic, result)
    print(f"yield={result.yield_rate:.3f}; wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
