import { useState, type FormEvent } from "react";
import { VerdictTag } from "@/components/FindingDetail";
import { useEval, useImpact } from "@/lib/api";

export function AccuracyPanel() {
  const report = useEval(true);
  if (report.isPending)
    return (
      <p className="card pad" role="status">
        Running every test case…
      </p>
    );
  if (report.isError)
    return (
      <p className="notice notice-fail" role="alert">
        {report.error.message}
      </p>
    );
  const e = report.data;
  return (
    <section className="card pad stack">
      <h2>Accuracy report</h2>
      <div className="measures">
        <div>
          <small>Injected defects found</small>
          <b>
            {e.defects_found} of {e.defects_total}
          </b>
        </div>
        <div>
          <small>False alarms</small>
          <b>
            {e.false_alarms} ({e.controls_total} controls)
          </b>
        </div>
        <div>
          <small>Original drawing</small>
          <b>
            {e.baseline.FAIL} fail, {e.baseline.NEEDS_REVIEW} review, {e.baseline.PASS} pass
          </b>
        </div>
      </div>
      <p className="muted">
        We wrote these defects and controls ourselves and injected them into the ship model. They
        test the checks and the verdict policy, not whether doors and rooms were extracted
        correctly.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Result</th>
              <th>Kind</th>
              <th>Case</th>
              <th>Detail</th>
              <th>Measured</th>
            </tr>
          </thead>
          <tbody>
            {e.cases.map((c) => (
              <tr key={c.name}>
                <td className={c.passed ? "text-pass" : "text-fail"}>{c.passed ? "OK" : "MISS"}</td>
                <td>{c.kind}</td>
                <td>{c.name}</td>
                <td>{c.detail}</td>
                <td>{c.measured_mm === null ? "" : `${c.measured_mm.toFixed(0)} mm`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ImpactPanel() {
  const [count, setCount] = useState(6);
  const [berths, setBerths] = useState(2);
  const [params, setParams] = useState<{ count: number; berths: number } | null>(null);
  const impact = useImpact(params);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams({ count, berths });
  };
  const r = impact.data;
  return (
    <section className="card pad stack">
      <h2>What changes if cabins are added</h2>
      <form className="row form-row" onSubmit={submit}>
        <label>
          Cabins to add
          <input
            type="number"
            min={1}
            max={200}
            required
            value={count}
            onChange={(e) => setCount(e.target.valueAsNumber)}
          />
        </label>
        <label>
          Berths in each
          <input
            type="number"
            min={1}
            max={6}
            required
            value={berths}
            onChange={(e) => setBerths(e.target.valueAsNumber)}
          />
        </label>
        <button className="btn primary" disabled={impact.isFetching}>
          {impact.isFetching ? "Checking…" : "Show impact"}
        </button>
      </form>
      {impact.isError && (
        <p className="notice notice-fail" role="alert">
          {impact.error.message}
        </p>
      )}
      {r && (
        <>
          <p>
            <strong>{r.persons_added} more persons</strong>, {r.persons_total} in total.{" "}
            {r.newly_failing.length === 0 && <VerdictTag verdict="PASS" label="No new FAIL" />}
          </p>
          {r.newly_failing.map((f) => (
            <p key={`${f.rule_id}:${f.subject_id}`}>
              <VerdictTag verdict="FAIL" label={`New FAIL: ${f.rule_id}`} /> {f.why}
            </p>
          ))}
          {r.stair_capacity && r.stair_capacity.verdict !== "FAIL" && <p>{r.stair_capacity.why}</p>}
          <div className="two-col">
            <div>
              <span className="eyebrow">Rules that now matter</span>
              <ul>
                {r.rules_that_apply.map((x) => (
                  <li key={x.ref}>
                    <strong>{x.ref}</strong>: {x.why}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <span className="eyebrow">Notify</span>
              <ul>
                {r.notify.map((x) => (
                  <li key={x.discipline}>
                    <strong>{x.discipline}</strong>: {x.why}
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <p className="muted">
            These are reminders. Nothing is calculated for these systems, because Keel has no system
            data.
          </p>
        </>
      )}
    </section>
  );
}
