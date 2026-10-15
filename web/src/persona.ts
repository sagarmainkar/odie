import { useEffect, useState } from "react";
import { getJSON } from "./api";

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
