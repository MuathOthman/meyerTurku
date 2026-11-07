import { createFileRoute } from "@tanstack/react-router";
import { FileText, Link2, NotebookText, Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import {
  requirement,
  useAddSource,
  useDeleteSource,
  useRules,
  useSources,
  type Rule,
  type Source,
} from "@/lib/api";

export const Route = createFileRoute("/app/rules")({
  head: () => ({ meta: [{ title: "Rules · Keel" }] }),
  component: RulesPage,
});

function RulesPage() {
  const rules = useRules();
  const sources = useSources();
  const [adding, setAdding] = useState(false);
  const backing = (id: string) => sources.data?.filter((s) => s.rule_ids.includes(id)) ?? [];
  const cited = uniqueCitations(rules.data ?? []);
  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Rules</span>
          <h1>Rules and sources</h1>
          <p className="muted">
            The regulations Keel can check, and the documents behind them. Add a regulation PDF, a
            web page or a note, with the pages that matter and the rules it backs. Each project then
            picks the rules it needs.
          </p>
        </div>
        <div className="page-actions">
          <button className="btn primary" onClick={() => setAdding(!adding)}>
            <Plus size={16} /> Add a source
          </button>
        </div>
      </header>

      {adding && <AddSource rules={rules.data ?? []} onDone={() => setAdding(false)} />}

      {(rules.isError || sources.isError) && (
        <p className="notice notice-fail" role="alert">
          {(rules.error ?? sources.error)?.message}
        </p>
      )}

      <section className="card" aria-label="Sources">
        <div className="card-head">
          <h2>Sources</h2>
          <span className="muted">{(sources.data?.length ?? 0) + cited.length}</span>
        </div>
        {sources.isPending && <p className="pad muted">Loading…</p>}
        {sources.data?.map((s) => (
          <SourceRow key={s.id} source={s} />
        ))}
        {sources.data?.length === 0 && (
          <p className="pad muted">
            No sources added yet. The ones below are cited by the rule database.
          </p>
        )}
        {cited.map((c) => (
          <div key={c.source} className="list-row">
            <Link2 size={18} className="muted" />
            <div>
              <strong>
                {c.ref_url ? (
                  <a href={c.ref_url} target="_blank" rel="noreferrer">
                    {c.source}
                  </a>
                ) : (
                  c.source
                )}
              </strong>
              <small className="muted">Cited by {c.ruleIds.join(", ")}</small>
            </div>
            <span className="status">Rule database</span>
          </div>
        ))}
      </section>

      <section className="card" aria-label="Rule database">
        <div className="card-head">
          <h2>Rule database</h2>
          <span className="muted">{rules.data?.length ?? "…"} rules</span>
        </div>
        {rules.isPending && <p className="pad muted">Loading rules…</p>}
        {rules.data?.map((r) => {
          const added = backing(r.id);
          return (
            <div key={r.id} className="list-row">
              <div>
                <strong>{r.title}</strong>
                <small className="muted">
                  {r.id} ·{" "}
                  {r.ref_url ? (
                    <a href={r.ref_url} target="_blank" rel="noreferrer">
                      {r.source}
                    </a>
                  ) : (
                    r.source
                  )}
                </small>
                {r.interpretation_note && <small className="muted">{r.interpretation_note}</small>}
                {added.length > 0 && (
                  <small>Backed by {added.map((s) => s.title).join(", ")}</small>
                )}
              </div>
              <span className="rule-value">{requirement(r)}</span>
              <span className="status" data-status={r.value_status}>
                {r.value_status}
              </span>
            </div>
          );
        })}
      </section>
    </>
  );
}

function uniqueCitations(rules: Rule[]) {
  const bySource = new Map<string, { source: string; ref_url: string; ruleIds: string[] }>();
  for (const r of rules) {
    const entry = bySource.get(r.source) ?? { source: r.source, ref_url: r.ref_url, ruleIds: [] };
    entry.ruleIds.push(r.id);
    bySource.set(r.source, entry);
  }
  return [...bySource.values()];
}

/** A PDF opens at the first page the engineer listed. */
function fileHref(s: Source) {
  const first = /^\s*(\d+)/.exec(s.pages)?.[1];
  return `/api/sources/${s.id}/file${first && s.file_name?.toLowerCase().endsWith(".pdf") ? `#page=${first}` : ""}`;
}

function SourceRow({ source: s }: { source: Source }) {
  const remove = useDeleteSource();
  const Icon = s.file_name ? FileText : s.url ? Link2 : NotebookText;
  return (
    <div className="list-row">
      <Icon size={18} className="muted" />
      <div>
        <strong>{s.title}</strong>
        <small className="muted">
          {[
            s.pages && `Pages ${s.pages}`,
            s.rule_ids.length ? `Backs ${s.rule_ids.join(", ")}` : "Not linked to a rule yet",
            `added ${new Date(s.added_at).toLocaleDateString()}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </small>
        {s.note && <small>{s.note}</small>}
        <span className="source-links">
          {s.file_name && (
            <a href={fileHref(s)} target="_blank" rel="noreferrer">
              Open {s.file_name}
            </a>
          )}
          {s.url && (
            <a href={s.url} target="_blank" rel="noreferrer">
              {s.url.replace(/^https?:\/\//, "").slice(0, 60)}
            </a>
          )}
        </span>
      </div>
      <button
        className="icon-btn"
        aria-label={`Delete ${s.title}`}
        disabled={remove.isPending}
        onClick={() => {
          if (window.confirm(`Delete the source “${s.title}”? This cannot be undone.`))
            remove.mutate(s.id);
        }}
      >
        <Trash2 size={16} />
      </button>
    </div>
  );
}

function AddSource({ rules, onDone }: { rules: Rule[]; onDone: () => void }) {
  const add = useAddSource();
  const [chosen, setChosen] = useState<string[]>([]);
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const file = form.get("file");
    if (file instanceof File && !file.name) form.delete("file");
    form.set("rule_ids", chosen.join(","));
    add.mutate(form, { onSuccess: onDone });
  };
  return (
    <form className="card pad stack form" onSubmit={submit} aria-label="Add a source">
      <h2>Add a source</h2>
      <label>
        Title
        <input name="title" required maxLength={200} placeholder="FSS Code, chapter 13" />
      </label>
      <div className="source-pair">
        <label>
          File (PDF, image, Word, Excel or text)
          <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.txt,.md,.doc,.docx,.xlsx" />
        </label>
        <label>
          Or a link
          <input name="url" type="url" placeholder="https://…" />
        </label>
      </div>
      <label>
        Pages that matter
        <input name="pages" maxLength={200} placeholder="12-14, 31" />
      </label>
      <fieldset className="rule-picks">
        <legend>Rules it backs</legend>
        {rules.map((r) => (
          <label key={r.id} className="check">
            <input
              type="checkbox"
              checked={chosen.includes(r.id)}
              onChange={(e) =>
                setChosen(e.target.checked ? [...chosen, r.id] : chosen.filter((i) => i !== r.id))
              }
            />
            <span>
              {r.title} <small className="muted">{r.id}</small>
            </span>
          </label>
        ))}
      </fieldset>
      <label>
        Note
        <textarea
          name="note"
          rows={3}
          maxLength={4000}
          placeholder="What this source says, in your words"
        />
      </label>
      {add.isError && (
        <p className="notice notice-fail" role="alert">
          {add.error.message}
        </p>
      )}
      <div className="row">
        <button className="btn primary" disabled={add.isPending}>
          {add.isPending ? "Saving…" : "Save source"}
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
