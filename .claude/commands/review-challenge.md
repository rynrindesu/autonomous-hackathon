---
description: Review the team's code against Airbus Challenge #2 requirements and judging rubric (read-only, Chinese report)
---

You are a senior reviewer for a 6-hour hackathon team. Review the code in this repository against the challenge below. **Do not modify any files.** Read code, and you may run read-only commands (e.g. `git log`, `ls`, running tests or a dry-run script if one exists and is cheap). Do not make paid API calls in bulk; at most one end-to-end run if a script clearly supports it.

Optional focus from the user: $ARGUMENTS

## The challenge (Airbus AI & Aerospace Track, Challenge #2)

"How might AI help air traffic controllers, pilots and ground operations staff make faster and better decisions?"

Build a multi-agent communication framework where an ATC agent, a Pilot agent and a Ground Ops agent negotiate a resolution to a real-time disruption, without human intervention, until consensus is reached.

- ATC agent: runway wake separation, taxiway blockage, maximise sector throughput
- Pilot agent: preserve fuel reserves, flight safety, minimise turbulence, protect passenger connections
- Ground agent: optimise gate utilisation, avoid ground-crew overtime, minimise turnaround delay

Required: structured messages between agents, explicit constraint checking, a traceable consensus log, a deterministic non-AI fallback.

Must avoid:
1. Combining the 3 roles into a single prompt/LLM call
2. Endless, unconstrained agent loops with no convergence logic or turn limit
3. Accepting solutions that ignore safety/operational constraints

Data: US DOT 2015 flight delays dataset. Pick a row with WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20, pass its parameters to the 3 agents, and show them negotiating a revised arrival time, gate assignment or flight-plan adjustment in under 3 turns. The dataset has NO gate, fuel, wake-category, runway or passenger-connection fields, so any such values must be synthesised.

## Judging rubric (weights)

- Technical soundness 25%: works end to end; right tool for each job. LLMs for reading, explanation, interaction; solvers/rules/statistics for scheduling, constraint and legality checks. LLM doing arithmetic or legality checks, or a polished UI over a hard-coded scenario, scores low. Must handle input beyond the scripted demo.
- Problem realism 20%: a named user, a clear status quo, a believable cost.
- Honest evaluation 20%: stated metrics, test data, results; synthetic data labelled; at least one visible failure/uncertain case explained.
- Trust & traceability 20%: outputs traceable to rules/data; uncertainty handled; a qualified human stays in control.
- Impact 10%: measured or reasoned improvement over a baseline.
- Time discipline 5%.

## What to check (answer each with evidence)

For every item give a verdict: ✅ done / ⚠️ partial / ❌ missing, plus evidence as `file:line` and one sentence of explanation.

1. **Agent independence** — Are ATC, Pilot and Ground separate LLM calls with their own system prompts? Does each have private state/data the others cannot see? Is there any place where all three roles end up in one prompt?
2. **Message schema** — Is there a defined structured format (JSON schema, Pydantic model, tool-use schema)? Are messages validated/parsed, and what happens when the model returns malformed output?
3. **Decision space** — What exactly is being negotiated (ETA slot, gate, holding/diversion, route)? Is it a bounded set of options or free text?
4. **Hard vs soft constraints** — Are hard constraints (wake separation, minimum fuel reserve, gate availability, runway/taxiway closure) checked in **deterministic code**, not by asking the LLM? What numeric values are used and are they plausible? Can a proposal that violates a hard constraint ever be accepted?
5. **Convergence protocol** — Who proposes first, what is the turn order, how is "consensus" defined, and is there a hard turn limit (≤ 3)? Any path to an infinite loop?
6. **Deterministic fallback** — Is there a non-AI algorithm used when no consensus is reached (or an API error occurs)? Is it actually wired in and reachable?
7. **Consensus log** — Is every message, constraint check result and final decision recorded with timestamps/turn numbers, in a form a human could audit?
8. **Data handling** — Is the scenario row selected with the WEATHER_DELAY > 15 / LATE_AIRCRAFT_DELAY > 20 filter? Which fields are synthesised, how (fixed rules, seeded random?), and are they clearly labelled as synthetic?
9. **Generalisation** — Can it run on arbitrary rows (not just one hard-coded demo scenario)? Is there a batch mode?
10. **Evaluation** — Is there a script that runs many scenarios and reports metrics (convergence rate within 3 turns, hard-constraint violations, delay vs the fallback baseline)? Is at least one failure case captured?
11. **Human in the loop** — Is the final plan presented for approval by a human (e.g. airline ops duty manager) rather than auto-executed?
12. **Robustness & hygiene** — API errors/timeouts handled; API key read from `.env` and not hard-coded or committed; `requirements.txt` present and complete; the app starts with a documented command; model name and token usage reasonable for a $50 budget.

## Output (write the whole report in Simplified Chinese; keep code identifiers, file paths and technical terms in English)

1. **一句话结论**: overall state, and whether it can be demoed end to end right now.
2. **检查清单**: a table with columns 编号 | 检查项 | 结论 (✅/⚠️/❌) | 证据 (file:line) | 说明.
3. **评分风险 Top 5**: the five issues most likely to cost points, each tied to a rubric criterion and its weight, ordered by impact.
4. **建议修改**: concrete, minimal fixes for the Top 5, each sized as 小 (<15 min) / 中 (15–45 min) / 大 (>45 min). Prefer fixes that fit in the remaining hackathon time.
5. **需要团队决定的问题**: open design questions the code does not answer (e.g. constraint values, consensus definition, which fields are synthetic, who the end user is).
6. **可直接放进 slides 的事实**: numbers or facts found in the code/logs (constraint values, turn limit, number of test scenarios, metrics) that can fill the pitch deck; mark anything not yet available as [待补].

Be specific and honest. If something cannot be determined from the code, say so instead of guessing.
