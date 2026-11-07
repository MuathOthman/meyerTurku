import { afterEach, describe, expect, it, vi } from "vitest";
import { currentUser, logIn } from "./auth";

const USER = { id: "1", name: "Ada", email: "ada@example.com" };

function answer(status: number, body: object) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));
}

describe("auth", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads who is logged in", async () => {
    answer(200, { user: USER });
    await expect(currentUser()).resolves.toEqual(USER);
  });

  it("treats a backend or database failure as logged out", async () => {
    answer(503, { detail: "The accounts database cannot be reached." });
    await expect(currentUser()).resolves.toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(currentUser()).resolves.toBeNull();
  });

  it("shows the backend's message when a login is refused", async () => {
    answer(401, { detail: "Wrong email or password." });
    await expect(logIn({ email: "a@b.co", password: "x" })).rejects.toThrow("Wrong email or password.");
  });
});
