import { Link, useLocation } from "@tanstack/react-router";
import {
  ArrowLeft,
  Bot,
  BookOpen,
  Box,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FolderOpen,
  FileText,
  History,
  Monitor,
  PanelLeft,
  Plus,
  Settings,
  Ship,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { KeelLogo, KeelMark } from "@/components/KeelLogo";
import { AGENTS, agentStatus, STATUS_LABEL } from "@/lib/agents";
import { useAnalyses, useMeta, useProjects, type AnalysisSummary, type Project } from "@/lib/api";
import { DEFAULT_PROJECT, useFloors } from "@/lib/floors";

const COLLAPSED_KEY = "keel.sidebar.collapsed";

/** The sidebar drills down: everything, then one project, then that project's model. */
type Level = "main" | "project" | "model";
type View = { level: Level; projectId: string };

/** Where the page sits: a floor opens its project's model, a project page opens its project. */
function viewFor(path: string, search: unknown, analyses: AnalysisSummary[] | undefined): View {
  if (path === "/app" || path === "/app/") return { level: "model", projectId: DEFAULT_PROJECT };
  const floor = /^\/app\/analysis\/([^/]+)/.exec(path)?.[1];
  if (floor) {
    const owner = analyses?.find((a) => a.id === floor)?.project ?? DEFAULT_PROJECT;
    return { level: "model", projectId: owner };
  }
  const project = /^\/app\/projects\/([^/]+)\/./.exec(path)?.[1];
  if (project) return { level: "project", projectId: decodeURIComponent(project) };
  if (path === "/app/new") {
    const chosen = (search as { project?: unknown } | undefined)?.project;
    return { level: "project", projectId: typeof chosen === "string" ? chosen : DEFAULT_PROJECT };
  }
  return { level: "main", projectId: DEFAULT_PROJECT };
}

function readCollapsed() {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const { pathname, search } = useLocation();
  const analyses = useAnalyses();
  const projects = useProjects();
  const place = viewFor(pathname, search, analyses.data);
  const [view, setView] = useState<View>(place);
  // Follow the page when it changes, e.g. a wall view tile opening a floor.
  const placeKey = `${place.level}:${place.projectId}`;
  useEffect(() => {
    const [level, projectId] = placeKey.split(":") as [Level, string];
    setView({ level, projectId });
  }, [placeKey]);
  const setLevel = (level: Level, projectId = view.projectId) => setView({ level, projectId });
  const project = projects.data?.find((p) => p.id === view.projectId);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // A blocked storage only means the sidebar opens expanded next time.
    }
  }, [collapsed]);

  const meta = useMeta();
  const openSection = (open: (value: boolean) => void) => {
    setCollapsed(false);
    setLevel("main");
    open(true);
  };
  // The icon rail always shows the main level.
  const shown: Level = collapsed || (view.level !== "main" && !project) ? "main" : view.level;

  return (
    <aside className="sidebar" data-collapsed={collapsed}>
      <div className="sidebar-head">
        <Link to="/" className="sidebar-logo" aria-label="Keel home">
          {collapsed ? <KeelMark /> : <KeelLogo />}
        </Link>
        <button
          className="icon-btn"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed(!collapsed)}
        >
          <PanelLeft size={20} />
        </button>
      </div>

      {shown === "project" && project && (
        <nav aria-label={project.name} className="nav-level" key="project">
          <BackButton label="All projects" onClick={() => setLevel("main")} />
          <ProjectPill project={project} />
          <div className="nav-level-items">
            <button className="nav-item nav-drill" onClick={() => setLevel("model")}>
              <Box size={20} />
              <span>Model</span>
              <ChevronRight size={18} className="chevron" />
            </button>
            <Link
              to="/app/projects/$projectId/ship"
              params={{ projectId: project.id }}
              className="nav-item"
            >
              <ClipboardCheck size={20} />
              <span>Whole ship</span>
            </Link>
            <Link
              to="/app/projects/$projectId/files"
              params={{ projectId: project.id }}
              className="nav-item"
            >
              <FolderOpen size={20} />
              <span>Files</span>
            </Link>
            <Link
              to="/app/projects/$projectId/rules"
              params={{ projectId: project.id }}
              className="nav-item"
            >
              <BookOpen size={20} />
              <span>Rules</span>
            </Link>
          </div>
        </nav>
      )}

      {shown === "model" && project && (
        <nav aria-label="Model" className="nav-level" key="model">
          <BackButton label={project.name} onClick={() => setLevel("project")} />
          <div className="nav-level-title">
            <Box size={20} />
            <span>Model</span>
          </div>
          <FloorList projectId={project.id} />
        </nav>
      )}

      {shown === "main" && (
        <nav aria-label="Main" className="nav-level" key="main">
          <Section
            icon={<Ship size={20} />}
            label="Projects"
            open={projectsOpen && !collapsed}
            collapsed={collapsed}
            onToggle={() =>
              collapsed ? openSection(setProjectsOpen) : setProjectsOpen(!projectsOpen)
            }
          >
            <div className="nav-tree">
              {projects.data?.map((p) => (
                <ProjectPill
                  key={p.id}
                  project={p}
                  current={place.level !== "main" && p.id === place.projectId}
                  onOpen={() => setLevel("project", p.id)}
                />
              ))}
              <Link to="/app/projects/new" className="nav-sub nav-add">
                <Plus size={14} /> New project
              </Link>
            </div>
          </Section>
          <Section
            icon={<Bot size={20} />}
            label="Agents"
            open={agentsOpen && !collapsed}
            collapsed={collapsed}
            onToggle={() => (collapsed ? openSection(setAgentsOpen) : setAgentsOpen(!agentsOpen))}
          >
            <AgentList />
          </Section>

          <div className="nav-divider" />

          <NavItem
            to="/app/rules"
            icon={<BookOpen size={20} />}
            label="Rules"
            collapsed={collapsed}
          />
          <NavItem
            to="/app/log"
            icon={<History size={20} />}
            label="Change log"
            collapsed={collapsed}
          />
          <NavItem
            to="/app/reports"
            icon={<FileText size={20} />}
            label="Reports"
            collapsed={collapsed}
          />
          <NavItem
            to="/app/wall"
            icon={<Monitor size={20} />}
            label="Wall view"
            collapsed={collapsed}
          />
          <NavItem
            to="/app/settings"
            icon={<Settings size={20} />}
            label="Settings"
            collapsed={collapsed}
          />
        </nav>
      )}

      {!collapsed && (
        <p className="sidebar-foot">
          {meta.isError ? (
            <span className="text-fail">Backend not reachable</span>
          ) : (
            `AI: ${meta.data?.llm ?? (meta.isPending ? "…" : "none configured")}`
          )}
        </p>
      )}
    </aside>
  );
}

function Section(props: {
  icon: ReactNode;
  label: string;
  open: boolean;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div className="nav-section">
      <button
        className="nav-heading"
        aria-expanded={props.open}
        title={props.collapsed ? props.label : undefined}
        onClick={props.onToggle}
      >
        {props.icon}
        <span>{props.label}</span>
        <ChevronDown size={18} className="chevron" />
      </button>
      {props.open && props.children}
    </div>
  );
}

function NavItem(props: {
  to: "/app/rules" | "/app/log" | "/app/reports" | "/app/wall" | "/app/settings";
  icon: ReactNode;
  label: string;
  collapsed: boolean;
}) {
  return (
    <Link to={props.to} className="nav-item" title={props.collapsed ? props.label : undefined}>
      {props.icon}
      <span>{props.label}</span>
    </Link>
  );
}

function BackButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button className="nav-back" onClick={onClick} aria-label={`Back to ${label}`}>
      <ArrowLeft size={18} />
      <span>{label}</span>
    </button>
  );
}

/** Opens the project when given onOpen; otherwise it is the heading of the open project. */
function ProjectPill({
  project,
  current = true,
  onOpen,
}: {
  project: Project;
  current?: boolean;
  onOpen?: () => void;
}) {
  const { floors } = useFloors(project.id);
  const body = (
    <>
      <span>{project.name}</span>
      <span className="badge" title={`${floors.length} floors`}>
        {floors.length}
      </span>
    </>
  );
  return onOpen ? (
    <button className="project-pill" data-current={current} onClick={onOpen}>
      {body}
    </button>
  ) : (
    <div className="project-pill">{body}</div>
  );
}

function FloorList({ projectId }: { projectId: string }) {
  const { floors, isPending } = useFloors(projectId);
  return (
    <div className="nav-level-items" aria-label="Floors">
      {isPending && <p className="sidebar-foot">Loading floors…</p>}
      {!isPending && floors.length === 0 && <p className="sidebar-foot">No floors yet.</p>}
      {floors.map((f) =>
        f.analysisId ? (
          <Link
            key={f.analysisId}
            to="/app/analysis/$jobId"
            params={{ jobId: f.analysisId }}
            className="nav-floor"
            title={`${f.file}, page ${f.page + 1}`}
          >
            {f.name}
            {f.status === "running" && <small>reading…</small>}
          </Link>
        ) : (
          <Link
            key="demo"
            to="/app"
            activeOptions={{ exact: true }}
            className="nav-floor"
            title={`${f.file}, page ${f.page + 1}`}
          >
            {f.name}
          </Link>
        ),
      )}
      <Link to="/app/new" search={{ project: projectId }} className="nav-floor nav-add">
        <Plus size={14} /> Add a floor
      </Link>
    </div>
  );
}

function AgentList() {
  const meta = useMeta();
  const analyses = useAnalyses();
  return (
    <div className="nav-tree">
      {AGENTS.map((agent) => {
        const status = agentStatus(agent, meta.data?.llm ?? null, analyses.data ?? []);
        return (
          <Link
            key={agent.id}
            to="/app/agents/$agentId"
            params={{ agentId: agent.id }}
            className="nav-sub nav-agent"
          >
            {agent.name}
            <span className="dot" data-status={status} title={STATUS_LABEL[status]} />
          </Link>
        );
      })}
    </div>
  );
}
