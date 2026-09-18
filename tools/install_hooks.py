#!/usr/bin/env python3
"""Install repository git hooks (pre-commit and pre-push).

Usage:
    python3 tools/install_hooks.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOOKS_DIR = HERE / "hooks"
GIT_DIR = ROOT / ".git"


def main():
    if not GIT_DIR.is_dir():
        print("Not a git repository (missing .git directory): %s" % GIT_DIR, file=sys.stderr)
        return 1

    # 1. Ensure hooks have executable permissions
    for hook_name in ("pre-commit", "pre-push"):
        src = HOOKS_DIR / hook_name
        if src.is_file():
            src.chmod(src.stat().st_mode | 0o755)

    # 2. Configure git core.hooksPath
    git_bin = shutil.which("git")
    if git_bin:
        res = subprocess.run([git_bin, "config", "core.hooksPath", "tools/hooks"], cwd=str(ROOT))
        if res.returncode != 0:
            print("Failed to set git config core.hooksPath", file=sys.stderr)
            return res.returncode
        print("Configured git core.hooksPath -> tools/hooks")

    # 3. Also copy to .git/hooks as fallback
    target_hooks = GIT_DIR / "hooks"
    target_hooks.mkdir(parents=True, exist_ok=True)
    for hook_name in ("pre-commit", "pre-push"):
        src = HOOKS_DIR / hook_name
        dst = target_hooks / hook_name
        if src.is_file():
            shutil.copy2(src, dst)
            dst.chmod(dst.stat().st_mode | 0o755)
            print("Installed fallback hook -> %s" % dst.relative_to(ROOT))

    print("\nGit hooks installed successfully:")
    print("  - pre-commit: checks whitespace, ruff lint/formatting, types, role schemas, and drift")
    print("  - pre-push:   runs pre-commit checks + complete unit tests + smoke install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
