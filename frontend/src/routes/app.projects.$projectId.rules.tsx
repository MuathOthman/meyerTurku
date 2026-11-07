import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { requirement, useProjects, useRules, useSaveProjectRules, useSources } from "@/lib/api";

export const Route = createFileRoute("/app/projects/$projectId/rules")({
  head: () => ({ meta: [{ title: "Project rules · Keel" }] }),
  component: ProjectRulesPage,
});

function ProjectRulesPage() {
  const { projectId } = Route.useParams();
  const projects = useProjects();
  const project = projects.data?.find((p) => p.id === projectId);
  const rules = useRules(project?.ship_type ?? "passenger");
  const sources = useSources();
  const save = useSaveProjectRules(projectId);
  const [chosen, setChosen] = useState<Set<string> | null>(null);

  // Start from what is saved. Nothing saved yet means every rule is checked.
  const savedIds = project ? (project.rule_ids ?? rules.data?.map((r) => r.id) ?? null) : null;
  useEffect(() => {
    if (chosen === null && savedIds && rules.data) setChosen(new Set(savedIds));
  }, [chosen, savedIds, rules.data]);

  const all = rules.data ?? [];
  const picked = chosen ?? new Set<string>();
  const dirty =
    chosen !== null &&
    savedIds !== null &&
    (picked.size !== new Set(savedIds).size || savedIds.some((id) => !picked.has(id)));
  const toggle = (id: string, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    setChosen(next);
  };

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">{project?.name ?? "Project"} · Rules</span>
          <h1>Rules for this project</h1>
          <p className="muted">
            Choose the rules this {project?.ship_type ?? "…"} ship is checked against. Findings on
            rules you leave out are hidden on every floor and in reports. The rules and their
            sources are kept in <Link to="/app/rules">Rules and sources</Link>.
          </p>
        </div>
        <div className="page-actions">
          <button
            className="btn primary"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate([...picked])}
          >
            {save.isPending ? "Saving…" : dirty ? "Save selection" : "Saved"}
          </button>
        </div>
      </header>

      {(rules.isError || projects.isError || save.isError) && (
        <p className="notice notice-fail" role="alert">
          {(rules.error ?? projects.error ?? save.error)?.message}
        </p>
      )}

      <section className="card" aria-label="Project rules">
        <div className="card-head">
          <h2>
            {picked.size} of {all.length} rules checked
          </h2>
          <span className="row">
            <button className="chip" onClick={() => setChosen(new Set(all.map((r) => r.id)))}>
              Select all
            </button>
            <button className="chip" onClick={() => setChosen(new Set())}>
              Clear
            </button>
          </span>
        </div>
        {rules.isPending && <p className="pad muted">Loading rules…</p>}
        {all.map((r) => {
          const backing = sources.data?.filter((s) => s.rule_ids.includes(r.id)).length ?? 0;
          return (
            <label key={r.id} className="list-row rule-pick">
              <input
                type="checkbox"
                checked={picked.has(r.id)}
                onChange={(e) => toggle(r.id, e.target.checked)}
              />
              <div>
                <strong>{r.title}</strong>
                <small className="muted">
                  {r.id} · {r.source}
                  {backing > 0 && ` · ${backing} added ${backing === 1 ? "source" : "sources"}`}
                </small>
              </div>
              <span className="rule-value">{requirement(r)}</span>
              <span className="status" data-status={r.value_status}>
                {r.value_status}
              </span>
            </label>
          );
        })}
      </section>
    </>
  );
}
