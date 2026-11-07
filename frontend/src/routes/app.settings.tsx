import { createFileRoute, useNavigate, useRouteContext } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { logOut } from "@/lib/auth";

export const Route = createFileRoute("/app/settings")({
  head: () => ({ meta: [{ title: "Settings · Keel" }] }),
  component: SettingsPage,
});

function SettingsPage() {
  const navigate = useNavigate();
  const { user } = useRouteContext({ from: "/app" });
  const [error, setError] = useState<string | null>(null);

  const leave = async () => {
    setError(null);
    try {
      await logOut();
      await navigate({ to: "/login" });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not log out. Try again.");
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <span className="crumb">Workspace</span>
          <h1>Settings</h1>
          <p className="muted">Manage how Keel connects to your AI provider.</p>
        </div>
      </header>
      <div className="settings-stack">
        <ApiKeyCard />
        <section className="card" aria-labelledby="account-title">
          <div className="card-head">
            <h2 id="account-title">Account</h2>
          </div>
          <div className="key-row pad">
            <span>
              <strong>{user.name}</strong> <span className="muted">{user.email}</span>
            </span>
            <button className="btn" onClick={leave}>
              Log out
            </button>
            {error && (
              <p className="notice notice-fail" role="alert">
                {error}
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}

/** For show only. The typed key is thrown away on save and the app keeps using its own key. */
function ApiKeyCard() {
  const [editing, setEditing] = useState(false);

  const save = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setEditing(false);
  };

  return (
    <section className="card" aria-labelledby="api-key-title">
      <div className="card-head">
        <h2 id="api-key-title">API key</h2>
      </div>
      {editing ? (
        <form className="key-row pad" onSubmit={save}>
          <label className="key-label" htmlFor="api-key">
            OpenAI
          </label>
          <input
            id="api-key"
            className="key-input"
            type="password"
            autoComplete="off"
            autoFocus
            required
          />
          <div className="row">
            <button className="btn primary" type="submit">
              Save
            </button>
            <button className="btn" type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="key-row pad">
          <span className="key-label">OpenAI</span>
          <span className="key-dots" role="img" aria-label="API key, hidden">
            {"•".repeat(32)}
          </span>
          <button className="btn" onClick={() => setEditing(true)}>
            Edit
          </button>
        </div>
      )}
    </section>
  );
}
