# Interview guide — M1 discovery

Three conversations, thirty minutes each. The purpose is to break DESIGN.md, not to confirm it.

A conversation that produces agreement has produced nothing: either the questions were leading
or the assumption was never at risk. DESIGN.md section 2 is a paragraph written by someone who
has not held the job. The working hypothesis for these calls is that it is wrong in at least one
load-bearing way, and the work is finding out which way.

## Method

**Do not describe the tool.** Not in the scheduling message, not in the introduction. Once they
know what is being built they start helping build it and stop describing their job. Say you are
researching how carriers recover the day of operations.

**Ask for the last instance, not the general case.** "Walk me through the last irregular-ops day
you worked" beats "how do you usually handle delays." General answers are reconstructed and tidy.
Instances carry the mess, and the mess is the finding.

**Ask what is on the screen.** Which system, which view, what is in front of them at 0800. Get
product names. What they use today is a factual question with a checkable answer, and it is the
fastest route to falsifying section 2.

**Reveal the persona last.** In the final five minutes, read the section 2 paragraph verbatim and
ask them to mark what is wrong. This is the highest-yield part of each call, and it only works
after their own unprompted account. Doing it earlier contaminates everything that follows.

**Get consent to quote anonymously**, since quotes may appear in a public repo. Offer the writeup
back; it is the only thing you have to trade.

**Write up within fifteen minutes**, verbatim where possible. Recall degrades fast, and paraphrase
loses their vocabulary, which is the part worth having.

## Assumptions on trial

| # | Assumption (DESIGN.md) | What would falsify it | Ask |
|---|---|---|---|
| 1 | §2 The controller cannot see the cascade and traces it by hand, tail by tail | They already run a rotation view that projects downstream times automatically, and have for years | 1, 3 |
| 2 | §2 Seeing the cascade earlier widens the option set | They see it fine; what binds is crew, spares, gates, or authority — not knowledge | 1, 3 |
| 3 | §2, §3 One controller owns the aircraft-routing recovery decision | The call is negotiated across desks, or made above them by a duty manager | 1, 3 |
| 4 | §6 delay, swap, cancel are the operative levers | The first moves are a spare tail, a gate change, a crew swap, a ferry, or cancelling the out-and-back as a pair | 1 |
| 5 | §3, §10 Downstream minutes is the decision currency | They rank by misconnecting passengers, completion factor, crew downline, or where the aircraft must overnight | 1, 3 |
| 6 | §8 Crew legality is a limitation worth naming, not a blocker | Crew binds most recovery decisions, so an aircraft-only answer cannot be acted on | 1, 3 |
| 7 | §10 min_turn is estimable from observed ground times | Turn time is contractual and stand-specific; controllers know the real number and would read the estimate as wrong | 2, 3 |
| 8 | §9, §10 BTS cause codes are usable ground truth for cascade attribution | Coding is post-hoc, administrative, sometimes negotiated; nobody looks at it during the day | 1, 2 |
| 9 | §5, §10 Delay propagates through the tail | It also propagates through gates, crew pairings, and passenger connections — paths the model cannot represent at all | 2, 3 |
| 10 | §10 Chains end at the overnight break | The overnight is the constraint: the aircraft must reach a maintenance base, and that dominates the last legs of the day | 1, 3 |

Assumption 9 is the one that would force a structural change rather than a wording change. Listen
for it in every call.

## Conversation 1 — Airline IOC or operations controller

More questions than fit in thirty minutes. The marked ones are what the milestone depends on; the
rest are there if the conversation goes wide.

1. Walk me through the last irregular-ops day you worked. Start from when you knew, and go
   forward. (Let it run. Do not steer.)
2. What told you? A screen, an alert, a phone call, someone walking over?
3. **(core, 1)** When a tail is running late, how do you work out what else it hits tonight? Talk
   me through it click by click. — *If a system already projects it: what does the projection not
   tell you, do you trust it, and when is it wrong?*
4. What is actually on your screens at 0800? What are the products called?
5. **(core, 2)** On that day, was the hard part seeing what would happen, or deciding what to do
   about it? Which took longer?
6. Last tail swap you made: what did you have to check, who did you have to call, and how long
   from deciding to it being real?
7. **(4)** What do you reach for before a swap? What is the cheapest move available at 0800 that
   is gone by noon?
8. **(4)** When you cancel, is it the leg or the round trip? What decides?
9. **(core, 6)** How often is it the aircraft that cancels the flight, versus the crew?
10. **(3)** Who else has to agree before it happens? Who can overrule you?
11. **(5)** When two recovery options are on the table, what makes one better? What number, if
    any, do you compare?
12. **(8)** Does anyone act on the DOT delay cause codes during the day? Who assigns them, and
    when?
13. **(10)** What decides where an aircraft has to end up at night?
14. If you could know one thing at 0800 that you do not know now, what is it? (Ask before the
    reveal, and do not offer options.)
15. **(final five minutes)** Read section 2 verbatim: "I wrote this description of a job I have
    never done. Where is it wrong? Where does it read like someone who has read about this rather
    than done it?"

## Conversation 2 — Airport operations manager

DESIGN.md models Airport as a code, a city, and a timezone. If the airport turns out to be an
actor with its own constraints rather than a location, that is a finding about the object model.

1. Walk me through the last morning your operation went sideways.
2. When an inbound runs late, what has to move on your side?
3. **(core, 7)** Is there a real minimum turn time here, or does it depend? On what — stand,
   carrier, aircraft size, time of day, who is handling?
4. Where do turns actually break at this airport? Rank the causes.
5. **(core, 9)** Does one late aircraft at a gate make other flights late? How does that happen?
6. What do you know about a carrier's downline that they do not tell you? What do you wish they
   told you?
7. Who calls you from an airline ops center, and what do they ask for?
8. **(8)** Who codes a delay, and does anyone ever argue about the code?
9. **(final five minutes)** Persona reveal, same wording, plus: "Does the airport appear anywhere
   in this description? Should it?"

## Conversation 3 — Dispatcher or line pilot

Under Part 121 dispatch holds operational control jointly with the captain, which makes this the
conversation that tests who actually decides. It is also the only one that can test section 10's
stated error sources, because the person absorbing delay in the air is the reason the model will
overpredict.

1. **(3)** Who actually decides a flight goes, is delayed, or is cancelled? Where does the ops
   center's decision meet yours?
2. Walk me through the last time you were the late aircraft. What did you know about the rest of
   the day, and when did you know it?
3. **(core, §10 padding)** How much of a delay can you realistically make up in the air, and does
   anyone ask you to?
4. When the ops center changes your aircraft or your sequence, how do you find out, and how often
   is the plan already stale by the time it reaches you?
5. **(core, 6)** When does crew time become the thing that cancels the flight, rather than the
   airplane?
6. **(7)** What makes a turn run long when nothing looks wrong?
7. **(8)** Do you see the cause code assigned to your delay? Is it right?
8. **(10)** What happens if the aircraft does not reach the base it was meant to overnight at?
9. **(final five minutes)** Persona reveal.

## Capture, within fifteen minutes of each call

- Role, carrier or airport type, date, length, consent to quote.
- At least three verbatim quotes, including their own name for the problem.
- Every system they named.
- Each place they contradicted DESIGN.md, with the section number.
- The thing that surprised you.
- What you now believe is wrong in DESIGN.md, and what you would change in the model.

Paste these back for synthesis into `docs/DISCOVERY.md`.

## Honesty guard

The brief requires the writeup to contain the moment the initial understanding turned out to be
wrong. That moment cannot be manufactured. If all three conversations confirm section 2, the
correct output is a DISCOVERY.md that says so and examines why the questions failed to put the
assumption at risk — not an invented reversal to fill the section. A discovery writeup reporting
a null result honestly survives an interview; a convenient one does not.
