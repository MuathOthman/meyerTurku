import { createFileRoute, Link } from "@tanstack/react-router";
import { AGENTS, agentStatus, STATUS_LABEL, type AgentId } from "@/lib/agents";
import { useAnalyses, useDecisions, useMeta, useRules } from "@/lib/api";
import { useFloors } from "@/lib/floors";

export const Route = createFileRoute("/app/agents/$agentId")({
  head: () => ({ meta: [{ title: "Agents · Keel" }] }),
  component: AgentPage,
});

function AgentPage() {
  const { agentId } = Route.useParams();
  const meta = useMeta();
  const analyses = useAnalyses();
  const agent = AGENTS.find((a) => a.id === agentId);
  if (!agent)
    return (
      <p className="notice notice-fail" role="alert">
        There is no agent called “{agentId}”.
      </p>
    );
  const status = agentStatus(agent, meta.data?.llm ?? null, analyses.data ?? []);
  const ai = {
    never: "Never uses AI.",
    optional: meta.data?.llm ? `Uses ${meta.data.llm} when it helps.` : "Works without AI.",
    required: meta.data?.llm ? `Uses ${meta.data.llm}.` : "Needs an AI key on the backend.",
  }[agent.usesAi];
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Agents</span>
          <h1>{agent.name}</h1>
          <p className="agent-status">
            <span className="dot" data-status={status} /> {STATUS_LABEL[status]}
          </p>
        </div>
      </header>
      <section className="card pad stack">
        <p>{agent.does}</p>
        <p className="muted">{ai}</p>
      </section>
      <section className="card pad stack" aria-label="What it has done">
        <h2>What it has done</h2>
        <AgentWork id={agent.id} />
      </section>
    </>
  );
}

function AgentWork({ id }: { id: AgentId }) {
  const { floors } = useFloors();
  const analyses = useAnalyses();
  const rules = useRules();
  const decisions = useDecisions();
  const meta = useMeta();
  const done = analyses.data?.filter((a) => a.status === "done") ?? [];
  const sum = (pick: (a: (typeof done)[number]) => number) =>
    done.reduce((total, a) => total + pick(a), 0);
  switch (id) {
    case "document":
      return (
        <p>
          Read {floors.length} floors from {new Set(floors.map((f) => f.file)).size} files and found{" "}
          {sum((a) => a.identified + a.unidentified)} spaces on the uploads,{" "}
          {sum((a) => a.unidentified)} of them still without a name.{" "}
          <Link to="/app/reports">See every floor</Link>
        </p>
      );
    case "rule":
      return (
        <p>
          Chooses from {rules.data?.length ?? "…"} rules in the database, limited to the rules each
          project selects. <Link to="/app/rules">Open rules and sources</Link>
        </p>
      );
    case "check":
      return (
        <p>
          {sum((a) => (a.counts ? a.counts.FAIL + a.counts.NEEDS_REVIEW + a.counts.PASS : 0))}{" "}
          measured checks on the uploaded floors, plus {meta.data?.spaces ?? "…"} spaces and{" "}
          {meta.data?.doors ?? "…"} doors on the demo deck.{" "}
          <Link to="/app/reports">See the report</Link>
        </p>
      );
    case "evidence":
      return (
        <p>
          Writes notes on request: open a floor and choose “Add AI notes”.{" "}
          <Link to="/app">Open the demo deck</Link>
        </p>
      );
    case "change":
      return (
        <p>
          {decisions.data?.length ?? "…"} decisions in the change log.{" "}
          <Link to="/app/log">Open the change log</Link>
        </p>
      );
  }
}
