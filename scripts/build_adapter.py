#!/usr/bin/env python3
"""Assemble one host's installable bundle, and prove the committed one matches.

ADR 0001 proposes moving host mechanics into `adapters/<host>/` and building
`dist/<host>/` from the portable core plus those mechanics plus the generated
agents. It also names the thing that migration would cost if taken carelessly:

    A build step means the thing reviewed stops being the thing that runs.

Today `agents/*.md` are committed and `render_agents.py --check` proves byte
equality against a re-render, so a reviewer sees the artifact that ships. A
`dist/` tree gives that up unless the same proof extends to the bundle. This
script is that proof, and it exists BEFORE anything moves, which is the order
the ADR calls load-bearing.

What `--check` does, and why it is not a manifest of hashes: a path -> sha256
list proves a bundle is internally consistent, not that it agrees with the
source it claims to come from. A bundle built from stale sources hashes
perfectly. So `--check` rebuilds into a temporary directory and compares the
result byte for byte against what is committed, reporting missing files, extra
files, and differing content separately -- each is a different kind of mistake.

    build_adapter.py --host claude-code
    build_adapter.py --host claude-code --check
"""

import argparse
import filecmp
import fnmatch
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ADAPTERS = ROOT / "adapters"
DIST = ROOT / "dist"


class BuildError(Exception):
    """A layout that cannot be built. Never a partially written bundle."""


def shown(path):
    """A path a reader can act on, without the formatting itself raising.

    relative_to() raises when the path is outside the repository, which is
    reachable whenever ADAPTERS is redirected -- tests do it, and an
    out-of-tree build would. An error message that cannot be built is a
    traceback in place of the diagnostic, which is the failure mode this
    repository keeps closing in its guards.
    """
    try:
        return Path(path).relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_layout(host):
    path = ADAPTERS / host / "layout.json"
    if not path.exists():
        raise BuildError("no adapter layout: %s" % shown(path))
    try:
        layout = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise BuildError("%s is not valid JSON: %s" % (shown(path), e))
    if layout.get("host") != host:
        raise BuildError(
            "%s declares host %r but is filed under %r" % (shown(path), layout.get("host"), host)
        )
    if not layout.get("place"):
        raise BuildError("%s places nothing" % shown(path))
    return layout


def resolve_source(host, source):
    """Adapter directory first, repository root second.

    This ordering is what lets ADR 0001's step 3 be a pure `git mv`: move
    `hooks/` into `adapters/claude-code/hooks/` and the layout entry keeps
    working, because the adapter copy now wins.
    """
    for base in (ADAPTERS / host, ROOT):
        candidate = base / source
        if candidate.exists():
            return candidate
    raise BuildError(
        "layout names a source that exists in neither adapters/%s/ nor the "
        "repository root: %s" % (host, source)
    )


def excluded(relative, patterns):
    text = relative.as_posix()
    return any(fnmatch.fnmatch(text, pattern) for pattern in patterns)


def build(host, out_dir):
    """Write the bundle. Always into an empty directory, never over one."""
    layout = load_layout(host)
    patterns = layout.get("exclude") or []
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    written = []
    for source, destination in sorted(layout["place"].items()):
        origin = resolve_source(host, source.rstrip("/"))
        target = out_dir / destination.rstrip("/")
        if source.endswith("/") != destination.endswith("/"):
            raise BuildError(
                "layout entry %r -> %r mixes a directory with a file; a "
                "trailing slash must appear on both sides or neither" % (source, destination)
            )
        is_dir = source.endswith("/")
        if is_dir:
            if not origin.is_dir():
                raise BuildError("%s is not a directory" % shown(origin))
            items = origin.rglob("*")
        else:
            if not origin.is_file():
                raise BuildError("%s is not a file" % shown(origin))
            items = [origin]

        for item in sorted(p for p in items if p.is_file()):
            relative = item.relative_to(origin) if is_dir else Path()
            if is_dir and excluded(relative, patterns):
                continue
            landing = target / relative
            landing.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, landing)
            written.append(landing.relative_to(out_dir))
    return sorted(written)


def tree(root, patterns=None):
    root = Path(root)
    files = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root)
            if patterns and excluded(rel, patterns):
                continue
            files.append(rel)
    return sorted(files)


def compare(built_dir, committed_dir, patterns=None):
    """Missing, extra and differing are three separate failures.

    Collapsing them into one "out of sync" loses the only information that
    tells a reader whether the build changed, the sources changed, or someone
    edited the bundle by hand.
    """
    built, committed = set(tree(built_dir, patterns)), set(tree(committed_dir, patterns))
    missing = sorted(built - committed)
    extra = sorted(committed - built)
    differing = sorted(
        p
        for p in (built & committed)
        if not filecmp.cmp(Path(built_dir) / p, Path(committed_dir) / p, shallow=False)
    )
    return missing, extra, differing


def cmd_check(host):
    committed = DIST / host
    if not committed.is_dir():
        print("no committed bundle to check: dist/%s" % host, file=sys.stderr)
        return 1
    layout = load_layout(host)
    patterns = layout.get("exclude") or []
    with tempfile.TemporaryDirectory() as scratch:
        fresh = Path(scratch) / host
        build(host, fresh)
        missing, extra, differing = compare(fresh, committed, patterns)
    if not (missing or extra or differing):
        print(
            "in sync: dist/%s matches a fresh build from adapters/%s and the "
            "repository core (%d files)" % (host, host, len(tree(committed, patterns)))
        )
        return 0
    print("dist/%s does NOT match a fresh build:" % host, file=sys.stderr)
    for path in missing:
        print("  missing from dist/: %s" % path.as_posix(), file=sys.stderr)
    for path in extra:
        print("  present in dist/ but not built: %s" % path.as_posix(), file=sys.stderr)
    for path in differing:
        print("  content differs: %s" % path.as_posix(), file=sys.stderr)
    print("\nRebuild with: python3 scripts/build_adapter.py --host %s" % host, file=sys.stderr)
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--out", help="defaults to dist/<host>")
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild into a temporary directory and fail if the committed "
        "bundle differs, instead of writing",
    )
    args = parser.parse_args(argv)

    try:
        if args.check:
            return cmd_check(args.host)
        out = Path(args.out) if args.out else DIST / args.host
        written = build(args.host, out)
        try:
            shown = out.relative_to(ROOT).as_posix()
        except ValueError:
            shown = str(out)
        print("built %s: %d files" % (shown, len(written)))
        return 0
    except BuildError as e:
        print("build failed: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
