# Using this: three tasks, ten minutes

Written for whoever runs the day, not for whoever built the tool. You do not need to know
anything about how it works to finish all three.

**What it is.** A replay of a real day of US airline operations. It walks each aircraft's line of
flying and works out what a late departure does to the rest of that tail's day, so you can see
which delay is actually costing you something and which one the schedule is going to absorb on
its own.

**What it is not.** It is not live, it does not know about crew, and it cannot see your
passengers. More on that at the bottom, and it matters.

---

## Task 1. Find the delay that is actually costing you (2 minutes)

Pick a day at the top right. The left column fills with the day's disruptions.

That column is **not** a list of late flights. It is a list of *roots*, ranked by the minutes each
one pushes onto everything the same aircraft flies afterwards. A flight that went out two hours
late but was the last leg of the day costs nothing downline and will not be near the top. A
flight that went out ninety minutes late at 08:00 with five legs to go will be.

Each row reads: the flight, the tail, what the delay was put down to, how late it went out, and
how many minutes and legs it cost downline.

> **Read the difference.** Take 3 January. The four latest departures that day went out 422,
> 367, 362 and 324 minutes down, and not one of them is on the list. Three of them were late
> because their own inbound aircraft was late, so they are somebody else's cascade, not a new
> one. The fourth, the 422, has a rotation the record cannot follow past that leg, so the tool
> says it does not know rather than guessing. Top of the list instead is a **142**-minute delay
> that cost 565 minutes across five legs, two rows above a **343**-minute delay that cost 338
> across one. Sorted by lateness, you would have worked the wrong aeroplane.

## Task 2. See where it lands, and what gets absorbed (3 minutes)

Click a row. The middle panel is that aircraft's whole day, in order.

- **Sched dep** is what the schedule says. **Projected** is when it actually gets away if nobody
  does anything.
- **Delay** is how late that leg ends up. Watch it come down as the day goes on: 142, then 127,
  117, 112. Each turn gives a few minutes back because there is slack in the ground time.
- **Absorbed** is how much the schedule ate at that station.
- The line underneath says where the cascade stops and why: usually the aircraft overnights, or
  the next turn has enough ground time to soak up what is left.

If the row says the rotation stops because the next leg is not the same aircraft, that is not a
bug. The source data has no ferry or positioning moves in it, so where the schedule shows a tail
appearing at a station it never flew into, the tool says so rather than joining two legs that are
not really connected.

## Task 3. Try the recovery (5 minutes)

Underneath the cascade, pick a tail from the dropdown and press **swap aircraft**.

The dropdown only offers tails that are on the ground at that station in time to make the
departure, with a realistic turn. If nothing is offered, nothing is in position.

You get a before-and-after for every leg, and a headline number: how many of those downline
minutes come back. Try **cancel this leg** for comparison. It clears the same downline minutes
but leaves the aircraft in the wrong place, and the tool says so.

**Read the notes under the diff. They are the important part.** Three of them show up on most
swaps, and each one is a thing the tool cannot check for you:

- *Fleet compatibility is not checked.* The data has the tail number but not the aircraft type.
  The swap it just offered you may be the wrong gauge for the route or the load.
- *The displaced aircraft is not re-projected.* The tail you swapped out has to pick up the other
  one's remaining flying. The number you are looking at is relief on **this** line, not the net
  across the network.
- *If the inbound slips, the swap slips with it.* It tells you which leg the replacement is
  arriving on.

Nothing you do here changes anything. You are working in a sandbox over a finished day; the
underlying record is never touched, and closing the tab throws your changes away.

---

## What it will get wrong, and roughly how much

**It over-predicts.** Checked against the day's own records, it is about five minutes on the
high side for one carrier's week, and between seven and fourteen across a full month depending
on the month. It always errs toward predicting more delay than was actually attributed. Two
reasons: crews routinely beat the scheduled block time, and the recorded day already includes
whatever somebody did about the problem. A cascade the tool shows you that never
happened is often a cascade a controller prevented. That is the tool doing its job, not failing
at it.

**It never misses one.** In the same check, there was no case where the day's own records showed
an aircraft-driven delay and the tool said the line was clean. If it says nothing is coming, that
part has held up.

**It knows nothing about crew.** No duty limits, no legality, no positioning. The single most
likely reason a swap it suggests is impossible in real life is one it cannot see.

**It knows nothing about passengers.** No loads, no misconnects, no rebooking. Two cancellations
that cost the same number of aircraft minutes can be very different for the people on them, and
the tool has no opinion about which.

**It is one month of one year.** No seasonality, and no sense of whether a day was unusual.

---

## The question box

If the box on the right is greyed out, live question-answering is switched off on this
deployment, because it costs money per question and the page is public. Underneath it are ten
questions
that were asked and answered, with the correct answer worked out by hand beforehand, so you can
see what the thing does and does not get right without anyone paying for it.

When it is on, ask in plain language. Every answer names the specific flights it used, so you can
go and check any number it gives you. If it cannot tell you something from this data, it is
supposed to say so rather than guess, and one of the ten questions exists purely to test that.
