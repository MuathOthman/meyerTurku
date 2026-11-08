// Projects and their floors (checked decks), named for people rather than by file name.
import { useMemo } from "react";
import { useAnalyses, useFindings, useMeta, useProjects, type Project, type Verdict } from "./api";

/** Holds the built-in demo deck and every floor saved before projects existed. */
export const DEFAULT_PROJECT = "default";

export function useProject(id: string | undefined): Project | undefined {
  return useProjects().data?.find((p) => p.id === id);
}

export type Floor = {
  /** The saved analysis, or null for the built-in demo deck at /app. */
  analysisId: string | null;
  project: string;
  name: string;
  file: string;
  page: number;
  status: "running" | "done";
  counts: Record<Verdict, number> | null;
  createdAt: string;
};

/** The uploaded file's name. The backend stores "<deck> · <file>" for one deck cut from a sheet. */
export function fileOf(deck: string | null, source: string): string {
  const prefix = deck ? `${deck} · ` : "";
  return prefix && source.startsWith(prefix) ? source.slice(prefix.length) : source;
}

/** "1st. DECK" → "1st deck", "PLATFORM/GALLOW DECK" → "Platform / gallow deck". */
export function floorName(deck: string | null, source: string): string {
  const raw =
    deck ??
    fileOf(null, source)
      .replace(/\.[a-z0-9]+$/i, "")
      .replace(/[_-]+/g, " ");
  const words = raw
    .replace(/(\d)(st|nd|rd|th)\./gi, "$1$2")
    .replace(/\s*\/\s*/g, " / ")
    .replace(/\s+/g, " ")
    .trim();
  const shouting = !/[a-z]/.test(words.replace(/\d(st|nd|rd|th)\b/g, ""));
  const tidy = shouting ? words.toLowerCase() : words;
  return tidy.charAt(0).toUpperCase() + tidy.slice(1) || "Untitled floor";
}

/** One project's floors, or every floor without a project. The demo deck first, then uploads
 * in the order they came in, then by name. */
export function useFloors(projectId?: string): { floors: Floor[]; isPending: boolean } {
  const meta = useMeta();
  const analyses = useAnalyses();
  const floors = useMemo(() => {
    const uploaded: Floor[] = (analyses.data ?? []).map((a) => ({
      analysisId: a.id,
      project: a.project,
      name: floorName(a.deck, a.source),
      file: fileOf(a.deck, a.source),
      page: a.page,
      status: a.status,
      counts: a.counts,
      createdAt: a.created_at,
    }));
    uploaded.sort(
      (a, b) =>
        a.createdAt.localeCompare(b.createdAt) ||
        a.name.localeCompare(b.name, undefined, { numeric: true }),
    );
    const demo: Floor[] = meta.data
      ? [
          {
            analysisId: null,
            project: DEFAULT_PROJECT,
            name: meta.data.deck,
            file: meta.data.source_pdf,
            page: meta.data.page_index,
            status: "done",
            counts: null,
            createdAt: "",
          },
        ]
      : [];
    return [...demo, ...uploaded].filter((f) => !projectId || f.project === projectId);
  }, [meta.data, analyses.data, projectId]);
  return { floors, isPending: meta.isPending || analyses.isPending };
}

/** Floors with the demo deck's counts filled in, which costs a measurement of that deck. */
export function useFloorsWithCounts(projectId?: string): { floors: Floor[]; isPending: boolean } {
  const { floors, isPending } = useFloors(projectId);
  const demo = useFindings("");
  const counts = demo.data?.counts ?? null;
  return {
    floors: useMemo(
      () => floors.map((f) => (f.analysisId ? f : { ...f, counts })),
      [floors, counts],
    ),
    isPending,
  };
}

export const openFindings = (f: Floor) => (f.counts ? f.counts.FAIL + f.counts.NEEDS_REVIEW : null);
