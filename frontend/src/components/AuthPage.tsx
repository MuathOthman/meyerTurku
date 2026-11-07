import { Link, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { KeelLogo } from "@/components/KeelLogo";
import { logIn, signUp } from "@/lib/auth";

const MIN_PASSWORD = 8;

export function AuthPage({ mode }: { mode: "login" | "signup" }) {
  const navigate = useNavigate();
  const signup = mode === "signup";
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const entered = new FormData(e.currentTarget);
    const email = String(entered.get("email"));
    const password = String(entered.get("password"));
    setPending(true);
    setError(null);
    try {
      if (signup) await signUp({ name: String(entered.get("name")), email, password });
      else await logIn({ email, password });
      await navigate({ to: "/app" });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong. Try again.");
      setPending(false);
    }
  };

  return (
    <div className="auth">
      <header>
        <Link to="/" aria-label="Keel home" className="sidebar-logo">
          <KeelLogo />
        </Link>
      </header>
      <main>
        <section className="card auth-card">
          <h1>{signup ? "Create your account" : "Log in to Keel"}</h1>
          {error && (
            <p className="notice notice-fail" role="alert">
              {error}
            </p>
          )}
          <form className="form" onSubmit={submit}>
            {signup && (
              <label>
                Name
                <input name="name" autoComplete="name" maxLength={120} required />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" autoComplete="email" maxLength={254} required />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete={signup ? "new-password" : "current-password"}
                minLength={signup ? MIN_PASSWORD : undefined}
                maxLength={128}
                required
              />
              {signup && <small className="muted">At least {MIN_PASSWORD} characters.</small>}
            </label>
            <button className="btn primary" type="submit" disabled={pending}>
              {signup ? "Sign up" : "Log in"}
            </button>
          </form>
          <p className="muted">
            {signup ? "Already have an account? " : "New to Keel? "}
            <Link to={signup ? "/login" : "/signup"}>{signup ? "Log in" : "Sign up"}</Link>
          </p>
        </section>
      </main>
    </div>
  );
}
