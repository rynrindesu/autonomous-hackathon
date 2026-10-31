---
doc: "FAA NOTAM decoding guide — contractions, time groups and Q-codes"
url: "https://notams.aim.faa.gov/notamSearch/"
synthetic: false
licence: "FAA NOTAM Search / FAA Order JO 7930.2 (US Government work, public domain)"
edition: "FAA domestic NOTAM format (paraphrased)"
paraphrase: true
---

# NOTAM decoding guide

## NOTAM structure and contractions

A domestic NOTAM starts with an exclamation mark, the affected location, the
NOTAM number and the location again, for example:

```
!DEN 01/123 DEN TWY K AND L CLSD 1501021200-1501021700
```

Common contractions are **TWY** (taxiway), **RWY** (runway), **CLSD** (closed),
**BTN** (between), **AVBL** (available), **U/S** (unserviceable), **APRON**
(ramp), **WI** (within), **AVOID** (do not proceed), **LGTD** (lighted) and
**BARRICADES** (physical barriers). A closure line may name one item
(`TWY K CLSD`) or several (`TWY K AND L CLSD`, `TWY K/L CLSD`). "BTN" defines
the limits of a closure, so `TWY K CLSD BTN K3 AND K5` means the segment of
Taxiway K between K3 and K5 is closed, not necessarily the whole taxiway.

## Time groups and validity

A NOTAM time group is **YYMMDDHHMM** in UTC. The first ten digits are the start
and the next ten are the end, separated by a hyphen:
`1501021200-1501021700` means 2025-01-02 12:00 UTC to 2025-01-02 17:00 UTC.
Other forms include **EST** (estimated), **PERM** (permanent), **WEF**
(with effect from), **UNTIL** and **APRX** (approximately). Always compare the
time group with the flight's UTC time; a closure that has already expired does
not create a taxiway block for the current arrival. Convert local times
carefully and remember that a NOTAM may cross midnight.

## Q-code basics

Many international NOTAMs include a five-character **Q-code** after `Q)`. The
first letter is always Q; the next two letters identify the subject and the last
two identify the condition. Common examples: **QMRLC** means runway closed,
**QMXLC** means taxiway closed, and **QMNLC** means movement area closed. The
same NOTAM usually also has a plain-language E) item, which is easier to read
and is the primary text an agent should cite. Use the Q-code as a cross-check,
not as the only source of truth, because national formats and code versions
differ.

## Reading a closure for the agent

The ATC agent must turn a NOTAM into a list of closed taxiways. Take each
`TWY ... CLSD` phrase, split on `AND`, `/`, and commas, and keep the taxiway
identifiers. If the text says `BTN`, the closure is a segment; for a conservative
perception default, treat the named taxiway as closed. Ignore expired time
groups and ignore unrelated constructions such as `APRON CONSTRUCTION WI TWY D
AVOID LGTD BARRICADES` unless they actually close a route. Cite this guide and
the NOTAM text in the perceived fact.
