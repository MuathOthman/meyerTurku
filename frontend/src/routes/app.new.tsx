import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useAnalyse, useMeta } from "@/lib/api";

export const Route = createFileRoute("/app/new")({
  head: () => ({ meta: [{ title: "Upload a drawing · Keel" }] }),
  component: NewAnalysis,
});

function NewAnalysis() {
  const meta = useMeta();
  const navigate = useNavigate();
  const analyse = useAnalyse();
  const llm = meta.data?.llm ?? null;
  const [useAi, setUseAi] = useState(true);
  const [shipType, setShipType] = useState("");

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const entered = new FormData(e.currentTarget);
    const form = new FormData();
    form.set("file", entered.get("file") as File);
    // People count pages from 1. The backend counts from 0.
    form.set("page", String(Number(entered.get("page")) - 1));
    const scale = String(entered.get("mm_per_unit") ?? "");
    if (scale) form.set("mm_per_unit", scale);
    form.set("use_ai", String(useAi && !!llm));
    form.set("ship_type", shipType);
    analyse.mutate(form, {
      onSuccess: (result) => navigate({ to: "/app/analysis/$jobId", params: { jobId: result.id } }),
    });
  };

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Checked deck</span>
          <h1>Upload a drawing</h1>
          <p className="muted">
            Keel finds the spaces on the drawing, then opens it as a checked deck with the
            regulations for each space.
          </p>
        </div>
      </header>
      <form className="card pad stack form" onSubmit={submit}>
        <label>
          Drawing (PDF or image, up to 80 MB)
          <input type="file" name="file" required accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp" />
        </label>
        <label>
          Ship type
          <select value={shipType} required onChange={(e) => setShipType(e.target.value)}>
            <option value="" disabled>
              Choose, because the limits differ
            </option>
            <option value="cargo">Cargo ship: escape routes at least 700 mm</option>
            <option value="passenger">Passenger ship: escape routes at least 900 mm</option>
          </select>
        </label>
        <label>
          PDF page number
          <input type="number" name="page" min={1} defaultValue={1} required />
        </label>
        <label>
          Scale, mm per PDF point (only if Keel cannot read it)
          <input type="number" name="mm_per_unit" step="any" min={0} placeholder="Not measured" />
          <small className="muted">
            Without a scale, Keel lists the regulations but measures nothing. Images are never
            measured.
          </small>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={useAi && !!llm}
            disabled={!llm}
            onChange={(e) => setUseAi(e.target.checked)}
          />
          <span>
            Use AI for spaces with no readable label.{" "}
            {llm ? (
              <span className="text-warn">Sends images of the drawing to {llm}.</span>
            ) : (
              "No AI is configured on the backend."
            )}
          </span>
        </label>
        <div className="row">
          <button className="btn primary" disabled={analyse.isPending}>
            {analyse.isPending ? "Uploading…" : "Upload and check"}
          </button>
        </div>
        {analyse.isError && (
          <p className="notice notice-fail" role="alert">
            Could not upload this file: {analyse.error.message}
          </p>
        )}
      </form>
    </>
  );
}
