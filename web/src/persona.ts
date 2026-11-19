import { useEffect, useState } from "react";
import { getJSON } from "./api";
import { onPickChange, withPick } from "./pick";

export type Persona = { name: string; avatar_url: string | null };
let cached: Persona = { name: "Odie", avatar_url: null };

/** The assistant's chosen name and photo. Settings fires "odie:persona" after a change so every screen updates. */
export function usePersona(): Persona {
  const [p, setP] = useState<Persona>(cached);
  useEffect(() => {
    const load = () => getJSON<Persona>("/api/persona").then((x) => { cached = x; setP(x); }).catch(() => {});
    load();
    window.addEventListener("odie:persona", load);
    return () => window.removeEventListener("odie:persona", load);
  }, []);
  return p;
}

export function personaChanged() { window.dispatchEvent(new Event("odie:persona")); }

/** The name and picture of whoever is picked: a personality's, or everyday Odie's when none is. The chat and Settings
 *  show this one; Today and the other Odie screens keep usePersona. It loads again when the pick changes and when a
 *  name or picture is saved. */
export function usePickedPersona(): Persona {
  const [p, setP] = useState<Persona>(cached);
  useEffect(() => {
    const load = () => getJSON<Persona>(withPick("/api/persona", true)).then(setP).catch(() => {});
    load();
    window.addEventListener("odie:persona", load);
    const stop = onPickChange(load);
    return () => { window.removeEventListener("odie:persona", load); stop(); };
  }, []);
  return p;
}

