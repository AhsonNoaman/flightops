'use client';

import { AffectedLeg, DisruptionEvent, Flight, hhmm } from '@/lib/api';

const MINUTE = 60_000;

/** Tick spacings in hours, coarsest last. Picked so a day of flying gets 6-9 labelled ticks. */
const TICK_HOURS = [1, 2, 3, 6, 12];

interface Lane {
  flight: Flight;
  isRoot: boolean;
  schedDep: number;
  schedArr: number;
  projDep: number;
  projArr: number;
  delay: number;
  absorbed: number;
}

/**
 * The cascade as geometry rather than as a column of numbers.
 *
 * Each leg gets two lanes on a shared clock: the schedule on top, what the projection says
 * actually happens underneath. The horizontal distance between their left edges *is* the delay,
 * so the thing the whole project is about -- one aircraft's late morning walking through its
 * afternoon -- is visible as a staircase instead of something you reconstruct from a table.
 *
 * The table underneath is not redundant with this. Every value here is also a number there,
 * which is what keeps the chart from being the only way to read the data.
 */
export function CascadeTimeline({
  rotation,
  event,
}: {
  rotation: Flight[];
  event: DisruptionEvent;
}) {
  const byId = new Map<string, AffectedLeg>(event.affected.map((leg) => [leg.flight_id, leg]));

  const lanes: Lane[] = rotation.map((flight) => {
    const affected = byId.get(flight.flight_id);
    const isRoot = flight.flight_id === event.root_flight_id;
    const schedDep = Date.parse(flight.sched_dep_utc);
    const schedArr = Date.parse(flight.sched_arr_utc);
    const shift = isRoot ? event.root_delay_minutes : (affected?.propagated_delay_minutes ?? 0);
    return {
      flight,
      isRoot,
      schedDep,
      schedArr,
      projDep: affected ? Date.parse(affected.projected_dep_utc) : schedDep + shift * MINUTE,
      projArr: affected ? Date.parse(affected.projected_arr_utc) : schedArr + shift * MINUTE,
      delay: shift,
      absorbed: affected?.absorbed_minutes ?? 0,
    };
  });

  if (lanes.length === 0) return null;

  const start = Math.min(...lanes.map((lane) => lane.schedDep));
  const end = Math.max(...lanes.map((lane) => Math.max(lane.projArr, lane.schedArr)));
  // A flat span would divide by zero; it cannot happen with real legs but the guard is cheaper
  // than reasoning about whether it can.
  const span = Math.max(end - start, MINUTE);
  const pct = (t: number) => ((t - start) / span) * 100;
  const width = (from: number, to: number) => Math.max(((to - from) / span) * 100, 0.35);

  const hours = span / 3_600_000;
  const step = TICK_HOURS.find((h) => hours / h <= 9) ?? 24;
  const ticks: number[] = [];
  const first = new Date(start);
  first.setUTCMinutes(0, 0, 0);
  for (
    let t = first.getTime() + (first.getTime() < start ? step * 3_600_000 : 0);
    t <= end;
    t += step * 3_600_000
  ) {
    ticks.push(t);
  }

  return (
    <div className="timeline">
      <div className="tl-body">
        <div className="tl-grid" aria-hidden="true">
          <span />
          <span className="lane">
            {ticks.map((t) => (
              <i key={t} style={{ left: `${pct(t)}%` }} />
            ))}
          </span>
          <span />
          <span />
        </div>

        {lanes.map((lane) => {
          const late = lane.delay > 0;
          return (
            <div
              key={lane.flight.flight_id}
              className={`tl-row${lane.isRoot ? ' is-root' : ''}`}
              tabIndex={0}
            >
              <span className="tl-name">
                <b>
                  {lane.flight.carrier}
                  {lane.flight.flight_number}
                </b>
                <em>
                  {lane.flight.origin}&#8202;&#8594;&#8202;{lane.flight.destination}
                </em>
              </span>

              <span className="tl-track">
                <span
                  className="tl-bar plan"
                  style={{
                    left: `${pct(lane.schedDep)}%`,
                    width: `${width(lane.schedDep, lane.schedArr)}%`,
                  }}
                />

                {late && (
                  <span
                    className="tl-shift"
                    style={{
                      left: `${pct(lane.schedDep)}%`,
                      width: `${width(lane.schedDep, lane.projDep)}%`,
                    }}
                  />
                )}

                {lane.absorbed > 0 && (
                  <span
                    className="tl-absorb"
                    style={{
                      left: `${pct(lane.projDep - lane.absorbed * MINUTE)}%`,
                      width: `${width(0, lane.absorbed * MINUTE)}%`,
                    }}
                  />
                )}

                <span
                  className={`tl-bar actual${late ? '' : ' ontime'}`}
                  style={{
                    left: `${pct(lane.projDep)}%`,
                    width: `${width(lane.projDep, lane.projArr)}%`,
                  }}
                />
              </span>

              <span className={`tl-num ${late ? 'delay' : 'faint'}`}>
                {late ? `+${lane.delay}` : '—'}
              </span>
              <span className={`tl-num ${lane.absorbed > 0 ? 'relief' : 'faint'}`}>
                {lane.absorbed > 0 ? `−${lane.absorbed}` : '—'}
              </span>

              <dl className="tl-tip">
                <div>
                  <dt>scheduled</dt>
                  <dd>
                    {hhmm(lane.flight.sched_dep_utc)} – {hhmm(lane.flight.sched_arr_utc)}
                  </dd>
                </div>
                <div>
                  <dt>projected</dt>
                  <dd className={late ? 'delay' : undefined}>
                    {hhmm(new Date(lane.projDep).toISOString())} –{' '}
                    {hhmm(new Date(lane.projArr).toISOString())}
                  </dd>
                </div>
                {lane.absorbed > 0 && (
                  <div>
                    <dt>absorbed by the turn</dt>
                    <dd className="relief">{lane.absorbed} min</dd>
                  </div>
                )}
                {lane.isRoot && (
                  <div>
                    <dt>this is the root</dt>
                    <dd className="delay">+{event.root_delay_minutes} min</dd>
                  </div>
                )}
              </dl>
            </div>
          );
        })}
      </div>

      <div className="tl-axis">
        <span />
        <span className="lane">
          {ticks.map((t) => (
            <span key={t} className="tick" style={{ left: `${pct(t)}%` }}>
              {hhmm(new Date(t).toISOString())}
            </span>
          ))}
        </span>
        <span />
        <span />
      </div>
    </div>
  );
}
