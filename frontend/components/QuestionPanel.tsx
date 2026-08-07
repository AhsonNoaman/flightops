'use client';

import { useEffect, useState } from 'react';
import { ApiError, AskResponse, EvalReport, api } from '@/lib/api';

/**
 * Ask a question, or read the recorded eval.
 *
 * Live answering costs money per question and this URL is public, so it is off unless the
 * deployment has an API key. When it is off the panel does not hide -- it shows the ten eval
 * questions, their hand-verified answers and the recorded scores, which is a more honest
 * demonstration than a live box would be anyway: fixed questions with published transcripts
 * cannot be cherry-picked after the fact.
 *
 * Pass and fail carry a glyph as well as a colour, here and everywhere else in this interface.
 * A tick that is only distinguishable by hue is not a result, it is a decoration.
 */
export function QuestionPanel({ liveEnabled }: { liveEnabled: boolean }) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<EvalReport | null>(null);

  useEffect(() => {
    api
      .evalReport()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

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
          questions below were run against both agents and every transcript is committed.
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
        ) : (
          <p className="caption">Eval unavailable.</p>
        )}
      </div>
    </>
  );
}
