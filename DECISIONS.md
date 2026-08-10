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

## D29 — The agent loop is hand-written, not the SDK's tool runner

**Decision.** `agent/loop.py` drives the request-execute-repeat cycle directly against the
Messages API. Every assistant turn is stored as raw content blocks and every tool call with its
verbatim result.

**Rejected.** `client.beta.messages.tool_runner`, which does the same cycle with less code.

**Why.** DESIGN.md §11 requires published, replayable transcripts, and the message list is the
transcript. The runner owns the message list; getting it back out means reconstructing what
happened from what the helper chose to expose. An eval whose evidence is a summary of the run
rather than the run is not checkable, and checkability is the entire claim being made. The cost
is about sixty lines, which is the right trade for owning the artefact.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D30 — Scenarios are keyed by a caller-supplied id, with the clock pinned once

**Decision.** `simulate_action` takes a `scenario_id` (default `"default"`). Actions sharing one
land in the same overlay. The clock is set from the first target's scheduled departure minus one
minute and never moves.

**Rejected.** A fresh scenario per tool call; a clock set to the wall-clock present.

**Why.** Two problems, one fix. Every flight in the data has already operated, so a real "now"
makes `is_pending` reject everything and no action is ever legal. And a recovery has to be
measured against a world where the delay exists -- a swap simulated against an undelayed rotation
clears nothing, so every recovery answer would read "saves 0 minutes" and the model would have no
way to tell that from a genuinely worthless swap. Both are covered by a test that asserts the
composed swap clears 565 minutes and the isolated one clears zero.

**Date.** 2026-08-06 (M6), from DESIGN.md §6, §11.

## D31 — Tool results cap at 40 rows and always say when they truncated

**Decision.** `find_objects` and the baseline's `run_sql` both return at most 40 rows and add a
`truncated` message naming the problem when there were more.

**Rejected.** A larger cap; silent truncation; no cap.

**Why.** The failure this prevents is not cost, it is a confident wrong answer: a model that
counts a list it believes is complete produces a number with no hedge in it. Saying so in the
result turns a silent miscount into a visible instruction to narrow the filter. The same cap
applies to both agents so neither can win on result volume.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D32 — Tool arguments are validated in the dispatcher, not by `strict: true`

**Decision.** The three tool schemas are plain JSON Schema. Every argument is checked in Python,
and a bad one comes back as a sentence naming the valid values.

**Rejected.** Structured outputs' `strict: true` on the tool schemas.

**Why.** Two reasons, and the second is the honest one. A rejection is a real output of these
tools -- "unknown link 'downstream'; the ontology has flown_by, operated_by, ..." teaches the
model what to do next, where a schema violation just fails. And `strict` mode's handling of
optional properties could not be verified against the live API without a key, so shipping it
would have meant guessing at a 400 nobody could reproduce. Revisit once there is a key.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D33 — Grading is programmatic; there is no LLM judge

**Decision.** Each question carries object ids that must be cited, numeric values with
tolerances, required phrasings, and forbidden claims. `Question.grade` is about twenty lines.

**Rejected.** A model grading the answers against the reference.

**Why.** A judge is a second model marking the first one's homework with no ground truth of its
own, and its disagreements cannot be adjudicated. These checks are crude -- a number satisfies
its check by appearing anywhere in the answer -- but they are inspectable, and paired with the
citation requirement they mean any passing answer can be re-verified by hand in about a minute.
A guard against the obvious failure mode: every hand-verified reference answer is run through its
own grader in `tests/test_agents.py`, so a check its own correct answer cannot pass is a test
failure rather than a surprise during a paid run.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D34 — The baseline gets the derived rotation tables and the projection formula

**Decision.** The SQL baseline's prompt includes `next_leg`, `chain_breaks` and
`rotation_sequence`, the propagation recurrence written out, and the exact turn-time percentile
rule. Both prompts are built from one shared preamble, and a test asserts they start with the
same bytes.

**Rejected.** Giving the baseline only the raw `flights` table.

**Why.** Withholding the derived links would make the comparison meaningless: M2's rotation
derivation is a data-engineering result, not a property of the object layer, and hiding it would
measure the wrong thing. The one asymmetry that remains is stated rather than hidden -- the
ontology agent's `simulate_action` calls the shipped propagation engine while the baseline
re-derives the projection in SQL per question. That gap is not an unfair prompt; it is the
hypothesis under test.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D35 — Two questions the object layer can lose stay in the set

**Decision.** `cancellations-by-reason` asks for a count of 106 objects through a tool that
returns 40. `unanswerable-aircraft-type` has no answer in the data at all.

**Rejected.** Replacing the aggregate with one that fits under the cap; raising the cap for it;
dropping the unanswerable question.

**Why.** The honest ceiling for the three tools on the aggregate is "more than 40, I cannot count
exactly"; SQL answers it with one `GROUP BY`. Keeping it means the published table shows where
the typed layer costs you, which is the difference between an eval and a demo. Whatever the
result, the writeup says so. The unanswerable question is there because BTS carries a tail number
but no aircraft type and no passenger data, and a model that pattern-matches Southwest to a 737
produces a fluent unverifiable answer -- exactly the failure the citation discipline exists to
make impossible.

**Date.** 2026-08-06 (M6), from DESIGN.md §11.

## D36 — The eval runs against the committed sample, not the full month

**Decision.** Every hand-verified answer and every transcript comes from
`data/sample/bts_wn_2026_01_w1.csv.gz` -- Southwest, 2026-01-01 to 2026-01-07, 26,161 flights.

**Rejected.** Running it against the full ingested month.

**Why.** The full month is gitignored and rebuilt on demand, so a transcript recorded against it
could not be re-verified by anyone cloning the repo, and replay would then assert nothing. The
sample is produced by the same ingest code path, so the eval is not running on a toy.

**Date.** 2026-08-06 (M6), from DESIGN.md §11, §12.

## D37 — The landing view ranks roots, not late flights

**Decision.** `/api/disruptions` returns one event per aircraft, ranked by minutes forced onto
downstream legs. A leg whose largest BTS cause bucket is `late_aircraft` is excluded as a
consequence rather than a cause.

**Rejected.** Ranking the day's flights by departure delay, which is what the data hands you.

**Why.** A list sorted by delay shows one disruption five times: the aircraft that went late at
08:55 appears again at 10:55, 14:40, 15:45 and 17:35, each as its own late flight, and the
second-worst problem of the day never makes the screen. The exclusion rule is not a heuristic
invented here -- BTS already records which legs were late because their inbound aircraft was
late, so the distinction is read from the data rather than guessed. On 2026-01-03 the top row is
WN3851 PHX-SFO with 565 downstream minutes, which is the cascade the eval set is built around.

**Date.** 2026-08-06 (M7), from DESIGN.md §2, §4.

## D38 — Scenario sessions are in-memory, bounded, and expiring

**Decision.** Scenarios live in a process-local `OrderedDict` with a 200-session cap, a 30-minute
idle TTL, and a 25-action limit each. Nothing is persisted. The cap evicts the least recently
used rather than refusing new sessions.

**Rejected.** A session table in the database (there is no writable database); a cookie or token
(nothing here is worth authenticating); no limit at all (the URL is public).

**Why.** DESIGN.md §7 already says the base file is immutable and a scenario is an overlay, which
means session state has nowhere to go but memory and nothing to lose on restart. Evicting rather
than refusing is the right failure: a demo that stops accepting new sandboxes because someone
left tabs open is worse than one that forgets an idle hypothetical. The action limit exists
because "delay this by 5 minutes" is cheap to send in a loop.

**Date.** 2026-08-06 (M7), from DESIGN.md §7.

## D39 — A rejected action is 409 with the precondition text, not 400 with "invalid"

**Decision.** `PreconditionFailed` becomes HTTP 409 and the response body is the precondition
string verbatim. The frontend renders it as-is.

**Rejected.** Mapping domain rejections to a generic 400 and a sanitised message.

**Why.** M5 spent its effort making rejections say the useful thing -- "N8528Q lands at PHX at
14:05 UTC and needs 38 min to turn, which is 12 min short of the 14:35 departure" -- and a
transport layer that replaces that with "invalid request" throws away the most valuable output
the domain produces. 409 rather than 400 because the request was well formed; it was the world
that said no.

**Date.** 2026-08-06 (M7), from DESIGN.md §6.

## D40 — The frontend is a static export; the API is a container with the data baked in

**Decision.** Next.js with `output: 'export'`, deployed to Vercel as files on a CDN, reading
everything from the API at runtime. The API is a Docker image that builds `sample.duckdb` from
the committed CSV during the build and opens it read-only.

**Rejected.** Server-side rendering or Next API routes (a serverless function with nothing to
do, and a second place for secrets to live); a mounted volume or hosted database for the API.

**Why.** The two halves have opposite cost profiles and should not share a runtime. The frontend
holds no secrets and needs no server, so it should be free and cacheable. The API needs a
process and 7 MB of immutable data, which an image holds perfectly well -- and building the
database during the image build means the deployed data is reproducible from the repository
rather than copied off a laptop.

The build caught a real bug the dev environment was hiding: duckdb converts `TIMESTAMPTZ` through
`pytz` and declares it optional, the virtualenv had it transitively, and every timestamp in this
schema is `TIMESTAMPTZ`. `/api/health` passed and `/api/disruptions` returned a 500 in the
container. It is now a declared dependency.

**Date.** 2026-08-06 (M7), from BRIEF M7, DESIGN.md §7.

## D41 — `vercel.json` declares the framework and nothing the framework already knows

**Decision.** `frontend/vercel.json` sets `framework: "nextjs"` and the two security headers, and
does not set `buildCommand` or `outputDirectory`.

**Rejected.** Pinning `outputDirectory: "out"` to match `output: 'export'`, which reads as the
careful thing to do and is the reason the first deploy failed.

**Why.** With the Next.js preset, Vercel reads `next.config.mjs`, sees the static export, and
finds the output itself. Setting the directory by hand does not confirm that detection, it
replaces it -- and it replaces it with a half-truth. A static export writes the site to `out/`
but leaves `routes-manifest.json` in `.next/`, so Vercel's post-build step looked for the
manifest under `out/` and failed with a missing-file error *after* a build that had already
compiled, typechecked and rendered all three pages successfully.

The failure is worth recording because of where it landed. Everything a build log usually tells
you had gone right; the break was in the handoff afterwards, and the error named a file nobody
had written a line about. Configuration that duplicates what a tool already derives is not
redundant, it is a second source of truth that only speaks up when it disagrees.

`headers` stays because a static export genuinely cannot express it: `headers` in
`next.config.mjs` is ignored under `output: 'export'`, since there is no server to send them.

**Date.** 2026-08-07 (M7), from the first Vercel deploy.

## D42 — Two data colours, chosen by a validator rather than by eye

**Decision.** The interface reserves hue for data and spends it on exactly two: orange for minutes
added, blue for minutes given back. Everything else -- selection, hover, focus, panel chrome -- is
greyscale. Selection is a surface change and a 2px rule, never a colour.

**Rejected.** Green for "recovered" and red for "worse", which is what the first version used and
what most dashboards use.

**Why.** Green `#0ca30c` and red `#d03b3b` differ by 4.1 under simulated deuteranopia, against a
floor of 8. A red-green viewer -- around one man in twelve -- could not tell a recovery from a
regression in the one panel where that distinction is the entire output. Orange `#d95926` and blue
`#3987e5` measure 26.8 under the same simulation and 31.8 under normal vision, and they carry the
better metaphor anyway: warm for time you have taken on, cool for time you have handed back.

The numbers above came from running the palette through a checker, not from looking at it. That
is the point worth keeping: "these look different enough" is not a test, and the failing pair
looked completely fine to me.

Two consequences follow from reserving hue for data. Cancellation is a state, not a magnitude, so
it is a struck-through row with a label rather than a third colour. And the interactive accent had
to leave the palette, because a blue that means "selected" in the chrome and "recovered" in a
chart is a colour with two meanings.

**Date.** 2026-08-07 (M7).

## D43 — The cascade is drawn, and the table stays

**Decision.** The centre pane leads with a rotation timeline: two lanes per leg on a shared clock,
the schedule above and the projection below, so the horizontal offset between them is the delay.
The table that used to be the only view is kept underneath, collapsed, labelled as the same values
as numbers.

**Rejected.** The table alone (what shipped first); the timeline alone.

**Why.** A cascade is a shape -- one aircraft's late morning walking through its afternoon -- and
a column of projected timestamps makes the reader rebuild that shape in their head. Drawing it is
not decoration; it is the difference between reading that WN65 departs at 01:37 and seeing that
the aircraft never recovers before it overnights.

The table stays for three reasons: it is the accessible equivalent of a chart that encodes with
position and colour, it is where a sceptical reader checks a number they do not believe, and a
chart whose values exist nowhere else is a chart you have to trust.

Ranking rows in the left list got the same treatment for the same reason. Thirteen near-identical
numerals do not communicate that the top cascade is three times the fifth, and that ratio is the
whole argument for triaging by propagated minutes rather than by delay. One colour for every bar:
shading them by size would encode the same fact twice and spend a channel on nothing.

**Date.** 2026-08-07 (M7).

## D44 — The recovery figure is scoped in its own label

**Decision.** The recovery panel reads "Cleared from this rotation: −565 min" and "Of this
aircraft's cascade: 100%", and the action's warnings sit in a bordered block attached directly
underneath, headed "What this figure does not include".

**Rejected.** "Recovered: 100%", which is what shipped first, with the warnings rendered as loose
notes below the chart.

**Why.** A swap does not recover 565 minutes from the operation. It moves them: the displaced
aircraft picks up the original's line of flying, and this diff does not re-project that. The
engine was always honest about it -- `available_tails` and the warnings say so in words -- but a
48-pixel "100%" above a caveat four scrolls away is not a qualified claim, it is an unqualified
one with a footnote. Naming the scope inside the label costs nothing and removes the only number
on this screen that a domain expert could have called out as overstated.

The general rule this is an instance of: when a figure needs a disclaimer, the disclaimer belongs
in the label or adjacent to the value, never below the fold. If that makes the headline less
impressive, the headline was measuring something other than what it claimed.

**Date.** 2026-08-07 (M7).

## D45 — The selected day and cascade live in the URL

**Decision.** `?date=…&root=…` is written with `replaceState` on every selection, read once on
mount, and ignored if the deployment does not hold the day asked for.

**Rejected.** Component state only; `pushState` per selection.

**Why.** A finding that cannot be sent to someone else is a finding for one person. "Look at the
WN3665 cascade on the third" should be a link, not a sequence of clicks to reproduce -- and for a
tool whose entire argument is that a specific delay is worth acting on, being unable to point at
one is a functional gap rather than a nicety. `replaceState` because paging down a ranked list
should not fill the back button with twelve entries.

A stale link degrades rather than breaks: a day outside the loaded window falls back to the
default day and still renders, because a link that outlives the data it referenced should land on
a working screen.

**Date.** 2026-08-07 (M7).

## D46 — Revises D1: the persona is grounded in published sources, not interviews

**Decision.** No interviews will be held. D1's obligation of "at least three conversations" is
withdrawn rather than left standing as an intention. In its place the persona is grounded in
primary published documentation, cited in the README, and the limits of that grounding are stated
in the same paragraph.

**Rejected.** Leaving "three conversations are scheduled" in the README against conversations that
were never scheduled. Deleting the caveat entirely and letting the persona read as researched.
Holding one token conversation to make the sentence true.

**Why.** An aspirational claim that quietly never resolves is worse than an admitted gap, and it
is the kind of claim a reviewer checks. The honest replacement turned out to be stronger than the
promise it replaced, in both directions:

- Two of the sources **corroborate the mechanics**. The BTS on-time reporting directive specifies
  late-aircraft attribution in terms of the previous flight's delay bounded by scheduled ground
  time and allotted turn time -- which is `projected_dep = max(sched_dep, projected_arr +
  min_turn)`, arrived at independently here. IATA AHM 730 codes rotation delay as **93 (RA)**
  inside the *reactionary* block, and carries **09 (SG)** for ground time below declared minimum
  turn. The root-versus-consequence exclusion and the absorption model are both industry
  categories, not inventions of this repo.
- The sources **do not corroborate the premise**, and say so loudly. Aircraft recovery has a
  literature reaching back to Teodorović and Guberinić (1984), mature commercial tooling, and BTS
  itself publishes a tool tracing original causes of late-arriving aircraft. The DESIGN.md §2
  claim that an operations controller lacks this visibility is, on the published evidence,
  probably false.

Writing that second bullet down is the point of this entry. The project's defensible claim is
narrower than the one it started with: a checkable implementation of a specified mechanic, and a
measurement that contradicted its own premise. Not evidence of a need.

D1's other obligations -- primary sources, a persona never presented as a customer -- stand and
are discharged. The reversibility list under "What discovery could still reverse" stays as
written, now describing work that is open rather than work that is scheduled.

**Date.** 2026-08-07 (M1, closed as not-done).

## Deployed

The frontend is a static export on Vercel; the API is the repository's Docker image on Render,
built from `render.yaml` in this repo rather than from a dashboard form. Both deploy on push.

- https://flightops-woad.vercel.app
- https://flightops-api.onrender.com/api/health

Two things the deploy taught, both recorded above: `outputDirectory` in `vercel.json` overrode
correct framework detection with a wrong answer and broke the first build after it had already
succeeded (D41), and the container build is what caught the missing `pytz` dependency that the
development virtualenv had been hiding (D40).

## Open, pending the live eval run

The ten questions, the graders, both agents, the loop and the replay harness are complete and
tested offline. The one thing missing is the result: `ANTHROPIC_API_KEY` is not set in this
environment, so no live run has happened, no transcripts exist under `data/transcripts/`, and
there is no n-out-of-10 for either agent. `scripts/run_eval.py --replay` reports 0/10 with "no
transcript recorded" against every question, which is the correct reading of an eval that has not
been run. Nothing in the README or the writeup should claim a score until it has.

## What discovery could still reverse

DESIGN.md §2 is a constructed persona and the decisions above inherit its assumptions. No
interviews were held (see D46), so this list describes work that is open rather than work that
is scheduled. `docs/interview-guide.md` holds the questions, written to break the assumptions
rather than confirm them. What a real conversation could reverse:

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
