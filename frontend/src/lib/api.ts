// Every call to the Keel backend. Types mirror backend/api/main.py.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type Verdict = "PASS" | "FAIL" | "NEEDS_REVIEW";
type Point = [number, number];

export type Meta = {
  deck: string;
  source_pdf: string;
  page_index: number;
  mm_per_pt: number;
  calibration: string;
  tolerance_mm: number;
  spaces: number;
  doors: number;
  unresolved_arcs: number;
  region: [number, number, number, number];
  scenarios: string[];
  llm: string | null;
};

export type Finding = {
  rule_id: string;
  rule_title: string;
  source: string;
  ref_url: string;
  value_status: "verified" | "assumed";
  verdict: Verdict;
  subject_id: string;
  subject_name: string;
  source_pdf: string;
  page_index: number;
  location_pt: Point;
  measured_mm: number | null;
  measured_display: string;
  required_mm: number | null;
  required_display: string;
  operator: string;
  tolerance_mm: number | null;
  margin_mm: number | null;
  why: string;
  interpretation_note: string;
  assumptions: string[];
  overlay_lines_pt: Point[][];
  overlay_polygon_pt: Point[];
  explanation: string | null;
  /** What the AI saw where Keel could not measure. Evidence for the engineer, never a verdict. */
  ai_look?: AiLook | null;
  why_it_matters: string;
  fix: string;
  pin?: string;
  could_not_check?: boolean;
};

export type Findings = {
  counts: Record<Verdict, number>;
  injected: string[];
  note_error: string | null;
  findings: Finding[];
};

export type Space = {
  id: string;
  name: string;
  category: string;
  area_m2: number;
  outline_pt: Point[];
};

export type EvalCase = {
  name: string;
  kind: "defect" | "control";
  passed: boolean;
  detail: string;
  measured_mm: number | null;
};

export type EvalReport = {
  baseline: Record<Verdict, number>;
  defects_total: number;
  defects_found: number;
  controls_total: number;
  false_alarms: number;
  cases: EvalCase[];
};

export type Impact = {
  count: number;
  persons_added: number;
  persons_total: number;
  stair_capacity: Finding | null;
  newly_failing: Finding[];
  rules_that_apply: { ref: string; why: string }[];
  notify: { discipline: string; why: string }[];
};

export type Rule = {
  id: string;
  title: string;
  source: string;
  ref_url: string;
  type: string;
  scope: string;
  applies_to: string[];
  operator: string | null;
  value_mm: number | null;
  value_mm_per_person: number | null;
  minimum_routes: number | null;
  minimum_area_m2: number | null;
  value_status: "verified" | "assumed";
  interpretation_note: string;
};

export type ChecklistItem = {
  ref: string;
  what: string;
  reference_confirmed: boolean;
  status: string;
  verdict: Verdict | null;
  measured: string | null;
};

export type AnalysedSpace = {
  number: number;
  name: string;
  compartment: string | null;
  category: string;
  confidence: number;
  evidence: string;
  name_on_drawing: boolean;
  area_m2: number | null;
  reviewed?: boolean;
  outline_px?: [number, number][][];
  checklist: ChecklistItem[];
};

export type Analysis = {
  id: string;
  source: string;
  page: number;
  route: string;
  scale_note: string;
  llm: string | null;
  naming_error: string | null;
  image: string;
  plan_image?: string;
  plan_size?: [number, number];
  plan_scale?: number;
  plan_origin?: [number, number];
  mm_per_unit?: number | null;
  ship_type?: string;
  deck?: string | null;
  project?: string;
  doors_found?: number;
  stairs_found?: number;
  findings?: Finding[];
  created_at: string;
  spaces: AnalysedSpace[];
  set_aside: { number: number; description: string; reason: string }[];
};

export type AnalysisSummary = Pick<Analysis, "id" | "source" | "page" | "created_at"> & {
  deck: string | null;
  project: string;
  status: "running" | "done";
  ship_type: string | null;
  identified: number;
  unidentified: number;
  /** Measured findings by verdict. Null while the drawing is still being read. */
  counts: Record<Verdict, number> | null;
};

export type AnalysisStatus = {
  id: string;
  status: "running" | "done" | "failed";
  step?: string;
  detail?: string;
  completed?: string[];
  error?: string | null;
  source?: string;
  deck?: string | null;
  project?: string;
  created_at?: string;
};

export type Regulation = {
  ref: string;
  confirmed: boolean;
  whats: string[];
  spaces: AnalysedSpace[];
  measured: number;
};

/** The checklist's stand-in for a space with no name yet. It is not a regulation. */
export const NO_REGULATIONS_YET = "None until identified";

export const needsNameFirst = (space: AnalysedSpace) =>
  space.checklist.some((item) => item.ref === NO_REGULATIONS_YET);

/** One entry per regulation across the whole drawing, with the spaces it applies to. */
export function regulationsOf(spaces: AnalysedSpace[]): Regulation[] {
  const byRef = new Map<string, Regulation>();
  for (const space of spaces) {
    for (const item of space.checklist) {
      if (item.ref === NO_REGULATIONS_YET) continue;
      let entry = byRef.get(item.ref);
      if (!entry) {
        entry = { ref: item.ref, confirmed: true, whats: [], spaces: [], measured: 0 };
        byRef.set(item.ref, entry);
      }
      entry.confirmed &&= item.reference_confirmed;
      if (!entry.whats.includes(item.what)) entry.whats.push(item.what);
      if (!entry.spaces.includes(space)) entry.spaces.push(space);
      if (item.verdict) entry.measured += 1;
    }
  }
  return [...byRef.values()].sort((a, b) => a.ref.localeCompare(b.ref));
}

/**
 * What Keel could not measure: each regulation once, with only the spaces it still has to be
 * checked on by hand. A regulation measured on every space it applies to is left out.
 */
export function manualChecksOf(spaces: AnalysedSpace[]): Regulation[] {
  const unmeasured = spaces.map((space) => ({
    ...space,
    checklist: space.checklist.filter((item) => !item.verdict),
  }));
  return regulationsOf(unmeasured).map((r) => ({
    ...r,
    spaces: r.spaces.map((s) => spaces.find((o) => o.number === s.number) ?? s),
  }));
}

/** The change-log key for a regulation checked by hand on one floor. */
export const manualCheckKey = (floorId: string, ref: string) => `${floorId}:manual:${ref}`;

export type DecisionKind =
  "accepted" | "need_info" | "rejected" | "cleared" | "renamed" | "complies" | "does_not_comply";

export type Decision = {
  finding: string;
  rule_id: string;
  subject: string;
  decision: DecisionKind;
  note: string;
  at: string;
};

export const DECISION_LABEL: Record<DecisionKind, string> = {
  accepted: "Finding accepted",
  need_info: "More information requested",
  rejected: "Finding rejected",
  cleared: "Decision undone",
  renamed: "Space renamed",
  complies: "Checked by hand: complies",
  does_not_comply: "Checked by hand: does not comply",
};

export const symbol = (operator: string) =>
  operator === ">=" ? "≥" : operator === "<=" ? "≤" : operator;

export const UNIDENTIFIED = "Unidentified space";

export const findingKey = (f: Pick<Finding, "rule_id" | "subject_id">) =>
  `${f.rule_id}:${f.subject_id}`;

/** The decision standing on each finding. An undo ("cleared") leaves none. */
export function currentDecisions(log: Decision[]): Map<string, Decision> {
  const current = new Map<string, Decision>();
  for (const entry of log) {
    if (entry.decision === "cleared") current.delete(entry.finding);
    else current.set(entry.finding, entry);
  }
  return current;
}

/** Reads the backend's `detail` message. Vite answers 5xx when the backend is down. */
export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("Cannot reach the Keel backend.");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    body = undefined;
  }
  if (response.ok && body !== undefined) return body as T;
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") throw new Error(detail);
  throw new Error(
    response.status >= 500
      ? `The Keel backend failed or is not running (HTTP ${response.status}).`
      : `Request failed (HTTP ${response.status}).`,
  );
}

export const useMeta = () =>
  useQuery({ queryKey: ["meta"], queryFn: () => request<Meta>("/api/meta") });

export const useSpaces = () =>
  useQuery({ queryKey: ["spaces"], queryFn: () => request<Space[]>("/api/spaces") });

export function useFindings(scenario: string) {
  const query = new URLSearchParams();
  if (scenario) query.set("scenario", scenario);
  return useQuery({
    queryKey: ["findings", scenario],
    queryFn: () => request<Findings>(`/api/findings?${query}`),
    placeholderData: (previous) => previous,
  });
}

export const useEval = (enabled: boolean) =>
  useQuery({
    queryKey: ["eval"],
    enabled,
    staleTime: Infinity,
    queryFn: () => request<EvalReport>("/api/eval"),
  });

export const useImpact = (params: { count: number; berths: number } | null) =>
  useQuery({
    queryKey: ["impact", params],
    enabled: params !== null,
    queryFn: () =>
      request<Impact>(`/api/impact?count=${params!.count}&berths_each=${params!.berths}`),
  });

/** The whole rule database, or only the rules for one ship type with that type's values. */
export const useRules = (shipType?: string) =>
  useQuery({
    queryKey: ["rules", shipType ?? null],
    queryFn: () => request<Rule[]>(shipType ? `/api/rules/${shipType}` : "/api/rules"),
  });

export const useAnalyses = () =>
  useQuery({
    queryKey: ["analyses"],
    queryFn: () => request<AnalysisSummary[]>("/api/analyses"),
    refetchInterval: (query) =>
      query.state.data?.some((a) => a.status === "running") ? 2000 : false,
  });

export const useAnalysisStatus = (id: string) =>
  useQuery({
    queryKey: ["analysis-status", id],
    queryFn: () => request<AnalysisStatus>(`/api/analyze/${id}/status`),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1000 : false),
  });

export const useAnalysis = (id: string, enabled: boolean) =>
  useQuery({
    queryKey: ["analysis", id],
    enabled,
    queryFn: () => request<Analysis>(`/api/analyze/${id}`),
  });

export function useAnalyse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) =>
      request<AnalysisStatus>("/api/analyze", { method: "POST", body: form }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["analyses"] }),
  });
}

export const useSpaceTypes = () =>
  useQuery({
    queryKey: ["space-types"],
    staleTime: Infinity,
    queryFn: () => request<string[]>("/api/space-types"),
  });

export function useCorrectSpace(jobId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      number,
      ...correction
    }: {
      number: number;
      name: string;
      category: string | null;
    }) =>
      request<Analysis>(`/api/analyze/${jobId}/spaces/${number}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(correction),
      }),
    onSuccess: (updated) => {
      client.setQueryData(["analysis", jobId], updated);
      client.invalidateQueries({ queryKey: ["decisions"] });
    },
  });
}

export function useDeleteAnalysis() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<void>(`/api/analyze/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["analyses"] }),
  });
}

export const useDecisions = () =>
  useQuery({ queryKey: ["decisions"], queryFn: () => request<Decision[]>("/api/decisions") });

export function useRecordDecision() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entry: Omit<Decision, "at">) =>
      request<Decision>("/api/decisions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(entry),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["decisions"] }),
  });
}

export type Source = {
  id: string;
  title: string;
  url: string;
  pages: string;
  note: string;
  rule_ids: string[];
  file_name: string | null;
  added_at: string;
};

export const useSources = () =>
  useQuery({ queryKey: ["sources"], queryFn: () => request<Source[]>("/api/sources") });

export function useAddSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => request<Source>("/api/sources", { method: "POST", body: form }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useDeleteSource() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<void>(`/api/sources/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export type Project = {
  id: string;
  name: string;
  ship_type: string;
  created_at: string;
  /** The rule ids the project checks. Null until an engineer chooses, which means every rule. */
  rule_ids: string[] | null;
};

export const useProjects = () =>
  useQuery({ queryKey: ["projects"], queryFn: () => request<Project[]>("/api/projects") });

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (entry: { name: string; ship_type: string }) =>
      request<Project>("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(entry),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useSaveProjectRules(projectId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (ruleIds: string[]) =>
      request<Project>(`/api/projects/${projectId}/rules`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ rule_ids: ruleIds }),
      }),
    onSuccess: () => {
      // The chosen rules decide which findings every floor of the project shows.
      for (const key of ["projects", "findings", "analyses", "analysis"])
        client.invalidateQueries({ queryKey: [key] });
    },
  });
}

/** The limit a rule sets, in a few words. */
export function requirement(r: Rule): string {
  if (r.value_mm !== null) {
    const width = `${symbol(r.operator ?? "")} ${r.value_mm} mm`;
    return r.minimum_area_m2 === null ? width : `${width} and ≥ ${r.minimum_area_m2} m²`;
  }
  if (r.value_mm_per_person !== null) return `${r.value_mm_per_person} mm per person`;
  if (r.minimum_routes !== null) return `At least ${r.minimum_routes} routes`;
  return "Geometry check";
}

/** One thing to check for the whole ship, from its main dimensions or across all its decks. */
export type ShipItem = {
  regulation: string;
  ref: string;
  title: string;
  status: "value" | "shown" | "not_shown" | "by_hand" | "not_applicable";
  detail: string;
  where: { analysis: string; deck: string; space: string; number: number }[];
};

export type ShipOverview = {
  particulars: {
    length_overall_m: number | null;
    length_pp_m: number | null;
    breadth_m: number | null;
    frame_spacing_mm: number | null;
    title: string;
  };
  decks: { analysis: string; deck: string }[];
  items: ShipItem[];
  ship_type: string;
};

export const useShipOverview = (projectId: string) =>
  useQuery({
    queryKey: ["ship", projectId],
    queryFn: () => request<ShipOverview>(`/api/projects/${encodeURIComponent(projectId)}/ship`),
  });

export type AiLook = { answer: "looks_ok" | "looks_wrong" | "unsure"; seen: string; count: number };

export const AI_ANSWER: Record<AiLook["answer"], string> = {
  looks_ok: "AI: looks OK",
  looks_wrong: "AI: looks wrong",
  unsure: "AI: unsure",
};
