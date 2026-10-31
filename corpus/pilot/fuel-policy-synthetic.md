---
doc: "Synthetic airline fuel policy — contingency, discretionary holding and minimum fuel"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v1"
paraphrase: false
---

# Synthetic airline fuel policy

## Fuel plan

This policy is **synthetic** and exists only for the Triad exercise. The
dispatch fuel plan contains trip fuel to the destination, fuel to the
most distant required alternate, a **45-minute reserve at normal cruise** (the
domestic rule used by the project), **5% contingency fuel** on the trip fuel,
and any discretionary fuel the captain requests.

For an airborne decision, discretionary fuel is expressed as **10 to 40 minutes
of holding** at the aircraft's holding burn rate. It is not a reserve: it may be
used to absorb delay, but the landing fuel must still respect the alternate
plus 45-minute reserve. For a ground decision, up to **800 to 3,000 kg** of
extra fuel can still be uplifted, subject to performance and tank limits.

## Absorbing delay

The airline prefers to absorb delay by reducing cruise speed rather than by
holding. The flight plan allows up to **8% of the remaining flight time** to be
added by slowing down, with roughly a 3% reduction in per-minute burn on the
slowed portion. On the ground, the crew may recover up to **6% of block time**
by flying faster, at a burn penalty of about 12% on the sped-up portion. These
are planning values, not guarantees; the pilot agent must still check the
landing fuel against the reserve.

## Minimum fuel and emergency thresholds

The final reserve is the alternate fuel plus 45 minutes at normal cruise. The
crew declares **MINIMUM FUEL** to ATC when the aircraft is committed to land at
a specific airport and any further change to the clearance would leave less
than a 15-minute margin above that final reserve. This is an advisory, not an
emergency.

The crew declares a fuel emergency ("MAYDAY FUEL") when the projected landing
fuel is at or below the final reserve, or when the remaining fuel is otherwise
critical. In that case the aircraft needs priority handling and should land at
the nearest suitable airport. Declaring minimum fuel does not give the flight
priority over other traffic; declaring an emergency does.

## Interaction with the checks

The fuel check is a hard constraint. If an option would land with less than the
alternate plus 45-minute reserve, the option is vetoed regardless of how much
delay it saves. The holding-minutes check is derived from the same reserve: it
is the number of minutes the aircraft can hold before the reserve is reached.
The agent should cite this policy for the contingency, discretionary and
minimum-fuel language, and cite 14 CFR 121.639 or 91.167 for the underlying
regulatory reserve.
