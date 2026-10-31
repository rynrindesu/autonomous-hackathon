# Ground corpus sources

| File | Document | URL | Edition | Licence | Synthetic | Paraphrase |
|---|---|---|---|---|---|---|
| `mmel-pl25.md` | FAA PL-25 — MMEL/MEL concepts, repair categories and (M)/(O) procedures | https://drs.faa.gov | FAA PL-25 (current policy) | FAA policy material (US Government work, public domain) | no | yes |
| `ata-chapters.md` | ATA Spec 100 / iSpec 2200 aircraft chapter list (21–80) | https://en.wikipedia.org/wiki/ATA_100 | ATA Spec 100 / iSpec 2200 numbering | Industry convention; list from public Wikipedia summary (CC BY-SA) | no | no |
| `b737-mmel-excerpts.md` | Boeing B737 MMEL Rev 63 — illustrative system excerpts | https://www.boeing.com/content/dam/boeing/boeingdotcom/commercial/mmel/B737_MMEL_Rev_63_signed.pdf | B737 MMEL Revision 63, 04/03/2026 | Boeing public MMEL; short training excerpts, not operational | no | yes |
| `airline-mel-excerpt.md` | Synthetic airline MEL excerpt — six defect entries | — | Triad synthetic corpus v1; mirrors `config/defects.yaml` | Team-written synthetic material | yes | no |
| `ramp-turnaround.md` | Synthetic ramp turnaround procedure and minimum turnaround times | — | Triad synthetic corpus v1; mirrors `config/synthetic.yaml` | Team-written synthetic material | yes | no |
| `ramp-crew-shift.md` | Synthetic ramp crew shift and overtime policy | — | Triad synthetic corpus v1; mirrors `config/synthetic.yaml` | Team-written synthetic material | yes | no |
| `eval.yaml` | Retrieval evaluation queries (20) | — | v1 | Team-written | — | — |

Notes:
- The B737 MMEL PDF (about 3.4 MB) was downloaded and parsed with `pypdf`.
  Only short, paraphrased excerpts are stored; the document is not an operator
  MEL and is not approved for dispatch.
- `airline-mel-excerpt.md` is the ground-truth lookup for the six defects in
  `config/defects.yaml`. Its ATA chapter, MEL item, category, deferrable flag and
  repair minutes match the config exactly. Every entry is labelled illustrative.
- The minimum turnaround values are REGIONAL 30, NARROW 40 and WIDE 75 minutes;
  the hard crew limit is shift end + 120 minutes with overtime at EUR 6.0/min,
  all mirroring `config/synthetic.yaml`.
