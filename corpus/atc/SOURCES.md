# ATC corpus sources

| File | Document | URL | Edition | Licence | Synthetic | Paraphrase |
|---|---|---|---|---|---|---|
| `wake-separation.md` | ICAO Doc 4444 §8.7.4.4 wake turbulence separation minima, reproduced in NATS AIC 044/2020 | https://www.aurora.nats.co.uk/htmlAIP/Publications/2020-07-02/html/eAIC/EG-eAIC-2020-044-P-en-GB.html | AIC 044/2020, effective 02 Jul 2020 | ICAO Doc 4444 is paid; free UK copy in the AIC. Values quoted only. | no | no |
| `arrival-rate-gdp.md` | FAA TFMS — Airport Acceptance Rate, operational capacity and ground delay basics | https://tfmlearning.faa.gov/tfm-training/atfm-basics/cdm-t1-lesson5b.html | FAA CDM International Online Workshop, Lesson 5 | FAA training material (US Government work, public domain) | no | yes |
| `holding-delay-absorption.md` | FAA AIM 4-4-3 / 4-4-12 — holding instructions, EFC and speed control | https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap4_section_4.html | AIM Chapter 4, Section 4 | FAA AIM (US Government work, public domain) | no | yes |
| `notam-decoding.md` | FAA NOTAM decoding guide — contractions, time groups and Q-codes | https://notams.aim.faa.gov/notamSearch/ | FAA domestic NOTAM format (paraphrased) | FAA Order JO 7930.2 / NOTAM Search (US Government work, public domain) | no | yes |
| `airport-operations-notes.md` | Synthetic airport operations notes — taxiway closures and gate reachability | — | Triad synthetic corpus v1 | Team-written synthetic material | yes | no |
| `eval.yaml` | Retrieval evaluation queries (18) | — | v1 | Team-written | — | — |

Notes:
- The wake minima table uses the unmodified ICAO J/H/M/L categories; the UK AIC
  also contains UK-specific Upper/Lower Medium and Small categories which are
  deliberately not used.
- `arrival-rate-gdp.md` was fetched from the FAA lesson; the page itself covers
  capacity and AAR. The ground-delay-program paragraph is an accurate
  paraphrase of standard FAA CDM practice rather than a verbatim quote.
- `notam-decoding.md` is a paraphrase of standard FAA/ICAO NOTAM contractions and
  the FAA NOTAM Search format; no FAA NOTAM PDF was stored.
