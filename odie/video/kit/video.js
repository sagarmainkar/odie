// video.js: the explainer-video kit, exposed as window.Video.
//
// How a video is drawn: the tool sets window.__timings = {starts: [...], lengths: [...], beats: [[...], ...]}
// (seconds, measured from the narration; beats are where each "|"-marked phrase starts, seconds into its scene), and
// the page calls Video.scenes([...]) with one {setup(s)?, draw(t, s)} per scene. The server then calls
// window.__frame(T) for every frame (T = frame / fps) and takes a picture of the 1920x1080 stage.
//
// Rules that keep frames deterministic (frame k always draws the same picture, whatever order frames are drawn in):
// draw(t, s) is a pure function of t; no requestAnimationFrame, no clock, no Math.random (use s.random(seed)); set
// every property you animate on every frame. Build three.js objects once, in setup(s), and keep them on `this`.
// Before every frame the kit puts back what a scene may have changed: the whole camera (position, orientation, fov,
// zoom, near, far, aspect, view offset), the renderer (clear colour, tone mapping and exposure, colour space,
// auto-clear, viewport, scissor), the 2D canvas (cleared, its state reset), and every text/tex div (hidden).
// Each scene has its own three.js scene, so objects never carry over from one scene to the next.
//
// Layers, back to front: the three.js canvas (cleared to the background colour), a 2D canvas (s.ctx, cleared every
// frame), then text and formulas (absolutely positioned divs, hidden every frame and shown by s.text / s.tex).
(function () {
  "use strict";

  const W = 1920;
  const H = 1080;
  const FADE = 0.6;  // seconds a fade in (or out) takes
  const SANS = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
  const colors = {bg: "#0e1117", blue: "#58C4DD", yellow: "#FFFF00", green: "#83C167", red: "#FC6255", text: "#ECECEC"};

  const STYLE = `
    #v-stage { position: absolute; left: 0; top: 0; width: ${W}px; height: ${H}px; overflow: hidden;
               background: ${colors.bg}; }
    #v-stage canvas, #v-layer { position: absolute; left: 0; top: 0; width: ${W}px; height: ${H}px; }
    .v-text, .v-tex { position: absolute; width: max-content; visibility: hidden; color: ${colors.text}; }
    .v-text { font-family: ${SANS}; white-space: pre; line-height: 1.25; -webkit-font-smoothing: antialiased; }
    .v-tex .katex-display { margin: 0; }`;

  // ---- Timing helpers: pure functions of time ----

  // A number kept inside 0..1. clamp01(1.4) -> 1
  function clamp01(x) {
    return Math.min(1, Math.max(0, x));
  }

  // Smooth in-out (smootherstep): starts and ends gently. ease(0) -> 0, ease(0.25) -> 0.10, ease(0.5) -> 0.5
  function ease(x) {
    const p = clamp01(x);
    return p * p * p * (p * (p * 6 - 15) + 10);
  }

  // Eased progress of t across [from, to], 0 before and 1 after. at(1.5, 1, 2) -> 0.5; at(3, 1, 2) -> 1
  function at(t, from, to) {
    if (to <= from) {
      return t >= from ? 1 : 0;
    }
    return ease((t - from) / (to - from));
  }

  // Opacity that fades in from inAt (over 0.6 s) and, if outAt is given, is gone again by outAt.
  // fade(t, 1, 5): t = 0.5 -> 0, t = 1.3 -> 0.5, t = 3 -> 1, t = 5 -> 0.   fade(t, 1): stays 1 once in.
  function fade(t, inAt, outAt) {
    const fadingIn = at(t, inAt, inAt + FADE);
    if (outAt === undefined) {
      return fadingIn;
    }
    const fadingOut = 1 - at(t, outAt - FADE, outAt);
    return Math.min(fadingIn, fadingOut);
  }

  // The value p of the way from a to b, for moving things. lerp(200, 900, 0.5) -> 550
  function lerp(a, b, p) {
    return a + (b - a) * p;
  }

  // A counter between two whole numbers. count(0, 1000, 0.5) -> 500
  function count(from, to, p) {
    return Math.round(lerp(from, to, p));
  }

  // A seeded random generator (mulberry32): the same seed gives the same numbers every frame.
  // const rnd = s.random(7); rnd() -> 0.0089...; rnd() -> the next number in 0..1
  function random(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let x = Math.imul(a ^ (a >>> 15), 1 | a);
      x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
      return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ---- Beats: where each phrase of a scene's narration starts, so a change lands on the word ----

  // A scene's beat starts from the timings; timings without beats (one phrase a scene) give one beat at 0.
  // beatsFor({beats: [[0, 1.2]]}, 0) -> [0, 1.2];   beatsFor({starts: [0], lengths: [3]}, 0) -> [0]
  function beatsFor(timings, i) {
    if (!timings.beats) {
      return [0];
    }
    return timings.beats[i];
  }

  // A count of beats in words. beatsInWords(1) -> "1 beat"; beatsInWords(3) -> "3 beats"
  function beatsInWords(n) {
    if (n === 1) {
      return "1 beat";
    }
    return n + " beats";
  }

  // Eased progress of t across beat i: from its start to the next beat's (or to the scene's end, for the last),
  // 0 before and 1 after. beats [0, 1, 3], length 5: beatProgress(beats, 5, 2, 1) -> 0.5; (beats, 5, 4, 2) -> 0.5;
  // (beats, 5, 4, 3) -> a RangeError saying the scene has 3 beats, so the page check tells the writer.
  function beatProgress(beats, length, t, i) {
    const known = Number.isInteger(i) && i >= 0 && i < beats.length;
    if (!known) {
      const last = beats.length - 1;
      throw new RangeError(`s.beat(t, ${i}): this scene has ${beatsInWords(beats.length)} (0 to ${last}); ` +
                           "mark one more phrase with '|' in its narration for each beat");
    }
    let end = length;
    if (i + 1 < beats.length) {
      end = beats[i + 1];
    }
    return at(t, beats[i], end);
  }

  // The index of the beat being spoken at t: the last one whose start has come. beats [0, 1, 3]: t 0.5 -> 0, 1 -> 1,
  // 4 -> 2
  function beatIndex(beats, t) {
    let current = 0;
    for (let i = 0; i < beats.length; i++) {
      if (beats[i] <= t) {
        current = i;
      }
    }
    return current;
  }

  // ---- Drawing on the 2D canvas ----

  // An arrow from (x1, y1) towards (x2, y2) that grows with p (0 nothing, 1 the whole arrow); its head rides the tip.
  // s.arrow(s.ctx, 300, 900, 760, 600, s.at(t, 1, 2), s.colors.yellow)
  function arrow(ctx, x1, y1, x2, y2, p, color) {
    const grown = clamp01(p);
    if (grown <= 0) {
      return;
    }
    const tipX = lerp(x1, x2, grown);
    const tipY = lerp(y1, y2, grown);
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const head = 28 * Math.min(1, grown * 4);  // the head is full size once the arrow is a quarter grown
    const shaft = Math.hypot(tipX - x1, tipY - y1) - head * 0.8;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 6;
    ctx.lineCap = "round";
    if (shaft > 0) {
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x1 + Math.cos(angle) * shaft, y1 + Math.sin(angle) * shaft);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - head * Math.cos(angle - 0.42), tipY - head * Math.sin(angle - 0.42));
    ctx.lineTo(tipX - head * Math.cos(angle + 0.42), tipY - head * Math.sin(angle + 0.42));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // ---- Text and formulas: one div per id, made on first use, hidden every frame, shown and placed by s.text/s.tex --

  const TEXT_DEFAULTS = {x: W / 2, y: H / 2, size: 48, color: colors.text, align: "center", weight: 400, opacity: 1,
                         write: 1};
  const TEX_DEFAULTS = {x: W / 2, y: H / 2, size: 56, color: colors.text, align: "center", opacity: 1, write: 1};
  const SHIFT_FOR_ALIGN = {left: "0%", center: "-50%", right: "-100%"};  // x is the left edge, middle or right edge
  const elements = new Map();  // id -> {el, content}
  let layer = null;

  // The div for an id, made the first time it's asked for (its DOM id is "v-" + id). element("title", "text")
  function element(id, kind) {
    let entry = elements.get(id);
    if (!entry) {
      const el = document.createElement("div");
      el.id = "v-" + id;
      el.className = "v-" + kind;
      layer.appendChild(el);
      entry = {el: el, content: null};
      elements.set(id, entry);
    }
    return entry;
  }

  // Reveals an element left to right with a soft edge, like writing it in. write = 0.5 -> its left half shows
  function writeOn(el, write) {
    let mask = "";
    if (write < 1) {
      const edge = 12;  // percent of the width the soft edge spans
      const to = clamp01(write) * (100 + edge);
      mask = `linear-gradient(90deg, #000 ${to - edge}%, transparent ${to}%)`;
    }
    el.style.maskImage = mask;
    el.style.webkitMaskImage = mask;
  }

  // Shows an element for this frame where the options say: centred on y; x is its left, middle or right per align.
  function show(el, o) {
    el.style.left = o.x + "px";
    el.style.top = o.y + "px";
    el.style.transform = `translate(${SHIFT_FOR_ALIGN[o.align]}, -50%)`;
    el.style.textAlign = o.align;
    el.style.fontSize = o.size + "px";
    el.style.color = o.color;
    el.style.opacity = o.opacity;
    writeOn(el, o.write);
    el.style.visibility = "visible";
  }

  // Words on the stage for this frame. Options: x, y, size, color, align, weight, opacity, write (0..1); "\n" breaks.
  // s.text("title", "How attention works", {y: 160, size: 80, weight: 600, opacity: s.fade(t, 0.2)})
  function text(id, str, options) {
    const o = Object.assign({}, TEXT_DEFAULTS, options);
    const entry = element(id, "text");
    if (entry.content !== str) {
      entry.el.textContent = str;
      entry.content = str;
    }
    entry.el.style.fontWeight = o.weight;
    show(entry.el, o);
  }

  // A KaTeX formula on the stage for this frame (rendered again only when the LaTeX changes). Options as s.text.
  // s.tex("formula", "\\sqrt{d}", {y: 480, size: 72, write: s.at(t, 0.2, 1.6)})
  function tex(id, latex, options) {
    const o = Object.assign({}, TEX_DEFAULTS, options);
    const entry = element(id, "tex");
    if (entry.content !== latex) {
      katex.render(latex, entry.el, {displayMode: true, throwOnError: true});
      entry.content = latex;
    }
    show(entry.el, o);
  }

  function hideAllElements() {
    for (const entry of elements.values()) {
      entry.el.style.visibility = "hidden";
    }
  }

  // ---- The stage, the three.js renderer and the scenes on the timeline ----

  let renderer = null;
  let camera = null;
  let cameraHome = null;  // a pristine camera, never drawn with: the shared camera is copied back from it every frame
  let ctx = null;
  let placed = [];  // [{scene, start, s}] in order

  // Builds the stage (three.js canvas, 2D canvas, text layer) at the top of the page.
  function buildStage() {
    const style = document.createElement("style");
    style.textContent = STYLE;
    document.head.appendChild(style);
    const stage = document.createElement("div");
    stage.id = "v-stage";
    renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
    renderer.setPixelRatio(1);
    renderer.setSize(W, H);
    renderer.setClearColor(colors.bg, 1);
    cameraHome = new THREE.PerspectiveCamera(45, W / H, 0.1, 1000);
    cameraHome.position.set(0, 0, 10);
    cameraHome.lookAt(0, 0, 0);
    camera = cameraHome.clone();
    const flat = document.createElement("canvas");
    flat.width = W;
    flat.height = H;
    ctx = flat.getContext("2d");
    layer = document.createElement("div");
    layer.id = "v-layer";
    stage.append(renderer.domElement, flat, layer);
    document.body.prepend(stage);
  }

  // Each scene gets its own three.js scene (so a cube from scene 1 never shows up in scene 2), lit softly from above.
  function litScene() {
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x1a2230, 1.6));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(4, 6, 8);
    scene.add(key);
    return scene;
  }

  // The helpers a scene's setup and draw get; `length` is this scene's length in seconds and `beats` the seconds into
  // it at which each phrase starts (the first 0). s.beat(t, 1) is the eased progress across the second phrase;
  // s.beatAt(t) is the phrase being spoken.
  function helpersFor(length, beats) {
    return {
      ease: ease, at: at, fade: fade, lerp: lerp, count: count, random: random, arrow: arrow, text: text, tex: tex,
      three: {scene: litScene(), camera: camera, renderer: renderer},
      ctx: ctx, colors: colors, W: W, H: H, length: length, beats: beats,
      beat: function (t, i) {
        return beatProgress(beats, length, t, i);
      },
      beatAt: function (t) {
        return beatIndex(beats, t);
      },
    };
  }

  // Puts the camera and the renderer back as the kit made them, so a frame never depends on the frame drawn before it
  // (a tab whose range starts in scene 2 draws scene 2 exactly as a tab that came through scene 1 does).
  function resetThree() {
    camera.copy(cameraHome, false);  // fov, zoom, near, far, aspect, view offset, position, orientation, up
    camera.updateProjectionMatrix();
    renderer.setClearColor(colors.bg, 1);
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.toneMappingExposure = 1;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.autoClear = true;
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, W, H);
  }

  // Starts loading every KaTeX font now. A font otherwise loads only when a formula first uses it, so a formula first
  // drawn inside a frame could be photographed before its font arrived; this way the sealed tab's wait for
  // document.fonts.ready (after the page loads) covers every font.
  function loadAllFonts() {
    document.fonts.forEach(function (face) {
      face.load();
    });
  }

  // The scene drawing at time T: the last one whose start has come (the first before 0). It keeps drawing through the
  // breath after it, and the last scene holds past its end. starts [0, 3.5]: T 3.4 -> scene 1; T 3.6 or 99 -> scene 2
  function sceneAt(T) {
    let current = placed[0];
    for (const p of placed) {
      if (p.start <= T) {
        current = p;
      }
    }
    return current;
  }

  // Draws the picture for time T (seconds into the video). The scene's t stops at its length, so through the breath
  // (and past the last scene's end) it holds its last picture. Returns true.
  function frame(T) {
    const current = sceneAt(T);
    const t = Math.min(Math.max(T - current.start, 0), current.s.length);
    hideAllElements();
    ctx.reset();
    resetThree();
    current.scene.draw(t, current.s);
    renderer.render(current.s.three.scene, camera);
    return true;
  }

  // Puts the page's scenes on the timeline and defines window.__frame; setup(s) (optional) runs once per scene, here.
  // Video.scenes([{setup(s) {...}, draw(t, s) {...}}, {draw(t, s) {...}}])
  function scenes(list) {
    window.__sceneCount = list.length;
    const timings = window.__timings;
    if (!timings || !timings.starts || !timings.lengths) {
      throw new Error("window.__timings is missing: the tool sets it from the narration before the page runs");
    }
    if (timings.lengths.length !== list.length) {
      throw new Error(`The page has ${list.length} scenes but the narration has ${timings.lengths.length}.`);
    }
    buildStage();
    loadAllFonts();
    placed = [];
    for (let i = 0; i < list.length; i++) {
      const s = helpersFor(timings.lengths[i], beatsFor(timings, i));
      placed.push({scene: list[i], start: timings.starts[i], s: s});
    }
    for (const p of placed) {
      if (p.scene.setup) {
        p.scene.setup(p.s);
      }
    }
    window.__frame = frame;
  }

  window.Video = {scenes: scenes, colors: colors, W: W, H: H};
})();
