import { createFileRoute } from "@tanstack/react-router";
import { symbol, useRules, type Rule } from "@/lib/api";

export const Route = createFileRoute("/app/rules")({
  head: () => ({ meta: [{ title: "Rules · Keel" }] }),
  component: RulesPage,
});

function requirement(r: Rule): string {
  if (r.value_mm !== null) {
    const width = `${symbol(r.operator ?? "")} ${r.value_mm} mm`;
    return r.minimum_area_m2 === null ? width : `${width} and ≥ ${r.minimum_area_m2} m²`;
  }
  if (r.value_mm_per_person !== null) return `${r.value_mm_per_person} mm per person`;
  if (r.minimum_routes !== null) return `At least ${r.minimum_routes} routes`;
  return "Geometry check";
}

function RulesPage() {
  const rules = useRules();
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Rules</span>
          <h1>Rule database</h1>
          <p className="muted">
            Summaries in our own words, loaded from backend/rules. Read the source for the binding
            text. The DNV values are from the July 2015 edition, the newest readable without a
            login.
          </p>
        </div>
      </header>
      {rules.isPending && <p role="status">Loading rules…</p>}
      {rules.isError && (
        <p className="notice notice-fail" role="alert">
          {rules.error.message}
        </p>
      )}
      <section className="card">
        {rules.data?.map((r) => (
          <div key={r.id} className="list-row">
            <div>
              <strong>{r.title}</strong>
              <small className="muted">
                {r.id} ·{" "}
                {r.ref_url ? (
                  <a href={r.ref_url} target="_blank" rel="noreferrer">
                    {r.source}
                  </a>
                ) : (
                  r.source
                )}
              </small>
              {r.interpretation_note && <small className="muted">{r.interpretation_note}</small>}
            </div>
            <span className="rule-value">{requirement(r)}</span>
            <span className="status" data-status={r.value_status}>
              {r.value_status}
            </span>
          </div>
        ))}
      </section>
    </>
  );
}
