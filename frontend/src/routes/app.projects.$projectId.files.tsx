import { createFileRoute, Link } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import { useFloors, useProject, type Floor } from "@/lib/floors";

export const Route = createFileRoute("/app/projects/$projectId/files")({
  head: () => ({ meta: [{ title: "Files · Keel" }] }),
  component: FilesPage,
});

function FilesPage() {
  const { projectId } = Route.useParams();
  const project = useProject(projectId);
  const { floors, isPending } = useFloors(projectId);
  const files = new Map<string, Floor[]>();
  for (const floor of floors) {
    const key = `${floor.file}\u0000${floor.page}`;
    files.set(key, [...(files.get(key) ?? []), floor]);
  }
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">{project?.name ?? "Project"} · Files</span>
          <h1>Files</h1>
          <p className="muted">
            The drawings this project was read from. A sheet with several deck plans becomes one
            floor per deck.
          </p>
        </div>
        <div className="page-actions">
          <Link to="/app/new" search={{ project: projectId }} className="btn primary">
            Upload a drawing
          </Link>
        </div>
      </header>
      <section className="card">
        {isPending && <p className="pad muted">Loading…</p>}
        {!isPending && floors.length === 0 && (
          <p className="pad muted">No drawings yet. Upload a general arrangement to add floors.</p>
        )}
        {[...files.values()].map((group) => {
          const first = group[0];
          if (!first) return null;
          return (
            <div key={`${first.file}-${first.page}`} className="list-row">
              <FileText size={20} className="muted" />
              <div>
                <strong>{first.file}</strong>
                <small className="muted">
                  Page {first.page + 1}
                  {first.createdAt && ` · added ${new Date(first.createdAt).toLocaleDateString()}`}
                  {" · "}
                  {group.length} {group.length === 1 ? "floor" : "floors"}
                </small>
                <span className="file-floors">
                  {group.map((f) =>
                    f.analysisId ? (
                      <Link
                        key={f.analysisId}
                        to="/app/analysis/$jobId"
                        params={{ jobId: f.analysisId }}
                        className="chip"
                      >
                        {f.name}
                        {f.status === "running" && " · reading…"}
                      </Link>
                    ) : (
                      <Link key="demo" to="/app" className="chip">
                        {f.name}
                      </Link>
                    ),
                  )}
                </span>
              </div>
            </div>
          );
        })}
      </section>
    </>
  );
}
