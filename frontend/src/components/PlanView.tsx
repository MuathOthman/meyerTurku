import { Minus, Plus } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Verdict } from "@/lib/api";
import { layoutPins } from "@/lib/pinLayout";

export type PlanGeometry = {
  image: string;
  /** Drawing units at the image's top left corner, and the image's size in those units. */
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PlanPin = { id: string; label: string; verdict: Verdict; x: number; y: number };

/** A drawing with pins and shapes over it. Everything is placed in drawing units. */
export function PlanView({
  plan,
  alt,
  pins,
  selectedPin,
  focus,
  onSelectPin,
  tools,
  children,
}: {
  plan: PlanGeometry;
  alt: string;
  pins: PlanPin[];
  selectedPin: string | null;
  focus: [number, number] | null;
  onSelectPin: (id: string) => void;
  tools?: ReactNode;
  children?: ReactNode;
}) {
  const [zoom, setZoom] = useState(1);
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");
  const view = useRef<HTMLDivElement>(null);
  const focusX = focus?.[0];
  const focusY = focus?.[1];
  const stage = useRef<HTMLDivElement>(null);
  const [stageWidth, setStageWidth] = useState(0);

  // Labels keep their size on screen, so where they fit depends on the drawn size of the plan.
  useLayoutEffect(() => {
    const element = stage.current;
    if (!element) return;
    setStageWidth(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      setStageWidth(element.getBoundingClientRect().width),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const pinById = useMemo(() => new Map(pins.map((pin) => [pin.id, pin])), [pins]);
  const placed = useMemo(() => {
    const scale = stageWidth / plan.width;
    return layoutPins(
      pins.map((pin) => ({
        id: pin.id,
        x: (pin.x - plan.x) * scale,
        y: (pin.y - plan.y) * scale,
      })),
      stageWidth,
      plan.height * scale,
    );
  }, [pins, stageWidth, plan.x, plan.y, plan.width, plan.height]);

  useEffect(() => {
    const box = view.current;
    if (!box || focusX === undefined || focusY === undefined) return;
    box.scrollTo({
      left: ((focusX - plan.x) / plan.width) * box.scrollWidth - box.clientWidth / 2,
      top: ((focusY - plan.y) / plan.height) * box.scrollHeight - box.clientHeight / 2,
      behavior: "smooth",
    });
  }, [focusX, focusY, zoom, plan.x, plan.y, plan.width, plan.height]);

  return (
    <section className="card plan">
      <div className="plan-tools">
        {tools}
        <span className="zoom">
          <button aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom(zoom - 0.5)}>
            <Minus size={15} />
          </button>
          <span>{Math.round(zoom * 100)}%</span>
          <button aria-label="Zoom in" disabled={zoom >= 6} onClick={() => setZoom(zoom + 0.5)}>
            <Plus size={15} />
          </button>
          <button onClick={() => setZoom(1)}>Fit</button>
        </span>
      </div>
      <div className="plan-view" ref={view}>
        {state === "loading" && (
          <p className="plan-status" role="status">
            Loading the drawing…
          </p>
        )}
        {state === "failed" && (
          <p className="plan-status text-fail" role="alert">
            Could not load the drawing.
          </p>
        )}
        <div className="plan-stage" ref={stage} style={{ width: `${zoom * 100}%` }}>
          <img
            src={plan.image}
            alt={alt}
            onLoad={() => setState("ready")}
            onError={() => setState("failed")}
          />
          <svg viewBox={`${plan.x} ${plan.y} ${plan.width} ${plan.height}`} aria-label="Overlays">
            {children}
          </svg>
          <svg className="pin-leaders" aria-hidden="true">
            {placed.map((p) => {
              const verdict = pinById.get(p.id)?.verdict;
              return (
                <g
                  key={p.id}
                  data-verdict={verdict}
                  data-selected={p.id === selectedPin}
                  className="pin-leader"
                >
                  {p.moved && <line x1={p.anchorX} y1={p.anchorY} x2={p.x} y2={p.y} />}
                  {p.moved && <circle cx={p.anchorX} cy={p.anchorY} r={4} />}
                </g>
              );
            })}
          </svg>
          {placed.map((p) => {
            const pin = pinById.get(p.id);
            if (!pin) return null;
            return (
              <button
                key={p.id}
                className="pin"
                data-verdict={pin.verdict}
                aria-pressed={p.id === selectedPin}
                title={pin.label}
                style={{ left: p.x, top: p.y, width: p.width, height: p.height }}
                onClick={() => onSelectPin(p.id)}
              >
                {p.id}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
