import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { FindingDetail, FindingShape, VerdictTag } from "@/components/FindingDetail";
import { PlanView, type PlanGeometry } from "@/components/PlanView";
import { Check, LoaderCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import {
  currentDecisions,
  needsNameFirst,
  symbol,
  useDecisions,
  type Finding,
  NO_REGULATIONS_YET,
  regulationsOf,
  UNIDENTIFIED,
  useAnalysis,
  useAnalysisStatus,
  useCorrectSpace,
  useDeleteAnalysis,
  useSpaceTypes,
  type AnalysedSpace,
  type Analysis,
  type AnalysisStatus,
  type Regulation,
} from "@/lib/api";

export const Route = createFileRoute("/app/analysis/$jobId")({
  head: () => ({ meta: [{ title: "Checked deck · Keel" }] }),
  component: AnalysisPage,
});

const TABS = ["Findings", "Spaces", "Regulations"] as const;
const FILTERS = ["To check", "FAIL", "NEEDS_REVIEW", "PASS", "All"] as const;

function AnalysisPage() {
  const { jobId } = Route.useParams();
  const status = useAnalysisStatus(jobId);

  if (status.isPending) return <p role="status">Opening the deck…</p>;
  if (status.isError)
    return (
      <p className="notice notice-fail" role="alert">
        Could not open this deck: {status.error.message}
      </p>
    );
  if (status.data.status === "running") return <AnalysisProgress state={status.data} />;
  if (status.data.status === "failed")
    return (
      <div className="stack">
        <h1>{status.data.source}</h1>
        <p className="notice notice-fail" role="alert">
          {status.data.error}
        </p>
        <div className="row">
          <Link to="/app/new" className="btn">
            Try another file
          </Link>
        </div>
      </div>
    );
  return <AnalysisResult jobId={jobId} />;
}

function useElapsedSeconds(since: string | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return since ? Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000)) : 0;
}

function AnalysisProgress({ state }: { state: AnalysisStatus }) {
  const elapsed = useElapsedSeconds(state.created_at);
  const minutes = Math.floor(elapsed / 60);
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Checked deck</span>
          <h1>{state.source}</h1>
          <p className="muted">
            Running for {minutes > 0 && `${minutes} min `}
            {elapsed % 60} s. You can leave this page, the check keeps going. The deck and its
            regulations open here when it is done.
          </p>
        </div>
      </header>
      <ol className="card pad steps" aria-label="Progress" aria-live="polite">
        {state.completed?.filter(Boolean).map((step) => (
          <li key={step} className="muted">
            <Check size={16} /> {step}
          </li>
        ))}
        <li>
          <LoaderCircle size={16} className="spin" /> <strong>{state.step}</strong>
          {state.detail && <span className="muted"> · {state.detail}</span>}
        </li>
      </ol>
    </>
  );
}

function AnalysisResult({ jobId }: { jobId: string }) {
  const analysis = useAnalysis(jobId, true);
  const remove = useDeleteAnalysis();
  const navigate = useNavigate();
  const [chosenTab, setTab] = useState<(typeof TABS)[number] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [pin, setPin] = useState<string | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("To check");
  const [showAll, setShowAll] = useState(false);
  const [showPassed, setShowPassed] = useState(false);
  const decisionLog = useDecisions();

  if (analysis.isPending) return <p role="status">Opening the deck…</p>;
  if (analysis.isError)
    return (
      <p className="notice notice-fail" role="alert">
        Could not open this deck: {analysis.error.message}
      </p>
    );

  const r = analysis.data;
  const named = r.spaces.filter((s) => s.name !== UNIDENTIFIED);
  const unnamed = r.spaces.filter((s) => s.name === UNIDENTIFIED);
  const ordered = [...named, ...unnamed];
  const regulations = regulationsOf(r.spaces);
  const toConfirm = ordered.filter(nameNeedsChecking).length;
  const current = ordered.find((s) => s.number === selected) ?? ordered[0];
  const findings = (r.findings ?? []).filter((f) => !f.could_not_check);
  const notApplied = (r.findings ?? []).filter((f) => f.could_not_check);
  const tab = chosenTab ?? (findings.length ? "Findings" : "Spaces");
  const currentFinding =
    findings.find((f) => f.pin === pin) ??
    findings.find((f) => f.verdict === "FAIL") ??
    findings.find((f) => f.verdict === "NEEDS_REVIEW") ??
    findings[0];
  const matches = (f: Finding, v: (typeof FILTERS)[number]) =>
    v === "All" || (v === "To check" ? f.verdict !== "PASS" : f.verdict === v);
  const shown = findings.filter((f) => matches(f, filter));
  const decisions = currentDecisions(decisionLog.data ?? []);
  const decisionKey = (f: Finding) => `${r.id}:${f.rule_id}:${f.subject_id}`;
  const scale = r.plan_scale ?? 1;
  const [originX, originY] = r.plan_origin ?? [0, 0];
  const size = r.plan_image ? r.plan_size : undefined;
  const plan: PlanGeometry = {
    image: r.plan_image ?? r.image,
    x: originX,
    y: originY,
    width: (size?.[0] ?? 1) / scale,
    height: (size?.[1] ?? 1) / scale,
  };
  const toUnits = ([x, y]: [number, number]) => `${x / scale + originX},${y / scale + originY}`;
  const spaceFocus = (s: AnalysedSpace | undefined): [number, number] | null => {
    const points = s?.outline_px?.flat();
    if (!points?.length) return null;
    const middle = (axis: 0 | 1) => {
      const values = points.map((p) => p[axis]);
      return (Math.min(...values) + Math.max(...values)) / 2;
    };
    return [middle(0) / scale + originX, middle(1) / scale + originY];
  };
  const onFindingsTab = tab === "Findings" && !!currentFinding;
  const openSpace = (space: AnalysedSpace) => {
    setSelected(space.number);
    setTab("Spaces");
  };
  const onDelete = () => {
    if (!window.confirm(`Delete ${r.source} from Keel? This cannot be undone.`)) return;
    remove.mutate(r.id, { onSuccess: () => navigate({ to: "/app/new" }) });
  };

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Checked deck</span>
          <h1>{r.source}</h1>
          <p className="muted">
            {ordered.length} spaces · {r.doors_found ?? 0} doors · {r.stairs_found ?? 0} stairs ·{" "}
            {findings.length} measured checks · {toConfirm} names to confirm
          </p>
        </div>
        <div className="page-actions">
          <Link to="/app/new" className="btn primary">
            Upload a drawing
          </Link>
          <button className="btn danger" disabled={remove.isPending} onClick={onDelete}>
            Delete
          </button>
        </div>
      </header>
      <p className="notice">
        {r.mm_per_unit
          ? `${r.scale_note} Limits for a ${r.ship_type} ship. Pick a pin to see why, and what to do.`
          : "This image has no scale, so nothing could be measured. These are the regulations to check for each space. Upload the PDF to get measured findings."}
        {r.naming_error && ` ${r.naming_error}`}
      </p>
      {remove.isError && (
        <p className="notice notice-fail" role="alert">
          {remove.error.message}
        </p>
      )}
      <PlanView
        plan={plan}
        alt={`Plan of ${r.source}`}
        pins={findings
          .filter((f) => showPassed || f.verdict !== "PASS" || f === currentFinding)
          .map((f) => ({
            id: f.pin ?? "",
            label: `${f.rule_id}: ${f.subject_name}`,
            verdict: f.verdict,
            x: f.location_pt[0],
            y: f.location_pt[1],
          }))}
        selectedPin={onFindingsTab ? (currentFinding?.pin ?? null) : null}
        focus={onFindingsTab ? (currentFinding?.location_pt ?? null) : spaceFocus(current)}
        onSelectPin={(id) => {
          setPin(id);
          const chosen = findings.find((f) => f.pin === id);
          if (chosen && !matches(chosen, filter)) setFilter("All");
          setTab("Findings");
        }}
        tools={
          <>
            {findings.length > 0 && (
              <button
                className="chip"
                aria-pressed={showPassed}
                onClick={() => setShowPassed(!showPassed)}
              >
                Show passed
              </button>
            )}
            {size && (
              <button className="chip" aria-pressed={showAll} onClick={() => setShowAll(!showAll)}>
                All spaces
              </button>
            )}
            <span className="plan-scale">
              {onFindingsTab ? currentFinding?.subject_name : current ? spaceName(current) : ""}
            </span>
          </>
        }
      >
        {size &&
          ordered.map((s) => (
            <g
              key={s.number}
              className="overlay-room"
              data-active={!onFindingsTab && s.number === current?.number}
              data-show={showAll}
              role="button"
              tabIndex={0}
              aria-label={spaceName(s)}
              onClick={() => openSpace(s)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  openSpace(s);
                }
              }}
            >
              <title>{spaceName(s)}</title>
              {s.outline_px?.map((outline, i) => (
                <polygon key={i} points={outline.map(toUnits).join(" ")} />
              ))}
            </g>
          ))}
        {onFindingsTab && currentFinding && <FindingShape finding={currentFinding} />}
      </PlanView>
      <div role="tablist" className="tabs">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
            {t === "Regulations"
              ? `Regulations (${regulations.length})`
              : t === "Findings"
                ? `Findings (${findings.length})`
                : `Spaces (${ordered.length})`}
          </button>
        ))}
      </div>
      {tab === "Findings" ? (
        <div className="findings-stack">
          <section className="card findings-list" aria-label="Findings">
            <div className="card-head">
              <h2>Findings</h2>
            </div>
            <div className="filters">
              {FILTERS.map((v) => {
                const count = findings.filter((f) => matches(f, v)).length;
                return (
                  <button
                    key={v}
                    className="chip"
                    aria-pressed={filter === v}
                    onClick={() => setFilter(v)}
                  >
                    {v.replace("_", " ")} {count}
                  </button>
                );
              })}
            </div>
            {shown.map((f) => {
              const decision = decisions.get(decisionKey(f));
              return (
                <button
                  key={f.pin}
                  className="finding-row"
                  aria-pressed={f.pin === currentFinding?.pin}
                  onClick={() => setPin(f.pin ?? null)}
                >
                  <VerdictTag verdict={f.verdict} />
                  <span>
                    <strong>
                      {f.pin} · {f.subject_name}
                    </strong>
                    <small>{f.rule_title}</small>
                    {f.measured_display && (
                      <small>
                        {f.measured_display} · limit {symbol(f.operator)} {f.required_display}
                      </small>
                    )}
                    {decision && (
                      <small className="decided">{decision.decision.replace("_", " ")}</small>
                    )}
                  </span>
                </button>
              );
            })}
            {findings.length === 0 && <p className="pad muted">Nothing could be measured here.</p>}
            {notApplied.length > 0 && (
              <details className="set-aside">
                <summary>{notApplied.length} checks could not be done on this deck</summary>
                <ul className="not-applied">
                  {notApplied.map((f) => (
                    <li key={f.pin}>
                      <strong>{f.rule_title}.</strong> {f.why}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
          {currentFinding && (
            <FindingDetail
              key={currentFinding.pin}
              finding={currentFinding}
              pin={currentFinding.pin ?? ""}
              decisionKey={decisionKey(currentFinding)}
              decision={decisions.get(decisionKey(currentFinding))}
              testScenario={false}
              plan={plan}
              mmPerUnit={r.mm_per_unit ?? null}
            />
          )}
        </div>
      ) : tab === "Regulations" ? (
        <AllRegulations
          regulations={regulations}
          unnamed={ordered.filter(needsNameFirst)}
          onOpenSpace={openSpace}
        />
      ) : (
        <div className="findings-layout">
          <section className="card findings-list" aria-label="Spaces">
            <div className="card-head">
              <h2>Spaces</h2>
            </div>
            {ordered.map((s) => (
              <button
                key={s.number}
                className="finding-row"
                aria-pressed={s.number === current?.number}
                onClick={() => setSelected(s.number)}
              >
                <span>
                  <strong>{spaceName(s)}</strong>
                  <small>
                    {[s.compartment, typeLabel(s.category)].filter(Boolean).join(" · ")}
                  </small>
                  {nameNeedsChecking(s) && <small className="text-warn">Confirm name</small>}
                </span>
              </button>
            ))}
            {ordered.length === 0 && <p className="pad muted">No spaces were found.</p>}
            {r.set_aside.length > 0 && (
              <p className="set-aside muted">
                {r.set_aside.length} small areas were set aside, not treated as rooms.
              </p>
            )}
          </section>
          {current && (
            <SpaceDetail key={current.number + current.name} jobId={r.id} space={current} />
          )}
        </div>
      )}
    </>
  );
}

const typeLabel = (category: string) => category.replaceAll("_", " ");
const nameNeedsChecking = (s: AnalysedSpace) => !s.reviewed && !s.name_on_drawing;
const spaceName = (s: AnalysedSpace) =>
  s.name === UNIDENTIFIED ? `${s.name} ${s.number}` : s.name;

function SpaceDetail({ jobId, space: s }: { jobId: string; space: AnalysedSpace }) {
  const correct = useCorrectSpace(jobId);
  const types = useSpaceTypes();
  const [name, setName] = useState(s.name === UNIDENTIFIED ? "" : s.name);
  const [category, setCategory] = useState<string | null>(null);
  const trimmed = name.trim();
  const unchanged = trimmed === s.name && category === null;
  const save = (e: FormEvent) => {
    e.preventDefault();
    if (trimmed) correct.mutate({ number: s.number, name: trimmed, category });
  };

  return (
    <section className="card finding-detail" aria-label={`Details of ${spaceName(s)}`}>
      <header>
        <h2>{spaceName(s)}</h2>
        <span className="muted">
          {[s.compartment, typeLabel(s.category), s.area_m2 !== null && `${s.area_m2} m²`]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </header>
      <form className="rename" onSubmit={save}>
        <label>
          Space name
          <input
            value={name}
            required
            maxLength={120}
            placeholder="Type the name from the drawing"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label>
          Type
          <select
            value={category ?? s.category}
            onChange={(e) => setCategory(e.target.value === s.category ? null : e.target.value)}
          >
            {(types.data ?? [s.category]).map((t) => (
              <option key={t} value={t}>
                {typeLabel(t)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn primary"
          disabled={correct.isPending || !trimmed || (unchanged && !nameNeedsChecking(s))}
        >
          {unchanged ? "Confirm name" : "Save"}
        </button>
      </form>
      {s.reviewed && <p className="text-pass">Confirmed by an engineer.</p>}
      {nameNeedsChecking(s) && (
        <p className="text-warn">
          Keel is not sure of this name. Check it against the drawing, because the regulations below
          depend on the type of space.
        </p>
      )}
      {correct.isError && (
        <p className="text-fail" role="alert">
          Could not save: {correct.error.message}
        </p>
      )}
      <div>
        <span className="eyebrow">Regulations to check</span>
        <ul className="regulations">
          {s.checklist.map((c) => (
            <li key={c.ref + c.what}>
              <div>
                <strong>{c.ref === NO_REGULATIONS_YET ? "No regulations yet" : c.ref}</strong>
                {!c.reference_confirmed && (
                  <small className="text-warn"> reference not yet confirmed</small>
                )}
                <p>{c.what}</p>
                {c.measured && <p className="measured">{c.measured}</p>}
              </div>
              {c.verdict ? (
                <VerdictTag verdict={c.verdict} />
              ) : (
                <span className="status">To check</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function AllRegulations({
  regulations,
  unnamed,
  onOpenSpace,
}: {
  regulations: Regulation[];
  unnamed: AnalysedSpace[];
  onOpenSpace: (space: AnalysedSpace) => void;
}) {
  return (
    <section className="card" aria-label="All regulations">
      {regulations.length === 0 && <p className="pad muted">No regulations to list.</p>}
      {unnamed.length > 0 && (
        <p className="pad text-warn">
          {unnamed.length} spaces have no regulations yet, because Keel does not know their type.
          Name them in the Spaces tab and their regulations will appear here.
        </p>
      )}
      {regulations.map((x) => (
        <div key={x.ref} className="list-row">
          <div>
            <strong>{x.ref}</strong>
            {!x.confirmed && <small className="text-warn">Reference not yet confirmed</small>}
            {x.whats.map((what) => (
              <small key={what} className="muted">
                {what}
              </small>
            ))}
            <span className="space-links">
              {x.spaces.map((s) => (
                <button key={s.number} onClick={() => onOpenSpace(s)}>
                  {spaceName(s)}
                </button>
              ))}
            </span>
          </div>
          <span className="status">{x.measured > 0 ? `${x.measured} measured` : "To check"}</span>
        </div>
      ))}
    </section>
  );
}
