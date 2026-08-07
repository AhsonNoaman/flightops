'use client';

import { useEffect, useRef, useState } from 'react';
import { ApiError, DisruptionEvent, Health, api } from '@/lib/api';
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
 *
 * The selected day and cascade live in the query string. A tool whose findings cannot be sent to
 * someone else is a tool for one person: "look at this cascade" has to be a link, not a sequence
 * of clicks to reproduce.
 */
export default function Page() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);
  const [date, setDate] = useState<string>('');
  const [events, setEvents] = useState<DisruptionEvent[] | null>(null);
  const [selected, setSelected] = useState<DisruptionEvent | null>(null);

  // What the incoming URL asked for. Read once on mount -- `window` does not exist while the
  // static export is being prerendered -- and consumed at most once, so that a later click is
  // never overridden by the link the visitor happened to arrive on.
  const requested = useRef<{ date: string | null; root: string | null }>({ date: null, root: null });
  const consumedRoot = useRef(false);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    requested.current = { date: query.get('date'), root: query.get('root') };

    // Free container hosting sleeps when idle, so the first visitor after a quiet spell waits
    // out a cold start. Retrying quietly for a minute is the difference between "this project
    // is dead" and "this took a moment" -- and a portfolio link is mostly read cold.
    let cancelled = false;
    let attempt = 0;

    async function connect(): Promise<void> {
      while (!cancelled && attempt < 20) {
        try {
          const body = await api.health();
          if (cancelled) return;
          setHealth(body);
          setWaking(false);
          setFailure(null);
          // A day from the URL wins, but only if the deployment actually holds it -- a stale
          // link should land on a working screen rather than an empty one. Otherwise the worst
          // day in the committed sample, chosen from the data rather than hardcoded, because
          // landing on a quiet day would make a working deployment look broken.
          const asked = requested.current.date;
          const holds = asked !== null && asked >= body.first_date && asked <= body.last_date;
          setDate(
            holds ? asked : body.last_date >= '2026-01-03' ? '2026-01-03' : body.first_date,
          );
          return;
        } catch (error) {
          attempt += 1;
          if (cancelled) return;
          if (attempt >= 20) {
            setWaking(false);
            setFailure(error instanceof ApiError ? error.message : String(error));
            return;
          }
          setWaking(true);
          await new Promise((resolve) => setTimeout(resolve, 3000));
        }
      }
    }

    void connect();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!date) return;
    setEvents(null);
    setSelected(null);
    api
      .disruptions(date)
      .then((body) => {
        setEvents(body);
        const wanted = consumedRoot.current ? null : requested.current.root;
        consumedRoot.current = true;
        setSelected(body.find((event) => event.root_flight_id === wanted) ?? body[0] ?? null);
      })
      .catch((error: ApiError) => setFailure(error.message));
  }, [date]);

  // replaceState rather than pushState: paging down a ranked list should not fill the back
  // button with twelve entries, but the address bar should always describe what is on screen.
  useEffect(() => {
    if (!date) return;
    const query = new URLSearchParams({ date });
    if (selected) query.set('root', selected.root_flight_id);
    window.history.replaceState(null, '', `${window.location.pathname}?${query}`);
  }, [date, selected]);

  return (
    <>
      <header className="masthead">
        <h1>flightops</h1>
        <span className="rule" />
        <span className="meta">rotation cascades over BTS On-Time Performance</span>
        <span className="spacer" />
        {health && (
          <span className="meta">
            {health.carriers.join(', ')} · {health.first_date} to {health.last_date} ·{' '}
            <span className="mono">{health.flight_count.toLocaleString()}</span> flights
          </span>
        )}
        <span className="rule" />
        <label>
          day
          <input
            type="date"
            value={date}
            min={health?.first_date}
            max={health?.last_date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
      </header>

      {waking && (
        <div className="note" style={{ margin: '12px 18px' }}>
          Waking the API. It sleeps when nobody is using it, so a first visit after a quiet spell
          takes up to a minute.
        </div>
      )}
      {failure && (
        <div className="error" style={{ margin: '12px 18px' }}>
          {failure} The API is hosted separately from this page and may be down; the repository,
          the container image and the recorded eval do not depend on it.
        </div>
      )}

      <div className="grid">
        <section className="pane">
          <div className="pane-head">
            <h2>Disruptions</h2>
            <p className="caption">
              Ranked by minutes forced onto downstream legs, one per aircraft. Legs whose delay BTS
              attributes mostly to a late inbound aircraft are consequences, not roots, and are
              excluded.
            </p>
          </div>
          <DisruptionList events={events} selected={selected} onSelect={setSelected} />
        </section>

        <section className="pane">
          {selected ? (
            <CascadeView event={selected} />
          ) : (
            <>
              <div className="pane-head">
                <h2>Cascade</h2>
              </div>
              <p className="caption">Select a disruption.</p>
            </>
          )}
        </section>

        <section className="pane">
          <QuestionPanel liveEnabled={health?.live_answers ?? false} />
        </section>
      </div>
    </>
  );
}
