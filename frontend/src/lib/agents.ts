// The stages of Keel's pipeline, named as agents. Their status comes from what the backend reports.
import type { AnalysisSummary } from "./api";

export type AgentId = "document" | "rule" | "check" | "evidence" | "change";
export type AgentStatus = "working" | "ready" | "off";

export type Agent = {
  id: AgentId;
  name: string;
  does: string;
  usesAi: "never" | "optional" | "required";
  /** Reading a drawing runs this agent, so it works while an upload is being read. */
  runsOnUpload: boolean;
};

export const AGENTS: Agent[] = [
  {
    id: "document",
    name: "Document agent",
    does: "Reads each uploaded drawing: finds the deck plans on a sheet, the scale, and the spaces, doors and stairs on each deck. With an AI key it also suggests names for spaces it cannot read.",
    usesAi: "optional",
    runsOnUpload: true,
  },
  {
    id: "rule",
    name: "Rule agent",
    does: "Picks the regulations that apply to each space from the rule database, using the ship type. It never invents a rule: every one has a source you can open.",
    usesAi: "never",
    runsOnUpload: true,
  },
  {
    id: "check",
    name: "Check agent",
    does: "Measures widths, areas and escape routes on the drawing and compares them with the rules. Plain code, no AI: every verdict shows the measured value, the required value and the tolerance.",
    usesAi: "never",
    runsOnUpload: true,
  },
  {
    id: "evidence",
    name: "Evidence agent",
    does: "Puts the evidence on each finding: the measurement, the source of the limit, why it matters and how it could be fixed, all from the rule database. It never changes a verdict.",
    usesAi: "never",
    runsOnUpload: false,
  },
  {
    id: "change",
    name: "Change agent",
    does: "Works out what a design change touches: checks that would newly fail, rules that start to apply and which disciplines to tell. Every engineer decision is kept in the change log.",
    usesAi: "never",
    runsOnUpload: false,
  },
];

export const STATUS_LABEL: Record<AgentStatus, string> = {
  working: "Working",
  ready: "Ready",
  off: "Off: no AI key on the backend",
};

export function agentStatus(
  agent: Agent,
  llm: string | null,
  analyses: AnalysisSummary[],
): AgentStatus {
  if (agent.usesAi === "required" && !llm) return "off";
  if (agent.runsOnUpload && analyses.some((a) => a.status === "running")) return "working";
  return "ready";
}
