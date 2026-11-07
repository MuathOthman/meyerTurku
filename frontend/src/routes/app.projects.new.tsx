import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { useCreateProject } from "@/lib/api";

export const Route = createFileRoute("/app/projects/new")({
  head: () => ({ meta: [{ title: "New project · Keel" }] }),
  component: NewProject,
});

function NewProject() {
  const navigate = useNavigate();
  const create = useCreateProject();
  const [shipType, setShipType] = useState("");

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name") ?? "").trim();
    create.mutate(
      { name, ship_type: shipType },
      {
        onSuccess: (project) =>
          navigate({ to: "/app/projects/$projectId/files", params: { projectId: project.id } }),
      },
    );
  };

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Projects</span>
          <h1>New project</h1>
          <p className="muted">
            One project per ship. Then upload its general arrangement and choose the rules it is
            checked against.
          </p>
        </div>
      </header>
      <form className="card pad stack form" onSubmit={submit}>
        <label>
          Name
          <input name="name" required maxLength={120} placeholder="Cruise ship NB 1234" autoFocus />
        </label>
        <label>
          Ship type
          <select value={shipType} required onChange={(e) => setShipType(e.target.value)}>
            <option value="" disabled>
              Choose, because the limits differ
            </option>
            <option value="passenger">Passenger ship: escape routes at least 900 mm</option>
            <option value="cargo">Cargo ship: escape routes at least 700 mm</option>
          </select>
        </label>
        {create.isError && (
          <p className="notice notice-fail" role="alert">
            {create.error.message}
          </p>
        )}
        <div className="row">
          <button className="btn primary" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </button>
        </div>
      </form>
    </>
  );
}
