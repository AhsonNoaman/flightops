'use client';

import { useEffect, useState } from 'react';
import {
  ActionDiff,
  ApiError,
  DisruptionEvent,
  Flight,
  api,
  hhmm,
  label,
  signed,
} from '@/lib/api';
import { CascadeTimeline } from '@/components/CascadeTimeline';

const TERMINATION: Record<string, string> = {
  absorbed: 'the next turn had enough scheduled ground time to absorb what was left',
  overnight_break: 'the aircraft overnights here, so the cascade stops',
  chain_break: 'the recorded rotation stops here — the next leg is not the same aircraft',
  end_of_window: 'the data window ends here, not the cascade',
  cancellation: 'the next leg was cancelled',
  guard_limit: 'the projection hit its length bound; this list is truncated',
};

const CAUSE: Record<string, string> = {
  carrier: 'carrier',
  weather: 'weather',
  nas: 'air traffic',
  security: 'security',
  late_aircraft: 'late aircraft',
  unattributed: 'no cause recorded',
};

/**
 * One cascade: the headline numbers, the shape of it, then the numbers again as a table.
 *
 * The projection is always shown against the schedule rather than instead of it. An operator
 * comparing a plan to a projection needs both in the same eye movement; showing only the
 * projection makes the number unfalsifiable at a glance, which is the failure this whole project
 * argues against.
 */
export function CascadeView({ event }: { event: DisruptionEvent }) {
  // The chart and the table are driven by a snapshot, not by two independently-updating pieces of
  // state. Holding a previous rotation while a new event's numbers were already on screen would
  // render one aircraft's legs against another aircraft's cascade -- briefly, but wrongly, which
  // is worse than a moment of blank. The headline figures above come straight from the list
  // response and so update instantly; only the chart lags, and it dims while it does.
  const [view, setView] = useState<{ rotation: Flight[]; event: DisruptionEvent } | null>(null);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailure(null);
    api
      .rotation(event.root_flight_id)
      .then((rotation) => {
        if (cancelled) return;
        setView({ rotation, event });
        setLoading(false);
      })
      .catch((error: ApiError) => {
        if (cancelled) return;
        setFailure(error.message);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [event]);

  const rotation = view?.rotation ?? null;
  const shown = view?.event ?? event;

  const byId = new Map(shown.affected.map((leg) => [leg.flight_id, leg]));
  const root = rotation?.find((leg) => leg.flight_id === shown.root_flight_id);
  const absorbed = event.affected.reduce((total, leg) => total + leg.absorbed_minutes, 0);

  return (
    <>
      <div className="pane-head">
        <div className="controls" style={{ marginTop: 0 }}>
          <span className="tag">{event.tail_number}</span>
          <strong style={{ fontSize: 14 }}>{label(event.root_flight_id)}</strong>
          <span className="faint">{CAUSE[event.cause] ?? event.cause}</span>
        </div>
        <p className="id">{event.root_flight_id}</p>
      </div>

      <div className="stats">
        <div className="stat hero">
          <span className="k">Propagated downstream</span>
          <span className="v">
            {event.total_propagated_minutes}
            <small>min</small>
          </span>
          <span className="sub">
            across {event.affected.length} leg{event.affected.length === 1 ? '' : 's'} of one
            aircraft
          </span>
        </div>
        <div className="stat">
          <span className="k">Root delay</span>
          <span className="v delay">
            {event.root_delay_minutes}
            <small>min</small>
          </span>
          <span className="sub">as departed</span>
        </div>
        <div className="stat">
          <span className="k">Absorbed by turns</span>
          <span className="v relief">
            {absorbed}
            <small>min</small>
          </span>
          <span className="sub">given back on the ground</span>
        </div>
      </div>

      {failure && <div className="error">{failure}</div>}

      <div className="chart-head">
        <h2 style={{ margin: 0 }}>Rotation</h2>
        <div className="legend">
          <span>
            <i className="plan" /> scheduled
          </span>
          <span>
            <i className="actual" /> projected
          </span>
          <span>
            <i className="absorbed" /> absorbed
          </span>
        </div>
      </div>

      {rotation === null ? (
        <p className="skeleton">Loading the rotation…</p>
      ) : (
        <div className={loading ? 'is-stale' : undefined}>
          <CascadeTimeline rotation={rotation} event={shown} />
        </div>
      )}

      <div className="note">Cascade ends: {TERMINATION[shown.termination] ?? shown.termination}.</div>

      <details>
        <summary>Table view — every value in the chart above, as numbers</summary>
        <table>
          <thead>
            <tr>
              <th>leg</th>
              <th>route</th>
              <th className="num">sched dep utc</th>
              <th className="num">projected utc</th>
              <th className="num">delay</th>
              <th className="num">absorbed</th>
            </tr>
          </thead>
          <tbody>
            {(rotation ?? []).map((leg) => {
              const affected = byId.get(leg.flight_id);
              const isRoot = leg.flight_id === shown.root_flight_id;
              const untouched = !affected && !isRoot;
              return (
                <tr key={leg.flight_id} className={isRoot ? 'root' : undefined}>
                  <td>
                    {leg.carrier}
                    {leg.flight_number}
                  </td>
                  <td>
                    {leg.origin}–{leg.destination}
                  </td>
                  <td className="num">{hhmm(leg.sched_dep_utc)}</td>
                  <td className="num">
                    {affected ? (
                      <span className="delay">{hhmm(affected.projected_dep_utc)}</span>
                    ) : isRoot ? (
                      <span className="delay">
                        {hhmm(
                          new Date(
                            Date.parse(leg.sched_dep_utc) + shown.root_delay_minutes * 60000,
                          ).toISOString(),
                        )}
                      </span>
                    ) : (
                      <span className="faint">on time</span>
                    )}
                  </td>
                  <td className="num">
                    {affected ? (
                      <span className="delay">+{affected.propagated_delay_minutes}</span>
                    ) : isRoot ? (
                      <span className="delay">+{shown.root_delay_minutes}</span>
                    ) : (
                      <span className="faint">—</span>
                    )}
                  </td>
                  <td className="num">
                    {affected && affected.absorbed_minutes > 0 ? (
                      <span className="relief">−{affected.absorbed_minutes}</span>
                    ) : (
                      <span className="faint">{untouched ? '—' : '0'}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </details>

      {root && <RecoveryPanel root={root} baseline={event.total_propagated_minutes} />}
    </>
  );
}

/**
 * The counterfactual. Opening a scenario, delaying the root by what it actually ran late, and
 * then trying a recovery in the same sandbox is the only sequence that measures anything: a swap
 * applied to an undelayed rotation has no cascade to clear and always reports zero.
 */
function RecoveryPanel({ root, baseline }: { root: Flight; baseline: number }) {
  const [candidates, setCandidates] = useState<{ tail_number: string }[]>([]);
  const [tail, setTail] = useState('');
  const [diff, setDiff] = useState<ActionDiff | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDiff(null);
    setFailure(null);
    api
      .swapCandidates(root.flight_id)
      .then((found) => {
        setCandidates(found);
        setTail(found[0]?.tail_number ?? '');
      })
      .catch(() => setCandidates([]));
  }, [root.flight_id]);

  async function attempt(action: 'swap_aircraft' | 'cancel_flight') {
    setBusy(true);
    setFailure(null);
    setDiff(null);
    try {
      const session = await api.openScenario(root.flight_id);
      await api.runAction(session.session_id, {
        action: 'delay_flight',
        flight_id: root.flight_id,
        additional_minutes: root.dep_delay_minutes ?? 0,
        reason: 'observed',
      });
      const response = await api.runAction(session.session_id, {
        action,
        flight_id: root.flight_id,
        reason: 'recovery',
        replacement_tail: action === 'swap_aircraft' ? tail : undefined,
      });
      setDiff(response.diff);
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  const scale = Math.max(
    1,
    ...(diff?.legs ?? []).flatMap((leg) => [
      Math.abs(leg.before_delay_minutes),
      Math.abs(leg.after_delay_minutes),
    ]),
  );

  return (
    <div className="section">
      <h2>Recovery</h2>
      <p className="caption">
        Simulated in a scenario over the read-only data. Nothing is written; the base day stays
        historical fact. A rejected action returns the precondition that rejected it.
      </p>
      <div className="controls">
        <select value={tail} onChange={(event) => setTail(event.target.value)}>
          {candidates.length === 0 && <option value="">no tail is in position</option>}
          {candidates.map((candidate) => (
            <option key={candidate.tail_number} value={candidate.tail_number}>
              {candidate.tail_number}
            </option>
          ))}
        </select>
        <button className="primary" disabled={busy || !tail} onClick={() => attempt('swap_aircraft')}>
          {busy ? 'simulating…' : 'swap aircraft'}
        </button>
        <button disabled={busy} onClick={() => attempt('cancel_flight')}>
          cancel this leg
        </button>
      </div>

      {failure && <div className="error">{failure}</div>}

      {diff && (
        <>
          <div className="stats" style={{ marginTop: 14 }}>
            <div className="stat">
              <span className="k">Net effect</span>
              <span className={`v ${diff.net_minutes < 0 ? 'relief' : 'delay'}`}>
                {signed(diff.net_minutes)}
                <small>min</small>
              </span>
              <span className="sub">against a {baseline}-minute cascade</span>
            </div>
            <div className="stat">
              <span className="k">Recovered</span>
              <span className="v relief">
                {baseline > 0 && diff.net_minutes < 0
                  ? Math.round((-diff.net_minutes / baseline) * 100)
                  : 0}
                <small>%</small>
              </span>
              <span className="sub">
                {diff.legs.length} leg{diff.legs.length === 1 ? '' : 's'} changed
              </span>
            </div>
          </div>

          <div className="chart-head">
            <div className="legend">
              <span>
                <i className="actual" style={{ borderRadius: '50%', width: 8, height: 8 }} /> before
              </span>
              <span>
                <i className="absorbed" style={{ borderRadius: '50%', width: 8, height: 8 }} /> after
              </span>
            </div>
          </div>

          {diff.legs.map((leg) => (
            <div className="db-row" key={leg.flight_id}>
              <span className="db-name">{leg.description}</span>
              <span className="db-track">
                <i
                  className="db-line"
                  style={{
                    left: `${(Math.min(leg.before_delay_minutes, leg.after_delay_minutes) / scale) * 100}%`,
                    width: `${(Math.abs(leg.before_delay_minutes - leg.after_delay_minutes) / scale) * 100}%`,
                  }}
                />
                <i
                  className="db-dot before"
                  style={{ left: `${(leg.before_delay_minutes / scale) * 100}%` }}
                />
                <i
                  className="db-dot after"
                  style={{ left: `${(leg.after_delay_minutes / scale) * 100}%` }}
                />
              </span>
              <span className="db-val">
                <span className="delay">{signed(leg.before_delay_minutes)}</span>
                <span className="faint"> → </span>
                <span className="relief">{signed(leg.after_delay_minutes)}</span>
              </span>
            </div>
          ))}

          <p className="caption" style={{ marginTop: 10 }}>
            {diff.summary}
          </p>

          {diff.warnings.map((warning) => (
            <div className="note" key={warning}>
              {warning}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
