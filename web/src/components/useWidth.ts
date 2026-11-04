// The width an element takes on screen, followed as it changes (the window resizes, the chat column moves), so a
// chart is drawn at its real size instead of being scaled up or down.
import { useLayoutEffect, useState, type RefObject } from "react";

/** The width assumed before anything is measured (and where nothing can be, as in tests): a typical chat column. */
const UNMEASURED_WIDTH = 560;

/** The element's width in whole px, measured before the first paint and again whenever it changes. */
export function useWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.round(el.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const watcher = new ResizeObserver(measure);
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [ref]);
  return width || UNMEASURED_WIDTH;
}
