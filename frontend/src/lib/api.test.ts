import { afterEach, describe, expect, it, vi } from "vitest";
import {
  currentDecisions,
  findingKey,
  manualChecksOf,
  needsNameFirst,
  NO_REGULATIONS_YET,
  regulationsOf,
  request,
  type AnalysedSpace,
  type Decision,
} from "./api";

const entry = (finding: string, decision: Decision["decision"]): Decision => ({
  finding,
  rule_id: "R",
  subject: "S",
  decision,
  note: "",
  at: "2026-11-07T00:00:00Z",
});

describe("currentDecisions", () => {
  it("keeps the latest decision for each finding", () => {
    const current = currentDecisions([
      entry("a", "need_info"),
      entry("a", "accepted"),
      entry("b", "rejected"),
    ]);
    expect(current.get("a")?.decision).toBe("accepted");
    expect(current.get("b")?.decision).toBe("rejected");
  });

  it("an undo removes the decision, and a later one restores it", () => {
    expect(currentDecisions([entry("a", "accepted"), entry("a", "cleared")]).has("a")).toBe(false);
    const again = currentDecisions([
      entry("a", "accepted"),
      entry("a", "cleared"),
      entry("a", "rejected"),
    ]);
    expect(again.get("a")?.decision).toBe("rejected");
  });
});

it("findingKey joins rule and subject", () => {
  expect(findingKey({ rule_id: "ESC-DEAD-END", subject_id: "C-1" })).toBe("ESC-DEAD-END:C-1");
});

describe("backend errors", () => {
  afterEach(() => vi.unstubAllGlobals());

  async function failure(response: Response | Error) {
    vi.stubGlobal("fetch", () =>
      response instanceof Error ? Promise.reject(response) : Promise.resolve(response),
    );
    return request("/api/x").catch((e: Error) => e.message);
  }

  it("shows the backend's own message", async () => {
    const body = JSON.stringify({ detail: "Could not read this drawing: bad page" });
    expect(await failure(new Response(body, { status: 422 }))).toBe(
      "Could not read this drawing: bad page",
    );
  });

  it("explains a backend that is down", async () => {
    expect(await failure(new Error("network"))).toBe("Cannot reach the Keel backend.");
    expect(await failure(new Response("", { status: 500 }))).toContain("not running");
  });
});

describe("regulationsOf", () => {
  const space = (
    number: number,
    ...items: [string, string, boolean, boolean][]
  ): AnalysedSpace => ({
    number,
    name: `S${number}`,
    compartment: null,
    category: "cabin",
    confidence: 1,
    evidence: "label_inside",
    name_on_drawing: true,
    area_m2: null,
    checklist: items.map(([ref, what, reference_confirmed, measured]) => ({
      ref,
      what,
      reference_confirmed,
      status: measured ? "measured" : "to_check",
      verdict: measured ? "PASS" : null,
      measured: measured ? "ok" : null,
    })),
  });

  it("lists each regulation once, with every space it applies to", () => {
    const list = regulationsOf([
      space(1, ["SOLAS B", "Doors", true, false], ["MLC A", "Berths", false, false]),
      space(2, ["SOLAS B", "Doors", true, true], ["SOLAS B", "Width", true, false]),
    ]);
    expect(list.map((r) => r.ref)).toEqual(["MLC A", "SOLAS B"]);
    const solas = list[1]!;
    expect(solas.spaces.map((s) => s.number)).toEqual([1, 2]);
    expect(solas.whats).toEqual(["Doors", "Width"]);
    expect(solas.measured).toBe(1);
    expect(list[0]!.confirmed).toBe(false);
  });

  it("leaves for checking by hand only what was not measured", () => {
    const list = manualChecksOf([
      space(1, ["SOLAS B", "Doors", true, true], ["MLC A", "Berths", false, false]),
      space(2, ["SOLAS B", "Doors", true, false]),
      space(3, ["SOLAS C", "Width", true, true]),
    ]);
    expect(list.map((r) => r.ref)).toEqual(["MLC A", "SOLAS B"]);
    expect(list[1]!.spaces.map((s) => s.number)).toEqual([2]);
    // The space keeps its full checklist, so its detail still shows what was measured.
    expect(list[0]!.spaces[0]!.checklist).toHaveLength(2);
  });

  it("does not count the placeholder for an unnamed space as a regulation", () => {
    const unnamed = space(3, [NO_REGULATIONS_YET, "Name it first", true, false]);
    expect(regulationsOf([unnamed])).toEqual([]);
    expect(needsNameFirst(unnamed)).toBe(true);
    expect(needsNameFirst(space(4, ["SOLAS B", "Doors", true, false]))).toBe(false);
  });

  it("gives nothing for no spaces", () => {
    expect(regulationsOf([])).toEqual([]);
  });
});
