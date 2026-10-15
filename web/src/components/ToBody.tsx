import { createPortal } from "react-dom";
import type { ReactNode } from "react";

/** Full-screen layers (viewer, tap-outside catcher) live on <body>: inside a frosted .glass box,
 * backdrop-filter makes `position: fixed` relative to that box instead of the screen. */
export function ToBody({ children }: { children: ReactNode }) {
  return createPortal(children, document.body);
}
