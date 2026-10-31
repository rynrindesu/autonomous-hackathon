---
doc: "FAA AIM TBL 7-1-18 — PIREP element codes and turbulence decoding"
url: "https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html"
synthetic: false
licence: "FAA Aeronautical Information Manual (US Government work, public domain)"
edition: "AIM, Chapter 7, Section 1"
paraphrase: false
---

# PIREP format and turbulence decoding

## Routine and urgent PIREPs

A pilot report starts with the nearest three-letter weather-reporting station
and a report type: **UA** for a routine PIREP and **UUA** for an urgent PIREP.
Urgent reports are used for hazardous conditions such as severe turbulence,
severe icing, low-level wind shear, microbursts or volcanic ash. The elements
follow in slash-marked groups, and only the groups that matter need to be
included.

## Element codes

- `/OV` — location, usually in relation to a VOR or airport.
- `/TM` — time of occurrence in UTC.
- `/FL` — altitude or flight level; essential for turbulence and icing.
- `/TP` — type of aircraft; essential for turbulence and icing.
- `/SK` — sky cover and cloud height.
- `/WX` — weather and visibility.
- `/TA` — temperature in degrees Celsius.
- `/WV` — wind direction (magnetic) and speed in knots.
- `/TB` — turbulence.
- `/IC` — icing.
- `/RM` — remarks for anything not covered above.

An example routine report is:
`KCMH UA /OV APE 230010/TM 1516/FL085/TP BE20/SK BKN065/WX FV03SM HZ FU/TA
20/TB LGT`. This means 10 NM southwest of the Appleton VOR at 1516Z, 8,500 ft,
a Beech 200, broken cloud at 6,500 ft, 3 SM visibility with haze and smoke,
20 °C, light turbulence.

## Decoding turbulence groups

The `/TB` group uses intensity contractions: **LGT** (light), **MOD**
(moderate), **SEV** (severe), **EXTRM** (extreme), **CHOP** (chop) and
**CAT** (clear-air turbulence). A range such as `LGT-MOD` means light to
moderate. A report such as:

```
KDEN UA /OV DEN/TM 1815/FL340/TP B738/TB MOD
```

means a routine PIREP near Denver at 1815Z, flight level 340, Boeing 737-800,
moderate turbulence. A report such as `PIREP UA360 SEV TURB FL360-FL380`
indicates severe turbulence between FL360 and FL380. A report that says
`NO TURB REPORTED` means no turbulence was observed, not that severe turbulence
was observed.

## From text to a structured fact

For each cruise level in the flight plan, scan the PIREP text for the matching
`FLxxx` and the `TB` value. Map LGT to LIGHT, MOD to MODERATE, SEV to SEVERE and
EXTRM to EXTREME. If a report covers a band (FL340-FL360), apply the reported
intensity to each level in the band. If there is no report for a level, do not
invent one; the conservative default is to treat unknown turbulence carefully,
but the documented fact should remain "no report".
