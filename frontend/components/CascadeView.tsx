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

const TERMINATION: Record<string, string> = {
  absorbed: 'the next turn had enough scheduled ground time to absorb what was left',
  overnight_break: 'the aircraft overnights here, so the cascade stops',
  chain_break: 'the recorded rotation stops here — the next leg is not the same aircraft',
  end_of_window: 'the data window ends here, not the cascade',
  cancellation: 'the next leg was cancelled',
  guard_limit: 'the projection hit its length bound; this list is truncated',
};

/**
 * One cascade, leg by leg, with the recovery panel underneath.
 *
 * The projected column is shown against the scheduled one rather than instead of it. An operator
 * comparing a plan to a projection needs both on the same row; showing only the projection makes
 * the number unfalsifiable at a glance, which is the failure this whole project is arguing
 * against.
 */
export function CascadeView({ event }: { event: DisruptionEvent }) {
  const [rotation, setRotation] = useState<Flight[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    setRotation(null);
    setFailure(null);
    api
      .rotation(event.root_flight_id)
      .then(setRotation)
      .catch((error: ApiError) => setFailure(error.message));
  }, [event.root_flight_id]);

  const byId = new Map(event.affected.map((leg) => [leg.flight_id, leg]));
  const root = rotation?.find((leg) => leg.flight_id === event.root_flight_id);

  return (
    <>
      <div className="controls">
        <span className="tag">{event.tail_number}</span>
        <strong>{label(event.root_flight_id)}</strong>
        <span className="delay">root +{event.root_delay_minutes} min</span>
        <span className="dim">
          → {event.total_propagated_minutes} min across {event.affected.length} downstream leg
          {event.affected.length === 1 ? '' : 's'}
        </span>
      </div>
      <p className="id">{event.root_flight_id}</p>

      {failure && <div className="error">{failure}</div>}

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
            const isRoot = leg.flight_id === event.root_flight_id;
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
                          Date.parse(leg.sched_dep_utc) + event.root_delay_minutes * 60000,
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
                    <span className="delay">+{event.root_delay_minutes}</span>
                  ) : (
                    <span className="faint">—</span>
                  )}
                </td>
                <td className="num">
                  {affected && affected.absorbed_minutes > 0 ? (
                    <span className="good">−{affected.absorbed_minutes}</span>
                  ) : (
                    <span className="faint">{untouched ? '—' : '0'}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="note">
        Cascade ends: {TERMINATION[event.termination] ?? event.termination}.
      </div>

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

  return (
    <div className="section">
      <h2>Recovery</h2>
      <p className="caption">
        Simulated in a scenario over the read-only data. Nothing is written; the base day is
        historical fact.
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
        <button disabled={busy || !tail} onClick={() => attempt('swap_aircraft')}>
          swap aircraft
        </button>
        <button disabled={busy} onClick={() => attempt('cancel_flight')}>
          cancel this leg
        </button>
      </div>

      {failure && <div className="error">{failure}</div>}

      {diff && (
        <>
          <div className="controls">
            <span className={diff.net_minutes < 0 ? 'good' : 'delay'}>
              {signed(diff.net_minutes)} min
            </span>
            <span className="dim">
              against a {baseline}-minute cascade
              {baseline > 0 && diff.net_minutes < 0
                ? ` — ${Math.round((-diff.net_minutes / baseline) * 100)}% recovered`
                : ''}
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>leg</th>
                <th className="num">before</th>
                <th className="num">after</th>
              </tr>
            </thead>
            <tbody>
              {diff.legs.map((leg) => (
                <tr key={leg.flight_id}>
                  <td>{leg.description}</td>
                  <td className="num delay">{signed(leg.before_delay_minutes)}</td>
                  <td className="num good">{signed(leg.after_delay_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
