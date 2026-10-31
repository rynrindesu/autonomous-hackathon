"""Print a run's negotiation transcript as Markdown (for slides).

    uv run python scripts/transcript.py runs/2015-09-17-UA1680-r293614-llm/log.jsonl
    uv run python scripts/transcript.py <log.jsonl> --rationale   # also quote full rationales

Deterministic: built only from log.jsonl by app/components/transcript.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from components.transcript import build_transcript, load_entries, to_markdown  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", type=Path, help="path to a run's log.jsonl (or its run directory)")
    parser.add_argument("--rationale", action="store_true", help="quote each agent's full rationale")
    args = parser.parse_args()
    path = args.log / "log.jsonl" if args.log.is_dir() else args.log
    entries = load_entries(path)
    title = f"Negotiation transcript · {entries[0].get('run_id', path.parent.name)}" if entries else None
    sys.stdout.write(to_markdown(build_transcript(entries), title=title, rationale=args.rationale))


if __name__ == "__main__":
    main()
