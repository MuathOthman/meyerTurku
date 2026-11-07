/** Places finding labels on a plan so that none covers another label or another pin's location. */

export type PinAnchor = { id: string; x: number; y: number };

export type PlacedPin = {
  id: string;
  /** The location on the drawing, in pixels on the stage. */
  anchorX: number;
  anchorY: number;
  /** The label's centre and size, in pixels on the stage. */
  x: number;
  y: number;
  width: number;
  height: number;
  moved: boolean;
};

const HEIGHT = 22;
const GAP = 6;
const ANCHOR_SIZE = 10;
const RING_STEP = 8;
const DIRECTIONS = 16;

type Box = { x: number; y: number; width: number; height: number };

function overlaps(a: Box, b: Box, gap: number): boolean {
  return (
    Math.abs(a.x - b.x) < (a.width + b.width) / 2 + gap &&
    Math.abs(a.y - b.y) < (a.height + b.height) / 2 + gap
  );
}

function labelWidth(id: string): number {
  return 14 + id.length * 7.5;
}

/**
 * Earlier pins are placed first, so the order passed in decides who keeps its exact spot.
 * Pins outside the stage, such as findings about the whole deck, are left out.
 */
export function layoutPins(anchors: PinAnchor[], stageWidth: number, stageHeight: number): PlacedPin[] {
  const onStage = anchors.filter(
    (a) => a.x >= 0 && a.y >= 0 && a.x <= stageWidth && a.y <= stageHeight,
  );
  const anchorBoxes = onStage.map((a) => ({ x: a.x, y: a.y, width: ANCHOR_SIZE, height: ANCHOR_SIZE }));
  const placed: Box[] = [];

  return onStage.map((anchor, index) => {
    const width = labelWidth(anchor.id);
    const inBounds = (x: number, y: number) =>
      x - width / 2 >= 0 &&
      x + width / 2 <= stageWidth &&
      y - HEIGHT / 2 >= 0 &&
      y + HEIGHT / 2 <= stageHeight;
    const isFree = (x: number, y: number) => {
      const box = { x, y, width, height: HEIGHT };
      return (
        inBounds(x, y) &&
        placed.every((other) => !overlaps(box, other, GAP)) &&
        anchorBoxes.every((other, i) => i === index || !overlaps(box, other, 0))
      );
    };

    const spot = findSpot(anchor, isFree, Math.hypot(stageWidth, stageHeight));
    // A plan too small to hold every label: stay on the drawing, the engineer can zoom in.
    const x = spot ? spot[0] : Math.min(Math.max(anchor.x, width / 2), stageWidth - width / 2);
    const y = spot ? spot[1] : Math.min(Math.max(anchor.y, HEIGHT / 2), stageHeight - HEIGHT / 2);
    placed.push({ x, y, width, height: HEIGHT });
    return {
      id: anchor.id,
      anchorX: anchor.x,
      anchorY: anchor.y,
      x,
      y,
      width,
      height: HEIGHT,
      moved: x !== anchor.x || y !== anchor.y,
    };
  });
}

/** The free spot nearest the anchor, searching outward in rings. */
function findSpot(
  anchor: PinAnchor,
  isFree: (x: number, y: number) => boolean,
  furthest: number,
): [number, number] | null {
  if (isFree(anchor.x, anchor.y)) return [anchor.x, anchor.y];
  for (let radius = RING_STEP * 2; radius <= furthest; radius += RING_STEP) {
    for (let i = 0; i < DIRECTIONS; i++) {
      const angle = -Math.PI / 2 + (i * 2 * Math.PI) / DIRECTIONS;
      const x = anchor.x + radius * Math.cos(angle);
      const y = anchor.y + radius * Math.sin(angle);
      if (isFree(x, y)) return [x, y];
    }
  }
  return null;
}
