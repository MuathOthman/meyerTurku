import { describe, expect, it } from "vitest";
import { fileOf, floorName } from "./floors";

describe("floorName", () => {
  it.each([
    ["MAIN DECK", "Main deck"],
    ["1st. DECK", "1st deck"],
    ["2nd. DECK", "2nd deck"],
    ["PLATFORM/GALLOW DECK", "Platform / gallow deck"],
    ["RCRV 01 Level (plan 8-4C)", "RCRV 01 Level (plan 8-4C)"],
  ])("tidies the deck name %s", (deck, name) => {
    expect(floorName(deck, `${deck} · sheet.pdf`)).toBe(name);
  });

  it("falls back to the file name without its extension", () => {
    expect(floorName(null, "deck_5-aft.pdf")).toBe("Deck 5 aft");
    expect(floorName(null, "image.png")).toBe("Image");
  });
});

describe("fileOf", () => {
  it("strips the deck from a sheet's source", () => {
    expect(fileOf("MAIN DECK", "MAIN DECK · ga-plan.pdf")).toBe("ga-plan.pdf");
    expect(fileOf(null, "image.png")).toBe("image.png");
  });
});
