---
doc: "FAA AIM 4-4-3 / 4-4-12 — Holding instructions, EFC and speed control"
url: "https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap4_section_4.html"
synthetic: false
licence: "FAA Aeronautical Information Manual (US Government work, public domain)"
edition: "AIM, Chapter 4, Section 4"
paraphrase: true
---

# Holding and delay absorption

## Linear holding versus stack holding

**Linear holding** (also called en-route delay absorption) means slowing the
aircraft before it reaches the destination so that it uses up the required
delay in level flight or in a shallow descent. The aircraft stays on its route,
does not enter a pattern, and arrives at the meter fix at the assigned time.
Speed control is the usual tool: ATC issues a lower indicated airspeed or Mach
number, and the pilot flies it until "resume normal speed" or a published
restriction. Linear holding burns less fuel than a holding pattern at low
altitude and avoids stacking aircraft over one fix, but it has a practical
limit: the aircraft still needs enough speed and energy to fly the approach.

**Stack holding** means entering a published or assigned holding pattern,
usually at a fix near the destination, with several aircraft stacked at
different altitudes. The lowest aircraft is normally the next to leave. Holding
is the fallback when delay cannot be absorbed earlier. Each holding aircraft
needs a clearance limit, a holding direction, an altitude, and an **Expect
Further Clearance (EFC)** time. If the pilot reaches the clearance limit
without a further clearance, the pilot holds as instructed or as published and
requests clearance as soon as possible.

## Speed control

AIM 4-4-12 says ATC issues speed adjustments to radar-controlled aircraft to
achieve or maintain spacing. Speeds are expressed in knots indicated airspeed
in 5- or 10-knot increments, or in Mach number in 0.01 increments at or above
FL240. Pilots are expected to keep the assigned speed within about 10 knots or
0.02 Mach. ATC may combine a speed adjustment with a descent clearance; the
word "then" shows the order of execution. Approach clearances supersede prior
speed assignments, though ATC can restate a speed to keep spacing inside the
final approach fix.

Typical minima: at or above 10,000 ft, not less than 250 knots or the
equivalent Mach; arriving turbojets below 10,000 ft, not less than 210 knots,
and not less than 170 knots within 20 NM of the airport; turboprops within 20
NM, not less than 150 knots. A pilot may reject a speed adjustment if it is
below the minimum safe airspeed and must tell ATC the speed that will be used.

## Delay absorption in this project

The pilot agent can trade **en-route speed reduction** against **holding
minutes**. Slowing down absorbs delay without entering a stack, but it changes
fuel burn and may affect the arrival sequence. Holding absorbs delay at the
destination but costs holding fuel and can threaten the fuel reserve. ATC
prefers a stable arrival flow; the pilot prefers the option that protects fuel
and connections. Both must still satisfy the wake, runway, AAR and fuel
checks, which are evaluated in code.
