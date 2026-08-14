'use client';

import { useEffect, useState } from 'react';
import { ApiError, AskResponse, EvalReport, api } from '@/lib/api';

/**
 * Ask a question, or read the recorded eval.
 *
 * Live answering costs money per question and this URL is public, so it is off unless the
 * deployment has an API key. When it is off the panel does not hide. It shows the ten eval
 * questions, their hand-verified answers, and whatever the scores actually are, which for now is
 * that there are none.
 *
 * Every claim in here is generated from the API's own report rather than written into the copy.
 * An earlier version of this panel hardcoded the sentence "the ten questions below were run
 * against both agents and every transcript is committed", which was false and stayed false while
 * the README two clicks away said the opposite. Prose that asserts a fact the server already
 * knows is prose that will eventually contradict it.
 *
 * Pass and fail carry a glyph as well as a colour, here and everywhere else in this interface.
 * A tick that is only distinguishable by hue is not a result, it is a decoration.
 */
export function QuestionPanel({
  liveEnabled,
  ready,
}: {
  liveEnabled: boolean;
  ready: boolean;
}) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    // Wait for the page to have reached the API at all before asking it for the eval. This used
    // to fire on mount with a single attempt, which meant that against a sleeping free-tier
    // container the request failed once, gave up, and left the panel reading "Eval unavailable"
    // long after the API had woken up and the rest of the screen had filled in.
    if (!ready) return;
    let cancelled = false;

    async function load(): Promise<void> {
      for (let attempt = 0; attempt < 5 && !cancelled; attempt += 1) {
        try {
          const body = await api.evalReport();
          if (cancelled) return;
          setReport(body);
          setReportError(null);
          return;
        } catch (error) {
          if (cancelled) return;
          if (attempt === 4) {
            setReportError(error instanceof ApiError ? error.message : String(error));
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [ready]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setFailure(null);
    setAnswer(null);
    try {
      setAnswer(await api.ask(question));
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="pane-head">
        <h2>Ask</h2>
        <p className="caption">
          Three tools over the object model: find objects, walk links, simulate an action. No SQL
          path. Answers cite flight ids so every number can be checked against the table.
        </p>
      </div>

      <form onSubmit={submit} className="controls" style={{ marginTop: 0 }}>
        <input
          style={{ flex: 1, minWidth: 170 }}
          placeholder={
            liveEnabled ? 'Why was WN4303 late on 2026-01-03?' : 'live answering is disabled'
          }
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={!liveEnabled || busy}
          aria-label="Ask a question about the data"
        />
        <button className="primary" disabled={!liveEnabled || busy}>
          {busy ? 'thinking…' : 'ask'}
        </button>
      </form>

      {!liveEnabled && (
        <div className="note">
          Live answering is off on this deployment so a public URL cannot accrue cost. The ten
          questions below, their hand-verified answers and the graders that check them are in the
          repository; the scores beside them are whatever has actually been recorded.
        </div>
      )}

      {failure && <div className="error">{failure}</div>}

      {answer && (
        <>
          <p style={{ whiteSpace: 'pre-wrap', fontSize: 12.5 }}>{answer.answer}</p>
          <details>
            <summary>
              {answer.tool_calls.length} tool call
              {answer.tool_calls.length === 1 ? '' : 's'} · ${answer.usage.cost_usd.toFixed(3)}
            </summary>
            {answer.tool_calls.map((call, index) => (
              <div key={index} className="id" style={{ marginBottom: 2 }}>
                {call.is_error ? '✗' : '·'} {call.name} {JSON.stringify(call.arguments)}
              </div>
            ))}
          </details>
        </>
      )}

      <div className="section">
        <h2>Eval</h2>
        {report ? (
          <>
            <div className="stats" style={{ marginBottom: 12 }}>
              <div className="stat">
                <span className="k">Ontology agent</span>
                <span className="v">{report.ontology_score}</span>
              </div>
              <div className="stat">
                <span className="k">SQL baseline</span>
                <span className="v">{report.sql_score}</span>
              </div>
            </div>
            <p className="caption">{report.note}</p>
            {report.questions.map((entry) => (
              <details key={entry.question_id}>
                <summary>
                  <span
                    className={`mark ${
                      entry.ontology_passed === null
                        ? 'faint'
                        : entry.ontology_passed
                          ? 'relief'
                          : 'delay'
                    }`}
                  >
                    {entry.ontology_passed === null ? '·' : entry.ontology_passed ? '✓' : '✗'}
                  </span>
                  {entry.question_id}
                </summary>
                <p className="caption" style={{ marginBottom: 6 }}>
                  {entry.question}
                </p>
                <p className="dim" style={{ fontSize: 11.5, margin: '0 0 6px' }}>
                  <span className="faint">Verified answer. </span>
                  {entry.reference}
                </p>
                {entry.ontology_failures.length > 0 && (
                  <div className="error">ontology: {entry.ontology_failures.join('; ')}</div>
                )}
                {entry.sql_failures.length > 0 && (
                  <div className="error">baseline: {entry.sql_failures.join('; ')}</div>
                )}
              </details>
            ))}
          </>
        ) : reportError ? (
          <div className="error">
            Could not load the eval from the API: {reportError} It is served from{' '}
            <code>/api/eval</code> and also committed to the repository as{' '}
            <code>docs/EVAL.md</code>.
          </div>
        ) : (
          <p className="skeleton">Loading the eval…</p>
        )}
      </div>
    </>
  );
}
