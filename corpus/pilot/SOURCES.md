# Pilot corpus sources

| File | Document | URL | Edition | Licence | Synthetic | Paraphrase |
|---|---|---|---|---|---|---|
| `cfr121-639.md` | 14 CFR 121.639 — Fuel supply: All domestic operations | https://www.ecfr.gov/current/title-14/section-121.639 | eCFR current | US Government work (public domain) | no | no |
| `cfr91-167.md` | 14 CFR 91.167 — Fuel requirements for flight in IFR conditions | https://www.ecfr.gov/current/title-14/section-91.167 | eCFR current | US Government work (public domain) | no | no |
| `cfr121-645.md` | 14 CFR 121.645 — Fuel supply: flag and supplemental operations | https://www.ecfr.gov/current/title-14/section-121.645 | eCFR current | US Government work (public domain) | no | yes |
| `part117.md` | 14 CFR Part 117 — flight duty period and flight time limits | https://www.ecfr.gov/current/title-14/part-117 | eCFR current | US Government work (public domain) | no | yes |
| `aim-turbulence.md` | FAA AIM §7-1-21 — PIREPs relating to turbulence (Table 7-1-11 / TBL 7-1-21) | https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html | AIM Chapter 7, Section 1 | FAA AIM (US Government work, public domain) | no | no |
| `pirep-format.md` | FAA AIM TBL 7-1-18 — PIREP element codes and turbulence decoding | https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html | AIM Chapter 7, Section 1 | FAA AIM (US Government work, public domain) | no | no |
| `fuel-policy-synthetic.md` | Synthetic airline fuel policy | — | Triad synthetic corpus v2; challenge-2 workbook fuel_and_crew | Team-written synthetic material | yes | no |
| `connections-synthetic.md` | Synthetic passenger-connection protection policy | — | Triad synthetic corpus v1 | Team-written synthetic material | yes | no |
| `eval.yaml` | Retrieval evaluation queries (19) | — | v2 | Team-written | — | — |

Notes:
- §121.639 is the domestic 45-minute normal-cruising reserve. §121.645 is the
  flag/supplemental 30-minute holding reserve at 1,500 ft; the corpus explicitly
  warns against mixing the two.
- Part 117 Table B values are reproduced in condensed form. §117.13 is the FDP
  rule; Table A (flight time) and §117.23 (cumulative limits) are separate.
- The eCFR pages were fetched directly. The Part 117 page and the 121.645 page
  were condensed into accurate paraphrases; the core numerical limits are kept.
- The hard fuel and duty limits come from the organisers' workbook
  (challenge-2 workbook: fuel_and_crew): final reserve 30 min holding, 5%
  contingency, spare 45 min holding on top of the reserve, holding burn
  2,400 kg/h narrowbody and 6,500 kg/h widebody, crew duty 13 h from report.
  The regulatory documents are background only.
- The connection policy and the uplift/speed values use `config/synthetic.yaml`
  (800–3,000 kg uplift, MCT map) and are labelled synthetic in the UI.
