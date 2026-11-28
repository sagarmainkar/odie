import { useState } from "react";
import type { ServerInfo, ServerParts } from "../voiceSettings";
import { libraSpeedLabel, libraToneLabel } from "../voiceSettings";

export type ServerSave = { server_style?: string; server_url?: string; server_speed?: string; hear_model?: string };

type Props = {
  server: ServerInfo;
  parts: ServerParts;  // which parts show for the engine on screen (serverParts)
  save: (body: ServerSave) => Promise<string | null>;  // null when saved, else why not
  hear: (tone: string, speed?: string) => void;  // plays a line in this tone, at this speed (else the saved one)
  playing: string | null;        // the tone whose line is playing now
};

/** The voice server's part of Settings → Voice: for a model with styles, the tone a reply is read in when the model
 *  names none (tapping one plays a line in it) and how quickly it talks; which model hears dictation; and where the
 *  voice server (voiced) answers: this Mac, or another on the home network. */
export function ServerSettings({ server, parts, save, hear, playing }: Props) {
  const [address, setAddress] = useState(server.url);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function saveAddress() {
    setBusy(true);
    const refused = await save({ server_url: address });
    setProblem(refused);
    setBusy(false);
  }

  const tones = ["", ...server.tones];
  const speeds = server.speeds ?? [];

  async function pickTone(tone: string) {
    hear(tone);  // in the tap itself: a phone plays sound only from one
    await save({ server_style: tone });
  }

  async function pickSpeed(speed: string) {
    hear(server.tone, speed);  // in the tap itself, at the speed just tapped
    await save({ server_speed: speed });
  }
  return (
    <>
      {parts.tone && (
        <section className="flex flex-col gap-2">
          <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Tone</div>
          <div className="glass rounded-card p-3 flex flex-col gap-3">
            <div className="text-small leading-[18px] text-muted px-1">
              Odie picks a tone for each reply and laughs or sighs where it fits; you never see the marks, you only hear
              them. This tone is used when a reply doesn't pick one. Tap a tone to hear it.
            </div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Tone">
              {tones.map((tone) => {
                const on = tone === server.tone;
                return (
                  <button key={tone || "none"} role="radio" aria-checked={on} onClick={() => void pickTone(tone)}
                    className={`rounded-control border px-3 h-9 text-small flex items-center gap-1.5 ${on ? "border-ember-text bg-ember-tint text-ember-text font-semibold" : "border-line text-muted"}`}>
                    {playing === tone && <span className="spinner" />}{libraToneLabel(tone)}
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}
      {parts.tone && speeds.length > 0 && (
        <section className="flex flex-col gap-2">
          <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Speed</div>
          <div className="glass rounded-card p-3 flex flex-col gap-3">
            <div className="text-small leading-[18px] text-muted px-1">
              It reads like a storyteller. A little quicker sounds more like talking.
            </div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Speed">
              {speeds.map((speed) => {
                const on = speed === server.speed;
                return (
                  <button key={speed} role="radio" aria-checked={on} onClick={() => void pickSpeed(speed)}
                    className={`rounded-control border px-3 h-9 text-small ${on ? "border-ember-text bg-ember-tint text-ember-text font-semibold" : "border-line text-muted"}`}>
                    {libraSpeedLabel(speed)}
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}
      {parts.hearing && (
        <section className="flex flex-col gap-2">
          <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Dictation</div>
          <div className="glass rounded-card p-3 flex flex-col gap-3">
            <div className="text-small leading-[18px] text-muted px-1">
              Which model on your voice server writes down what you say into the mic.
            </div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Dictation model">
              {(server.hear_models ?? []).map((model) => {
                const on = model === server.hear_model;
                return (
                  <button key={model} role="radio" aria-checked={on} onClick={() => void save({ hear_model: model })}
                    className={`rounded-control border px-3 h-9 text-small ${on ? "border-ember-text bg-ember-tint text-ember-text font-semibold" : "border-line text-muted"}`}>
                    {model}
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}
      {parts.address && (
        <section className="flex flex-col gap-2">
          <div className="section-label text-small leading-5 font-bold text-muted px-1.5">Voice server</div>
          <div className="glass rounded-card p-3 flex flex-col gap-2">
            <div className="text-small leading-[18px] text-muted px-1">
              {server.answering ? "Answering. Models load when used and unload when idle."
                : "Not answering here: start it with voiced start, or fix the address."}
            </div>
            <div className="flex gap-2">
              <input value={address} onChange={(e) => setAddress(e.target.value)} aria-label="Voice server address"
                inputMode="url" autoCapitalize="off" autoCorrect="off" spellCheck={false}
                className="flex-1 min-w-0 h-11 rounded-control border border-line bg-well px-3 text-body" />
              <button onClick={() => void saveAddress()} disabled={busy || address.trim() === server.url}
                className="pill px-4 disabled:opacity-40">Save</button>
            </div>
            {problem && <div className="text-small leading-[18px] text-warn-ink px-1">{problem}</div>}
          </div>
        </section>
      )}
    </>
  );
}
