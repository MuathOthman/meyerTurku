import { createFileRoute, Link } from "@tanstack/react-router";
import { useProjects, useShipOverview, type ShipItem } from "@/lib/api";

export const Route = createFileRoute("/app/projects/$projectId/ship")({
  head: () => ({ meta: [{ title: "Whole ship · Keel" }] }),
  component: ShipPage,
});

/** Plain words for each status, in the order an engineer works through them. */
const STATUS: Record<ShipItem["status"], { label: string; tone: string; hint: string }> = {
  not_shown: { label: "Not found", tone: "review", hint: "Find it on another drawing, or add it" },
  value: { label: "Value to meet", tone: "info", hint: "Worked out from the main dimensions" },
  shown: { label: "Shown", tone: "pass", hint: "On the drawing; confirm the details" },
  by_hand: { label: "Check by hand", tone: "muted", hint: "A plan cannot show this" },
  not_applicable: { label: "Not for this ship", tone: "muted", hint: "Does not apply to this ship type" },
};
const ORDER = Object.keys(STATUS) as ShipItem["status"][];

function ShipPage() {
  const { projectId } = Route.useParams();
  const project = useProjects().data?.find((p) => p.id === projectId);
  const overview = useShipOverview(projectId);
  const data = overview.data;
  const p = data?.particulars;

  // One card per regulation, keeping the order the backend gives.
  const groups = new Map<string, ShipItem[]>();
  for (const item of data?.items ?? []) {
    groups.set(item.regulation, [...(groups.get(item.regulation) ?? []), item]);
  }
  const dims = [
    p?.length_overall_m != null && `${p.length_overall_m} m long overall`,
    p?.length_pp_m != null && `${p.length_pp_m} m between perpendiculars`,
    p?.breadth_m != null && `${p.breadth_m} m breadth`,
    data && `checked as a ${data.ship_type} ship`,
  ].filter(Boolean);

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">{project?.name ?? "Project"} · Whole ship</span>
          <h1>{p?.title || "Whole ship"}</h1>
          <p className="muted">
            What one deck cannot tell: values this ship must meet, and whether the spaces each
            regulation needs are shown on any of its {data?.decks.length ?? "…"} decks. Nothing
            here passes or fails the ship. An engineer decides.
          </p>
          {dims.length > 0 && <p className="ship-dims">{dims.join(" · ")}</p>}
        </div>
      </header>

      {overview.isError && (
        <p className="notice notice-fail" role="alert">
          {overview.error.message}
        </p>
      )}
      {overview.isPending && <p className="muted">Reading the ship…</p>}

      {data && (
        <div className="ship-summary" aria-label="Summary">
          {ORDER.map((status) => {
            const count = data.items.filter((i) => i.status === status).length;
            if (count === 0) return null;
            return (
              <div key={status} className="ship-count" data-tone={STATUS[status].tone}>
                <strong>{count}</strong>
                <span>{STATUS[status].label}</span>
                <small>{STATUS[status].hint}</small>
              </div>
            );
          })}
        </div>
      )}

      {[...groups].map(([regulation, items]) => (
        <section key={regulation} className="card ship-group" aria-label={regulation}>
          <div className="card-head">
            <h2>{regulation}</h2>
            <span className="muted">{items.length} {items.length === 1 ? "item" : "items"}</span>
          </div>
          {[...items]
            .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
            .map((item) => (
              <div key={item.ref + item.title} className="ship-row">
                <span className="ship-badge" data-tone={STATUS[item.status].tone}>
                  {STATUS[item.status].label}
                </span>
                <div>
                  <strong>{item.title}</strong>
                  <small className="muted"> · {item.ref}</small>
                  <p>{item.detail}</p>
                  {item.where.length > 0 && (
                    <p className="ship-where">
                      {item.where.map((w) => (
                        <Link
                          key={`${w.analysis}-${w.number}`}
                          to="/app/analysis/$jobId"
                          params={{ jobId: w.analysis }}
                          className="chip"
                        >
                          {w.space} · {w.deck.split(" · ")[0]}
                        </Link>
                      ))}
                    </p>
                  )}
                </div>
              </div>
            ))}
        </section>
      ))}
    </>
  );
}
