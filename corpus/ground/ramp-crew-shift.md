---
doc: "Synthetic ramp crew shift and overtime policy"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v2; limits from challenge-2 workbook: fuel_and_crew (config/operational_limits.yaml)"
paraphrase: false
---

# Synthetic ramp crew shift policy

## Shift templates

The ramp team works one of three **8-hour shifts** (challenge-2 workbook:
fuel_and_crew, "Ground crew shift: 8 hours; overtime costs 1.5x after that"),
expressed in minutes after local midnight:

- **EARLY**: 05:00 to 13:00 (300 to 780 minutes).
- **LATE**: 13:00 to 21:00 (780 to 1260 minutes).
- **NIGHT**: 21:00 to 05:00 next day (1260 to 1740 minutes, wrapping past
  midnight).

There is **no hard shift limit**: a turnaround that runs past the normal shift
end is overtime, and overtime is a cost only, never a veto. Overtime minutes
are paid at **1.5 times the base rate**. The base rate for the whole
turnaround team is EUR 4.0 per minute (synthetic assumption: an 8-person team
at about EUR 30 per hour), so overtime costs **EUR 6.0 per minute**.

## Applying the policy

The Ground agent computes, for every option, when the turnaround ends
(arrival plus the airport's minimum turnaround from the workbook
airport_capacity sheet). Minutes beyond the covering shift's end are overtime.
GND-CREW-01 reports these minutes for information only (it is not a hard
check); the agent adds overtime minutes x base rate x 1.5 to its disclosed cost
and treats overtime as a soft objective (category OVERTIME). A later arrival
inside the next shift avoids overtime, but it may delay the turnaround and
affect passenger connections.

A **gate change** must be notified **at least 20 minutes before arrival**
(challenge-2 workbook: fuel_and_crew, "Gate change notice"). This one is a hard
rule, GND-GATE-04: if an option moves the aircraft away from its planned gate,
the time between the decision and the arrival must be at least 20 minutes.

## Caveat

These are synthetic planning values taken from the organisers' constraints
workbook (cite "challenge-2 workbook: fuel_and_crew"). Real labour rules,
collective agreements, rest requirements and local regulations vary by airport
and carrier and are not represented here.
