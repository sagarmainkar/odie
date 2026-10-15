import { useState } from "react";
import { usePersona } from "../persona";
import { Orb, moodClass, type OrbState } from "./Orb";

export function avatarMode(url: string | null | undefined, failed: boolean): "photo" | "orb" {
  return url && !failed ? "photo" : "orb";
}

/** The assistant as the user chose: their photo in an iridescent ring, or (no photo, or it failed) the orb itself. */
export function Avatar({ size = 34, state = "idle", halo = false }: { size?: number; state?: OrbState; halo?: boolean }) {
  const { name, avatar_url } = usePersona();
  const [failed, setFailed] = useState(false);
  if (avatarMode(avatar_url, failed) === "orb") return <Orb state={state} size={size} halo={halo} />;
  return (
    <span className={`av ${moodClass(state)} ${halo ? "av-halo" : ""}`} style={{ width: size, height: size, padding: Math.max(2, size / 40) }} role="img" aria-label={name}>
      <img src={avatar_url!} alt="" onError={() => setFailed(true)} />
    </span>
  );
}
