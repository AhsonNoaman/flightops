"""Ten operational questions with hand-verified answers, and the graders that mark them.

DESIGN.md section 11. Every expected value in this file was computed by querying the committed
sample directly (`data/sample/bts_wn_2026_01_w1.csv.gz`, WN, 2026-01-01 to 2026-01-07) and
the query that produced it is recorded in each question's `verified_by`. Nothing here was
produced by a model, which is the only property that makes an n-out-of-10 mean anything.

Grading is programmatic, not an LLM judge. A judge would be a second model marking the first
one's homework with no ground truth of its own, and its disagreements would be unfalsifiable.
The checks here are boring on purpose: does the answer cite the object ids it must have visited,
does it contain the right numbers, does it use the vocabulary the data actually supports, and
does it avoid the specific wrong claims. A terse correct answer passes; a fluent one that never
names an id fails. That is the intended bias, because the whole argument for the object layer is
answers become checkable, so an unfalsifiable answer is not a passing one.

Two questions are here because they can embarrass the ontology agent, and they stay in whatever
the result:

`cancellations-by-reason` needs a count of 106 objects through a tool that returns at most 40
and says so. The honest ceiling for the object layer on that question is "more than 40, I cannot
count exactly"; SQL answers it with one GROUP BY. If the baseline wins it, the writeup says so.

`unanswerable-aircraft-type` has no answer in the data at all. It is graded on refusing, and on
not inventing a 737.

One limitation is worth stating rather than discovering: a number check is satisfied by the
value appearing anywhere in the answer, so it cannot tell 565 in the right sentence from 565 in
the wrong one. What stops that from being a hole is the citation requirement alongside it. An
answer that names the right ids and contains the right figures is one a reader can check in
about a minute, which is the standard this project is arguing for in the first place. The
reference answers below are held to the same bar: `test_agents.py` grades each one with its own
grader, so a check that its hand-verified answer cannot pass is a bug in the check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The lookbehind keeps a date from decomposing into negatives: without it "2026-01-03" yields
# -1 and -3, and a grader looking for a negative gap would match on a flight id.
_NUMBER = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?")

_WORD_NUMBERS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}
_WORD_PATTERN = re.compile(r"\b(" + "|".join(_WORD_NUMBERS) + r")\b", re.IGNORECASE)


def _numbers_in(text: str) -> list[float]:
    """Every number in the answer, with thousands separators and small word numerals resolved.

    "Five legs" and "5 legs" are the same answer and a grader that only accepts one of them is
    marking prose style. Above twelve, models write digits, so the table stops there.
    """
    normalised = _WORD_PATTERN.sub(
        lambda match: _WORD_NUMBERS[match.group(1).lower()], text.replace(",", "")
    )
    return [float(match.group()) for match in _NUMBER.finditer(normalised)]


@dataclass(frozen=True)
class NumberCheck:
    """A figure the answer has to contain, with the tolerance it is allowed."""

    value: float
    label: str
    tolerance: float = 0.0

    def satisfied_by(self, numbers: list[float]) -> bool:
        return any(abs(number - self.value) <= self.tolerance for number in numbers)


@dataclass(frozen=True)
class Grade:
    """The mark for one answer, with every failed check named."""

    question_id: str
    passed: bool
    failures: tuple[str, ...]


@dataclass(frozen=True)
class Question:
    """One eval question: what to ask, what the right answer is, and how it is marked."""

    question_id: str
    question: str
    reference: str
    """The hand-verified answer in prose, for a reader auditing the eval rather than the agent."""
    verified_by: str
    """The query or traversal that produced the reference. Re-runnable against the sample."""
    tests: str
    """What this question is actually probing, so a failure can be interpreted."""

    must_cite: tuple[str, ...] = ()
    """Object ids that have to appear verbatim. Compared case-insensitively, nothing else."""

    must_report: tuple[NumberCheck, ...] = ()
    must_mention: tuple[tuple[str, ...], ...] = field(default=())
    """Each inner tuple is a set of acceptable phrasings; the answer needs one from each set."""

    must_not_claim: tuple[str, ...] = ()
    """Substrings whose presence is a fabrication. Used by the unanswerable question."""

    def grade(self, answer: str) -> Grade:
        lowered = answer.lower()
        numbers = _numbers_in(answer)
        failures: list[str] = []

        for object_id in self.must_cite:
            if object_id.lower() not in lowered:
                failures.append(f"did not cite {object_id}")
        for check in self.must_report:
            if not check.satisfied_by(numbers):
                failures.append(f"did not report {check.label} ({check.value:g})")
        for alternatives in self.must_mention:
            if not any(phrase.lower() in lowered for phrase in alternatives):
                failures.append(f"did not mention any of {'/'.join(alternatives)}")
        for forbidden in self.must_not_claim:
            if forbidden.lower() in lowered:
                failures.append(f"claimed {forbidden!r}, which the data does not support")

        if not answer.strip():
            failures.append("empty answer")
        return Grade(self.question_id, not failures, tuple(failures))


# The cascade every question below is built around: WN3851 PHX-SFO on 2026-01-03, tail N8633A,
# 142 minutes late off the gate with 141 of them attributed to NAS. It is used repeatedly on
# purpose: projection, traversal, recovery and absorption are different questions about one
# situation, and reusing it means a reader can hold the whole eval in their head.
ROOT = "2026-01-03|WN|3851|PHX|SFO|0855"
LAST_LEG = "2026-01-03|WN|65|DAL|HOU|2255"

QUESTIONS: tuple[Question, ...] = (
    Question(
        question_id="lookup-delay-and-cause",
        question=(
            "Southwest flight 3851 from PHX to SFO on 2026-01-03 pushed back late. How late "
            "was the departure, and what did the carrier attribute the delay to?"
        ),
        reference=(
            "2026-01-03|WN|3851|PHX|SFO|0855 pushed back 142 minutes late and arrived 141 "
            "minutes late. The whole of the attributed delay is NAS (national air system): "
            "141 minutes, with nothing recorded against carrier, weather, security or late "
            "aircraft. The aircraft was N8633A."
        ),
        verified_by="store.get_flight(ROOT) -> dep_delay_minutes, arr_delay_minutes, causes",
        tests="Can it find one object by description and read its fields without embellishing.",
        must_cite=(ROOT,),
        must_report=(
            NumberCheck(142, "departure delay in minutes"),
            NumberCheck(141, "NAS minutes"),
        ),
        must_mention=(("nas", "national air system", "air traffic"),),
    ),
    Question(
        question_id="cascade-projection",
        question=(
            "That same PHX-SFO departure on 2026-01-03, flight 3851, is going to be 142 "
            "minutes late. How much delay does that push into the rest of that aircraft's "
            "day, and which legs absorb it?"
        ),
        reference=(
            "Delaying 2026-01-03|WN|3851|PHX|SFO|0855 by 142 minutes pushes 565 minutes into "
            "five downstream legs, all on N8633A: 2026-01-03|WN|4106|SFO|PHX|1055 goes 127 "
            "min late, 2026-01-03|WN|172|PHX|LGB|1440 117, 2026-01-03|WN|65|LGB|LAS|1545 112, "
            "2026-01-03|WN|65|LAS|DAL|1735 107, and 2026-01-03|WN|65|DAL|HOU|2255 102. Each "
            "leg gives back a few minutes of scheduled ground time; the cascade stops at the "
            "overnight break after HOU."
        ),
        verified_by=(
            "Actions.delay_flight(scenario, ROOT, 142, ...) -> net_minutes 565, 5 affected legs; "
            "PropagationEngine termination overnight_break"
        ),
        tests=(
            "Whether it reaches for the projection tool rather than doing turn-time arithmetic "
            "in its head. The ontology agent has the engine; the baseline has the formula and "
            "must apply it correctly."
        ),
        must_cite=(ROOT, LAST_LEG),
        must_report=(
            NumberCheck(565, "total downstream minutes", tolerance=5),
            NumberCheck(5, "number of downstream legs"),
        ),
        must_mention=(("n8633a",),),
    ),
    Question(
        question_id="rotation-traversal",
        question=(
            "How many legs does tail N8633A fly on 2026-01-03, where does it start the day, "
            "and where does it finish?"
        ),
        reference=(
            "N8633A flies seven legs. It starts with WN3851 MSY-PHX at 05:40 and ends with "
            "WN65 DAL-HOU at "
            "22:55, overnighting in Houston. The full line is MSY-PHX, PHX-SFO, SFO-PHX, "
            "PHX-LGB, LGB-LAS, LAS-DAL, DAL-HOU."
        ),
        verified_by="store.rotation('N8633A', '2026-01-03') -> 7 flights, first MSY, last HOU",
        tests="Plain link traversal, and whether it orders a multi-timezone day correctly.",
        must_cite=("N8633A",),
        must_report=(NumberCheck(7, "leg count"),),
        must_mention=(("msy",), ("hou", "houston")),
    ),
    Question(
        question_id="chain-break-impossible-turn",
        question=(
            "Does WN1016 from BWI to RSW on 2026-01-07 have a following leg on the same "
            "aircraft? If not, why does the rotation stop there?"
        ),
        reference=(
            "No. 2026-01-07|WN|1016|BWI|RSW|1430 has no next leg. Tail N247WN's next recorded "
            "RSW departure is WN120 RSW-MKE at 20:05 UTC, but WN1016 is not scheduled to "
            "arrive at RSW until 22:20 UTC, 135 minutes after that departure. The rotation "
            "link is therefore not built, and the break is recorded as an impossible turn: "
            "the two legs cannot be the same aircraft as scheduled, so this is a "
            "tail-assignment artefact in the source data rather than a real connection."
        ),
        verified_by="store.chain_break_after(...) -> impossible_turn, gap_minutes -135",
        tests=(
            "Whether it reports the absence of a link as a fact with a reason, or quietly "
            "invents the next leg by picking the tail's next departure anywhere."
        ),
        must_cite=("2026-01-07|WN|1016|BWI|RSW|1430", "N247WN"),
        must_report=(NumberCheck(135, "size of the negative gap in minutes", tolerance=1),),
        must_mention=(("impossible turn", "impossible_turn"),),
    ),
    Question(
        question_id="recovery-swap",
        question=(
            "Flight 3851 PHX-SFO on 2026-01-03 is going to be 142 minutes late and I have "
            "spare tails at PHX. If I swap the aircraft, how many of the downstream minutes do "
            "I get back, and what does the swap not tell me?"
        ),
        reference=(
            "All 565 of them. Swapping 2026-01-03|WN|3851|PHX|SFO|0855 moves the delayed "
            "rotation off N8633A, so the five downstream legs go back to schedule. N8528Q, "
            "N8803L, N8922Q, N8963Q and several "
            "other WN tails are on the ground at PHX in time. The caveat is the one the diff "
            "carries: the displaced aircraft N8633A takes over the replacement's remaining "
            "line of flying and that is not re-projected, so 565 is the relief on this "
            "rotation, not the net effect on the network. Fleet compatibility is also "
            "unchecked, because BTS carries no aircraft type."
        ),
        verified_by=(
            "delay_flight(scenario, ROOT, 142) then swap_aircraft(same scenario, ROOT, "
            "'N8528Q') -> net_minutes -565, warnings list the un-reprojected displacement"
        ),
        tests=(
            "Two things: whether it composes two actions in one scenario rather than "
            "simulating the swap against an undelayed world, and whether it passes on the "
            "warning instead of presenting 565 as a clean win."
        ),
        must_cite=(ROOT,),
        must_report=(NumberCheck(565, "minutes recovered", tolerance=5),),
        must_mention=(
            ("swap",),
            ("n8633a",),
            ("not re-projected", "not reprojected", "displaced", "takes over", "line of flying"),
        ),
    ),
    Question(
        question_id="worst-departure-of-week",
        question=(
            "Across the whole week in this data, which departure was the latest, and what was "
            "it blamed on?"
        ),
        reference=(
            "2026-01-01|WN|4285|SDF|BWI|0540, WN4285 SDF-BWI scheduled 05:40, departed "
            "692 minutes late. "
            "677 of those minutes are attributed to the carrier. The aircraft was N291WN and "
            "its next leg was WN1732 BWI-MCI the same evening."
        ),
        verified_by="ORDER BY dep_delay_minutes DESC LIMIT 1 over the sample",
        tests=(
            "Ranking across the whole window. The ontology agent has to use the "
            "min_dep_delay filter to get under the 40-row cap; the baseline sorts."
        ),
        must_cite=("2026-01-01|WN|4285|SDF|BWI|0540",),
        must_report=(
            NumberCheck(692, "departure delay in minutes"),
            NumberCheck(677, "carrier-attributed minutes"),
        ),
        must_mention=(("carrier",),),
    ),
    Question(
        question_id="upstream-attribution",
        question=(
            "WN4303 SFO-DEN on 2026-01-03 left 362 minutes late, and BTS blames 338 of that on "
            "a late inbound aircraft. Which inbound was it, and how far back can you trace the "
            "delay?"
        ),
        reference=(
            "The inbound was 2026-01-03|WN|4124|PHX|SFO|1840, same tail N8747Q, which arrived 357 "
            "minutes late with 348 minutes attributed to NAS. The trace stops there: the "
            "rotation link into WN4124 does not exist, because the aircraft's preceding leg "
            "WN2601 DEN-PHX is recorded as an impossible turn: it is scheduled to arrive at "
            "PHX at 02:50 UTC, 70 minutes after WN4124 is scheduled to leave PHX. So the "
            "furthest verifiable root is an NAS delay at PHX on WN4124."
        ),
        verified_by=(
            "traverse previous_leg from 2026-01-03|WN|4303|SFO|DEN|2025; previous_leg of "
            "WN4124 is absent, chain_breaks records impossible_turn on WN2601 with gap -70"
        ),
        tests=(
            "Backwards traversal, and honesty about where the chain ends. A naive "
            "tail-and-timestamp join in SQL will happily return WN2601 as the inbound and "
            "produce a longer, wrong story."
        ),
        must_cite=("2026-01-03|WN|4124|PHX|SFO|1840",),
        must_report=(
            NumberCheck(357, "inbound arrival delay in minutes"),
            NumberCheck(348, "NAS minutes on the inbound"),
        ),
        must_mention=(
            ("nas", "national air system"),
            ("cannot", "can't", "no further", "stops", "breaks", "not linked", "no previous"),
        ),
    ),
    Question(
        question_id="cancellations-by-reason",
        question=(
            "How many flights were cancelled across the week in this data, and what was the "
            "most common reason?"
        ),
        reference=(
            "106 cancellations. The dominant reason is the national air system with 65, then "
            "weather with 27 and carrier with 14. They are heavily concentrated: 55 of the 106 "
            "fall on 2026-01-03, and 29 on 2026-01-01."
        ),
        verified_by="GROUP BY cancellation_code over status = 'cancelled' in the sample",
        tests=(
            "Aggregation. This is the question the object layer is worst at: find_objects caps "
            "at 40 rows, so counting 106 cancellations exactly is not something the three "
            "tools can do, and the correct behaviour for the ontology agent is to say so. It "
            "is kept in the set because an eval that only asks questions the design wins is "
            "not evidence."
        ),
        must_report=(
            NumberCheck(106, "total cancellations"),
            NumberCheck(65, "national air system cancellations"),
        ),
        must_mention=(("national air system", "national_air_system", "nas"),),
    ),
    Question(
        question_id="absorption-threshold",
        question=(
            "Same aircraft, same day: if flight 3851 PHX-SFO on 2026-01-03 were only 20 "
            "minutes late instead of 142, how far down N8633A's day would that propagate?"
        ),
        reference=(
            "Barely at all. One leg is touched, 2026-01-03|WN|4106|SFO|PHX|1055, which goes 5 "
            "minutes late, and the scheduled ground time at PHX absorbs the rest. Nothing "
            "after that moves. A 10-minute delay propagates nothing at all."
        ),
        verified_by=(
            "delay_flight(scenario, ROOT, 20) -> net_minutes 5 over 1 affected leg; the same "
            "call with 10 minutes returns 0 legs"
        ),
        tests=(
            "Whether it understands that schedule buffer absorbs small delays, instead of "
            "assuming every minute of delay propagates one-for-one down the rotation."
        ),
        must_cite=("2026-01-03|WN|4106|SFO|PHX|1055",),
        must_report=(
            NumberCheck(5, "downstream minutes", tolerance=2),
            NumberCheck(1, "number of legs affected"),
        ),
        must_mention=(("absorb", "buffer", "ground time", "slack"),),
    ),
    Question(
        question_id="unanswerable-aircraft-type",
        question=(
            "What aircraft type operated flight 3851 PHX-SFO on 2026-01-03, and how many "
            "passengers had to be rebooked because of the delay?"
        ),
        reference=(
            "Neither is answerable from this data. BTS On-Time Performance records the tail "
            "number, N8633A, but not the aircraft type; the type would have to come from "
            "the FAA registry, looked up by that tail. Passenger counts and rebookings are not "
            "in the dataset in any form; they would come from the airline's own reservation "
            "system. The delay itself is known: 142 minutes."
        ),
        verified_by=(
            "The BTS On-Time Performance schema has no aircraft-type or passenger columns; the "
            "ingested tables carry neither."
        ),
        tests=(
            "Refusal under pressure. The question presupposes both facts exist, and a model "
            "that pattern-matches 'Southwest' to '737' will produce a plausible, unverifiable, "
            "wrong answer."
        ),
        must_mention=(
            ("not in", "does not", "doesn't", "cannot", "can't", "no aircraft type", "unavailable"),
            ("passenger",),
            ("faa", "registry", "reservation", "would need", "would come from", "not recorded"),
        ),
        must_not_claim=("737", "boeing", "airbus", "a320", "max 8"),
    ),
)

BY_ID = {question.question_id: question for question in QUESTIONS}


def score(grades: list[Grade]) -> tuple[int, int]:
    """n out of 10, the only headline number this eval produces."""
    return sum(1 for grade in grades if grade.passed), len(grades)
