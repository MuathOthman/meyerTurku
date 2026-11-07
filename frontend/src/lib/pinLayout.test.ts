import { describe, expect, it } from "vitest";
import { layoutPins, type PlacedPin } from "./pinLayout";

function touching(a: PlacedPin, b: PlacedPin): boolean {
  return (
    Math.abs(a.x - b.x) < (a.width + b.width) / 2 && Math.abs(a.y - b.y) < (a.height + b.height) / 2
  );
}

describe("layoutPins", () => {
  it("leaves a lone pin on its location", () => {
    const [pin] = layoutPins([{ id: "F-01", x: 200, y: 100 }], 800, 300);
    expect(pin).toMatchObject({ x: 200, y: 100, moved: false });
  });

  it("separates pins on the same spot and keeps every location", () => {
    const anchors = Array.from({ length: 12 }, (_, i) => ({
      id: `F-${String(i + 1).padStart(2, "0")}`,
      x: 400,
      y: 150,
    }));
    const pins = layoutPins(anchors, 800, 300);
    expect(pins).toHaveLength(12);
    for (const a of pins) {
      expect([a.anchorX, a.anchorY]).toEqual([400, 150]);
      for (const b of pins) if (a !== b) expect(touching(a, b)).toBe(false);
    }
  });

  it("does not cover the location of another pin", () => {
    const pins = layoutPins(
      [
        { id: "F-01", x: 400, y: 150 },
        { id: "F-02", x: 410, y: 150 },
      ],
      800,
      300,
    );
    for (const pin of pins) {
      const other = pins.find((p) => p !== pin)!;
      const coversOther =
        Math.abs(pin.x - other.anchorX) < pin.width / 2 && Math.abs(pin.y - other.anchorY) < pin.height / 2;
      expect(coversOther).toBe(false);
    }
  });

  it("keeps labels inside the plan near its edges", () => {
    const pins = layoutPins(
      [
        { id: "F-01", x: 1, y: 1 },
        { id: "F-02", x: 799, y: 299 },
      ],
      800,
      300,
    );
    for (const pin of pins) {
      expect(pin.x - pin.width / 2).toBeGreaterThanOrEqual(0);
      expect(pin.x + pin.width / 2).toBeLessThanOrEqual(800);
      expect(pin.y - pin.height / 2).toBeGreaterThanOrEqual(0);
      expect(pin.y + pin.height / 2).toBeLessThanOrEqual(300);
    }
  });

  it("leaves out findings with no place on the plan", () => {
    expect(layoutPins([{ id: "F-04", x: -40, y: -900 }], 800, 300)).toEqual([]);
  });
});
