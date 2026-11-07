import { createFileRoute } from "@tanstack/react-router";
import { DECISION_LABEL, useDecisions } from "@/lib/api";

export const Route = createFileRoute("/app/log")({
  head: () => ({ meta: [{ title: "Change log · Keel" }] }),
  component: LogPage,
});

function LogPage() {
  const log = useDecisions();
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Change log</span>
          <h1>Change log</h1>
          <p className="muted">Every decision engineers recorded on a finding, newest first.</p>
        </div>
      </header>
      {log.isError && (
        <p className="notice notice-fail" role="alert">
          {log.error.message}
        </p>
      )}
      <section className="card">
        {log.isPending && <p className="pad muted">Loading…</p>}
        {log.data?.length === 0 && <p className="pad muted">No decisions recorded yet.</p>}
        {log.data
          ?.slice()
          .reverse()
          .map((d) => (
            <div key={d.at + d.finding} className="list-row">
              <div>
                <strong>{d.subject}</strong>
                <small className="muted">
                  {d.rule_id} · {new Date(d.at).toLocaleString()}
                </small>
                {d.note && <small>“{d.note}”</small>}
              </div>
              <span className="status">{DECISION_LABEL[d.decision]}</span>
            </div>
          ))}
      </section>
    </>
  );
}
