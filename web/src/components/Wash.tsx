import { useEffect } from "react";
import { applyLight } from "../light";
import { usePick } from "../pick";

/** Three slow, blurred lights behind every screen; their colours come from data-tod (theme.ts), or from the picked
 *  personality's own light (light.ts). */
export function Wash() {
  const pick = usePick();
  useEffect(() => { applyLight(pick); }, [pick]);
  return <div className="wash" aria-hidden="true"><i /><i /><i /></div>;
}
