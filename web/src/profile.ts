import { useEffect, useState } from "react";
import { getJSON } from "./api";
import { rememberLocale } from "./locale";

export type Profile = { user_name: string; timezone: string; locale: string; country: string; currency: string; machine: string };
let cached: Profile | null = null;

/** Who the assistant works for, and where (from the server). Settings fires "odie:profile" after a change. */
export function useProfile(): Profile | null {
  const [p, setP] = useState<Profile | null>(cached);
  useEffect(() => {
    const load = () => getJSON<Profile>("/api/profile").then((x) => { cached = x; rememberLocale(x.locale); setP(x); }).catch(() => {});
    load();
    window.addEventListener("odie:profile", load);
    return () => window.removeEventListener("odie:profile", load);
  }, []);
  return p;
}

export function profileChanged() { window.dispatchEvent(new Event("odie:profile")); }
