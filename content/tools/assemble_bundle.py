"""Assemble the pgrep content bundle end to end, then gate it.

One command in place of the four-step landing runbook. It calls the existing
tools in order, without reimplementing any of them, and finishes by running the
deterministic invariants over the resulting bundle:

  1. content/tools/land_triple.py     add problems + decompositions + text edits
  2. tools/pgrep_math_convert.py       --apply: bare math -> delimited LaTeX
  3. tools/pgrep_wire_figures.py        --figures: embed the approved SVGs
  4. anki.pgrep.content_invariants     check_bundle + hard_failures (the gate)

Each step runs as a subprocess with the current interpreter, from the repo root,
and a failing step aborts the run. The math step is applied in place (its output
is written back to the same bundle) so the next step sees it. The final gate
prints the report and exits non-zero when a hard invariant fails, so this is safe
to wire into CI or a release script.

Steps can be skipped when their inputs are not ready (for example --skip-math
when no OPENAI_API_KEY is set, or --skip-figures when there is no figure set).
Use --check-only to gate the current bundle without running any step.

Examples:
    # the full runbook, then the gate
    python content/tools/assemble_bundle.py --figures content/run/triple/figures/approved_final.json

    # just gate whatever is currently on disk
    python content/tools/assemble_bundle.py --check-only

    # land and gate, skipping math and figures for a quick loop
    python content/tools/assemble_bundle.py --skip-math --skip-figures
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[2]
DEFAULT_BUNDLE = REPO / "pylib" / "anki" / "pgrep" / "content_bundle.json"
INVARIANTS = REPO / "pylib" / "anki" / "pgrep" / "content_invariants.py"


def _load_invariants() -> ModuleType:
    """Import content_invariants from its file, without importing the anki package.

    The module is stdlib-only, so loading it by path keeps this tool light and
    independent of whether ``anki`` is installed or built.
    """
    spec = importlib.util.spec_from_file_location(
        "pgrep_content_invariants", INVARIANTS
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load invariants module at {INVARIANTS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(cmd: list[str]) -> None:
    """Run a pipeline step from the repo root, aborting on a non-zero exit."""
    print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(REPO), check=False)
    if result.returncode != 0:
        raise SystemExit(f"step failed (exit {result.returncode}): {' '.join(cmd)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    # land_triple inputs (omitted -> the tool's own defaults, i.e. the runbook).
    ap.add_argument("--accepted", nargs="+", default=None)
    ap.add_argument("--decomps", default=None)
    ap.add_argument("--textonly", default=None)
    # pgrep_math_convert options.
    ap.add_argument("--model", default=None)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--env-file", dest="env_file", default=None)
    # pgrep_wire_figures input.
    ap.add_argument("--figures", default=None, help="JSON list of {id, svg} to embed")
    # step toggles.
    ap.add_argument("--skip-land", action="store_true")
    ap.add_argument("--skip-math", action="store_true")
    ap.add_argument("--skip-figures", action="store_true")
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="run only the invariant gate on the current bundle",
    )
    ap.add_argument(
        "--json", action="store_true", help="print the invariant report as JSON"
    )
    args = ap.parse_args(argv)

    py = sys.executable
    bundle = args.bundle

    if not args.check_only:
        if not args.skip_land:
            cmd = [py, "content/tools/land_triple.py", "--bundle", bundle]
            if args.accepted:
                cmd += ["--accepted", *args.accepted]
            if args.decomps:
                cmd += ["--decomps", args.decomps]
            if args.textonly:
                cmd += ["--textonly", args.textonly]
            _run(cmd)
        else:
            print("skip: land_triple")

        if not args.skip_math:
            # --apply writes to --out; point it at the bundle for an in-place pass.
            cmd = [
                py,
                "tools/pgrep_math_convert.py",
                "--bundle",
                bundle,
                "--apply",
                "--out",
                bundle,
            ]
            if args.model:
                cmd += ["--model", args.model]
            if args.workers is not None:
                cmd += ["--workers", str(args.workers)]
            if args.env_file:
                cmd += ["--env-file", args.env_file]
            _run(cmd)
        else:
            print("skip: pgrep_math_convert")

        if not args.skip_figures:
            if not args.figures:
                raise SystemExit(
                    "the figures step needs --figures PATH (or pass --skip-figures)"
                )
            _run(
                [
                    py,
                    "tools/pgrep_wire_figures.py",
                    "--bundle",
                    bundle,
                    "--figures",
                    args.figures,
                ]
            )
        else:
            print("skip: pgrep_wire_figures")

    ci = _load_invariants()
    data = json.loads(Path(bundle).read_text(encoding="utf-8"))
    report = ci.check_bundle(data)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("\n" + ci.format_report(report))

    sys.stdout.flush()
    fails = ci.hard_failures(report)
    if fails:
        print(f"\nGATE: FAIL ({len(fails)} hard invariant(s))", file=sys.stderr)
        return 1
    print("\nGATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
