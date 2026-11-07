import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { PlanView, type PlanGeometry } from "@/components/PlanView";
import { FindingDetail, FindingShape, VerdictTag } from "@/components/FindingDetail";
import { AccuracyPanel, ImpactPanel } from "@/components/DeckPanels";
import {
  currentDecisions,
  findingKey,
  useDecisions,
  useFindings,
  useMeta,
  useSpaces,
  type Verdict,
} from "@/lib/api";

export const Route = createFileRoute("/app/")({
  head: () => ({ meta: [{ title: "Checked deck · Keel" }] }),
  component: DeckPage,
});

const TABS = ["Model", "Accuracy", "Add cabins"] as const;
const VERDICTS: Verdict[] = ["FAIL", "NEEDS_REVIEW", "PASS"];

function DeckPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Model");
  const [scenario, setScenario] = useState("");
  const [explain, setExplain] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [showPassed, setShowPassed] = useState(false);
  const [showSpaces, setShowSpaces] = useState(false);

  const meta = useMeta();
  const findingsQuery = useFindings(scenario, explain);
  const spaces = useSpaces();
  const decisionLog = useDecisions();
  const decisions = useMemo(() => currentDecisions(decisionLog.data ?? []), [decisionLog.data]);

  const data = findingsQuery.data;
  const selected = data?.findings.find((f) => findingKey(f) === selectedKey) ?? null;

  // Open on the first finding an engineer needs to look at, also after changing design state.
  useEffect(() => {
    if (!data || selected) return;
    const first = data.findings.find((f) => f.verdict !== "PASS") ?? data.findings[0];
    setSelectedKey(first ? findingKey(first) : null);
  }, [data, selected]);

  if (meta.isPending) return <p role="status">Loading the deck…</p>;
  if (meta.isError)
    return (
      <div className="card empty" role="alert">
        <h2>Could not load the deck</h2>
        <p>{meta.error.message}</p>
        <p className="muted">Start the backend with ./dev.sh from the project folder.</p>
      </div>
    );

  const m = meta.data;
  const [x0, y0, x1, y1] = m.region;
  const plan: PlanGeometry = {
    image: "/api/drawing.png",
    x: x0,
    y: y0,
    width: x1 - x0,
    height: y1 - y0,
  };
  const findings = data?.findings ?? [];
  const pinOf = new Map(
    findings.map((f, i) => [findingKey(f), `F-${String(i + 1).padStart(2, "0")}`]),
  );
  const pins = findings
    .filter((f) => showPassed || f.verdict !== "PASS" || f === selected)
    .map((f) => ({
      id: pinOf.get(findingKey(f)) ?? "",
      label: `${f.rule_id}: ${f.subject_name}`,
      verdict: f.verdict,
      x: f.location_pt[0],
      y: f.location_pt[1],
    }));
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Checked deck · demo</span>
          <h1>{m.deck}</h1>
          <p className="muted">
            {m.spaces} spaces · {m.doors} doors · {m.unresolved_arcs} door arcs left for review ·{" "}
            {m.source_pdf}, page {m.page_index + 1}
          </p>
        </div>
        <div className="page-actions">
          <Link to="/app/new" className="btn primary">
            Upload a drawing
          </Link>
          <label className="field-inline">
            Design state
            <select
              value={scenario}
              onChange={(e) => {
                setScenario(e.target.value);
                setExplain(false);
                setSelectedKey(null);
              }}
            >
              <option value="">Original drawing</option>
              {m.scenarios.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <button
            className="btn"
            disabled={!m.llm || explain}
            title={m.llm ? `Sends finding text to ${m.llm}` : "No AI configured on the backend"}
            onClick={() => setExplain(true)}
          >
            {explain && findingsQuery.isFetching ? "Writing notes…" : "Add AI notes"}
          </button>
        </div>
      </header>

      <p className="notice">
        RCRV is a research vessel, not a cruise ship, so these rules are applied for demonstration.
        Keel does not certify compliance. An engineer decides.
      </p>

      <div role="tablist" className="tabs">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Accuracy" && <AccuracyPanel />}
      {tab === "Add cabins" && <ImpactPanel />}
      {tab === "Model" && (
        <>
          <PlanView
            plan={plan}
            alt={`Deck plan of ${m.deck}`}
            pins={pins}
            selectedPin={selected ? (pinOf.get(findingKey(selected)) ?? null) : null}
            focus={selected?.location_pt ?? null}
            onSelectPin={(pin) => {
              const f = data?.findings.find((x) => pinOf.get(findingKey(x)) === pin);
              if (f) setSelectedKey(findingKey(f));
            }}
            tools={
              <>
                <button
                  className="chip"
                  aria-pressed={showPassed}
                  onClick={() => setShowPassed(!showPassed)}
                >
                  Show passed
                </button>
                <button
                  className="chip"
                  aria-pressed={showSpaces}
                  onClick={() => setShowSpaces(!showSpaces)}
                >
                  Spaces
                </button>
                <span className="plan-scale" title={m.calibration}>
                  {m.mm_per_pt.toFixed(2)} mm/pt · tolerance {m.tolerance_mm.toFixed(0)} mm
                </span>
              </>
            }
          >
            {showSpaces &&
              spaces.data?.map((s) => (
                <polygon
                  key={s.id}
                  className="overlay-space"
                  points={s.outline_pt.map((p) => p.join(",")).join(" ")}
                >
                  <title>{`${s.name} · ${s.category} · ${s.area_m2} m²`}</title>
                </polygon>
              ))}
            {selected && <FindingShape finding={selected} />}
          </PlanView>
          {findingsQuery.isError && (
            <p className="notice notice-fail" role="alert">
              Could not load findings: {findingsQuery.error.message}
            </p>
          )}
          {data?.injected.length ? (
            <p className="notice">
              Test scenario, injected into the ship model: {data.injected.join(", ")}.
            </p>
          ) : null}
          {data?.note_error && <p className="notice">{data.note_error}</p>}
          <div className="findings-stack">
            <section className="card findings-list" aria-label="Findings">
              <div className="card-head">
                <h2>Findings</h2>
                <span className="counts">
                  {data &&
                    VERDICTS.map((v) => (
                      <VerdictTag
                        key={v}
                        verdict={v}
                        label={`${v.replace("_", " ")} ${data.counts[v]}`}
                      />
                    ))}
                </span>
              </div>
              {data?.findings.map((f) => {
                const key = findingKey(f);
                const decision = decisions.get(key);
                return (
                  <button
                    key={key}
                    className="finding-row"
                    aria-pressed={key === selectedKey}
                    onClick={() => setSelectedKey(key)}
                  >
                    <VerdictTag verdict={f.verdict} />
                    <span>
                      <strong>
                        {pinOf.get(key)} · {f.subject_name}
                      </strong>
                      <small>{f.rule_id}</small>
                      {decision && !scenario && (
                        <small className="decided">{decision.decision.replace("_", " ")}</small>
                      )}
                    </span>
                  </button>
                );
              })}
              {findingsQuery.isPending && <p className="pad muted">Measuring…</p>}
            </section>
            {selected && (
              <FindingDetail
                key={findingKey(selected)}
                finding={selected}
                pin={pinOf.get(findingKey(selected)) ?? ""}
                decisionKey={findingKey(selected)}
                decision={decisions.get(findingKey(selected))}
                testScenario={!!scenario}
                plan={plan}
                mmPerUnit={m.mm_per_pt}
              />
            )}
          </div>
        </>
      )}
    </>
  );
}
