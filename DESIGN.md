# DESIGN.md: flight disruption cascades, problem statement and object model

Produced at Milestone 0, before any code. This is the contract between milestones and
tools: ingestion (M2), the domain model (M3), propagation (M4), actions (M5), and the
question-answering layer (M6) implement what is specified here. If discovery (M1)
falsifies an assumption, this file is revised first and the change recorded in
DECISIONS.md. Milestone numbers follow .local/BRIEF.md.

## 1. Variant decision

Variant B: US commercial flight disruption, BTS On-Time Performance data. This holds
unless all three are true, in which case the project pivots to Variant A and this
document is rewritten around the real operation:

1. A named organization and person will give two 30-minute conversations within seven
   days and will actually try the tool.
2. The operation contains a recurring decision that data would change, not
   record-keeping.
3. Some of their data can appear in a public repo, at least anonymized.

Why B is defensible here: the applicant shipped Uber Reserve airport pickup enablement
at Billy Bishop and Edmonton and worked directly with airport operations; the domain has
a hard computable core (delay propagation through aircraft rotation) rather than
dashboard analytics; and the dataset carries its own ground truth for cascades
(LateAircraftDelay attribution), so the model can be validated honestly.

What B obligates: at least three real conversations with people adjacent to airline or
airport operations during M1, primary-source research, and a persona that is always
labeled as constructed.

## 2. The operator and the problem

Operator: a constructed persona, to be grounded and revised during M1 discovery. An
operations controller in the Integrated Operations Center of a mid-size US carrier,
responsible for aircraft routing recovery on the day of operations.

The problem, stated the way the operator states it:

The delay board shows me twenty late flights as twenty separate problems. It doesn't
show me that six of them are the same airplane working down its line all day, and that
all six trace back to one bad turn at O'Hare at eight in the morning. I do that tracing
by hand, pulling the tail, walking its day leg by leg, doing the turn math, while the phones
are ringing. By the time I can see the whole cascade, the cheap fixes are gone: the
airplane is three legs out of position and my only options are the expensive ones. What
I need is to look at any late flight and see what it drags down tonight if I do nothing,
and what a tail swap or an early cancel actually buys me, while the decision is still
mine to make.

## 3. The decisions the model must support

The object model is shaped by three decisions. Anything that does not serve one of them
was cut.

1. Triage: which of tonight's late flights are one problem rather than many. Served by
   next_leg chains grouped into DisruptionEvents.
2. Intervention: for a given root delay, compare do-nothing, swap, and cancel by
   projected downstream minutes. Served by the actions and their diffs.
3. Attribution: after the operating day, which root events cost the most downstream
   minutes. Served by DisruptionEvent aggregates.

## 4. Objects (five)

### Flight
One operated leg on one calendar date. Key: date, operating carrier, flight number,
origin, scheduled departure time (flight numbers can repeat same-day on a route).
Properties: carrier code, flight number, origin, destination; scheduled and actual
departure and arrival, each stored in both local time (as BTS reports, for display) and
UTC (computed at ingest, for all ordering and arithmetic); departure and arrival delay
minutes; tail number (nullable, often absent on cancellations); status enum
(scheduled, departed, arrived, cancelled, diverted); cancellation code (A carrier,
B weather, C NAS, D security); the five BTS cause buckets (carrier, weather, NAS,
security, late_aircraft), nullable because BTS populates them only when arrival delay
is 15 minutes or more; distance.
Rejected: modeling FlightNumber as an entity. It is a label; the operational unit that
gets delayed, swapped, or cancelled is the leg.

### Aircraft
The tail as BTS reports it, keyed by tail number, with operating carrier and its derived
daily rotation (via links). Deliberately not the FAA registry object: BTS carries no
aircraft type, and joining the registry would be a second data source. Consequence:
swap_aircraft validates carrier, position, and timing, not fleet compatibility. That is a
named limitation surfaced in TRAINING.md rather than papered over.

### Airport
IATA code, city, IANA timezone. Timezone is the load-bearing property: BTS times are
local, and rotation ordering across timezones is wrong without normalization to UTC.
Source is a small committed reference table with provenance noted in-file: reference
data, not a second operational source. Validation: UTC offsets are independently
derivable from CRSElapsedTime versus local-time deltas per city pair; that derivation is
an ingest-time cross-check, not the source, because it is fragile around DST and 2400.

### Carrier
Code and name from the BTS lookup table. BTS reporting carrier is the operating
reporting entity: regionals (SkyWest, Republic, Envoy) report separately from the
mainline brand they fly for. The tool is scoped to the operating carrier; the
marketing-versus-operating split is a named limitation.

### DisruptionEvent
Persisted output of the propagation engine: id, root flight, cause bucket (from the root
flight's BTS attribution), affected legs each with attributed downstream minutes, total
propagated minutes, and how the chain ended (absorbed, overnight break, cancellation,
chain break). An object rather than a report because the operator needs to reference
"this morning's ORD cascade" as an addressable thing that questions and actions can
point at. Always recomputed from flights and chains, never hand-edited: a curated event
would be synthetic data presented as real.

## 5. Links

- Flight -[flown_by]-> Aircraft (nullable)
- Flight -[operated_by]-> Carrier
- Flight -[departs_from]-> Airport, Flight -[arrives_at]-> Airport
- Flight -[next_leg]-> Flight (the load-bearing link)
- DisruptionEvent -[root_cause]-> Flight, DisruptionEvent -[affects]-> Flight

next_leg derivation, at ingest: group legs by tail and date window, order by scheduled
departure UTC, link consecutive legs, and validate station continuity (this leg's
destination equals the next leg's origin). Where continuity fails, no link is created; a
chain break is recorded with a reason (positioning or ferry move invisible to OTP data,
tail reassignment, or data error). Chain breaks are counted and reported at M2 as
findings, not noise.
Rejected: computing rotation at query time, which re-derives the same chain on every
traversal and hides data-quality failures inside query logic instead of surfacing them
once, countable, at ingest. Rejected: a Rotation object, a sixth object that adds
identity without adding any decision the chain of links does not already support.

## 6. Actions (three)

Common contract: every action validates preconditions against the scenario state and
either rejects with the object id and the specific failed precondition, or returns a
structured diff. No action ever writes to the base tables. Hard preconditions are
impossibilities; costly-but-possible consequences are flagged in the diff instead of
blocking, because judging costs is the operator's job and surfacing them is the tool's.

### delay_flight(flight_id, additional_minutes, reason)
Preconditions: flight exists; status is scheduled as of the scenario clock (not
departed, cancelled, or diverted); additional_minutes > 0; reason nonempty.
Diff: the flight's shifted times, plus the recomputed projection for every downstream
leg on its tail's chain, before and after per leg, and the updated DisruptionEvent.

### swap_aircraft(flight_id, replacement_tail)
Semantics: exchange the two tails' remaining lines of flying from this flight onward. That
is a line swap, which is what carriers actually do, rather than a single-leg borrow, which
creates repositioning problems the model would then have to fake.
Preconditions: flight not departed or cancelled as of the scenario clock; replacement
tail exists and is operated by the same carrier; replacement is projected on the ground
at the flight's origin with minimum turn time before the new departure.
Diff: both rotations before and after, cascade deltas on both chains, net system minutes
saved or lost, and any new station discontinuities flagged explicitly.

### cancel_flight(flight_id, reason)
Preconditions: flight not departed; not already cancelled; reason nonempty.
Diff: status change; downstream relief on the tail's chain (delays absorbed because the
aircraft now sits); and a stranded-rotation flag when the cancelled leg was positioning
the tail, so the next leg now departs from a station the aircraft never reaches, which in
reality forces another cancellation or a ferry. Passenger reaccommodation is not
modeled; named limitation.

## 7. The scenario mechanism (not a domain object)

The base DuckDB file is immutable historical fact. A scenario is a pinned clock (a "now"
inside a replayed day) plus an ordered list of applied action diffs; actions and
projections read through the overlay. This is a mechanism like a transaction, not an
entity in the operation, so it does not appear in the ontology and does not count against
the five objects. It exists because: the brief forbids silent mutation; the deployed API
ships DuckDB baked in read-only, which this turns from a contradiction into a feature
(session sandboxes); and it gives the demo its shape, which is to replay a real disrupted
day and try the swap you wish you'd made.

## 8. Cross-cutting rejections

- Sixth object (Rotation, FlightNumber, Crew, Passenger): no decision in section 3
  needs them; crew and passengers also have no data in BTS. Crew legality is the first
  thing a real controller will raise; it is a named limitation, not a modeled object.
- Second data source (FAA registry for fleet type, weather feeds): scope discipline.
  Each is a named limitation where it bites.
- Local-time-only or UTC-only storage: store both; compute in UTC, display local.
- Live mutation of base data: replaced by the scenario overlay.

## 9. Data realities the ingest must absorb (M2 checklist)

Expectations to verify with counts against the real file, not claims to assert:

- Times are local hhmm with a 2400 quirk; overnight arrivals (arrival local earlier
  than departure local) must not produce negative blocks.
- Tail numbers: null especially on cancellations (breaking chains, which is a policy and
  not a bug); inconsistent leading-N formatting across carriers.
- Cause buckets populated only when arrival delay >= 15; buckets need not sum to the
  total delay.
- Reporting carrier is the operating entity; mainline and regional legs for one brand
  appear under different carriers.
- Station discontinuities in tail sequences (ferry and positioning moves are not in
  OTP data): count them as chain breaks by reason.
- Diverted flights have their own field semantics; do not treat them as arrivals.

## 10. Propagation sketch (implemented and validated at M4)

For consecutive legs n, n+1 on one tail's chain:

    projected_dep(n+1) = max(sched_dep(n+1), projected_arr(n) + min_turn(carrier, station))
    projected_arr(n+1) = projected_dep(n+1) + sched_block(n+1)

min_turn is estimated from observed ground times per carrier and station (candidate:
5th percentile with a minimum sample threshold, falling back carrier-wide); the exact
estimator is chosen at M4 with the real turn-time distribution in hand. Chains
terminate at: no next_leg (chain break), scheduled ground gap above an overnight
threshold (chosen empirically from the expected bimodal turn distribution), or
cancellation.

Validation, two ways: replay real root delays and compare projected versus actual
downstream delays; and compare per-leg projected propagated minutes against BTS's own
LateAircraftDelay attribution on those legs, which is the dataset's independent answer.

Known error sources, to be written up honestly at M4: schedule padding absorbs delay
(actual blocks beat scheduled, so the model overpredicts); controller interventions are
already embedded in the actuals, so the model predicts cascades a human prevented;
min_turn is an estimate, not the carrier's contractual minimum; mainline-regional tail
handoffs and ferry moves are invisible to the data.

Honesty note on the brief's motivating example: per-leg delay typically decays down a
rotation while the sum across legs can still exceed the root delay. Cascade size is
defined as summed downstream attributed minutes. Measure first; the README claims what
the data shows, whether that is amplification or damping.

## 11. Question-answering layer (M6)

The model gets exactly three tools, mirroring the ontology: find_objects (typed
filters), traverse_links (walk named links from an object), simulate_action (run one of
the three actions in a scenario and return its diff). No SQL path. Answers must cite
object ids so they can be checked. Eval: ten operational questions with hand-verified
answers; a baseline agent with the schema and read-only SQL, same LLM, fair prompt;
both reported as n out of 10 with full transcripts published. Transcripts are cached
and committed so pytest runs offline and deterministic; live question-answering is
env-gated behind an API key so the public URL cannot accrue cost. If week three forces
a cut: the baseline goes first, the eval set stays.

## 12. Data policy (M2)

Full set: one recent winter month, all carriers (winter gives dense weather-driven
cascades), fetched by script, loaded into a single DuckDB file. Committed offline
sample: Southwest, one week of that month. Single fleet type (the fleet-compatibility
caveat is moot inside the sample), no regional operators (no marketing-operating
ambiguity), high-frequency point-to-point rotations with tight turns (dense, legible
cascades). Rejected as sample: a network carrier week, where regional handoffs make
chains noisier than they are instructive.

## 13. Scope guard

Five objects, three actions, one operational data source (plus two committed static
reference tables: airport timezones and carrier names), one operator, one carrier scope
in the UI at a time. Pressure to add a sixth object, a fourth action, or a second
source means stop and ask.

## 14. Recorded pushback on the brief (M0)

1. The runbook's milestone numbers drift from the brief's (it calls ingestion M1; the
   brief's M1 is discovery, which the runbook omits because it cannot be delegated).
   Numbering here follows the brief; discovery is the applicant's own legwork and gates
   the writeup's "what I got wrong" moment.
2. A read-only deployed database contradicts mutating actions; resolved now by the
   scenario overlay (section 7) rather than discovered at M7.
3. The eval baseline persuades only if it is not a strawman: same model, fair prompt,
   published transcripts, or no comparison at all.
4. BTS has no aircraft type; swap validates carrier, position, and timing only. Named
   limitation, chosen over adding a second data source.
5. The brief's ORD-to-DEN example presumes amplification; the data will show a
   distribution. Measure before claiming (section 10).
6. LLM nondeterminism and cost are handled by committed cached transcripts and
   env-gated live mode (section 11).
7. DisruptionEvent stays derived-only, recomputed from flights and chains; hand-curated
   events would be synthetic data presented as real.
