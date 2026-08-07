'use client';

import { DisruptionEvent } from '@/lib/api';

const CAUSE_LABEL: Record<string, string> = {
  carrier: 'carrier',
  weather: 'weather',
  nas: 'air traffic',
  security: 'security',
  late_aircraft: 'late aircraft',
  unattributed: 'no cause recorded',
};

function parts(flightId: string): { ident: string; route: string; time: string } {
  const field = flightId.split('|');
  if (field.length !== 6) return { ident: flightId, route: '', time: '' };
  const [, carrier, number, origin, destination, hhmm] = field;
  return {
    ident: `${carrier}${number}`,
    route: `${origin} → ${destination}`,
    time: `${hhmm.slice(0, 2)}:${hhmm.slice(2)}`,
  };
}

/**
 * The ranked list, with the ranking made visible.
 *
 * Each row leads with the downstream cost because that is the number the list is sorted by, and a
 * list sorted on a figure you have to hunt for reads as unsorted. The bar is the same figure as
 * length: thirteen rows of near-identical numerals do not communicate that the top one is three
 * times the fifth, and that ratio is the entire argument for triaging by cascade rather than by
 * delay. One colour for every bar -- shading them by size would encode the same fact twice.
 */
export function DisruptionList({
  events,
  selected,
  onSelect,
}: {
  events: DisruptionEvent[] | null;
  selected: DisruptionEvent | null;
  onSelect: (event: DisruptionEvent) => void;
}) {
  if (events === null) return <p className="skeleton">Loading…</p>;
  if (events.length === 0)
    return <p className="caption">No delay over 30 minutes started a cascade on this day.</p>;

  const worst = Math.max(1, ...events.map((event) => event.total_propagated_minutes));

  return (
    <div className="rank-list">
      {events.map((event, index) => {
        const { ident, route, time } = parts(event.root_flight_id);
        const on = selected?.event_id === event.event_id;
        return (
          <button
            key={event.event_id}
            className={`rank${on ? ' on' : ''}`}
            onClick={() => onSelect(event)}
            aria-pressed={on}
          >
            <span className="ord">{index + 1}</span>
            <span className="body">
              <span className="ident">
                <strong>
                  {ident} <span className="dim">{route}</span>{' '}
                  <span className="faint">{time}</span>
                </strong>
                <span className="val">{event.total_propagated_minutes} min</span>
              </span>
              <span className="magnitude">
                <i
                  style={{
                    width: `${Math.max((event.total_propagated_minutes / worst) * 100, 1.5)}%`,
                  }}
                />
              </span>
              <span className="foot">
                <span>
                  {event.tail_number} · {CAUSE_LABEL[event.cause] ?? event.cause} · root +
                  {event.root_delay_minutes}
                </span>
                <span>
                  {event.affected.length} leg{event.affected.length === 1 ? '' : 's'}
                </span>
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
