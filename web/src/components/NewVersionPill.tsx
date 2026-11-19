import { fresh, useNewVersionPill } from "../freshness";

/** A quiet pill at the top while a new version of the app waits for a safe moment to reload; a tap reloads now. */
export function NewVersionPill() {
  const shown = useNewVersionPill();
  if (!shown) return null;
  return (
    <button type="button" onClick={() => fresh.tap()}
      className="pill fixed left-1/2 lg:left-[calc(50%+42px)] -translate-x-1/2 top-[max(env(safe-area-inset-top),10px)] z-40 h-[34px] text-ui font-semibold rise">
      <span className="text-muted">New version</span><span aria-hidden="true" className="text-muted">·</span><span>Reload</span>
    </button>
  );
}
