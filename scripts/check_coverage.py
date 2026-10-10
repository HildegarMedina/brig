"""Run all unit test modules and enforce the repository coverage threshold."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    modules = [
        f"tests.{path.stem}" for path in sorted((root / "tests").glob("test_*.py"))
    ]
    if not modules:
        print("No unit tests found.", file=sys.stderr)
        return 1
    tests = subprocess.run(
        [sys.executable, "-m", "coverage", "run", "-m", "unittest", *modules],
        cwd=root,
        check=False,
    )
    report = subprocess.run(
        [sys.executable, "-m", "coverage", "report"], cwd=root, check=False
    )
    return tests.returncode or report.returncode


if __name__ == "__main__":
    raise SystemExit(main())
