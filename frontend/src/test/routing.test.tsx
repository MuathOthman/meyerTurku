import { createRouter, rootRouteId } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

describe("routes", () => {
  const router = createRouter({ routeTree });
  it.each(["/", "/app", "/app/new", "/app/rules", "/app/log", "/app/analysis/abc"])(
    "%s has a page",
    (path) => {
      expect(router.matchRoutes(path).at(-1)?.routeId).not.toBe(rootRouteId);
    },
  );
});
