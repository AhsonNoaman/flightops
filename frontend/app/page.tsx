'use client';

import { useEffect, useState } from 'react';
import {
  ApiError,
  DisruptionEvent,
  Health,
  api,
} from '@/lib/api';
import { DisruptionList } from '@/components/DisruptionList';
import { CascadeView } from '@/components/CascadeView';
import { QuestionPanel } from '@/components/QuestionPanel';

/**
 * Three panes, left to right: what hurt today, where it went, and what to ask about it.
 *
 * The ordering is the operator's question order rather than the data model's. Section 2 of
 * DESIGN.md claims the missing thing is knowing which delay is worth acting on, so the ranked
 * list is the landing view and a single cascade is what you get by clicking one -- not the other
 * way round, which would make this a flight search box with a chart attached.
 */
export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [date, setDate] = useState<string>('');
  const [events, setEvents] = useState<DisruptionEvent[] | null>(null);
  const [selected, setSelected] = useState<DisruptionEvent | null>(null);

  useEffect(() => {
    api
      .health()
      .then((body) => {
        setHealth(body);
        // The worst day in the committed sample. Landing on an empty day would make a working
        // deployment look broken, so the default is chosen from the data, not hardcoded.
        setDate(body.last_date >= '2026-01-03' ? '2026-01-03' : body.first_date);
      })
      .catch((error: ApiError) => setFailure(error.message));
  }, []);

  useEffect(() => {
    if (!date) return;
    setEvents(null);
    setSelected(null);
    api
      .disruptions(date)
      .then((body) => {
        setEvents(body);
        setSelected(body[0] ?? null);
      })
      .catch((error: ApiError) => setFailure(error.message));
  }, [date]);

  return (
    <>
      <header className="masthead">
        <h1>flightops</h1>
        <span className="meta">rotation cascades over BTS On-Time Performance</span>
        <span className="spacer" />
        {health && (
          <span className="meta">
            {health.carriers.join(', ')} · {health.first_date} to {health.last_date} ·{' '}
            {health.flight_count.toLocaleString()} flights
          </span>
        )}
        <label className="meta">
          day{' '}
          <input
            type="date"
            value={date}
            min={health?.first_date}
            max={health?.last_date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
      </header>

      {failure && <div className="error" style={{ margin: 12 }}>{failure}</div>}

      <div className="grid">
        <section className="pane">
          <h2>Disruptions</h2>
          <p className="caption">
            Ranked by minutes forced onto downstream legs, one per aircraft. Legs whose delay BTS
            attributes mostly to a late inbound aircraft are consequences, not roots, and are
            excluded.
          </p>
          <DisruptionList events={events} selected={selected} onSelect={setSelected} />
        </section>

        <section className="pane">
          <h2>Cascade</h2>
          {selected ? (
            <CascadeView event={selected} />
          ) : (
            <p className="caption">Select a disruption.</p>
          )}
        </section>

        <section className="pane">
          <QuestionPanel liveEnabled={health?.live_answers ?? false} />
        </section>
      </div>
    </>
  );
}
