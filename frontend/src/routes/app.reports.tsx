import { createFileRoute, Link } from "@tanstack/react-router";
import { Printer } from "lucide-react";
import { useState } from "react";
import { useDecisions, useProjects, type Verdict } from "@/lib/api";
import { useFloorsWithCounts, type Floor } from "@/lib/floors";

export const Route = createFileRoute("/app/reports")({
  head: () => ({ meta: [{ title: "Reports · Keel" }] }),
  component: ReportsPage,
});

const VERDICTS: Verdict[] = ["FAIL", "NEEDS_REVIEW", "PASS"];

function FloorName({ floor }: { floor: Floor }) {
  return floor.analysisId ? (
    <Link to="/app/analysis/$jobId" params={{ jobId: floor.analysisId }}>
      {floor.name}
    </Link>
  ) : (
    <Link to="/app">{floor.name}</Link>
  );
}

function ReportsPage() {
  const [projectId, setProjectId] = useState("");
  const projects = useProjects();
  const nameOf = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? id;
  const { floors, isPending } = useFloorsWithCounts(projectId || undefined);
  const decisions = useDecisions();
  const total = (v: Verdict) => floors.reduce((sum, f) => sum + (f.counts?.[v] ?? 0), 0);
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Reports</span>
          <h1>Compliance summary</h1>
          <p className="muted">
            {projectId ? nameOf(projectId) : "All projects"} · {floors.length} floors ·{" "}
            {decisions.data?.length ?? 0} engineer decisions · {new Date().toLocaleDateString()}.
            Keel does not certify compliance. An engineer decides.
          </p>
        </div>
        <div className="page-actions no-print">
          <label className="field-inline">
            Project
            <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">All projects</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn primary" onClick={() => window.print()}>
            <Printer size={16} /> Print or save as PDF
          </button>
        </div>
      </header>
      <section className="card">
        <table className="report-table">
          <thead>
            <tr>
              <th>Floor</th>
              {!projectId && <th>Project</th>}
              <th>Drawing</th>
              <th className="num">Fail</th>
              <th className="num">Needs review</th>
              <th className="num">Pass</th>
            </tr>
          </thead>
          <tbody>
            {floors.map((f) => (
              <tr key={f.analysisId ?? "demo"}>
                <td>
                  <FloorName floor={f} />
                </td>
                {!projectId && <td>{nameOf(f.project)}</td>}
                <td className="muted">
                  {f.file}, page {f.page + 1}
                </td>
                {VERDICTS.map((v) => (
                  <td key={v} className="num" data-verdict={f.counts?.[v] ? v : undefined}>
                    {f.counts ? f.counts[v] : f.status === "running" ? "reading…" : "…"}
                  </td>
                ))}
              </tr>
            ))}
            {isPending && (
              <tr>
                <td colSpan={projectId ? 5 : 6} className="muted">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={projectId ? 2 : 3}>All floors</th>
              {VERDICTS.map((v) => (
                <th key={v} className="num">
                  {total(v)}
                </th>
              ))}
            </tr>
          </tfoot>
        </table>
      </section>
    </>
  );
}
