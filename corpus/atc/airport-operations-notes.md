---
doc: "Synthetic airport operations notes — taxiway closures and gate reachability"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v1"
paraphrase: false
---

# Airport operations notes

## Gate routes depend on open taxiways

Each stand has a deterministic taxi route from the arrival runway side to the
gate. The route is derived from the airport code and the gate id, so the same
gate always uses the same sequence of taxiways. The available taxiways at the
synthetic airports are A, B, C, D, E, F, K, L and M. A typical route is two or
three of those taxiways, for example `A -> K -> B`.

A NOTAM that closes any taxiway on a gate's route makes that gate **unreachable
by taxi** for the duration of the closure. It is not enough that the gate itself
is physically free: the aircraft must be able to get there. If the route is
blocked, the operation needs a different open route or a different gate. Closing
a connector between two taxiways can have the same effect as closing the whole
taxiway, so the closure text must be read carefully.

## What the ATC agent should report

For each candidate gate, compare its taxi route with the perceived closed
taxiways. If there is an intersection, record the gate as blocked and name the
blocking taxiway. This is the fact used by the ATC taxiway constraint. The agent
does not need the ground agent's gate inventory or occupancy data; it only needs
the public gate id and the closed-taxiway list from the NOTAM.

## Operational caveat

These notes describe the synthetic airport model used in this exercise, not a
real airport. Real airports may have one-way taxiways, runway crossings,
low-visibility procedures and local marshalling rules that are not represented
here.
