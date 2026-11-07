import { Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Verdict } from "@/lib/api";

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
        <div className="plan-stage" style={{ width: `${zoom * 100}%` }}>
          <img
            src={plan.image}
            alt={alt}
            onLoad={() => setState("ready")}
            onError={() => setState("failed")}
          />
          <svg viewBox={`${plan.x} ${plan.y} ${plan.width} ${plan.height}`} aria-label="Overlays">
            {children}
          </svg>
          {pins.map((pin) => (
            <button
              key={pin.id}
              className="pin"
              data-verdict={pin.verdict}
              aria-pressed={pin.id === selectedPin}
              title={pin.label}
              style={{
                left: `${((pin.x - plan.x) / plan.width) * 100}%`,
                top: `${((pin.y - plan.y) / plan.height) * 100}%`,
              }}
              onClick={() => onSelectPin(pin.id)}
            >
              <span className="pin-dot" />
              {pin.id}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
