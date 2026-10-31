---
doc: "Synthetic airline MEL excerpt — six defect entries (illustrative)"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v1; values mirror config/defects.yaml"
paraphrase: false
---

# Synthetic airline MEL excerpt

## Using this excerpt

This is a **synthetic** operator MEL excerpt written for the Triad exercise. Each
section is one defect in `config/defects.yaml`. The ATA chapter, MEL item
number, repair category, deferrable flag and estimated repair time are the
ground truth the Ground agent must extract. The MEL item numbers are
illustrative: they follow ATA chapter numbering but are not real operator data.
A category **B** item must be repaired within 3 consecutive calendar days, a
**C** item within 10 days and a **D** item within 120 days, excluding the day of
discovery. Category **A** uses the interval in the item remarks. An item with no
relief is not deferrable and the aircraft cannot depart until it is repaired.

## DEF-HYD-02 — HYD SYS A LO PRESS

Crew-chief wording: "HYD LO PRESS light on the left system, fluid seeping in the
left main gear bay." Fault code: **HYD SYS A LO PRESS**. ATA chapter: **29
(Hydraulic Power)**. MEL item: **29-11-01 (illustrative)**. Repair category:
**none — no MEL relief**. Deferrable: **no**; the aircraft cannot be dispatched
until the leak is found and the system is serviced or repaired. (M)/(O): none
(no relief). Estimated repair time: **45 minutes**.

## DEF-BRK-01 — BRAKE WEAR #3

Crew-chief wording: "Wear pin flush on number three brake, found on walkaround."
Fault code: **BRAKE WEAR #3**. ATA chapter: **32 (Landing Gear)**. MEL item:
**32-42-01 (illustrative)**. Repair category: **none — no MEL relief**.
Deferrable: **no**; a brake at the wear pin is a maintenance limit, not a
dispatch relief. (M)/(O): none. Estimated repair time: **60 minutes**.

## DEF-PACK-01 — PACK 2 TRIP

Crew-chief wording: "Pack two tripped off during taxi-in, cabin running warm,
reset did not hold." Fault code: **PACK 2 TRIP**. ATA chapter: **21 (Air
Conditioning and Pressurization)**. MEL item: **21-51-01 (illustrative)**.
Repair category: **C (10 consecutive calendar days, excluding the day of
discovery)**. Deferrable: **yes**, subject to the operator MEL conditions.
(M)/(O): **(O)** operational procedure — verify the remaining pack and cabin
temperature control operate normally before dispatch. Estimated repair time:
**15 minutes**.

## DEF-APU-01 — APU START FAIL

Crew-chief wording: "APU will not start, no fault light, need ground power and
air at the gate." Fault code: **APU START FAIL**. ATA chapter: **49 (Airborne
Auxiliary Power)**. MEL item: **49-11-01 (illustrative)**. Repair category:
**C (10 consecutive calendar days, excluding the day of discovery)**.
Deferrable: **yes**, provided ground power and air are available and the
operator MEL does not require the APU. (M)/(O): **(O)** operational procedure —
confirm the flight does not require APU power or air. Estimated repair time:
**10 minutes**.

## DEF-NAV-01 — ILS 1 FAIL

Crew-chief wording: "Number one ILS receiver flagged inop on the taxi-in check."
Fault code: **ILS 1 FAIL**. ATA chapter: **34 (Navigation)**. MEL item:
**34-31-01 (illustrative)**. Repair category: **C (10 consecutive calendar
days, excluding the day of discovery)**. Deferrable: **yes**, provided the
approach and runway minima can be met with the remaining equipment. (M)/(O):
**(O)** operational procedure — verify the remaining ILS/approach capability
before dispatch. Estimated repair time: **10 minutes**.

## DEF-ELEC-01 — IDG 1 DISC

Crew-chief wording: "IDG one disconnect light came on after landing, generator
offline." Fault code: **IDG 1 DISC**. ATA chapter: **24 (Electrical Power)**.
MEL item: **24-21-01 (illustrative)**. Repair category: **C (10 consecutive
calendar days, excluding the day of discovery)**. Deferrable: **yes**, subject
to the operator MEL conditions and available generator capacity. (M)/(O):
**(M)(O)** maintenance and operational procedures — deactivate the affected
generator drive as required and confirm the remaining electrical power
configuration. Estimated repair time: **20 minutes**.

## Caveat

These entries are synthetic and exist only to give the Ground agent a citable
MEL lookup. They are not approved maintenance data. A real dispatch decision
must use the operator's current MEL, the aircraft configuration, the MMEL and
any applicable airworthiness directives.
