"""CLI dispatcher (frozen). `uv run triad run --row 34` / `uv run triad pick --n 500`."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="triad")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run one negotiation on a dataset row")
    r.add_argument("--row", type=int, help="row_index in flights.csv (0-based data row)")
    r.add_argument("--scenario", help="name from config/demo_scenarios.yaml")
    r.add_argument("--defect", help="force a defect id from config/defects.yaml (GROUND mode)")
    r.add_argument("--ai-off", action="store_true", help="skip agents; deterministic fallback only")
    r.add_argument("--red-team", action="store_true", help="inject unsafe-approval behaviour into the Pilot agent")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--impl", choices=["stub", "llm"], default="stub", help="agent implementation")
    r.add_argument("--no-cache", action="store_true", help="bypass the LLM response cache")
    r.add_argument("--out", default=None, help="runs directory (default: runs/)")
    r.add_argument("--quiet", action="store_true")

    k = sub.add_parser("pick", help="Scan rows and select demo scenarios")
    k.add_argument("--n", type=int, default=500, help="rows to sample")
    k.add_argument("--seed", type=int, default=0)
    k.add_argument("--write", action="store_true", help="write config/demo_scenarios.yaml")

    x = sub.add_parser("index", help="Build per-agent RAG indexes from corpus/")
    x.add_argument("--eval", action="store_true", help="also run retrieval evaluation (hit@3)")

    e = sub.add_parser("eval-perception", help="Score LLM perception on corpus/eval/perception.yaml")
    e.add_argument("--model", required=True, help="LLM model name (e.g. x-test-4)")
    e.add_argument("--limit", type=int, default=None, help="evaluate only the first N items")

    args = p.parse_args(argv)
    if args.cmd == "index":
        from triad.rag.ingest import index_main

        index_main(args)
        return
    if args.cmd == "eval-perception":
        from triad.eval.perception_eval import eval_main

        eval_main(args)
        return
    if args.cmd == "run":
        from triad.runner import run_main

        run_main(args)
    else:
        from triad.picker import pick_main

        pick_main(args)


if __name__ == "__main__":
    main()
