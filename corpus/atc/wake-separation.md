---
doc: "ICAO Doc 4444 §8.7.4.4 — Wake turbulence separation minima (NATS AIC 044/2020)"
url: "https://www.aurora.nats.co.uk/htmlAIP/Publications/2020-07-02/html/eAIC/EG-eAIC-2020-044-P-en-GB.html"
synthetic: false
licence: "ICAO Doc 4444 (paid); free UK copy in NATS AIC 044/2020. Quoted values only."
edition: "NATS AIC 044/2020, effective 02 Jul 2020"
paraphrase: false
---

# Wake turbulence separation minima

## ICAO wake categories

ICAO uses four wake turbulence categories for flight-plan item 9: **J** (Super,
the Airbus A380-800), **H** (Heavy, maximum take-off mass 136,000 kg or more),
**M** (Medium, above 7,000 kg and below 136,000 kg) and **L** (Light, 7,000 kg
or less). The category belongs to the aircraft generating the wake, not to the
follower. In this project we use these ICAO categories only; we do not mix them
with the FAA's newer wake groups (CWT, groups A–G).

A wake encounter is most likely when an aircraft operates directly behind
another aircraft at the same altitude or less than 1,000 ft below it. The
minimum is applied at the final-approach gate or at the runway threshold,
because vortices sink and drift with the wind after the leader passes.

## Distance minima on final approach

The ICAO distance minima from Doc 4444 §8.7.4.4, reproduced in UK AIC 044/2020,
are:

| Leader | Follower H | Follower M | Follower L |
|---|---|---:|---:|
| J (Super, A380) | 6 NM | 7 NM | 8 NM |
| H (Heavy) | 4 NM | 5 NM | 6 NM |
| M (Medium) | — | — | 5 NM |
| L (Light) | — | — | — |

Read the table as leader → follower. A Heavy leading a Heavy needs 4 NM; a
Heavy leading a Medium needs 5 NM; a Heavy leading a Light needs 6 NM; a Medium
leading a Light needs 5 NM. A Super (J) leading Heavy, Medium or Light needs 6,
7 or 8 NM respectively. Where no wake minimum applies, the ordinary radar
minimum (normally 3 NM) still applies. The minima are distances, so converting
them to time for a slot model must use the follower's ground speed on final
approach.

## Applying the minima to a landing sequence

For each arrival slot, compare the leader's wake category with the follower's
wake category and select the required distance. The available gap is the
distance behind the leader if the follower takes that slot. The slot is
acceptable only when the available gap is at least the required minimum. A
Medium following a Heavy is therefore the classic tight case: 5 NM is needed,
and a 3 NM radar gap is not enough.

Separating a Light behind a Super is the most expensive case in the table: 8 NM.
If the sequence cannot provide that gap, ATC must re-sequence, delay the
follower, or use another runway. In a time-based model the corresponding time
separation is obtained by dividing the distance by the follower's approach
ground speed; the code checker compares the resulting value against its
configured limit.

## Sources and caveats

The full PANS-ATM text is a paid ICAO document. The values above are the free
copy published by the UK in NATS AIC 044/2020, which also records UK-specific
modifications (Upper/Lower Medium and a UK-only Small category). The project
deliberately uses the unmodified ICAO J/H/M/L table, not the UK subcategories.
The Super/J minima originate in ICAO guidance for the A380-800. Always check
the current AIP/NOTAM for local procedures, and never use this summary as an
operational separation authority.

## Limits used in this project

The ATC checker (ATC-WAKE-01) does not use the ICAO table above directly. It
uses the organisers' simplified table (challenge-2 workbook: wake_separation,
"simplified from FAA JO 7110.65"), with the workbook classes mapped to ICAO
categories Super = J, Heavy = H, Large = M and Small = L: Super leading Heavy,
Large or Small 6, 7 or 8 NM; Heavy leading Heavy, Large or Small 4, 5 or 6 NM;
**Large leading Small 4 NM**; and **any other pair 3 NM** (so a Super behind a
Super, or a Medium behind a Medium, needs 3 NM). Cite "challenge-2 workbook:
wake_separation" for these values; the ICAO table above is background.
