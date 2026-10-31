---
doc: "Synthetic passenger-connection protection policy"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v1"
paraphrase: false
---

# Synthetic passenger-connection protection policy

## Minimum connection time

Each airport has a minimum connection time (MCT) for a domestic connection.
The synthetic values in this exercise are: default 40 minutes; ATL 35; ORD 40;
DFW 40; DEN 35; LAX 45; SFO 45; LAS 35; IAH 40; PHX 35; CLT 35; MSP 35; DTW 40;
JFK 50; EWR 45; LGA 40; BOS 40; SEA 40; MCO 40. A connection is protected only
if the arrival is early enough for the passenger to reach the onward departure
with at least the MCT. A delay that lands after the MCT has been consumed makes
the connection a misconnect.

## Priority order

When not every connection can be protected, the airline protects the most
connecting passengers first, subject to the special-handling list. The order is:

1. **Unaccompanied minors (UMNR)** — never leave them without a supervised
   handover; if the connection is missed, rebook and keep them supervised.
2. **Passengers with reduced mobility or medical assistance** — protect the
   connection and arrange assistance at the gate.
3. **Company priority passengers** — protect where possible.
4. **Largest connecting groups** — protect the flight that saves the most
   passengers from a misconnect; break ties by the earliest onward departure.

A single flight carrying many connecting passengers is worth more than a
flight carrying one, even if the single passenger is in a higher fare cabin,
unless the special-handling list applies. The agent's soft score uses the
number of protected passengers and the number of misconnects, not the fare.

## Rebooking and baggage

If a connection is missed, the passenger is rebooked on the next available
flight with seats, and checked baggage is re-tagged. The policy does not
guarantee a hotel or compensation; those depend on the carrier's conditions of
carriage. For the negotiation, the ground agent reports the connection list and
the pilot agent weighs the misconnects against fuel, turbulence and duty time.
The final decision must still pass the hard safety checks; protecting
connections can never justify landing below the fuel reserve.
