/**
 * The typed client for the flightops API.
 *
 * The types are written by hand against the FastAPI response models rather than generated from
 * the OpenAPI schema. Generation would be better in a codebase with a dozen endpoints; with
 * eight it buys a build step and a second source of truth, and the shapes below are short enough
 * to read next to the handlers they mirror.
 */

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');

export interface CauseBuckets {
  carrier: number;
  weather: number;
  nas: number;
  security: number;
  late_aircraft: number;
}

export interface Flight {
  flight_id: string;
  flight_date: string;
  carrier: string;
  flight_number: string;
  origin: string;
  destination: string;
  tail_number: string | null;
  status: string;
  cancellation_code: string | null;
  sched_dep_local: string;
  sched_arr_local: string;
  sched_dep_utc: string;
  sched_arr_utc: string;
  dep_delay_minutes: number | null;
  arr_delay_minutes: number | null;
  sched_block_minutes: number;
  distance_miles: number | null;
  causes: CauseBuckets | null;
}

export interface AffectedLeg {
  flight_id: string;
  position: number;
  projected_dep_utc: string;
  projected_arr_utc: string;
  propagated_delay_minutes: number;
  absorbed_minutes: number;
}

export interface DisruptionEvent {
  event_id: string;
  root_flight_id: string;
  tail_number: string;
  cause: string;
  root_delay_minutes: number;
  affected: AffectedLeg[];
  total_propagated_minutes: number;
  termination: string;
}

export interface Airport {
  iata: string;
  city: string;
  iana_timezone: string;
}

export interface FlightDetail {
  flight: Flight;
  aircraft: { tail_number: string; carrier: string } | null;
  origin_airport: Airport;
  destination_airport: Airport;
  operating_carrier: { code: string; name: string };
  previous_leg: Flight | null;
  next_leg: Flight | null;
  ground_minutes_after: number | null;
  chain_break_reason: string | null;
}

export interface Health {
  status: string;
  flight_count: number;
  first_date: string;
  last_date: string;
  carriers: string[];
  live_answers: boolean;
  active_sessions: number;
}

export interface LegDelta {
  flight_id: string;
  description: string;
  before_delay_minutes: number;
  after_delay_minutes: number;
}

export interface ActionDiff {
  action: string;
  target_flight_id: string;
  summary: string;
  legs: LegDelta[];
  net_minutes: number;
  warnings: string[];
}

export interface ScenarioState {
  session_id: string;
  clock_utc: string;
  description: string;
  actions_applied: number;
  changes: string[];
}

export interface ActionResponse {
  diff: ActionDiff;
  scenario: ScenarioState;
  available_tails: { tail_number: string; arrives_utc: string }[];
}

export interface EvalQuestion {
  question_id: string;
  question: string;
  reference: string;
  tests: string;
  ontology_passed: boolean | null;
  sql_passed: boolean | null;
  ontology_failures: string[];
  sql_failures: string[];
}

export interface EvalReport {
  recorded: boolean;
  ontology_score: string;
  sql_score: string;
  questions: EvalQuestion[];
  note: string;
}

export interface AskResponse {
  answer: string;
  error: string | null;
  tool_calls: { name: string; arguments: Record<string, unknown>; is_error: boolean }[];
  usage: { input_tokens: number; output_tokens: number; cost_usd: number };
}

/**
 * A failed request carrying the API's own message.
 *
 * The domain layer writes rejections for a human to act on, like "N8528Q lands at PHX at 14:05
 * UTC and needs 38 min to turn", and the whole point of surfacing them is lost if the UI replaces
 * that with "Request failed". The status is kept so 503 (feature switched off) can be rendered
 * differently from 409 (the world said no).
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `Cannot reach the API at ${BASE}. Is it running?`);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* a non-JSON error body is not worth a second failure mode */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  base: BASE,
  health: () => request<Health>('/api/health'),
  disruptions: (date: string, limit = 12) =>
    request<DisruptionEvent[]>(`/api/disruptions?date=${date}&limit=${limit}`),
  flight: (id: string) => request<FlightDetail>(`/api/flights/${encodeURIComponent(id)}`),
  rotation: (id: string) => request<Flight[]>(`/api/flights/${encodeURIComponent(id)}/rotation`),
  cascade: (id: string, minutes?: number) =>
    request<DisruptionEvent>(
      `/api/flights/${encodeURIComponent(id)}/cascade` +
        (minutes === undefined ? '' : `?minutes=${minutes}`),
    ),
  swapCandidates: (id: string) =>
    request<{ tail_number: string; arrives_utc: string }[]>(
      `/api/flights/${encodeURIComponent(id)}/swap-candidates`,
    ),
  openScenario: (flightId: string) =>
    request<ScenarioState>('/api/scenarios', {
      method: 'POST',
      body: JSON.stringify({ flight_id: flightId }),
    }),
  runAction: (sessionId: string, body: Record<string, unknown>) =>
    request<ActionResponse>(`/api/scenarios/${sessionId}/actions`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  ask: (question: string) =>
    request<AskResponse>('/api/ask', { method: 'POST', body: JSON.stringify({ question }) }),
  evalReport: () => request<EvalReport>('/api/eval'),
};

/** `2026-01-03|WN|3851|PHX|SFO|0855` is a primary key; `WN3851 PHX-SFO 08:55` is a label. */
export function label(flightId: string): string {
  const parts = flightId.split('|');
  if (parts.length !== 6) return flightId;
  const [, carrier, number, origin, destination, hhmm] = parts;
  return `${carrier}${number} ${origin}-${destination} ${hhmm.slice(0, 2)}:${hhmm.slice(2)}`;
}

export function signed(minutes: number): string {
  // U+2212, not a hyphen: in a column of tabular figures a hyphen is visibly too short and sits
  // at the wrong height, which is exactly where it is most obvious.
  return minutes > 0 ? `+${minutes}` : minutes < 0 ? `−${Math.abs(minutes)}` : '0';
}

export function hhmm(iso: string): string {
  return iso.slice(11, 16);
}
