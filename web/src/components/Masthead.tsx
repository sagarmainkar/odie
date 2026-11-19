import type { ReactNode } from "react";
import { datelineParts } from "../pulse";

/** The head of a Pulse in the Newspaper style: the date line (with the personality's name on its own Pulse), "Pulse"
 *  set large between double rules, and a strip of what the page holds ("4 need you · 1 on it · 6 done today"), the
 *  count that needs him in red. `corner` sits at the end of the date line (the avatar that opens Settings). Glass
 *  never draws it: its Pulse keeps the greeting. */
export function Masthead({ dateLine, counts, corner }: {
  dateLine: string; counts: { needs: number; onIt: number; done: number }; corner?: ReactNode;
}) {
  const parts = datelineParts(counts);
  return (
    <header className="masthead">
      <div className="masthead-top">
        <span className="masthead-date">{dateLine}</span>
        {corner}
      </div>
      <h1 className="masthead-name">Pulse</h1>
      <p className="masthead-strip">
        {parts.map((part, i) => (
          <span key={part}>
            {i > 0 && <span className="masthead-dot" aria-hidden="true"> · </span>}
            <span className={i === 0 && counts.needs > 0 ? "masthead-needs" : undefined}>{part}</span>
          </span>
        ))}
      </p>
    </header>
  );
}
