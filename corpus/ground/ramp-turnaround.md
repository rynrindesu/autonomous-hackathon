---
doc: "Synthetic ramp turnaround procedure and minimum turnaround times"
url: null
synthetic: true
licence: "Team-written synthetic training material (not operational data)"
edition: "Triad synthetic corpus v2; minimum turnaround from challenge-2 workbook: airport_capacity"
paraphrase: false
---

# Synthetic ramp turnaround procedure

## Minimum turnaround by airport

The minimum turnaround from arrival on stand to the next departure is set per
destination airport by the organisers' constraints workbook (challenge-2
workbook: airport_capacity, column min_turnaround_min). It is the same for every
aircraft size at that airport:

- **Large hub** airports (ORD, ATL, DFW, DEN, LAX): **45 minutes**.
- **Medium hub**, **Small hub** and **Non-hub** airports: **35 minutes**.

The minimum is measured from the time the aircraft is chocked at the gate to
the time it is ready for pushback. The next leg may depart only if the gap
between arrival and scheduled departure is at least the minimum, or if the next
leg is explicitly delayed or a spare aircraft is substituted. A ten-minute gate
buffer is used separately for gate occupancy checks; it is not part of the
turnaround minimum.

## Turnaround sequence

The normal sequence is: arrive and marshal onto stand, chocks on and engines
off, passenger deplaning, cabin security check and cleaning, catering and
water/waste service, baggage and cargo unloading, fuel uplift, routine
maintenance and defect check, baggage and cargo loading, passenger boarding,
doors closed, load sheet and pushback clearance. A defect discovered during the
turnaround pauses the sequence until the MEL decision is made: a deferrable
item can continue with the (M)/(O) actions, while a non-deferrable item stops
the departure until repair.

## Using the procedure

The Ground agent checks the arrival-to-departure gap against the workbook
minimum for the destination airport (GND-TURN-01). If the gap is too short, the option must delay the next
leg, swap to a spare aircraft if one is available, or be rejected. The agent
should cite this procedure for the minimum, and the synthetic MEL excerpt for
the defect action. The real-world turnaround also depends on crew availability,
gate layout, fuelling and ATC slots; those are represented by the other
synthetic constraints in this project.
