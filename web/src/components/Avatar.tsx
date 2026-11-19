import { useState } from "react";
import { usePersona, type Persona } from "../persona";
import { Orb, moodClass, type OrbState } from "./Orb";

export function avatarMode(url: string | null | undefined, failed: boolean): "photo" | "orb" {
  return url && !failed ? "photo" : "orb";
}

/** The assistant as the user chose: their photo in an iridescent ring, or (no photo, or it failed) the orb itself.
 *  `who`: draw this one instead of everyday Odie (the chat and Settings pass the picked personality).
 *  `light`: that personality's light (light.ts), which colours its face or its picture's ring; 0 for Odie. */
export function Avatar({ size = 34, state = "idle", halo = false, who, light = 0 }: { size?: number; state?: OrbState; halo?: boolean; who?: Persona; light?: number }) {
  const odie = usePersona();
  const { name, avatar_url } = who ?? odie;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const failed = failedUrl !== null && failedUrl === avatar_url;  // a picture that failed, not the next one picked
  if (avatarMode(avatar_url, failed) === "orb") return <Orb state={state} size={size} halo={halo} light={light} />;
  return (
    <span className={`av ${moodClass(state)} ${halo ? "av-halo" : ""} ${light ? `light-${light}` : ""}`} style={{ width: size, height: size, padding: Math.max(2, size / 40) }} role="img" aria-label={name}>
      <img src={avatar_url!} alt="" onError={() => setFailedUrl(avatar_url)} />
    </span>
  );
}
