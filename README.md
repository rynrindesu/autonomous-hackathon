# Triad: multi-agent flight disruption negotiation

Triad is a prototype for Challenge #2. Three agents (ATC, Pilot, Ground) each hold their own private data and manuals, and negotiate a response to a real flight disruption from the 2015 DOT dataset. A deterministic orchestrator, written in plain Python with no AI, routes the messages, enforces the turn limit, and writes the log. It never chooses the answer itself.

The agents can run as LLM agents or as deterministic stub agents. Every option passes through hard safety checks written in code, and every run ends in one of three ways: consensus, a fallback choice, or escalation to a human.

## How it works

Each run follows this sequence:

1. **Setup.** The orchestrator builds the disruption from one `flights.csv` row and generates candidate options. Shared checks remove any option that fails.
2. **Turn 1, PROPOSE.** Each agent returns vetoes (from its own code checks), a ranking, objections, and at most one counter-option.
3. **Turn 2, BALLOT.** Each agent approves or disapproves a shortlist of up to six options. Each agent may attach one counter-option.
4. **Turn 3, FINAL BALLOT.** A shortlist of up to four options, decided by 2-of-3 approvals. No new options.
5. **Commit or fallback.** If the agents agree, the option is committed. Otherwise a deterministic solver picks the cheapest option that passes every check, and the log records why.

Before anything is committed, `assert_commit_safe` re-runs every check on the chosen option.

Two decision modes are used, chosen by the row's delay causes:

- **AIRBORNE:** `WEATHER_DELAY > 15`. The decision is made about 60 minutes before arrival.
- **GROUND:** `LATE_AIRCRAFT_DELAY > 20` with no weather delay. The decision is made at the origin, before departure.

A row is a valid disruption only if it meets one of these conditions (`is_candidate`).

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- An OpenAI-compatible LLM endpoint, only if you want LLM agents

## Setup

```bash
uv sync
uv run pytest -q          # run the test suite
```

To use LLM agents, create a `.env` file in the project root (it is gitignored):

```bash
LLM_BASE_URL=https://your-endpoint/v1
LLM_MODEL=your-model-id
LLM_API_KEY=...            # or SOCLAAS_API_KEY
LLM_TIMEOUT_S=90           # optional
LLM_MAX_TOKENS=1500        # optional, 0 disables the cap
LLM_CACHE=1                # optional, 0 disables the response cache
```

`.env.example` lists the same variables. Without a `.env`, the code uses the defaults in `src/triad/llm/client.py`.

The endpoint must accept strict JSON-schema output. The client sends `strict: true` with every object closed (`additionalProperties: false`), and it does not send numeric bounds or map-typed fields. Agent output models use lists of objects for that reason.

## Running a negotiation

Pick a demo scenario:

| Scenario       | Row    | Mode     | What it shows                                                         |
| -------------- | ------ | -------- | --------------------------------------------------------------------- |
| `scenario_a` | 293614 | AIRBORNE | Weather cuts the destination arrival rate                             |
| `scenario_b` | 18896  | GROUND   | Late aircraft with a non-deferrable hydraulic defect (`DEF-HYD-02`) |
| `scenario_c` | 168086 | AIRBORNE | Fuel reserve, with `--red-team` to show a blocked unsafe approval   |

```bash
uv run triad run --scenario scenario_a                  # stub agents (default)
uv run triad run --scenario scenario_a --impl llm       # LLM agents
uv run triad run --scenario scenario_c --red-team       # Pilot pushed to approve an unsafe option
uv run triad run --scenario scenario_a --ai-off         # deterministic fallback only
uv run triad run --row 293614 --seed 0                  # any candidate row
uv run triad run --scenario scenario_b --defect DEF-HYD-02 --no-cache
```

Other commands:

```bash
uv run triad pick                 # sample candidate rows and look for demo scenarios
uv run triad index                # build per-agent RAG indexes from corpus/
uv run triad eval-perception      # score LLM perception on corpus/eval/perception.yaml
uv run python scripts/batch_eval.py --n 50 --impl stub   # batch evaluation report
```

## Web app

```bash
uv run streamlit run app/streamlit_app.py
```

The app has two modes:

- **Replay saved run:** opens a finished run from `runs/`.
- **Run new scenario:** pick a demo scenario or a dataset row, then run it. The page shows each turn as it is logged.

## Outputs

Each run writes a folder to `runs/<run_id><suffix>/`:

- `log.jsonl`: the hash-chained event log. Each entry includes the previous entry's hash.
- `manifest.json`: the run's inputs and flags.
- `resolution.json`: the committed option, or the fallback decision.

## Caching and replay

LLM responses are cached in `.cache/llm/`, keyed by a hash of the model, prompts, and schema. With the cache on, a repeated call replays the stored response and makes no network request. A cache miss calls the endpoint.

The cache is what makes a run repeatable. The provider's own output is not deterministic even at temperature 0. The cache is gitignored, so it does not travel with the repository.

There is no separate offline mode. A run with a complete cache replays without network access. A run with any cache miss needs the endpoint.

## Data

- `datasets/flights.csv`: a subset of the 2015 DOT on-time data, with delayed flights only.
- `datasets/airports.csv`, `datasets/airlines.csv`: airport coordinates and carrier names.

Some values are synthetic and seeded per row: aircraft type, fuel, gate inventory, crew shifts, NOTAM and turbulence text, and defect reports. The UI labels each seeded value as synthetic. Real DOT values are labelled as real.

Runways and operational limits come from `config/runways.yaml` and `config/operational_limits.yaml`. The limits file was generated from the challenge's constraints workbook by `scripts/import_constraints_workbook.py`, which needs `openpyxl` (`uv run --with openpyxl python scripts/import_constraints_workbook.py`).

`config/negotiable_rows.yaml` is generated by `scripts/build_negotiable_rows.py`. Edit the script, not the YAML.

## Layout

```
src/triad/
  coordinator/   orchestrator, protocol turns, commit gate
  agents/        stub and LLM agents, prompts, output schemas
  constraints/   hard checks (wake, runway, fuel, gate, turnaround, crew, MEL)
  options/       candidate option generator
  fallback/      deterministic cheapest-safe solver
  llm/           OpenAI-compatible client, cache, strict-schema sanitizer
  rag/           per-agent BM25 retrieval over corpus/
  data/          dataset loader, scenario builder, row catalogue
  log/           hash-chained log and run manifest
  nlp/           defect intake and role briefings
app/             Streamlit app and components
config/          demo scenarios, costs, constraints, synthetic values, agent weights
corpus/          per-agent manuals and synthetic notes (labelled)
scripts/         batch evaluation and config generators
tests/           unit, protocol, safety, and live-view tests
```

## License

MIT. See `LICENSE`.
