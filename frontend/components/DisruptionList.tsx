'use client';

import { DisruptionEvent, label } from '@/lib/api';

const CAUSE_LABEL: Record<string, string> = {
  carrier: 'carrier',
  weather: 'weather',
  nas: 'air traffic',
  security: 'security',
  late_aircraft: 'late aircraft',
  unattributed: 'no cause recorded',
};

/**
 * The ranked list. Each row leads with the downstream cost, because that is the number the
 * ranking is by and a list sorted on a number you have to hunt for reads as unsorted.
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
  if (events === null) return <p className="caption">Loading…</p>;
  if (events.length === 0)
    return <p className="caption">No delay over 30 minutes started a cascade on this day.</p>;

  return (
    <>
      {events.map((event) => (
        <button
          key={event.event_id}
          className={`row${selected?.event_id === event.event_id ? ' selected' : ''}`}
          onClick={() => onSelect(event)}
        >
          <span className="top">
            <strong>{label(event.root_flight_id)}</strong>
            <span className="delay">+{event.total_propagated_minutes} min downstream</span>
          </span>
          <span className="sub">
            <span>
              {event.tail_number} · {CAUSE_LABEL[event.cause] ?? event.cause} · root +
              {event.root_delay_minutes}
            </span>
            <span>
              {event.affected.length} leg{event.affected.length === 1 ? '' : 's'}
            </span>
          </span>
        </button>
      ))}
    </>
  );
}
