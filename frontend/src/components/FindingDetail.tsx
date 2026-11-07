import { useState } from "react";
import type { PlanGeometry } from "@/components/PlanView";
import {
  DECISION_LABEL,
  symbol,
  useRecordDecision,
  type Decision,
  type DecisionKind,
  type Finding,
  type Verdict,
} from "@/lib/api";

const VERDICT_TITLE: Record<Verdict, string> = {
  FAIL: "Does not meet the rule",
  NEEDS_REVIEW: "An engineer should decide",
  PASS: "Meets the rule",
};

export function VerdictTag({ verdict, label }: { verdict: Verdict; label?: string }) {
  return (
    <span className="verdict" data-verdict={verdict}>
      {label ?? verdict.replace("_", " ")}
    </span>
  );
}

/** The measured area of a finding, drawn on the plan. */
export function FindingShape({ finding: f }: { finding: Finding }) {
  return (
    <g className="overlay-finding" data-verdict={f.verdict} data-active="true">
      {f.overlay_polygon_pt.length > 0 && (
        <polygon points={f.overlay_polygon_pt.map((p) => p.join(",")).join(" ")} />
      )}
      {f.overlay_lines_pt.map((line, i) => (
        <polyline key={i} points={line.map((p) => p.join(",")).join(" ")} />
      ))}
    </g>
  );
}

export function FindingDetail({
  finding: f,
  pin,
  decisionKey,
  decision,
  testScenario,
  plan,
  mmPerUnit,
}: {
  finding: Finding;
  pin: string;
  decisionKey: string;
  decision: Decision | undefined;
  testScenario: boolean;
  plan: PlanGeometry;
  mmPerUnit: number | null;
}) {
  const steps = [
    f.why,
    f.why_it_matters,
    ...(f.interpretation_note ? [f.interpretation_note] : []),
  ].filter(Boolean);
  return (
    <section className="card finding-detail" id="finding-detail">
      <header>
        <span className="pin-title" data-verdict={f.verdict}>
          <span className="pin-dot" />
          {pin}
        </span>
        <h2>
          {f.rule_title}: {f.subject_name}
        </h2>
        <span className="muted detail-verdict">{VERDICT_TITLE[f.verdict]}</span>
      </header>
      <div className="detail-columns">
        <div>
          <span className="eyebrow">
            {f.verdict === "PASS" ? "Why this meets the rule" : "Why this may not comply"}
          </span>
          {f.measured_display && (
            <div className="measures">
              <div data-bad={f.verdict !== "PASS"}>
                <small>Measured</small>
                <b>{f.measured_display}</b>
              </div>
              <div>
                <small>Limit</small>
                <b>
                  {symbol(f.operator)} {f.required_display}
                </b>
              </div>
            </div>
          )}
          <ol className="why-steps">
            {steps.map((step, i) => (
              <li key={i}>
                <span>{i + 1}</span>
                <p>{step}</p>
              </li>
            ))}
          </ol>
          {f.explanation && (
            <p className="ai-note">
              <strong>AI note, not used in the verdict:</strong> {f.explanation}
            </p>
          )}
        </div>
        <div>
          <span className="eyebrow">Resources</span>
          <div className="resources">
            <div className="resource">
              <div>
                {f.ref_url ? (
                  <a href={f.ref_url} target="_blank" rel="noreferrer">
                    {f.source}
                  </a>
                ) : (
                  <strong>{f.source}</strong>
                )}
                <small className="muted">The regulation this limit comes from</small>
              </div>
              <span className="status" data-status={f.value_status}>
                {f.value_status === "assumed" ? "Assumed" : "Checked"}
              </span>
            </div>
            {f.value_status === "assumed" && (
              <p className="text-warn resource-note">
                This limit is a placeholder, not read from the source. Do not rely on it.
              </p>
            )}
            <div className="resource">
              <div>
                <strong>
                  {f.source_pdf}, page {f.page_index + 1}
                </strong>
                <small className="muted">
                  At ({f.location_pt[0].toFixed(1)}, {f.location_pt[1].toFixed(1)}) on the drawing
                  {f.tolerance_mm !== null && ` · tolerance ${f.tolerance_mm.toFixed(0)} mm`}
                </small>
              </div>
            </div>
            {f.assumptions.map((a) => (
              <div className="resource" key={a}>
                <div>
                  <strong>Assumes</strong>
                  <small className="muted">{a}</small>
                </div>
              </div>
            ))}
          </div>
        </div>
        <SuggestedDesign finding={f} plan={plan} mmPerUnit={mmPerUnit} />
      </div>
      {f.verdict === "PASS" ? null : testScenario ? (
        <p className="muted">This is an injected test scenario, so decisions are not recorded.</p>
      ) : (
        <DecisionBar finding={f} decisionKey={decisionKey} decision={decision} />
      )}
    </section>
  );
}

function SuggestedDesign({
  finding: f,
  plan,
  mmPerUnit,
}: {
  finding: Finding;
  plan: PlanGeometry;
  mmPerUnit: number | null;
}) {
  const [view, setView] = useState<"Current" | "After">("After");
  const canDraw =
    mmPerUnit !== null &&
    f.measured_mm !== null &&
    f.required_mm !== null &&
    f.operator === ">=" &&
    f.location_pt[0] !== 0;
  if (f.verdict === "PASS" && !canDraw)
    return (
      <div>
        <span className="eyebrow">Suggested design</span>
        <p className="muted">No change needed.</p>
      </div>
    );
  const scale = mmPerUnit ?? 1;
  const measured = (f.measured_mm ?? 0) / scale;
  const required = (f.required_mm ?? 0) / scale;
  const reach = Math.max(measured, required) * 2.2;
  const [x, y] = f.location_pt;
  const showFix = view === "After" && f.verdict !== "PASS";
  return (
    <div>
      <div className="design-head">
        <span className="eyebrow">
          {f.verdict === "PASS" ? "On the drawing" : "Suggested design"}
        </span>
        {canDraw && f.verdict !== "PASS" && (
          <span className="segmented">
            {(["Current", "After"] as const).map((v) => (
              <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>
                {v}
              </button>
            ))}
          </span>
        )}
      </div>
      {canDraw && (
        <figure className="design">
          <svg
            viewBox={`${x - reach} ${y - reach} ${reach * 2} ${reach * 2}`}
            role="img"
            aria-label={
              showFix
                ? `Space needed: ${f.required_mm?.toFixed(0)} mm`
                : `Space measured: ${f.measured_mm?.toFixed(0)} mm`
            }
          >
            <image
              href={plan.image}
              x={plan.x}
              y={plan.y}
              width={plan.width}
              height={plan.height}
            />
            {showFix ? (
              <circle className="design-after" cx={x} cy={y} r={required / 2} />
            ) : (
              <circle
                className={f.verdict === "PASS" ? "design-ok" : "design-now"}
                cx={x}
                cy={y}
                r={measured / 2}
              />
            )}
          </svg>
          <figcaption>
            {showFix
              ? `Green: the ${f.required_mm?.toFixed(0)} mm that must fit here`
              : `The ${f.measured_mm?.toFixed(0)} mm measured here`}
          </figcaption>
        </figure>
      )}
      {f.fix && (
        <div className="fix">
          <strong>What to do</strong>
          <p>{f.fix}</p>
        </div>
      )}
      {f.verdict !== "PASS" && !f.fix && (
        <p className="muted">
          Keel has no suggestion here, so this is for the engineer to work out.
        </p>
      )}
      {canDraw && f.verdict !== "PASS" && (
        <p className="muted design-note">
          A suggestion for the engineer to check, not a finished design.
        </p>
      )}
    </div>
  );
}

function DecisionBar({
  finding: f,
  decisionKey,
  decision,
}: {
  finding: Finding;
  decisionKey: string;
  decision: Decision | undefined;
}) {
  const [note, setNote] = useState("");
  const record = useRecordDecision();
  const decide = (kind: DecisionKind) =>
    record.mutate(
      {
        finding: decisionKey,
        rule_id: f.rule_id,
        subject: f.subject_name,
        decision: kind,
        note: kind === "cleared" ? "" : note.trim(),
      },
      { onSuccess: () => setNote("") },
    );

  return (
    <div className="decision">
      {decision ? (
        <p>
          <strong>{DECISION_LABEL[decision.decision]}</strong> ·{" "}
          {new Date(decision.at).toLocaleString()}
          {decision.note && ` · “${decision.note}”`}{" "}
          <button className="link" disabled={record.isPending} onClick={() => decide("cleared")}>
            Undo
          </button>
        </p>
      ) : (
        <>
          <label>
            Reason (optional)
            <input value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="row">
            <button
              className="btn primary"
              disabled={record.isPending}
              onClick={() => decide("accepted")}
            >
              Accept finding
            </button>
            <button className="btn" disabled={record.isPending} onClick={() => decide("need_info")}>
              Need info
            </button>
            <button className="btn" disabled={record.isPending} onClick={() => decide("rejected")}>
              Reject
            </button>
          </div>
          <p className="muted">
            Keel measures. The engineer decides, and the decision goes in the change log.
          </p>
        </>
      )}
      {record.isError && (
        <p className="text-fail" role="alert">
          Could not save the decision: {record.error.message}
        </p>
      )}
    </div>
  );
}
