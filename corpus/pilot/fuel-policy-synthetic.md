---
doc: "Synthetic airline fuel policy — contingency, discretionary holding and minimum fuel"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v2; limits from challenge-2 workbook: fuel_and_crew"
paraphrase: false
---

# Synthetic airline fuel policy

## Fuel plan

This policy is **synthetic** and exists only for the Triad exercise. Its limits
come from the organisers' constraints workbook (challenge-2 workbook:
fuel_and_crew). The fuel on board contains trip fuel to the destination,
**5% contingency fuel** on the trip fuel, a **final reserve of 30 minutes of
holding fuel** (never plan below it), and an assumed **spare fuel on arrival of
45 minutes of holding** carried on top of the final reserve. Holding burn is
**2,400 kg per hour** for narrowbody aircraft (A320/737 class, also used for
regional jets) and **6,500 kg per hour** for widebody aircraft (A330/777 class).

For an airborne decision, the spare 45 minutes (plus the contingency) may be
used to absorb delay by holding or slowing down; the landing fuel must still
respect the 30-minute final reserve. For a ground decision, up to **800 to
3,000 kg** of extra fuel can still be uplifted, subject to performance and tank
limits. Fuel to the alternate is checked only when the option is a diversion.

## Absorbing delay

The airline prefers to absorb delay by reducing cruise speed rather than by
holding. The flight plan allows up to **8% of the remaining flight time** to be
added by slowing down, with roughly a 3% reduction in per-minute burn on the
slowed portion. On the ground, the crew may recover up to **6% of block time**
by flying faster, at a burn penalty of about 12% on the sped-up portion. These
are planning values, not guarantees; the pilot agent must still check the
landing fuel against the final reserve.

## Minimum fuel and emergency thresholds

The final reserve is 30 minutes of holding fuel. The crew declares **MINIMUM
FUEL** to ATC when the aircraft is committed to land at a specific airport and
any further change to the clearance would leave less than a 15-minute margin
above that final reserve. This is an advisory, not an emergency.

The crew declares a fuel emergency ("MAYDAY FUEL") when the projected landing
fuel is at or below the final reserve, or when the remaining fuel is otherwise
critical. In that case the aircraft needs priority handling and should land at
the nearest suitable airport. Declaring minimum fuel does not give the flight
priority over other traffic; declaring an emergency does.

## Interaction with the checks

The fuel check is a hard constraint. If an option would land with less than the
30-minute final reserve (PLT-FUEL-01), it is vetoed regardless of how much
delay it saves; a diversion must still reach the alternate with the final
reserve intact. The holding-minutes check (PLT-FUEL-02) is derived from the
same reserve: it is the number of minutes the aircraft can hold before the
reserve is reached, about 45 minutes plus the contingency. The agent should
cite "challenge-2 workbook: fuel_and_crew" for these limits; 14 CFR 121.639 and
91.167 are background on the real regulatory reserves.
