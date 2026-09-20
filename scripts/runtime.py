"""Offline inspection commands for the runtime store; no dispatch surface."""

import argparse
from pathlib import Path

from runtime_store import RuntimeStore


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline runtime store commands")
    parser.add_argument("--state-root", required=True, type=Path)
    subcommands = parser.add_subparsers(dest="operation", required=True)
    subcommands.add_parser("init", help="create or migrate an offline local store")
    export = subcommands.add_parser("export", help="generate disposable JSON and Markdown exports")
    export.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    store = RuntimeStore(args.state_root)
    if args.operation == "export":
        store.export(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
