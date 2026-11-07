import { createRouter, rootRouteId } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

describe("routes", () => {
  const router = createRouter({ routeTree });
  it.each([
    "/",
    "/app",
    "/app/new",
    "/app/rules",
    "/app/log",
    "/app/analysis/abc",
    "/app/projects/new",
    "/app/projects/default/files",
    "/app/projects/default/rules",
    "/app/reports",
    "/app/wall",
    "/app/agents/check",
    "/app/settings",
    "/login",
    "/signup",
  ])("%s has a page", (path) => {
    expect(router.matchRoutes(path).at(-1)?.routeId).not.toBe(rootRouteId);
  });
});
