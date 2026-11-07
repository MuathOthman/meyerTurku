import { createFileRoute, Link } from "@tanstack/react-router";
import { Maximize } from "lucide-react";
import { useRef } from "react";
import { useProjects } from "@/lib/api";
import { openFindings, useFloorsWithCounts, type Floor } from "@/lib/floors";

export const Route = createFileRoute("/app/wall")({
  head: () => ({ meta: [{ title: "Wall view · Keel" }] }),
  component: WallPage,
});

function state(f: Floor) {
  if (f.status === "running") return "running";
  if (!f.counts) return "pending";
  if (f.counts.FAIL) return "FAIL";
  if (f.counts.NEEDS_REVIEW) return "NEEDS_REVIEW";
  return "PASS";
}

function Tile({ floor }: { floor: Floor }) {
  const open = openFindings(floor);
  const body = (
    <>
      <strong>{floor.name}</strong>
      <span className="wall-big">{open ?? "…"}</span>
      <small>
        {floor.status === "running"
          ? "Reading the drawing…"
          : floor.counts
            ? `${floor.counts.FAIL} fail · ${floor.counts.NEEDS_REVIEW} to review · ${floor.counts.PASS} pass`
            : "Measuring…"}
      </small>
    </>
  );
  return floor.analysisId ? (
    <Link
      to="/app/analysis/$jobId"
      params={{ jobId: floor.analysisId }}
      className="wall-tile"
      data-state={state(floor)}
    >
      {body}
    </Link>
  ) : (
    <Link to="/app" className="wall-tile" data-state={state(floor)}>
      {body}
    </Link>
  );
}

function WallPage() {
  const { floors } = useFloorsWithCounts();
  const projects = useProjects();
  const wall = useRef<HTMLDivElement>(null);
  return (
    <div className="wall" ref={wall}>
      <header className="page-head">
        <div>
          <span className="crumb">Wall view</span>
          <h1>All projects</h1>
          <p className="muted">
            Open findings per floor: fails plus checks waiting for an engineer.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => wall.current?.requestFullscreen?.()}>
            <Maximize size={16} /> Full screen
          </button>
        </div>
      </header>
      {projects.data?.map((p) => {
        const own = floors.filter((f) => f.project === p.id);
        return (
          <section key={p.id} className="stack" aria-label={p.name}>
            <h2>{p.name}</h2>
            {own.length === 0 ? (
              <p className="muted">No floors yet.</p>
            ) : (
              <div className="wall-grid">
                {own.map((f) => (
                  <Tile key={f.analysisId ?? "demo"} floor={f} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
