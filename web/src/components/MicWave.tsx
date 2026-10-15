import { useEffect, useRef } from "react";

/** The voice, drawn as it comes in: bars that rise with how loud you speak, newest on the right. */
export function MicWave({ level }: { level: { current: number } }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = canvas.current;
    const g = c?.getContext("2d");
    if (!c || !g) return;
    const bars: number[] = new Array(36).fill(0);
    let raf = 0, frame = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      if (frame++ % 3) return;  // about 20 new bars a second
      bars.shift();
      bars.push(level.current);
      const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
      if (c.width !== w * dpr) { c.width = w * dpr; c.height = h * dpr; }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      g.fillStyle = getComputedStyle(c).color;
      const step = w / bars.length;
      bars.forEach((v, i) => {
        const bh = Math.max(3, v * h);
        g.beginPath();
        g.roundRect(i * step + step * 0.25, (h - bh) / 2, step * 0.5, bh, step * 0.25);
        g.fill();
      });
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [level]);
  return <canvas ref={canvas} aria-hidden="true" className="w-full h-7 text-ember-text" />;
}
