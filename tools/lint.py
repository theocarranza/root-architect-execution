#!/usr/bin/env python3
"""Format, lint, and type-check the repository.

Usage:
    tools/lint.py          # check linter rules, formatting, and types
    tools/lint.py --check  # check without modifying files (fails on violations)
    tools/lint.py --fix    # apply auto-fixes, reformat code, and rebuild bundles
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def find_tool(name):
    """Locate an executable in venv, on PATH, or in standard user local bin."""
    # 1. Active / project virtualenv
    venv_bin = ROOT / ".venv" / "bin" / name
    if venv_bin.is_file() and os.access(venv_bin, os.X_OK):
        return str(venv_bin)
    # 2. System PATH
    path = shutil.which(name)
    if path:
        return path
    # 3. User local bin
    candidate = Path.home() / ".local" / "bin" / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def run_cmd(cmd, cwd=None):
    """Run a subprocess and forward stdout/stderr."""
    result = subprocess.run(cmd, cwd=cwd or str(ROOT))
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="automatically fix linter errors, reformat files, and rebuild bundles",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check formatting and types without modifying files (default)",
    )
    args = parser.parse_args(argv)

    ruff_bin = find_tool("ruff")
    if not ruff_bin:
        print(
            "ruff is required for linting and formatting.\n"
            "Install it with: pip install ruff (or 'uv tool install ruff')",
            file=sys.stderr,
        )
        return 1

    # 1. Whitespace and merge conflict check
    git_bin = shutil.which("git")
    if git_bin:
        res = subprocess.run([git_bin, "diff", "--check"], cwd=str(ROOT))
        if res.returncode != 0:
            print("git diff --check detected whitespace or conflict errors", file=sys.stderr)
            return res.returncode

    # 2. Ruff check (linter)
    check_args = [ruff_bin, "check"]
    if args.fix:
        check_args.append("--fix")
    code = run_cmd(check_args)
    if code != 0:
        return code

    # 3. Ruff format
    format_args = [ruff_bin, "format"]
    if not args.fix:
        format_args.append("--check")
    code = run_cmd(format_args)
    if code != 0:
        return code

    # 4. Type checking / missing imports check (pyright / basedpyright / mypy)
    type_checker = find_tool("basedpyright") or find_tool("pyright")
    if type_checker:
        code = run_cmd([type_checker, "adapters/claude-code/hooks/"])
        if code != 0:
            return code

    mypy_bin = find_tool("mypy")
    if mypy_bin:
        code = run_cmd([mypy_bin, "scripts/"])
        if code != 0:
            return code

    # If --fix was requested, rebuild host bundles
    if args.fix:
        build_script = ROOT / "scripts" / "build_adapter.py"
        res = subprocess.run([sys.executable, str(build_script), "--all"], cwd=str(ROOT))
        if res.returncode != 0:
            print("failed rebuilding host adapter bundles", file=sys.stderr)
            return res.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
