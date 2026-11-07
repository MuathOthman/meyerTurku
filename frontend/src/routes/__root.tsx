import { createRootRoute, HeadContent, Link, Outlet } from "@tanstack/react-router";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { title: "Keel · Compliance Assistant" },
      { name: "description", content: "Checks ship drawings against a rule database." },
    ],
  }),
  component: () => (
    <>
      <HeadContent />
      <Outlet />
    </>
  ),
  notFoundComponent: NotFound,
  errorComponent: ({ error }) => (
    <main className="center-page">
      <h1>This page didn't load</h1>
      <p>{(error as Error).message}</p>
      <a className="btn" href="/">
        Go home
      </a>
    </main>
  ),
});

function NotFound() {
  return (
    <main className="center-page">
      <h1>Page not found</h1>
      <Link className="btn" to="/">
        Go home
      </Link>
    </main>
  );
}
