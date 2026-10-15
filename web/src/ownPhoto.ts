// One of Odie's own photos in the large view: what it is (/api/photos/<uuid>/info) and, for a video, the original
// fetched from iCloud on a tap (POST /api/photos/<uuid>/fetch, then GET until ready, then /original plays).
export type Original = { state: "missing" | "fetching" | "ready" | "failed"; error: string };
export type OwnInfo = { kind: "photo" | "video"; original: Original; taken?: string; place?: string; people?: string[]; has_big?: boolean };
export type View = { show: "picture" | "poster" | "video"; button: "Play" | "Try again" | null; note: string };

const OWN = /^\/api\/photos\/([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\/(thumb|big)$/;

/** The uuid in one of Odie's own photo addresses: "/api/photos/<uuid>/thumb" → "<uuid>"; anything else → null. */
export function uuidOf(url: string): string | null {
  const m = OWN.exec(url);
  return m ? m[1] : null;
}

/**
 * What the large view shows. A photo is its big copy. A video is its poster with Play until the original is here,
 * "Fetching from iCloud…" while Photos downloads it, the player once it's here, and the reason with Try again if not.
 *   {kind: "video", original: {state: "missing"}}  → poster + Play
 *   {kind: "video", original: {state: "ready"}}    → the video
 */
export function viewFor(info: OwnInfo): View {
  if (info.kind !== "video") return { show: "picture", button: null, note: "" };
  const o = info.original;
  if (o.state === "ready") return { show: "video", button: null, note: "" };
  if (o.state === "fetching") return { show: "poster", button: null, note: "Fetching from iCloud…" };
  if (o.state === "failed") return { show: "poster", button: "Try again", note: o.error };
  return { show: "poster", button: "Play", note: "" };
}

export const originalUrl = (uuid: string) => `/api/photos/${uuid}/original`;
