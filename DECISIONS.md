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
