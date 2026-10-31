---
doc: "FAA TFMS — Airport Acceptance Rate (AAR), operational capacity and ground delay basics"
url: "https://tfmlearning.faa.gov/tfm-training/atfm-basics/cdm-t1-lesson5b.html"
synthetic: false
licence: "FAA training material (US Government work, public domain)"
edition: "FAA CDM International Online Workshop, Lesson 5"
paraphrase: true
---

# Airport capacity and traffic-flow delay

## Airport Acceptance Rate (AAR)

The FAA defines the **Airport Acceptance Rate (AAR)** as a dynamic input
parameter specifying the number of arriving aircraft an airport or its
surrounding airspace can accept per hour. It is also called the operational
arrival capacity. The AAR is used to calculate the desired interval between
successive arrivals, so an AAR of 60 means one arrival per minute on average,
while an AAR of 30 means one every two minutes.

The tower or terminal traffic management coordinator sets the AAR from the
runway configuration, winds, weather, airspace limitations, fleet mix and
controller experience. In good visual conditions the benchmark (optimum) rate
is highest; marginal weather reduces it; instrument conditions with poor
visibility and radar separation produce the lowest IFR rate. A runway closure,
construction, or a crane near the approach path can also change the AAR. Rates
are published and updated through FAA traffic-management systems as conditions
change.

## Weather cuts and arrival spacing

When weather reduces the AAR, the same demand produces more delay. If an
airport normally accepts 60 arrivals per hour and weather cuts that to 36, only
36 aircraft can be landed in the hour; the remaining 24 must be delayed,
vectored, slowed, held, or sent to another airport. The arrival-rate check in
this project compares the number of landings proposed in a window against the
weather-reduced AAR. It is a capacity constraint, not a wake-separation
constraint: the wake check compares each pair, while the AAR check compares the
total count in the window.

## Ground Delay Program (GDP) basics

A **Ground Delay Program** is a traffic-flow initiative used when arrival
demand exceeds the airport's acceptance rate. Instead of absorbing all delay in
the air, the flow manager assigns departure times to affected flights so that
they arrive at a rate the airport can accept. The assigned time is commonly an
**Expect Departure Clearance Time (EDCT)** or slot; the delay is moved to the
origin, where aircraft can wait at the gate rather than burn fuel in a holding
stack.

Ground delay programs are part of collaborative decision making (CDM): the
airport, airspace users and the flow manager exchange capacity and demand data,
and flights may be exempted or swapped under published rules. For a single
flight, the operational question is whether to accept the assigned slot, absorb
some delay en route by slowing down, or hold near the destination. From a
fuel-and-CO2 viewpoint, a ground delay is usually cheaper than airborne
holding, but it can miss passenger connections and crew duty limits. The
synthetic airline policy documents in this corpus explain those trade-offs.

## Using this in the agent

The ATC agent perceives the NOTAM/METAR text and checks the slot list against
the reduced AAR. If a slot would push the count over the limit, the option is
not feasible even when the runway and wake checks pass. The check should cite
this AAR definition and report the value (proposed landings), the limit
(weather-reduced AAR) and the unit (arrivals per hour or per window).
