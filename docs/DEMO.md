# Three-minute demo

The script for the recorded walkthrough. Everything in **bold** is what to say out loud. The rest
is what to do while saying it.

Every number below was read off the live site on 14 August 2026, so the screen will match as long
as the API is serving January 2026.

Record at 1280x800 or wider. The three columns need the room.

**Before you hit record:** open the site and let it finish loading. The API sleeps when nobody is
using it and takes up to a minute to wake up, and you do not want the first frame of your demo to
be a loading spinner. Once it is warm, reload and start.

<https://flightops-woad.vercel.app/?date=2026-01-03&root=2026-01-03%7CWN%7C3851%7CPHX%7CSFO%7C0855>

---

## 0:00 to 0:25

Landing view. Do not touch anything yet.

> **This is one day of Southwest's US flying, about twenty six thousand flights, from the Bureau
> of Transportation Statistics.**
>
> **The list on the left is that day's delays. But it isn't sorted by how late anything was. It's
> sorted by how many minutes each delay pushed onto later flights flown by the same plane.**
>
> **That difference turned out to be the whole project.**

---

## 0:25 to 1:10

Point at row one, then row three. This is the most important thing you say, so slow down.

> **Look at the top row next to the third one.**
>
> **The top one is a Phoenix to San Francisco flight that left 142 minutes late. Third row down,
> also Phoenix to San Francisco, left 343 minutes late. More than twice as bad.**
>
> **But the 142 minute delay is the one that actually cost more. It pushed 565 minutes onto five
> later flights. The 343 minute one pushed 338 minutes onto a single flight, because it happened
> late enough in the evening that the plane only had one leg left to fly.**
>
> **So if you're working a delay board sorted by minutes late, you're starting with the wrong
> one.**

---

## 1:10 to 1:50

Row one is already selected. Point at the timeline in the middle.

> **This is that aircraft's day. Five flights after the one that broke.**
>
> **You can watch the delay shrink as it goes. 127 minutes, then 117, 112, 107, 102. Every
> turnaround eats a bit of it, fifteen minutes at the first stop and five at the rest, because the
> scheduled ground time is longer than what the plane actually needs.**
>
> **And then it stops overnight. The aircraft parks, and the next morning starts clean.**

Open **Table view** for a second so it is clear the chart is backed by numbers, then close it.

---

## 1:50 to 2:30

Scroll to Recovery. Leave the dropdown alone and press **swap aircraft**.

> **Down here I can try to fix it. Ten aircraft were sitting in Phoenix in time to take that
> flight. If I swap the first one in, it clears all 565 minutes across all five legs.**
>
> **And then it tells me three things it doesn't know.**

Let the warnings finish appearing before you keep going.

> **It hasn't checked whether that aircraft can actually fly the route, because this data doesn't
> include aircraft type. It hasn't worked out what happens to the plane I just displaced. And the
> replacement is only in position if its own inbound flight isn't late.**
>
> **I care about those three lines more than I care about the 565. A number without them is how
> you get someone in trouble.**

---

## 2:30 to 2:55

Switch to the README, scrolled to the two month table.

> **I didn't want to trust one month, so I ran the same thing on July 2025, which is a pretty
> different month.**
>
> **The main number held up exactly. A delay carries 0.91 of itself into the next flight, in both
> months.**
>
> **One thing didn't hold. January said 43 percent of these get worse as they go. July said 31. So
> I report the weaker one. I didn't touch anything to make them agree.**

---

## 2:55 to 3:10

Scroll to the eval section, or use the right hand pane on the site.

> **Last thing. Ten questions, graded on whether the answer is right and whether it cites flight
> numbers you can go and check yourself. This version gets 9 out of 10. A plain SQL version of the
> same model gets 8.**
>
> **And the gap is at the top of the README. I never interviewed a real dispatcher. Everything
> about their problem I got from published sources, and the questions I'd ask are written down in
> the repo.**

Stop there. Do not add a closing line.

---

## If you run long

The full read is about three and a quarter minutes. Two cuts get you under three:

- Drop **"Every turnaround eats a bit of it... what the plane actually needs"** at 1:10. The
  shrinking numbers make the point on their own.
- Drop **"Ten aircraft were sitting in Phoenix in time to take that flight"** at 1:50 and go
  straight to the swap.

Do not cut the three warnings or the July paragraph. Those two are the reason anyone watches to
the end.

---

## Things to avoid

- Don't open the code. Anyone who wants it will read the repo. The video is for someone with three
  minutes who is not going to.
- Don't narrate your clicking. "Now I'm going to click the first row" is three seconds gone.
- Don't apologise for the missing interviews. Say it flat and move on. It's already the first
  thing the README owns up to.
- Don't re-record over a small stumble. One slightly rough take sounds like a person. Four clean
  spliced pieces sound like someone reading.
