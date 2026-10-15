const COLORS = ["#7d8cff", "#b08bff", "#ff9cc8", "#22b07d"];

/** A closed row breaks into a little cloud of dots, fades and blurs away. Resolves when it's done. */
export function dissolve(el: HTMLElement): Promise<void> {
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (reduce || typeof el.animate !== "function") return Promise.resolve();
  const r = el.getBoundingClientRect();
  for (let i = 0; i < 46; i++) {
    const d = document.createElement("span");
    Object.assign(d.style, {
      position: "fixed", width: "5px", height: "5px", borderRadius: "50%", pointerEvents: "none", zIndex: "50",
      left: `${r.left + Math.random() * r.width}px`, top: `${r.top + Math.random() * r.height}px`, background: COLORS[i % COLORS.length],
    });
    document.body.appendChild(d);
    const dx = (Math.random() - 0.3) * 120, dy = -20 - Math.random() * 70;
    d.animate([{ transform: "translate(0,0) scale(1)", opacity: 0.95 }, { transform: `translate(${dx}px,${dy}px) scale(.2)`, opacity: 0 }],
      { duration: 700 + Math.random() * 500, easing: "cubic-bezier(.2,.8,.2,1)", delay: Math.random() * 180 }).onfinish = () => d.remove();
  }
  return el.animate([{ opacity: 1, filter: "blur(0)" }, { opacity: 0, filter: "blur(6px)" }], { duration: 420, fill: "forwards", easing: "ease-out" })
    .finished.then(() => undefined, () => undefined);
}
