import { useState } from "react";
import type { LibraInfo } from "../voiceSettings";
import { libraToneLabel } from "../voiceSettings";

type Props = {
  libra: LibraInfo;
  chosen: boolean;  // Libra is the read-aloud engine now: the tone choice shows
  save: (body: { libra_style?: string; libra_url?: string }) => Promise<string | null>;  // null when saved, else why not
};

/** Libra's own part of Settings → Voice: the tone a reply is read in when the model names none, and where the Libra
 *  voice server answers (this Mac, or another on the home network). The address also shows while Libra isn't
 *  answering, so it can be fixed before Libra can be chosen. */
export function LibraSettings({ libra, chosen, save }: Props) {
  const [address, setAddress] = useState(libra.url);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function saveAddress() {
    setBusy(true);
    const refused = await save({ libra_url: address });
    setProblem(refused);
    setBusy(false);
  }

  const tones = ["", ...libra.tones];
  return (
    <>
      {chosen && (
        <section className="flex flex-col gap-2">
          <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Tone</div>
          <div className="glass rounded-card p-3 flex flex-col gap-3">
            <div className="text-small leading-[18px] text-muted px-1">
              Odie picks a tone for each reply and laughs or sighs where it fits; you never see the marks, you only hear
              them. This tone is used when a reply doesn't pick one.
            </div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Libra tone">
              {tones.map((tone) => {
                const on = tone === libra.tone;
                return (
                  <button key={tone || "none"} role="radio" aria-checked={on} onClick={() => void save({ libra_style: tone })}
                    className={`rounded-control border px-3 h-9 text-small ${on ? "border-ember-text bg-ember-tint text-ember-text font-semibold" : "border-line text-muted"}`}>
                    {libraToneLabel(tone)}
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}
      <section className="flex flex-col gap-2">
        <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Libra server</div>
        <div className="glass rounded-card p-3 flex flex-col gap-2">
          <div className="text-small leading-[18px] text-muted px-1">
            {libra.answering ? "Answering." : "Not answering here: start it with ./libra start in its folder, or fix the address."}
          </div>
          <div className="flex gap-2">
            <input value={address} onChange={(e) => setAddress(e.target.value)} aria-label="Libra server address"
              inputMode="url" autoCapitalize="off" autoCorrect="off" spellCheck={false}
              className="flex-1 min-w-0 h-11 rounded-control border border-line bg-well px-3 text-body" />
            <button onClick={() => void saveAddress()} disabled={busy || address.trim() === libra.url}
              className="pill px-4 disabled:opacity-40">Save</button>
          </div>
          {problem && <div className="text-small leading-[18px] text-warn-ink px-1">{problem}</div>}
        </div>
      </section>
    </>
  );
}
