import { createFileRoute, Link } from "@tanstack/react-router";
import { KeelLogo } from "@/components/KeelLogo";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Keel · Compliance Assistant" },
      {
        name: "description",
        content: "Keel checks ship drawings against a rule database. An engineer decides.",
      },
    ],
  }),
  component: Landing,
});

function Landing() {
  return (
    <div className="landing">
      <header>
        <KeelLogo />
      </header>
      <main>
        <h1>Ship design compliance, checked before class does.</h1>
        <p>
          Keel reads a general arrangement drawing, works out its rooms, doors and escape routes,
          and checks them against a rule database. Every finding shows the measured value, the
          required value and its source. AI reads, code measures, the engineer decides.
        </p>
        <div className="row">
          <Link to="/app" className="btn primary">
            Open the checked deck
          </Link>
          <Link to="/app/new" className="btn">
            Upload a drawing
          </Link>
        </div>
      </main>
    </div>
  );
}
