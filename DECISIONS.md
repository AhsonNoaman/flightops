# DECISIONS

What was chosen, what was rejected, and why. Maintained from M1 onward per `.local/BRIEF.md`.
Every entry is written to be defended out loud.

Seeded at M1 from DESIGN.md sections 8 and 14 — the cross-cutting rejections, and the pushback
recorded against the brief at M0 — plus the variant choice those sections presuppose. Decisions
made inside later milestones are appended as they land. Revisions get a new dated entry rather
than an edit to the entry above.

## D1 — Variant B: public data with grounded discovery

**Decision.** Build on public BTS On-Time Performance data with a constructed persona, always
labeled as constructed, grounded in at least three conversations with people adjacent to airline
or airport operations.

**Rejected.** Variant A, a real named operator with direct access and a tool in their hands.

**Why.** Variant A is the stronger deliverable and remains preferred. It was not chosen because
no organization currently meets all three conditions in DESIGN.md §1: two thirty-minute
conversations inside seven days, a recurring decision that data would change rather than
record-keeping, and data that can appear in a public repo at least anonymized. B is defensible on
its own terms rather than as a fallback: the domain has a hard computable core (propagation
through rotation) instead of dashboard analytics, and BTS carries an independent cascade
attribution in LateAircraftDelay, so the propagation model can be checked against something other
than itself. The obligation B creates — three real conversations, primary sources, a persona never
presented as a customer — is what M1 discharges.

**Date.** 2026-08-05 (M0), from DESIGN.md §1.

## D2 — Five objects, no sixth

**Decision.** Flight, Aircraft, Airport, Carrier, DisruptionEvent, and nothing else.

**Rejected.** Rotation, FlightNumber, Crew, Passenger.

**Why.** None of the three decisions in DESIGN.md §3 requires them. Rotation adds identity without
adding a decision the `next_leg` chain does not already support. FlightNumber is a label; the leg
is what gets delayed, swapped, and cancelled. Crew and Passenger have no data in BTS at all, so
modeling them means either a second source or invented rows. Crew legality is the first objection
a real controller is expected to raise, and it is carried as a named limitation rather than a
modeled object — a position M1 is explicitly testing rather than assuming.

**Date.** 2026-08-05 (M0), from DESIGN.md §8, with the specifics in §4 and §5.

## D3 — One operational data source, and a swap that cannot check fleet compatibility

**Decision.** BTS On-Time Performance only, plus two committed static reference tables (airport
timezones, carrier names). `swap_aircraft` validates carrier, position, and timing — not aircraft
type.

**Rejected.** Joining the FAA aircraft registry for fleet type; adding a weather feed.

**Why.** Scope discipline, and each addition buys less than it costs. BTS carries no aircraft
type, so the registry would be the only way to check that one tail's line of flying can absorb
another's; the cost is a second source, a join on tail numbers that are already inconsistently
formatted across carriers, and registry-versus-operator currency problems. The resulting gap is
real and gets surfaced in TRAINING.md as a limitation rather than papered over. Reference tables
are not operational sources: static, small, committed, provenance noted in-file.

**Date.** 2026-08-05 (M0), from DESIGN.md §8, §14.4, §13.

## D4 — Store every time in both local and UTC

**Decision.** Persist BTS local times as reported, and UTC computed at ingest. Order and compute
in UTC; display local.

**Rejected.** Local only. UTC only.

**Why.** Local only makes rotation ordering wrong across timezones, which breaks the single link
the whole project rests on. UTC only discards what the operator says and sees, making every screen
a translation. Storing both costs a column pair and one ingest-time conversion, and makes the
airport timezone table load-bearing — which is why §4 puts an independent cross-check on it
(offsets derivable from CRSElapsedTime against local-time deltas) as a check rather than a source.

**Date.** 2026-08-05 (M0), from DESIGN.md §8, §4.

## D5 — Scenario overlay instead of mutation

**Decision.** The DuckDB file is immutable historical fact. A scenario is a pinned clock plus an
ordered list of applied action diffs; actions and projections read through the overlay. The
scenario is a mechanism, not an object in the ontology.

**Rejected.** Actions writing to base tables. A writable copy of the database per user. Deferring
the question to M7.

**Why.** The brief forbids silent mutation, and the deployment ships DuckDB baked in read-only —
a direct contradiction if actions mutate. Resolving it at M0 instead of discovering it at deploy
turns the constraint into a feature: per-session sandboxes, and a demo shaped as replaying a real
disrupted day to try the swap that was not made. It does not count against the five-object limit
because it is transaction-like plumbing with no referent in the operation; an operations
controller does not have scenarios, they have a day.

**Date.** 2026-08-05 (M0), from DESIGN.md §7, §8, §14.2.

## D6 — Milestone numbering follows the brief; discovery is not delegated

**Decision.** M1 is discovery, M2 ingestion, M3 domain model, per `.local/BRIEF.md`. The runbook
was corrected to match.

**Rejected.** The original brief's numbering, which calls ingestion M1 and has no discovery
milestone.

**Why.** The original numbering omits discovery because a model cannot do it, which is precisely
why it needs its own milestone rather than none. Discovery gates the README's strongest section —
the moment the initial understanding of the problem turned out to be wrong — and that section
cannot be written from the dataset. Leaving two numbering schemes in play would also make every
later instruction ambiguous about which artifact it targets.

**Date.** 2026-08-05 (M0), from DESIGN.md §14.1.

## D7 — A fair eval baseline, or none

**Decision.** If the raw-SQL baseline ships, it uses the same model, a genuinely competitive
prompt, and published transcripts for both arms. If that cannot be done honestly, the comparison
is dropped and the ten-question eval set ships alone.

**Rejected.** A weaker baseline — lesser model, thin prompt, unpublished transcripts — that makes
the ontology look good.

**Why.** The comparison is the most persuasive artifact in the repo only while it is not rigged,
and a reader who can spot the difference is exactly the reader this is written for. A rigged
comparison converts the strongest artifact into the strongest reason to distrust everything else
in the repo. Dropping it costs one claim; publishing a strawman costs credibility across all of
them. The baseline is also first to be cut under time pressure, which is a reason to decide its
terms now rather than while rushing.

**Date.** 2026-08-05 (M0), from DESIGN.md §14.3, §11.

## D8 — Measure the cascade shape before claiming it

**Decision.** Define cascade size as summed downstream attributed minutes, and report the measured
distribution, whether it shows amplification or damping.

**Rejected.** Carrying the brief's motivating example — forty minutes at ORD becoming three hours
at DEN — as a premise the build assumes.

**Why.** Per-leg delay typically decays down a rotation as padding and slack absorb it, while the
sum across legs can still exceed the root delay. Those are two different claims and the example
conflates them. Asserting amplification and then finding damping would mean quietly rewriting the
premise late; measuring first makes either outcome a result. Damping is still a case for the tool
— it changes which legs are worth intervening on, and by how much.

**Date.** 2026-08-05 (M0), from DESIGN.md §14.5, §10.

## D9 — Cached transcripts committed, live question-answering behind an env gate

**Decision.** Eval transcripts are cached and committed so pytest runs offline and deterministic.
Live question-answering requires an API key in the environment and is off by default on the public
URL.

**Rejected.** Live LLM calls inside tests. A public demo with an embedded key.

**Why.** Tests that are nondeterministic and cost money per run get disabled, then rot, and the
eval numbers in the README have to be reproducible by a reader who holds no key. An embedded key
on a public URL is an unbounded bill and a leaked credential. The tradeoff is that cached
transcripts go stale against newer models; the answer is regenerating them deliberately and
committing the diff, which stays visible in history.

**Date.** 2026-08-05 (M0), from DESIGN.md §14.6, §11.

## D10 — DisruptionEvent is derived, never authored

**Decision.** DisruptionEvents are recomputed from flights and chains by the propagation engine.
There is no path to hand-create or edit one.

**Rejected.** Curating a few clean events for the demo.

**Why.** A hand-curated event is synthetic data presented as real, which the brief prohibits
outright, and in the UI it would be indistinguishable from a computed one. It is also
self-defeating: the demo's claim is that the engine surfaces cascades the delay board does not,
and a curated event demonstrates only that a human can write one down. If the computed events are
not legible enough to demo, that is a finding about the engine, not a gap to fill by hand.

**Date.** 2026-08-05 (M0), from DESIGN.md §14.7, §4.

## D11 — Reconstruct actual times from delay minutes, not from the hhmm fields

**Decision.** `actual = scheduled + delay`, computed in UTC. The reported DepTime and ArrTime
strings are parsed only to establish whether a leg departed or arrived, and to count the 2400
convention for the quality report.

**Rejected.** Parsing DepTime/ArrTime as local hhmm and reconstructing the calendar date.

**Why.** BTS reports actual times as local hhmm with no date, so recovering a timestamp means
inferring whether the leg crossed midnight -- and the file uses 2400 for midnight, which appears
249 times in January 2026. Delay minutes are signed offsets from times that are already anchored
to a date, so the arithmetic is exact and the ambiguity never arises. The measured consequence:
the 2400 convention appears in no scheduled field and therefore never reaches the model at all.
The check that this is not merely convenient is a test asserting the reconstruction reproduces
the reported delay on every leg.

**Date.** 2026-08-05 (M2), from DESIGN.md §9.

## D12 — Compute scheduled arrival from CRSElapsedTime, making CRSArrTime a free check

**Decision.** `sched_arr_utc = sched_dep_utc + CRSElapsedTime`. CRSArrTime is not used to build
the model; it is compared against the computed local arrival on every row.

**Rejected.** Parsing CRSArrTime directly and inferring the overnight rollover from whether the
arrival hhmm is smaller than the departure hhmm.

**Why.** DESIGN.md §4 requires the timezone table be cross-checked against the offsets implied
by CRSElapsedTime, since a wrong zone silently corrupts rotation ordering. Deriving arrival from
the block turns that cross-check from a separate validation script into a property of the load:
if a zone is wrong, every leg touching that airport disagrees with its own reported arrival time
by exactly an hour. Measured over 544,003 legs, 543,995 agree. The 8 that do not are isolated
rows whose CRSElapsedTime contradicts their own scheduled times -- one has a scheduled block of
minus 64 minutes -- and no airport disagrees systematically, which is what distinguishes a bad
row from a bad zone. All three hand-filled zones (BIH, EAR, XWA) agree on 100% of their legs.

**Date.** 2026-08-05 (M2), from DESIGN.md §4, §9.

## D13 — Destination belongs in the flight key

**Decision.** A leg is keyed by date, carrier, flight number, origin, destination, and scheduled
departure time.

**Rejected.** DESIGN.md §4's key, which omits destination.

**Why.** The design argued destination was redundant because flight numbers repeat on a route,
not across routes. January 2026 contains a counterexample: F9 3237 out of JFK at 0659 on
2026-01-04 is filed twice, once to CVG and once to LAS, both cancelled. One collision in 544,003
rows is still a collision, and a primary key that is almost unique is not a primary key -- it
would silently merge two legs during link derivation. Found by testing the key rather than
assuming it.

**Date.** 2026-08-05 (M2), from DESIGN.md §4.

## D14 — Leave non-standard tail numbers exactly as reported

**Decision.** Tail numbers are stored verbatim. No normalisation, no N-prefixing.

**Rejected.** Prepending "N" to the 123 tails that lack it, to make the format uniform.

**Why.** DESIGN.md §9 anticipated inconsistent leading-N formatting as a problem to repair. It is
real -- 8,754 legs carry tails like "188NV" -- but it is entirely one carrier's reporting
convention (Allegiant), and there are zero cases where the same aircraft appears in both forms.
So normalising fixes nothing and asserts a registration that has not been verified against any
registry. Chains are unaffected: every tail in the month is flown by exactly one reporting
carrier, so the format never has to be reconciled across operators. The related finding is
sharper than the design expected: tails are missing only on cancellations, never on a flown leg.

**Date.** 2026-08-05 (M2), from DESIGN.md §9.

## D15 — Build chains from the schedule, cancellations included

**Decision.** A cancelled leg keeps its place in the tail's ordered line of flying and can be
linked through.

**Rejected.** Excluding cancelled legs before deriving next_leg.

**Why.** Excluding them manufactures station discontinuities: with the cancelled leg removed, the
aircraft's next scheduled departure appears to come from an airport it never flew to, and a
genuine data gap becomes indistinguishable from a routine cancellation. It also buries the
operational consequence in the wrong layer -- what a cancellation does to the rest of the day is
exactly what cancel_flight and the propagation engine exist to compute, and they cannot reason
about a leg that link derivation already deleted.

**Date.** 2026-08-05 (M2), from DESIGN.md §5, §6.

## D16 — impossible_turn, a third chain-break reason the design did not anticipate

**Decision.** Where a tail's next leg is scheduled to depart before the current leg is scheduled
to land, no link is created and the pair is recorded as `impossible_turn`. 6,256 of 512,451
candidate links in January 2026.

**Rejected.** Linking them anyway with a negative ground time. Silently dropping them.

**Why.** DESIGN.md §5 anticipated two break reasons: station discontinuity and end of window.
This is a third and distinct failure. Station continuity holds -- the aircraft does depart from
where it landed -- but the timing is physically impossible, as with N574DT, reported on DL740
JFK-SEA departing 21:40 UTC and DL415 SEA-JFK departing 21:45 UTC. The tail assignment cannot be
right for both, most likely a swap that BTS recorded against the original schedule. Linking
through it would compute a cascade for an aircraft that was never there, which is worse than a
missing link because it is confidently wrong. 5,552 of the affected legs actually operated, so
this is not a cancellation artefact.

**Date.** 2026-08-05 (M2), from DESIGN.md §5.

## D17 — LateAircraftDelay is an exact partition, so it can validate propagation

**Decision.** M4 validates the propagation engine against BTS's own LateAircraftDelay attribution.

**Rejected.** Treating the cause buckets as approximate, per DESIGN.md §9's expectation that they
"need not sum to the total delay".

**Why.** That expectation is falsified by the data. Across all 107,475 legs that carry cause
buckets, the five buckets sum to the arrival delay exactly, with zero exceptions, and buckets
appear if and only if arrival delay reaches 15 minutes. That makes LateAircraftDelay a clean
independent measurement of how much of a leg's delay the carrier attributed to its inbound
aircraft -- which is the quantity the propagation engine predicts. The validation is only as good
as the assumption, so it is pinned by a test rather than left as a note.

**Date.** 2026-08-05 (M2), from DESIGN.md §9, §10.

## D18 — Commit the sample in the original BTS schema, gzipped

**Decision.** The committed sample is Southwest's first week of January 2026 as raw BTS rows,
all 110 columns, gzipped to 1.4 MB. The DuckDB file is rebuilt from it and is not committed.

**Rejected.** Committing the built DuckDB file. Committing a slimmed CSV of only the columns the
model reads.

**Why.** Both alternatives create a second code path. A committed database skips the parser
entirely, so tests would stop exercising the thing most likely to break; a slimmed CSV would
diverge from the real file's shape the first time a column is added. Keeping the source schema
means `load_month` handles the sample and the full month identically, and the sample still
contains every anomaly the ingest has to survive: 2400 times, overnight legs, a negative
scheduled block, a null tail on a cancellation, and all three chain-break reasons.

**Date.** 2026-08-05 (M2), from DESIGN.md §12.

## D19 — previous_leg is an inverse traversal, not a new link

**Decision.** The store exposes `previous_leg` alongside `next_leg`, implemented as a lookup on
the same stored table by `to_flight_id`.

**Rejected.** Exposing only the forward link, per DESIGN.md §5's list. Storing a second table.

**Why.** Triage runs backwards. The operator does not start from a root cause; they start from a
late flight on the board and need to know what put it there. With only the forward link, every
caller answering "why is this late" would have to scan for the flight that links to it, which
means writing SQL outside the store -- the one thing the store exists to prevent. This adds no
object, no table, and no ambiguity: it is the same edge read from the other end.

**Date.** 2026-08-05 (M3), from DESIGN.md §5, §11.

## D20 — The overlay is an in-memory dict, not a DuckDB temp table

**Decision.** A `Scenario` holds a pinned clock and a `dict[flight_id, Flight]` of overridden
legs. Reads check the dict, then fall through to the store.

**Rejected.** Materialising each scenario as a DuckDB temp table or view and querying through
COALESCE.

**Why.** The deployed API opens the database read-only, so a scenario that needs to write to it
is a contradiction, not a design. An in-memory overlay makes session isolation free -- two
operators replaying the same day cannot see each other, which is asserted by a test -- and it
keeps the immutability guarantee checkable in one place instead of spread across SQL. The cost
would be scale, and there is none to pay: an action touches one rotation, tens of legs, not
thousands. The base file stays what DESIGN.md §7 says it is, historical fact.

**Date.** 2026-08-05 (M3), from DESIGN.md §7.

## D21 — Pending is decided by the scenario clock, not the recorded status

**Decision.** `Scenario.is_pending` compares a leg's scheduled departure against the pinned
clock. The BTS status field is used only to exclude legs already cancelled in the source data.

**Rejected.** Treating the recorded status as the precondition input.

**Why.** Every leg in the base data has already happened -- it is a completed month. If actions
keyed off the recorded status, nothing would ever be actionable, because every flight is already
`arrived` or `cancelled`. Replay only means anything if "now" is a position inside the day, so
the clock is what decides whether a flight can still be delayed, swapped, or cancelled. This is
also what makes preconditions deterministic: the same scenario replays identically tomorrow,
which the eval set at M6 depends on.

**Date.** 2026-08-05 (M3), from DESIGN.md §6, §7.

## D22 — The store refuses a turn estimate below 30 observations

**Decision.** `turn_percentile` returns None when a carrier-station pair has fewer than 30
observed turns, leaving the fallback to the caller.

**Rejected.** Returning the quantile regardless. Silently falling back carrier-wide inside the
store.

**Why.** DESIGN.md §10 makes min_turn a percentile of observed ground times with "a minimum
sample threshold, falling back carrier-wide". A percentile over four turns at a small station is
noise presented as a measurement, and propagation would inherit it invisibly. Returning None
forces the choice into the propagation engine where it can be seen, tested, and reported. The
station-level distribution justifies the effort: measured p05 turn times differ sharply by
carrier -- WN 35 minutes, OO 30, DL 47, UA 56 -- so a single global constant would be wrong for
almost everyone.

**Date.** 2026-08-05 (M3), from DESIGN.md §10.

## D23 — Both propagation thresholds are measured, and only one touches the arithmetic

**Decision.** min_turn is the 5th percentile of observed ground times per carrier and station,
excluding turns under 15 minutes, requiring 30 observations before a station-level estimate is
used. The turn-versus-overnight boundary is 285 minutes. The overnight boundary labels a
termination reason and is deliberately kept out of every calculation.

**Rejected.** A single global minimum turn time. Letting the overnight threshold decide
absorption.

**Why.** The measured distribution is bimodal exactly as DESIGN.md §10 predicted -- a turn mode
peaking at 60-89 minutes, a minimum-density bin at 270-299, an overnight mode rising from 360 --
so 285 is the centre of the trough rather than a round number. Per-carrier turn estimates differ
too much for a constant to be defensible: WN 35 minutes at LAS, UA 57 at ORD. Excluding sub-15
minute turns matters because 1,943 links show scheduled ground times no narrowbody can achieve,
including zeros, and they drag the 5th percentile from 33 to 31.

Keeping the overnight boundary out of the arithmetic is the load-bearing half of this. Absorption
is already decided by the `max` in the projection formula, which handles a ten-hour sit correctly
without being told it is overnight. If the constant also gated propagation, then an empirical
choice made once would silently move every number the tool reports. A test asserts that changing
it from 285 to 60 relabels terminations and leaves every projected minute identical.

**Date.** 2026-08-05 (M4), from DESIGN.md §10.

## D24 — Validate against LateAircraftDelay, and report the error rather than tune it away

**Decision.** The engine is scored against BTS's own late-aircraft attribution on the same legs.
The residual error is published, not minimised.

**Rejected.** Fitting min_turn, or adding a recovery factor, until projections match the recorded
outcomes.

**Why.** The gap between projection and outcome is not noise to be removed; it is the tool's
subject. The engine projects a do-nothing world, while the recorded data is a world where a
controller swapped a tail, called a spare, or told a crew to turn fast. Tuning the model to
reproduce the recorded outcome would make it predict the recovery that the operator has not
decided to make yet, which is precisely the decision the tool exists to support.

Measured on the full month: mean error +19.8 minutes, median +14, 59% of legs within 30 minutes.
The asymmetry is the operationally important part -- 117 legs where the engine warned and BTS
attributed nothing, and **zero** where BTS attributed a cascade the engine missed. For triage,
over-warning is visible and correctable; under-warning is neither.

**Date.** 2026-08-05 (M4), from DESIGN.md §10.

## D25 — The model's error is carrier-dependent, and that is a finding, not a defect

**Decision.** Report per-carrier calibration rather than a single accuracy number. Tests assert
calibration for the sample carrier, not a universal direction of error.

**Rejected.** A single headline accuracy figure. Asserting that the model always over-predicts.

**Why.** This was written first as a test claiming the error must be biased high, on the
reasoning that scheduled blocks are padded (actual beats scheduled by a median 8-9 minutes across
every carrier) and crews compress turns when late (SkyWest 66 scheduled versus 48 actual
minutes). The test failed. On Southwest's week the mean error is -0.5 minutes.

Measuring per carrier explains it: SkyWest +74, United +28, Republic +27, American +16, Southwest
+6, Frontier -7. The aggregate +19.8 was almost entirely SkyWest, the largest group in the
sample. The error is a measure of how aggressively a carrier recovers, and a regional flying for
several mainlines has the most spare aircraft and the most reason to swap. Southwest's dense
point-to-point rotations leave the least room to recover, so its outcomes sit closest to the
do-nothing projection.

This changes what the tool should claim. A single accuracy number would have been an average
across operating models that behave differently, and it would have read as precision the model
does not have.

**Date.** 2026-08-05 (M4), from DESIGN.md §10.

## D26 — Cascades damp per leg while the total exceeds the root

**Decision.** Cascade size is reported as summed downstream attributed minutes, and the README
will state that per-leg delay decays.

**Rejected.** The brief's framing, in which a 40-minute delay at ORD "becomes" a three-hour
cascade at DEN.

**Why.** DESIGN.md §10 flagged the brief for presuming amplification and required measuring
first. Measured: the pinned Southwest cascade decays 142, 127, 117, 112, 107, 102 down the
rotation as scheduled slack absorbs it at every turn, while the sum across the five downstream
legs reaches 565 minutes. Both statements are true and they are different claims. The honest one
is that a root delay spreads across many legs rather than growing on any one of them -- which is
still the operator's problem, because it is five late flights instead of one.

**Date.** 2026-08-05 (M4), from DESIGN.md §10.

## D27 — Impossibilities reject; costly consequences are flagged in the diff

**Decision.** Preconditions reject only what cannot happen: a flight already departed relative to
the scenario clock, an already-cancelled leg, a replacement tail that does not exist, is another
carrier's, or cannot physically reach the station in time. Everything expensive but real is
returned as a warning on the diff.

**Rejected.** Blocking swaps that strand a rotation or leave an aircraft out of position.

**Why.** DESIGN.md §6 draws this line and it is the right one. Carriers strand rotations on bad
days, deliberately, because the alternative is worse. A tool that refuses is a tool that gets
worked around, and the workaround happens outside the system where nothing is recorded. Judging
whether a cost is worth paying is the controller's job; making the cost visible before they
commit is the tool's. So `cancel_flight` returns the stranded-rotation warning and applies
anyway, and every swap carries the fleet-compatibility caveat it cannot check.

**Date.** 2026-08-05 (M5), from DESIGN.md §6.

## D28 — Recovery actions project zero additional delay, never the delay already applied

**Decision.** `cancel_flight` and `swap_aircraft` project the scenario's current cascade by
passing zero additional delay. The delay already applied is read only to populate the diff.

**Rejected.** Measuring the leg's accumulated delay from the overlay and re-projecting with it,
which is how this was first written.

**Why.** A bug, caught by rendering a real diff rather than by the tests. The overlay already
carries an applied delay inside the leg's own scheduled times, so passing that same delay back
into the projection applied it twice. On UA1636's real cascade the swap reported clearing 1,447
minutes of what is actually a 510-minute cascade -- nearly triple, and in the direction that
overstates the value of the tool's own advice, which is the worst way for it to be wrong.

The fix is one line in each action. The more useful outcome is the invariant it exposed: what a
delay creates, an equivalent recovery removes. That symmetry is now two tests, including one for
stacked delays where the double-counting compounded. Sixty-one tests passed while this bug was
live, which is the honest reason the invariant is worth having.

**Date.** 2026-08-05 (M5), from DESIGN.md §6, §7.

## Open, pending M1 discovery

DESIGN.md §2 is a constructed persona, and the decisions above inherit its assumptions.
`docs/interview-guide.md` is built to break them. What discovery could reverse:

- **D1**, if an operator meeting all three conditions in §1 appears. The project becomes Variant A
  and DESIGN.md is rewritten around the real operation.
- **D2**, if crew legality binds most recovery decisions rather than constraining some. An
  aircraft-only answer the operator cannot act on is a worse outcome than a sixth object.
- **D3**, if turn feasibility at the stand is what actually decides swaps in practice.
- **D8**, if controllers measure recovery in something other than minutes — misconnects,
  completion factor, overnight maintenance positioning. The propagation output would be right and
  the ranking wrong.
- **The problem statement itself**, if ops controllers already run automatic rotation projection
  today. The gap would then be elsewhere — options, authority, or trust in the projection — and §2
  needs rewriting before M4 builds toward it.
