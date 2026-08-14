# Three-minute demo

A shot list for the recorded walkthrough. Every number below was read off the live deployment on
2026-08-14, so the screen will match the script as long as the API is serving January 2026.

Record at 1280x800 or wider. The three panes need the width, and a phone-shaped window stacks them.

**Before you hit record:** open <https://flightops-woad.vercel.app/?date=2026-01-03&root=2026-01-03%7CWN%7C3851%7CPHX%7CSFO%7C0855>
and let it finish loading. The API sleeps when idle and takes up to a minute to wake, and the
first frame of a demo should not be a spinner. Reload once it is warm and start from there.

---

## 0:00 to 0:25 · What the screen is

**On screen:** the landing view, 3 January 2026, ranked list on the left.

> This is one carrier's day of US domestic flying, twenty six thousand flights, from the Bureau of
> Transportation Statistics. The left pane ranks the day's delays, but not by how late anything
> was. It ranks them by how many minutes each one forced onto later flights flown by the same
> aircraft.

Do not explain the architecture yet. The ranking is the claim, so lead with it.

---

## 0:25 to 1:00 · Why the ranking is the point

**On screen:** point at row 1, then row 3.

> The top row is a Phoenix to San Francisco departure that ran 142 minutes late. Third row down is
> another Phoenix to San Francisco that ran 343 minutes late, more than twice as bad.
>
> The 142 minute delay is the more expensive one. It pushed 565 minutes onto five later flights.
> The 343 minute delay pushed 338 minutes onto one, because it happened late enough in the evening
> that the aircraft only had one leg left.
>
> If you sort a delay board by minutes late, you work the second one first. That is the thing this
> is for.

This is the whole pitch. If the recording only lands one beat, land this one.

---

## 1:00 to 1:40 · The cascade, and what absorbs it

**On screen:** row 1 is already selected; the middle pane shows the rotation timeline.

> Same aircraft, five legs after the one that broke. The delay decays as it goes: 127 minutes,
> then 117, 112, 107, 102. Each turn absorbs a little, 15 minutes at the first one and 5 at the
> rest, because scheduled ground time is longer than the minimum the aircraft actually needs.
>
> It stops at the overnight break. The aircraft sits, the schedule resets, and the next morning
> starts clean.

Open the **Table view** disclosure for two seconds so it is visible that every number in the chart
is available as numbers, then close it again.

---

## 1:40 to 2:20 · The counterfactual, and what it refuses to claim

**On screen:** scroll to Recovery. Leave the tail dropdown on its default and press **swap
aircraft**.

> Ten aircraft were on the ground in Phoenix in time to take that flight. Swapping in the first
> one clears all 565 downstream minutes across all five legs.
>
> And then it tells me three things it does not know. It has not checked fleet compatibility,
> because the source data carries no aircraft type. It has not re-projected what happens to the
> aircraft I displaced. And the replacement is only in position if its own inbound leg holds.

Let the warnings sit on screen while you say that last line. Then:

> Nothing was written. The historical day is read only and the simulation runs in a scenario over
> the top of it.

The warnings are the most interview-relevant thing on the page. A tool that reports a 565 minute
saving without them is the tool that gets the operator fired.

---

## 2:20 to 2:45 · Whether the model is right

**On screen:** the README, scrolled to the two-month comparison.

> I did not want to trust one month. So I ran the same measurement on July 2025, which is a
> structurally different month: fewer cancellations, more traffic, worse congestion.
>
> The core number replicated exactly. A first downstream leg carries 0.91 times the root delay in
> both months, and the median cascade is one leg in both.
>
> The amplification tail did not replicate. January said 43 percent of cascades get worse as they
> go, July said 31. So the weaker reading is the one I report. I did not tune anything to make
> them agree.

---

## 2:45 to 3:00 · The eval, and the gap

**On screen:** the right pane, Eval section.

> Ten questions, graded on whether the answer is right and whether it cites flight ids you can
> check. The agent that goes through the object model gets 9. A baseline agent with raw SQL and
> the same model gets 8, and both of the ones it misses are answers that were correct but
> uncitable.
>
> The object model costs about 65 percent more per answer. On nine of the ten questions the cost
> is a wash. One question blows it out, and that question is one the object model has no efficient
> way to serve.
>
> The honest gap is at the top of the README. I ran no user interviews. Everything about the
> operator's problem is inferred from published sources, and the questions that would settle it
> are written down in the repository.

End there. Do not add a summary sentence.

---

## What not to do

- Do not open the code. The repository is the artefact for anyone who wants it; the demo is for
  someone who has three minutes and no intention of reading files.
- Do not narrate clicks. "Now I'm going to click on the first row" is three wasted seconds.
- Do not apologise for the missing interviews. State it as a known boundary and stop. It is
  already the first thing the README admits.
- Do not run a second take to fix a stumble in the middle. A slightly rough single take reads as a
  person; four clean spliced segments read as a script being performed.
