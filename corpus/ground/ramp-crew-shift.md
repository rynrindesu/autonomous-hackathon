---
doc: "Synthetic ramp crew shift and overtime policy"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v1; values mirror config/synthetic.yaml"
paraphrase: false
---

# Synthetic ramp crew shift policy

## Shift templates

The ramp team works one of three shifts, expressed in minutes after local
midnight:

- **EARLY**: 05:00 to 13:00 (300 to 780 minutes).
- **LATE**: 13:00 to 22:00 (780 to 1320 minutes).
- **NIGHT**: 22:00 to 05:00 next day (1320 to 1740 minutes, wrapping past
  midnight).

A turnaround must be completed within the assigned shift's normal end. The
company/labour **hard limit** is the normal shift end plus **120 minutes**;
rostering beyond that is not permitted. Work between the normal end and the
hard limit is overtime and costs **EUR 6.0 per minute** for the whole
turnaround team.

## Applying the policy

The Ground agent checks every option's crew finish time against the hard limit.
If the planned departure or the next-leg turnaround would run past the hard
limit, the option fails GND-CREW-01 even if it is otherwise cheap. Using
overtime up to the hard limit is allowed, but it carries a soft cost: the agent
adds the overtime minutes multiplied by EUR 6.0 per minute to its score. A crew
change or a later shift can avoid overtime, but it may delay the turnaround and
affect passenger connections.

## Caveat

These are synthetic values chosen for the exercise. Real labour rules,
collective agreements, rest requirements and local regulations vary by
airport and carrier and are not represented here. The hard limit in this
project is deliberately simple so the code checker can enforce it
deterministically.
