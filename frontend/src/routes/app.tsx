import { createFileRoute, Link, Outlet } from "@tanstack/react-router";
import { ClipboardList, History, Plus, Ship } from "lucide-react";
import { KeelLogo } from "@/components/KeelLogo";
import { useAnalyses, useMeta } from "@/lib/api";

export const Route = createFileRoute("/app")({ component: AppShell });

function AppShell() {
  const meta = useMeta();
  const analyses = useAnalyses();
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link to="/" className="sidebar-logo">
          <KeelLogo />
        </Link>
        <nav>
          <div className="nav-heading">
            <Ship size={18} />
            <span>Checked deck</span>
          </div>
          <div className="nav-group">
            {analyses.data?.map((a) => (
              <Link
                key={a.id}
                to="/app/analysis/$jobId"
                params={{ jobId: a.id }}
                className="nav-sub"
                title={`${a.source}, page ${a.page + 1}`}
              >
                {a.source} · {a.status === "running" ? "checking…" : `p${a.page + 1}`}
              </Link>
            ))}
            <Link to="/app" activeOptions={{ exact: true }} className="nav-sub">
              {meta.data?.deck ?? "RCRV demo deck"}
            </Link>
            <Link to="/app/new" className="nav-sub">
              <Plus size={13} /> Upload a drawing
            </Link>
          </div>
          <div className="nav-divider" />
          <Link to="/app/rules" className="nav-item">
            <ClipboardList size={18} />
            <span>Rules</span>
          </Link>
          <Link to="/app/log" className="nav-item">
            <History size={18} />
            <span>Change log</span>
          </Link>
        </nav>
        <p className="sidebar-foot">
          {meta.isError ? (
            <span className="text-fail">Backend not reachable</span>
          ) : (
            `AI: ${meta.data?.llm ?? (meta.isPending ? "…" : "none configured")}`
          )}
        </p>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
