// video.js: the explainer-video kit, exposed as window.Video.
//
// How a video is drawn: the tool sets window.__timings = {starts: [...], lengths: [...], beats: [[...], ...]}
// (seconds, measured from the narration; beats are where each "|"-marked phrase starts, seconds into its scene), and
// the page calls Video.scenes([...]) with one {setup(s)?, draw(t, s)} per scene. The server then calls
// window.__frame(T) for every frame (T = frame / fps) and takes a picture of the stage: 1920x1080, or the size the
// page sets in window.__stage = {width, height, safe} before this script (1080x1920 for a vertical video, whose safe
// area, the room Instagram's buttons cover, scenes read as s.safe = {top, bottom, side}). A video with pictures
// or clips calls Video.assets({...}) before Video.scenes (see registerAssets); the first frame waits until they are
// loaded, and a frame that draws a clip returns a promise, settled once the clip shows its moment. Odie's credits
// card calls Video.closing({...}) before the page's script: it plays after the page's last scene (see closing). A
// video with sound effects calls Video.sounds([...]) next to its scenes (see sounds); Odie reads the cues back with
// Video.soundCues() and mixes them under the narration. The kit draws and plays nothing for them. A video with a timed
// segment (odie.video.timed) marks its first and last scene in Video.scenes ({timed_start: true, ...}, {timed_end:
// true, ...}; Odie reads them back with Video.timedScenes()), and Odie sets window.ODIE_TIMED = {start, seconds, end}
// (the segment's first word, its length, its last word): s.left() and Video.clockAt(T) count from `seconds` at the
// first word to 0 at the last, null before. A video with a brand kit (odie.video.brand) has the kit's brand.js and
// Video.brand({...}) before the page's script: the kit's background is drawn under every scene, its character over
// the timed segment, its fixed scenes (bookends) around the segment and at the end, and window.Brand is frozen.
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
// frame; pictures, clips, wipes, scrims and map.js's maps are drawn here), then text and formulas (absolutely
// positioned divs, hidden every frame and shown by s.text / s.tex).
(function () {
  "use strict";

  // The stage the page asked for (odie.video.page.stage_script), else the landscape one with nothing covered.
  // {width: 1080, height: 1920, safe: {top: 140, bottom: 340, side: 72}} -> W 1080, H 1920, that safe area;
  // no window.__stage -> W 1920, H 1080, safe {top: 0, bottom: 0, side: 0}.
  const STAGE = window.__stage || {width: 1920, height: 1080, safe: {top: 0, bottom: 0, side: 0}};
  const W = STAGE.width;
  const H = STAGE.height;
  const SAFE = Object.freeze(Object.assign({top: 0, bottom: 0, side: 0}, STAGE.safe));
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

  // ---- Pictures and clips: registered by Video.assets, drawn on the 2D canvas between the 3D scene and the text ----

  const PHOTO_DEFAULTS = {fit: "cover", zoom: 1, opacity: 1, radius: 0, angle: 0, blur: 0};
  const PORTRAIT_FOCUS_Y = 0.33;  // a picture cropped top and bottom keeps its upper third, where faces are
  const SCRIM_DEFAULTS = {from: "bottom", strength: 0.7, height: 0.45};
  const NOUNS = {image: "picture", clip: "clip"};
  const HAVE_CURRENT_DATA = 2;  // a video's readyState once the frame at its current time can be drawn
  const assets = new Map();  // name -> {name, kind, width, height, seconds, el}, in the order Video.assets gave them
  let loading = null;  // while pictures and clips load, the promise of them all; null once they are all in
  let clipsThisFrame = new Map();  // clip name -> the time (seconds into the clip) the frame being drawn asked for
  let seeksNeeded = [];  // [{asset, time}]: clips not yet showing their time; the frame is drawn again once they are
  let afterSeeks = false;  // true while a frame is drawn the second time, its clips seeked: they are drawn as they are

  // Starts loading a picture from its data address; settles once it is decoded and ready to draw.
  // loadImage({name: "img1", ...}, "data:image/jpeg;base64,...") -> a promise; asset.el is the <img>
  function loadImage(asset, src) {
    const img = new Image();
    asset.el = img;
    img.src = src;
    return img.decode().catch(function () {
      throw new Error(`picture ${asset.name} couldn't be loaded`);
    });
  }

  // Starts loading a clip (muted, never played: every frame seeks it); settles once its first frame can be drawn.
  // loadClip({name: "clip1", ...}, "data:video/webm;base64,...") -> a promise; asset.el is the <video>
  function loadClip(asset, src) {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    asset.el = video;
    const loaded = new Promise(function (resolve, reject) {
      video.onloadeddata = function () {
        resolve();
      };
      video.onerror = function () {
        reject(new Error(`clip ${asset.name} couldn't be loaded`));
      };
    });
    video.src = src;
    return loaded;
  }

  // Registers the video's pictures and clips and starts loading them, before Video.scenes; the first frame waits until
  // they are all in. Each entry: kind "image" or "clip", src a data address, width and height in pixels, and for a clip
  // its length in seconds. Video.assets({img1: {kind: "image", src: "data:image/jpeg;base64,...", width: 2400,
  // height: 1600}, clip1: {kind: "clip", src: "data:video/webm;base64,...", width: 1280, height: 720, seconds: 15}})
  function registerAssets(list) {
    const loads = [];
    for (const name of Object.keys(list)) {
      const given = list[name];
      const asset = {name: name, kind: given.kind, width: given.width, height: given.height, seconds: given.seconds,
                     el: null};
      if (given.kind === "image") {
        loads.push(loadImage(asset, given.src));
      } else if (given.kind === "clip") {
        loads.push(loadClip(asset, given.src));
      } else {
        throw new Error(`Video.assets: ${name} has kind "${given.kind}"; a kind is "image" or "clip"`);
      }
      assets.set(name, asset);
    }
    if (loading) {
      loads.push(loading);  // a second call waits for the first's too
    }
    const all = Promise.all(loads).then(function () {
      if (loading === all) {
        loading = null;
      }
    });
    all.catch(function () {});  // a load that failed is told by the first frame, which waits on this promise
    loading = all;
  }

  // Names in words, a run of three or more as its first and last (Odie numbers them in order).
  // [] -> "none"; ["img1"] -> "img1"; ["img1", "img2"] -> "img1 and img2"; img1 to img8 -> "img1…img8"
  function namesInWords(names) {
    if (names.length === 0) {
      return "none";
    }
    if (names.length === 1) {
      return names[0];
    }
    if (names.length === 2) {
      return names[0] + " and " + names[1];
    }
    return names[0] + "…" + names[names.length - 1];
  }

  // What there is of one kind, for an error. "image" with img1..img8 -> "the pictures are img1…img8";
  // "clip" with none -> "this video has no clips"
  function whatThereIs(kind) {
    const names = [];
    for (const asset of assets.values()) {
      if (asset.kind === kind) {
        names.push(asset.name);
      }
    }
    if (names.length === 0) {
      return `this video has no ${NOUNS[kind]}s`;
    }
    return `the ${NOUNS[kind]}s are ${namesInWords(names)}`;
  }

  // The registered picture or clip called name, of the kind asked for (null: either kind); anything else is an error
  // that says what there is. ("img2", "image") -> img2; ("img9", "image") with img1..img8 -> Error "no picture called
  // img9; the pictures are img1…img8"; ("clip1", "image") -> Error "clip1 is a clip: draw it with s.clip(...)"
  function assetCalled(name, kind) {
    const asset = assets.get(name);
    if (!asset) {
      if (kind === null) {
        throw new Error(`no picture or clip called ${name}; ${whatThereIs("image")}; ${whatThereIs("clip")}`);
      }
      throw new Error(`no ${NOUNS[kind]} called ${name}; ${whatThereIs(kind)}`);
    }
    const wrongKind = kind !== null && asset.kind !== kind;
    if (wrongKind && asset.kind === "clip") {
      throw new Error(`${name} is a clip: draw it with s.clip("${name}", t, o)`);
    }
    if (wrongKind) {
      throw new Error(`${name} is a picture, not a clip: draw it with s.photo("${name}", o)`);
    }
    return asset;
  }

  // A picture's or clip's size in pixels: the loaded element's own, else what Video.assets said (before it loads).
  // a loaded 400x300 picture -> {width: 400, height: 300}
  function sizeOf(asset) {
    let width = asset.el.naturalWidth;
    let height = asset.el.naturalHeight;
    if (asset.kind === "clip") {
      width = asset.el.videoWidth;
      height = asset.el.videoHeight;
    }
    if (!width || !height) {
      return {width: asset.width, height: asset.height};
    }
    return {width: width, height: height};
  }

  // Refuses a fit that isn't "cover" or "contain", naming both. checkFit("cover") -> fine; checkFit("fill") -> Error
  function checkFit(fit) {
    if (fit !== "cover" && fit !== "contain") {
      throw new Error(`fit "${fit}" isn't "cover" (fill the box, cropping) or "contain" (all of it, with bars)`);
    }
  }

  // The focus a picture gets when the options give none: its centre, except a portrait picture (taller than wide)
  // that "cover" crops top and bottom (taller in shape than its box), which keeps its upper third, where faces are.
  // In the 1920x1080 stage with cover: 300x600 -> {x: 0.5, y: 0.33}; 300x400 -> {x: 0.5, y: 0.33};
  // 400x300 (a landscape, though cover crops it top and bottom too) -> {x: 0.5, y: 0.5};
  // 300x600 with contain -> {x: 0.5, y: 0.5}
  function defaultFocus(imageW, imageH, box, fit) {
    const portrait = imageH > imageW;
    const tallerThanBox = imageH / imageW > box.h / box.w;
    if (fit === "cover" && portrait && tallerThanBox) {
      return {x: 0.5, y: PORTRAIT_FOCUS_Y};
    }
    return {x: 0.5, y: 0.5};
  }

  // Where the whole picture lands: scaled to fill the box ("cover", the overflow cropped) or to fit inside it
  // ("contain", bars beside it), grown by zoom, and slid so the focus point stays in view (focus {x: 0, y: 0} keeps
  // the top-left corner, {x: 1, y: 1} the bottom-right). A 400x300 picture in the stage {x: 0, y: 0, w: 1920, h: 1080}:
  // cover, zoom 1, focus {x: 0.5, y: 0.5} -> {x: 0, y: -180, w: 1920, h: 1440};
  // contain, zoom 1, focus {x: 0.5, y: 0.5} -> {x: 240, y: 0, w: 1440, h: 1080};
  // cover, zoom 1.5, focus {x: 0, y: 0} -> {x: 0, y: 0, w: 2880, h: 2160}
  function pictureRect(imageW, imageH, box, fit, zoom, focus) {
    const across = box.w / imageW;
    const down = box.h / imageH;
    let scale = Math.max(across, down);
    if (fit === "contain") {
      scale = Math.min(across, down);
    }
    const w = imageW * scale * zoom;
    const h = imageH * scale * zoom;
    return {x: box.x + (box.w - w) * focus.x, y: box.y + (box.h - h) * focus.y, w: w, h: h};
  }

  // Turns the canvas by `degrees` (clockwise) about the box's centre, so what is drawn next is tilted in place.
  // turnAbout({x: 0, y: 0, w: 1920, h: 1080}, 3) -> the stage tilted 3 degrees about (960, 540)
  function turnAbout(box, degrees) {
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    ctx.translate(cx, cy);
    ctx.rotate(degrees * Math.PI / 180);
    ctx.translate(-cx, -cy);
  }

  // Draws a picture (an <img>, or a <video> at its current frame) on the 2D canvas with the photo options (see
  // s.photo), inside its box only, and leaves the canvas's settings as it found them.
  // drawPicture(img, 400, 300, {zoom: 1.12}) -> the whole stage covered, pushed in a little
  function drawPicture(el, imageW, imageH, options) {
    const o = Object.assign({x: 0, y: 0, w: W, h: H}, PHOTO_DEFAULTS, options);
    checkFit(o.fit);
    if (o.opacity <= 0) {
      return;
    }
    const box = {x: o.x, y: o.y, w: o.w, h: o.h};
    const focus = Object.assign(defaultFocus(imageW, imageH, box, o.fit), o.focus);
    const rect = pictureRect(imageW, imageH, box, o.fit, o.zoom, focus);
    ctx.save();
    ctx.globalAlpha = ctx.globalAlpha * clamp01(o.opacity);
    turnAbout(box, o.angle);
    ctx.beginPath();
    ctx.roundRect(box.x, box.y, box.w, box.h, o.radius);
    ctx.clip();
    if (o.blur > 0) {
      ctx.filter = `blur(${o.blur}px)`;
    }
    ctx.drawImage(el, rect.x, rect.y, rect.w, rect.h);
    ctx.restore();
  }

  // A picture drawn this frame. Options: x, y, w, h (its box in pixels; the whole stage by default), fit ("cover"
  // fills the box, "contain" shows all of it), zoom (1 fills the box; 1.12 pushes in), focus ({x, y} in 0..1, where
  // the zoom looks; the centre, or the upper third for a portrait cropped by cover), opacity, radius (rounded corners,
  // pixels), angle (degrees, clockwise), blur (pixels). The push-in:
  // s.photo("img1", {zoom: s.lerp(1, 1.12, s.at(t, 0, s.length))})
  function photo(name, options) {
    const asset = assetCalled(name, "image");
    const size = sizeOf(asset);
    drawPicture(asset.el, size.width, size.height, options);
  }

  // A clip's length in seconds: the video's own, else what Video.assets said. A 15 s clip -> 15
  function clipLength(asset) {
    const duration = asset.el.duration;
    if (Number.isFinite(duration) && duration > 0) {
      return duration;
    }
    return asset.seconds;
  }

  // Seconds into a clip for time t, looping past its end. A 1-second clip: clipTime(0.5, 1) -> 0.5;
  // clipTime(1.5, 1) -> 0.5; clipTime(1, 1) -> 0
  function clipTime(t, length) {
    const looped = t % length;
    if (looped < 0) {
      return looped + length;
    }
    return looped;
  }

  // Whether a clip's video already shows the frame at `time`: it is at that time, not mid-seek, its frame decoded.
  // at 0.5, not seeking, readyState 2 or more, asked 0.5 -> true (draw it now); asked 0.7 -> false (seek first)
  function showsTime(video, time) {
    return video.currentTime === time && !video.seeking && video.readyState >= HAVE_CURRENT_DATA;
  }

  // Asks a clip's video for the moment `time`; settles once it shows it (the browser's "seeked").
  // seekTo(clip1, 0.5) -> a promise; then clip1.el.currentTime is 0.5 and its frame is the one at 0.5 s
  function seekTo(asset, time) {
    const video = asset.el;
    return new Promise(function (resolve, reject) {
      video.onseeked = function () {
        resolve();
      };
      video.onerror = function () {
        reject(new Error(`clip ${asset.name} couldn't be shown at ${time} s`));
      };
      video.currentTime = time;
    });
  }

  // A clip's frame at time t (seconds into the clip, looping past its end), drawn like s.photo with the same options.
  // A clip shows one moment a frame: drawn twice in a frame, it must be at the same t. When the video isn't at that
  // moment yet, nothing is drawn now: the seek is noted and the whole frame is drawn again once it is done.
  // s.clip("clip1", t, {opacity: s.fade(t, 0, 4)})
  function clip(name, t, options) {
    const asset = assetCalled(name, "clip");
    const time = clipTime(t, clipLength(asset));
    const earlier = clipsThisFrame.get(name);
    if (earlier !== undefined && earlier !== time) {
      throw new Error(`s.clip("${name}") is drawn at ${earlier} s and at ${time} s in one frame; a clip shows ` +
                      "one moment a frame");
    }
    clipsThisFrame.set(name, time);
    if (!afterSeeks && !showsTime(asset.el, time)) {
      if (earlier === undefined) {
        seeksNeeded.push({asset: asset, time: time});
      }
      return;
    }
    const size = sizeOf(asset);
    drawPicture(asset.el, size.width, size.height, options);
  }

  // A picture as a THREE.Texture for 3D (a photo on a tilting plane, a card in space, a globe), made once per scene and
  // kept in `cache`: asking twice gives the same texture. new THREE.MeshBasicMaterial({map: s.texture("img1")})
  function textureFor(cache, name) {
    let texture = cache.get(name);
    if (!texture) {
      const asset = assetCalled(name, "image");
      texture = new THREE.Texture(asset.el);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;
      cache.set(name, texture);
    }
    return texture;
  }

  // The raw element of a picture (<img>) or clip (<video>) and its size, for anything custom.
  // s.image("img1") -> {el: <img>, width: 2400, height: 1600}
  function image(name) {
    const asset = assetCalled(name, null);
    const size = sizeOf(asset);
    return {el: asset.el, width: size.width, height: size.height};
  }

  // The longest way from (x, y) to a corner of the stage: how far an iris must open to uncover all of it.
  // farthestCorner(960, 540) -> 1101.5; farthestCorner(0, 0) -> 2202.9
  function farthestCorner(x, y) {
    const across = Math.max(x, W - x);
    const down = Math.max(y, H - y);
    return Math.hypot(across, down);
  }

  // The part of the stage a wipe has uncovered at progress p, added to the canvas's path, one shape per direction.
  // ("right", 0.5) -> x 0..960; ("up", 0.25) -> y 810..1080; ("circle", 1) -> a circle reaching every corner;
  // ("sideways", 0.5) -> Error naming the directions
  function wipePath(o, p) {
    if (o.dir === "right") {
      ctx.rect(0, 0, W * p, H);
    } else if (o.dir === "left") {
      ctx.rect(W * (1 - p), 0, W * p, H);
    } else if (o.dir === "down") {
      ctx.rect(0, 0, W, H * p);
    } else if (o.dir === "up") {
      ctx.rect(0, H * (1 - p), W, H * p);
    } else if (o.dir === "circle") {
      ctx.arc(o.x, o.y, p * farthestCorner(o.x, o.y), 0, Math.PI * 2);
    } else if (o.dir === "diagonal") {
      const reach = p * (W + H);  // a triangle from the top-left corner; at p = 1 its long side passes (W, H)
      ctx.moveTo(0, 0);
      ctx.lineTo(reach, 0);
      ctx.lineTo(0, reach);
      ctx.closePath();
    } else {
      throw new Error(`s.wipe: dir "${o.dir}" isn't one of right, left, down, up, circle, diagonal`);
    }
  }

  // Clips everything drawn after it this frame to what a wipe has uncovered at progress p (0..1): draw A, then
  // s.wipe(p, o), then B, and B takes over from A. dir: "right" (the default; the edge moves right, so B comes in
  // from the left), "left", "down" (B from the top), "up", "circle" (an iris opening from o.x, o.y, the stage's
  // centre by default), "diagonal" (from the top-left corner). p 0.5, "right" -> B on the left half, A on the right.
  // A second wipe in the same frame narrows to both; put one between s.ctx.save() and s.ctx.restore() to end it.
  function wipe(p, options) {
    const o = Object.assign({dir: "right", x: W / 2, y: H / 2}, options);
    ctx.beginPath();
    wipePath(o, clamp01(p));
    ctx.clip();
  }

  // The gradient's line for a scrim: from the darkened edge inward by `reach` (a share of the stage's height, or of
  // its width from the left or right). ("bottom", 0.45) -> {x0: 0, y0: 1080, x1: 0, y1: 594};
  // ("left", 0.5) -> {x0: 0, y0: 0, x1: 960, y1: 0}; ("middle", 0.5) -> Error naming the edges
  function scrimLine(from, reach) {
    if (from === "bottom") {
      return {x0: 0, y0: H, x1: 0, y1: H * (1 - reach)};
    }
    if (from === "top") {
      return {x0: 0, y0: 0, x1: 0, y1: H * reach};
    }
    if (from === "left") {
      return {x0: 0, y0: 0, x1: W * reach, y1: 0};
    }
    if (from === "right") {
      return {x0: W, y0: 0, x1: W * (1 - reach), y1: 0};
    }
    throw new Error(`s.scrim: from "${from}" isn't one of bottom, top, left, right`);
  }

  // A soft darkening from one edge of the stage, so text over a photo reads. Options: from ("bottom", "top", "left",
  // "right"), strength (0.7: the darkness at the edge, 0..1), height (0.45: how far in it reaches, a share of the
  // stage). s.photo("img1"); s.scrim(); s.text("caption", "Panipat, 1526", {y: 960})
  function scrim(options) {
    const o = Object.assign({}, SCRIM_DEFAULTS, options);
    const line = scrimLine(o.from, o.height);
    const gradient = ctx.createLinearGradient(line.x0, line.y0, line.x1, line.y1);
    gradient.addColorStop(0, `rgba(0, 0, 0, ${o.strength})`);
    gradient.addColorStop(0.5, `rgba(0, 0, 0, ${o.strength * 0.45})`);  // eases off, so the scrim has no visible edge
    gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.save();
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, W, H);
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
  let placed = [];  // [{scene, label, index, start, s}] in playing order (see layout)

  // Builds the stage (three.js canvas, 2D canvas, text layer) at the top of the page. With a brand kit, its top canvas
  // (its character and bookends) goes over them all, and, when the kit draws the background, its background canvas
  // under them all, with the three.js canvas cleared to transparent so the background shows through.
  function buildStage() {
    const style = document.createElement("style");
    style.textContent = STYLE;
    document.head.appendChild(style);
    const stage = document.createElement("div");
    stage.id = "v-stage";
    renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true, alpha: kitDrawsBackground()});
    renderer.setPixelRatio(1);
    renderer.setSize(W, H);
    renderer.setClearColor(colors.bg, clearAlpha());
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
    if (brand !== null) {
      brand.top = brandCanvas();
      stage.append(brand.top.canvas);
    }
    if (kitDrawsBackground()) {
      brand.back = brandCanvas();
      stage.prepend(brand.back.canvas);
    }
    document.body.prepend(stage);
  }

  // A canvas the size of the stage for the brand kit, and its 2D context.
  function brandCanvas() {
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    return {canvas: canvas, ctx: canvas.getContext("2d")};
  }

  // Decides whether the brand kit draws the background: a kit set up with {background: true} -> true; a kit without
  // one, or no kit -> false (the stage's own background colour, as before kits).
  function kitDrawsBackground() {
    return brand !== null && brand.settings.background === true;
  }

  // The three.js canvas's clear alpha: 0 (transparent) over a kit's background, else 1, as before kits.
  function clearAlpha() {
    if (kitDrawsBackground()) {
      return 0;
    }
    return 1;
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

  // ---- Extensions: the kit's other files (map.js) add helpers to every scene's s ----

  const extensions = [];  // [{helpers(s), beforeFrame()}], in the order the kit's files added them

  // Lets another kit file add helpers: helpers(s) runs as each scene's s is made (it adds to s), and beforeFrame(),
  // if given, runs before every frame is drawn (it forgets anything kept for one frame only, as video.js does).
  // map.js: Video.extend({helpers(s) { s.map = ...; }, beforeFrame() { projection = null; }})
  function extend(extension) {
    extensions.push(extension);
  }

  // The helpers a scene's setup and draw get; `length` is this scene's length in seconds and `beats` the seconds into
  // it at which each phrase starts (the first 0). s.beat(t, 1) is the eased progress across the second phrase;
  // s.beatAt(t) is the phrase being spoken. Textures are kept per scene, made the first time s.texture asks. Then
  // each extension adds its own (s.map and the rest from map.js).
  // ---- The segment clock: a timed segment's countdown (odie.video.timed), read from window.ODIE_TIMED ----

  let frameTime = 0;  // seconds into the video of the frame being drawn (drawFrame sets it), for s.left()

  // Seconds left on the segment clock at T seconds into the video: `seconds` at the segment's first word, 0 at its last
  // word and after, null before the first word and in a video without a timed segment. The clock runs from the first
  // word to the last as measured, so it reaches 0 exactly on the last word. {start: 6.5, seconds: 60, end: 66.5}:
  // T 3 -> null; T 6.5 -> 60; T 36.5 -> 30; T 66.5 or 70 -> 0.
  function clockAt(T) {
    const timed = window.ODIE_TIMED;
    if (!timed || T < timed.start) {
      return null;
    }
    const span = timed.end - timed.start;
    if (!(span > 0) || T >= timed.end) {
      return 0;
    }
    const left = timed.seconds * (timed.end - T) / span;
    return Math.max(0, Math.round(left * 1000) / 1000);
  }

  // ---- A dialogue video's lines (odie.video.dialogue): who speaks when, and how loud, for the characters' mouths ----

  const LOUDNESS_STEP = 0.02;  // seconds per loudness value, as odie.video.dialogue.loudness gives them
  let lines = [];  // Video.lines: [{index, speaker, scene, t, dur, amplitude}], t in seconds into the video

  // The page's line timeline, given once by Odie before the writer's page in a dialogue video. Speakers are kept in
  // lower case, as the script's are. Video.lines([{index: 0, speaker: "anna", scene: 1, t: 0.5, dur: 1.2,
  // amplitude: [0, 0.4, 1]}])
  function registerLines(list) {
    if (!Array.isArray(list)) {
      throw new Error("Video.lines takes a list of lines");
    }
    lines = list.map(function (line) {
      return Object.assign({}, line, {speaker: String(line.speaker).toLowerCase()});
    });
  }

  // The line being spoken at T, or null (before the first, between lines, after the last, and in any video without
  // lines). Lines at 0.5 for 1.0 s and at 2.0: T 1.0 -> the first; T 1.6 -> null.
  function lineAt(T) {
    for (const line of lines) {
      if (T >= line.t && T < line.t + line.dur) {
        return line;
      }
    }
    return null;
  }

  // Who is speaking at T: {speaker, index, progress (0..1 through the line), text}, or null.
  function speakingAt(T) {
    const line = lineAt(T);
    if (line === null) {
      return null;
    }
    const progress = Math.round(((T - line.t) / line.dur) * 1000) / 1000;
    return {speaker: line.speaker, index: line.index, progress: progress, text: line.text || ""};
  }

  // How open a speaker's mouth is at T: 0 closed, 1 half, 2 open, from the line's loudness at that moment (under 0.15
  // closed, under 0.5 half, else open); closed when they aren't speaking; half open all through a line whose loudness
  // isn't known (the page check draws before anything is spoken). Anna's line at 0.5 with amplitude [0.1, 0.6]:
  // mouthAt("anna", 0.53) -> 2; mouthAt("anna", 0.51) -> 0; mouthAt("ben", 0.53) -> 0.
  function mouthAt(id, T) {
    const line = lineAt(T);
    if (line === null || line.speaker !== String(id).toLowerCase()) {
      return 0;
    }
    if (!line.amplitude || line.amplitude.length === 0) {
      return 1;
    }
    const level = line.amplitude[Math.floor((T - line.t) / LOUDNESS_STEP)] || 0;
    if (level < 0.15) {
      return 0;
    }
    if (level < 0.5) {
      return 1;
    }
    return 2;
  }

  let timedMarks = {starts: [], ends: []};  // the scenes (from 1) the page marked timed_start and timed_end

  // The scenes the page marked as its timed segment's first and last, from 1, as Video.scenes was given them; Odie
  // checks there is one of each. {timed_start: true} on scene 2 and {timed_end: true} on scene 3 -> {starts: [2],
  // ends: [3]}; no marks -> {starts: [], ends: []}.
  function timedScenes() {
    return {starts: timedMarks.starts.slice(), ends: timedMarks.ends.slice()};
  }

  function helpersFor(length, beats) {
    const textures = new Map();  // picture name -> its THREE.Texture
    const s = {
      ease: ease, at: at, fade: fade, lerp: lerp, count: count, random: random, arrow: arrow, text: text, tex: tex,
      photo: photo, clip: clip, wipe: wipe, scrim: scrim, image: image,
      texture: function (name) {
        return textureFor(textures, name);
      },
      three: {scene: litScene(), camera: camera, renderer: renderer},
      ctx: ctx, colors: colors, W: W, H: H, safe: SAFE, length: length, beats: beats,
      beat: function (t, i) {
        return beatProgress(beats, length, t, i);
      },
      beatAt: function (t) {
        return beatIndex(beats, t);
      },
      // Seconds left on the segment clock in this frame (clockAt): 60 at the segment's first word down to 0 at its
      // last; null before it and in a video without a timed segment. A countdown draws only when it isn't null.
      left: function () {
        return clockAt(frameTime);
      },
      // A dialogue video: the line being spoken in this frame ({speaker, index, progress, text}, or null), and how open a
      // speaker's mouth is (0 closed, 1 half, 2 open). Both read the frame's time, not the scene's.
      speaking: function () {
        return speakingAt(frameTime);
      },
      mouth: function (id) {
        return mouthAt(id, frameTime);
      },
    };
    for (const extension of extensions) {
      extension.helpers(s);
    }
    return s;
  }

  // Puts the camera and the renderer back as the kit made them, so a frame never depends on the frame drawn before it
  // (a tab whose range starts in scene 2 draws scene 2 exactly as a tab that came through scene 1 does).
  function resetThree() {
    camera.copy(cameraHome, false);  // fov, zoom, near, far, aspect, view offset, position, orientation, up
    camera.updateProjectionMatrix();
    renderer.setClearColor(colors.bg, clearAlpha());
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

  // Draws the scene for time T once, from a clean stage. The scene's t stops at its length, so through the breath (and
  // past the last scene's end) it holds its last picture. `again` is true for the second drawing of a frame whose
  // clips have just been seeked: they are drawn as they now are.
  function drawFrame(T, again) {
    frameTime = T;
    const current = sceneAt(T);
    const t = Math.min(Math.max(T - current.start, 0), current.s.length);
    hideAllElements();
    ctx.reset();
    resetThree();
    clipsThisFrame = new Map();
    seeksNeeded = [];
    afterSeeks = again;
    for (const extension of extensions) {
      if (extension.beforeFrame) {
        extension.beforeFrame();
      }
    }
    if (brand !== null) {
      brandBefore(T);
    }
    current.scene.draw(t, current.s);
    renderer.render(current.s.three.scene, camera);
    if (brand !== null) {
      brandAfter(T, current);
    }
  }

  // Draws the picture for time T (seconds into the video) and says when it is ready to be photographed: true at once
  // for a frame without clips; a promise of true for a frame that draws a clip (the renderer's evaluate awaits it).
  // While pictures are still loading (the first frame) it waits for them, then draws. A clip not yet at its moment
  // is seeked and the whole frame drawn again, so a clip at the same t always gives the same picture.
  // frame(1.2) with only shapes -> true; frame(1.2) with s.clip("clip1", t) -> Promise -> true
  function frame(T) {
    if (loading) {
      return loading.then(function () {
        return frame(T);
      });
    }
    drawFrame(T, false);
    if (clipsThisFrame.size === 0) {
      return true;
    }
    if (seeksNeeded.length === 0) {
      return Promise.resolve(true);
    }
    const seeks = seeksNeeded.map(function (need) {
      return seekTo(need.asset, need.time);
    });
    return Promise.all(seeks).then(function () {
      drawFrame(T, true);
      return true;
    });
  }

  // ---- Sound cues: placed by Video.sounds, read back by Odie (Video.soundCues); nothing here is drawn or played ----

  const cues = [];  // every item Video.sounds was given, in order, as given (a copy), right or wrong

  // An item as it is kept and given back: an object copied with every key it was given (a key set to undefined
  // left out, as JSON would); anything else as it is. Whether its shape is right is Odie's to judge
  // (odie.video.sounds.shape_problem), so a slip is told once like any cue problem, then dropped.
  // {scene: 1, at: 0, name: "rain", gain: undefined} -> {scene: 1, at: 0, name: "rain"};
  // {scene: 1, at: "1.5", name: "ting", volume: 0.3} -> the same, copied; "ting" -> "ting"
  function copyOfItem(item) {
    if (Array.isArray(item)) {
      return item.slice();
    }
    if (item === null || typeof item !== "object") {
      return item;
    }
    const copy = {};
    for (const key of Object.keys(item)) {
      if (item[key] !== undefined) {
        copy[key] = item[key];
      }
    }
    return copy;
  }

  // Places the video's sound effects; called once in the page, next to Video.scenes. Each cue: scene (from 1), name
  // (a sound in Odie's set), at (seconds into the scene) or beat (a phrase of the scene's narration, from 0), and
  // optionally seconds (how long a loop plays) and gain (0..1). A second call adds to the first. Every item is kept
  // as given, right or wrong: Odie judges them when the page is submitted. Only something other than a list throws:
  // Video.sounds([{scene: 2, at: 0, name: "footsteps", seconds: 6, gain: 0.4}, {scene: 2, beat: 1, name: "whoosh"}])
  //   -> both kept; Video.sounds([{scene: 1, name: "ting"}]) -> kept (Odie tells "cue 1 has neither at nor beat")
  // Video.sounds({scene: 1, at: 0, name: "rain"}) -> Error("Video.sounds takes a list: …")
  function sounds(list) {
    if (!Array.isArray(list)) {
      throw new Error('Video.sounds takes a list: Video.sounds([{scene: 1, at: 0, name: "rain"}, ...])');
    }
    for (const item of list) {
      cues.push(copyOfItem(item));
    }
  }

  // The items Video.sounds was given, in order, as copies (changing them changes nothing kept); [] when the page
  // placed none. Odie reads this once in the submit check.
  function soundCues() {
    return cues.map(copyOfItem);
  }

  // Odie's own scenes after the writer's last (the credits card), registered before the page's script runs.
  const closingScenes = [];

  // Adds a scene that plays after the page's own, whatever the page's Video.scenes([...]) holds: Odie's credits card
  // calls it ahead of the writer's body, and its length is the last entry of window.__timings.
  // Video.closing({draw(t, s) { s.text("odie-credits-title", "Pictures"); }})
  function closing(scene) {
    closingScenes.push(scene);
  }

  let pageScenes = [];  // the scenes the page gave Video.scenes, kept until they are laid out
  let playingLabels = [];  // each laid-out scene's label, in playing order (see playingOrder)

  // Takes the page's scenes and puts them on the timeline (layout), with Odie's closing scenes after them (see
  // closing). window.__sceneCount is the page's own scenes, which the check matches against the narration. In the
  // page check of a video with a brand kit (window.__layoutLater), the scenes wait: the check reads the timed marks
  // first, then gives the timings with the kit's bookends in them to Video.layout.
  // Video.scenes([{setup(s) {...}, draw(t, s) {...}}, {draw(t, s) {...}}])
  function scenes(list) {
    window.__sceneCount = list.length;
    timedMarks = {starts: [], ends: []};
    list.forEach(function (scene, i) {
      if (scene && scene.timed_start === true) {
        timedMarks.starts.push(i + 1);
      }
      if (scene && scene.timed_end === true) {
        timedMarks.ends.push(i + 1);
      }
    });
    pageScenes = list;
    if (window.__layoutLater) {
      return;
    }
    layout();
  }

  // The scenes in playing order, each with its label: the page's own by number (from 1), a brand kit's handoff just
  // before the timed segment's first scene and its ending right after its last, then Odie's closing scenes (the
  // credits card "closing", then a kit's "card"). Three scenes, the second the segment, every bookend ->
  // labels [1, "handoff", 2, "ending", 3, "card"]; no kit -> [1, 2, 3], then "closing" for a credits card.
  function playingOrder(list) {
    const around = brandSegment();
    const order = [];
    list.forEach(function (scene, i) {
      if (around && i === around.first && bookends.handoff) {
        order.push({scene: bookends.handoff, label: "handoff"});
      }
      order.push({scene: scene, label: i + 1});
      if (around && i === around.last && bookends.ending) {
        order.push({scene: bookends.ending, label: "ending"});
      }
    });
    for (const scene of closingScenes) {
      order.push({scene: scene, label: scene.label || "closing"});
    }
    return order;
  }

  // Puts the scenes on the timeline in playing order and defines window.__frame; setup(s) (optional) runs once per
  // scene, here. `timings` (given by the page check once it has read the marks) replaces window.__timings first.
  // Video.layout({starts: [...], lengths: [...], beats: [[...], ...]})
  function layout(timings) {
    if (timings) {
      window.__timings = timings;
    }
    const given = window.__timings;
    if (!given || !given.starts || !given.lengths) {
      throw new Error("window.__timings is missing: the tool sets it from the narration before the page runs");
    }
    const order = playingOrder(pageScenes);
    if (given.lengths.length !== order.length) {
      const narrated = given.lengths.length - (order.length - pageScenes.length);
      throw new Error(`The page has ${pageScenes.length} scenes but the narration has ${narrated}.`);
    }
    buildStage();
    loadAllFonts();
    placed = [];
    for (let i = 0; i < order.length; i++) {
      const s = helpersFor(given.lengths[i], beatsFor(given, i));
      placed.push({scene: order[i].scene, label: order[i].label, index: i, start: given.starts[i], s: s});
    }
    playingLabels = order.map(function (entry) {
      return entry.label;
    });
    if (brand !== null) {
      settleBrand();
    }
    for (const p of placed) {
      if (p.scene.setup) {
        p.scene.setup(p.s);
      }
    }
    window.__frame = frame;
  }

  // The scenes' labels in playing order (see playingOrder), for Odie to check against its own order.
  function order() {
    return playingLabels.slice();
  }

  // ---- A brand kit (odie.video.brand): a skill's own fixed drawing, set up by Odie before the page's script ----

  let brand = null;  // {kit, settings, back, top, segment, byNumber, covered} for a video with a kit; null without
  const bookends = {};  // the kit's handoff and ending scenes, placed around the timed segment (playingOrder)
  const moveCues = [];  // every item Video.moves was given, in order, as given (a copy)
  const COVERED_SHARE = 0.95;  // a scene opaque at this share of the grid's points has covered the kit's background

  // Freezes an object and everything under it, so nothing in the page can change it. Returns it.
  function deepFreeze(value) {
    const freezable = value !== null && (typeof value === "object" || typeof value === "function");
    if (!freezable || Object.isFrozen(value)) {
      return value;
    }
    Object.freeze(value);
    for (const key of Reflect.ownKeys(value)) {
      const property = Object.getOwnPropertyDescriptor(value, key);
      if (property && "value" in property) {
        deepFreeze(property.value);
      }
    }
    return value;
  }

  // Sets up the kit that brand.js put in window.Brand, with Odie's settings for this video ({background, character,
  // moves, bookends: {handoff: {seconds}, ...}, vars, timed}): checks Brand has every function the settings call
  // for, freezes it all and fixes window.Brand so the page can't replace or change it, and makes the bookend scenes
  // (the card plays after everything, as a closing scene, after the credits card). A kit missing a function ->
  // Error("brand kit: Brand.background isn't a function"); keep a kit's state in its own variables, not on Brand.
  function brandKit(settings) {
    const kit = window.Brand;
    if (!kit || typeof kit !== "object") {
      throw new Error("brand kit: brand.js didn't set window.Brand");
    }
    const needed = [];
    if (settings.background) {
      needed.push(["background", kit.background]);
    }
    if (Object.keys(settings.bookends).length > 0) {
      needed.push(["bookend", kit.bookend]);
    }
    if (settings.character) {
      const character = kit[settings.character];
      needed.push([settings.character + ".draw", character && character.draw]);
    }
    for (const [name, fn] of needed) {
      if (typeof fn !== "function") {
        throw new Error(`brand kit: Brand.${name} isn't a function`);
      }
    }
    deepFreeze(kit);
    Object.defineProperty(window, "Brand", {value: kit, writable: false, configurable: false, enumerable: true});
    brand = {kit: kit, settings: deepFreeze(JSON.parse(JSON.stringify(settings))), back: null, top: null,
             segment: null, byNumber: new Map(), covered: new Set()};
    for (const name of ["handoff", "ending"]) {
      if (settings.bookends[name]) {
        bookends[name] = bookendScene(name, settings.bookends[name].seconds);
      }
    }
    if (settings.bookends.card) {
      closing(bookendScene("card", settings.bookends.card.seconds));
    }
  }

  // One of the kit's fixed scenes: Brand.bookend draws it on the kit's top canvas, over the kit's background; its
  // animation runs for the bookend's seconds, then holds its last frame (a handoff held longer for a long line).
  function bookendScene(name, seconds) {
    return {
      label: name,
      draw: function (t) {
        kitCall(function () {
          brand.kit.bookend(name, brand.top.ctx, Math.min(t, seconds), W, H, brand.settings.vars);
        });
      },
    };
  }

  // The timed segment's first and last page scene (from 0), for placing a kit's handoff and ending: only for a video
  // with a kit and a timed segment, and only when the page marked one segment. Marks {starts: [2], ends: [3]} ->
  // {first: 1, last: 2}; no kit, no timed segment, or marks Odie refuses (none, two starts, an end before the
  // start) -> null.
  function brandSegment() {
    if (brand === null || !brand.settings.timed) {
      return null;
    }
    if (timedMarks.starts.length !== 1 || timedMarks.ends.length !== 1) {
      return null;
    }
    const first = timedMarks.starts[0] - 1;
    const last = timedMarks.ends[0] - 1;
    if (last < first) {
      return null;
    }
    return {first: first, last: last};
  }

  // Once the scenes are laid out: where the timed segment plays among them (for the character) and each page
  // scene by its number (for the moves).
  function settleBrand() {
    for (const p of placed) {
      if (typeof p.label === "number") {
        brand.byNumber.set(p.label, p);
      }
    }
    const around = brandSegment();
    if (around !== null) {
      brand.segment = {first: brand.byNumber.get(around.first + 1).index,
                       last: brand.byNumber.get(around.last + 1).index};
    }
  }

  // Decides whether the scene drawing now is in the timed segment, where the kit's character is drawn: a scene
  // between the segment's first and last (the breaths between them too) -> true; the handoff, the ending, any
  // scene before or after, or a video without a segment -> false.
  function inSegment(current) {
    const segment = brand.segment;
    return segment !== null && current.index >= segment.first && current.index <= segment.last;
  }

  // Runs one of the kit's own functions; an error in it is told as the kit's ("brand kit: …"), not the page's, so
  // Odie can tell the user the kit is broken instead of asking the writer to fix what isn't its.
  function kitCall(fn) {
    try {
      return fn();
    } catch (error) {
      const words = error && error.message ? error.message : String(error);
      throw new Error("brand kit: " + words);
    }
  }

  // Before the scene draws at T: the kit's top canvas cleared, and its background drawn under everything.
  function brandBefore(T) {
    brand.top.ctx.reset();
    if (brand.back) {
      brand.back.ctx.reset();
      kitCall(function () {
        brand.kit.background(brand.back.ctx, T, W, H);
      });
    }
  }

  // After the scene drew at T: the segment clock given to the kit's timer hooks (Brand.timer and the character's
  // timer, whichever it has) whenever the clock runs, so a countdown is always the clock's; the character drawn over
  // the scene through the whole timed segment, with the clock and the moves playing; and, in the page check, whether
  // the page's scene covered the kit's background.
  function brandAfter(T, current) {
    const kit = brand.kit;
    const left = clockAt(T);
    let character = null;
    if (brand.settings.character) {
      character = kit[brand.settings.character];
    }
    if (left !== null) {
      kitCall(function () {
        if (typeof kit.timer === "function") {
          kit.timer(left);
        }
        if (character && typeof character.timer === "function") {
          character.timer(left);
        }
      });
    }
    if (character && inSegment(current)) {
      const into = T - placed[brand.segment.first].start;
      const info = {left: left, moves: activeMoves(T), safe: SAFE};
      kitCall(function () {
        character.draw(brand.top.ctx, into, W, H, info);
      });
    }
    if (window.__brandCheck && typeof current.label === "number" && coversBackground(current)) {
      brand.covered.add(current.label);
    }
  }

  // Decides, in the page check, whether the page's scene covered the kit's background: a three.js background or an
  // opaque clear colour, or a 2D canvas opaque at nearly every point of a 9 x 16 grid (a fill or a picture over the
  // whole stage) -> true; shapes, text and framed pictures leave most of the grid clear -> false. Only a kit that
  // draws the background asks.
  function coversBackground(current) {
    if (!brand.back) {
      return false;
    }
    if (current.s.three.scene.background || renderer.getClearAlpha() > 0.01) {
      return true;
    }
    const data = ctx.getImageData(0, 0, W, H).data;
    let opaque = 0;
    let points = 0;
    for (let row = 0; row < 16; row++) {
      for (let column = 0; column < 9; column++) {
        const x = Math.floor((column + 0.5) * W / 9);
        const y = Math.floor((row + 0.5) * H / 16);
        if (data[(y * W + x) * 4 + 3] > 240) {
          opaque += 1;
        }
        points += 1;
      }
    }
    return opaque / points >= COVERED_SHARE;
  }

  // What the page check found about the kit: the page's scenes (from 1) that covered its background.
  function brandReport() {
    if (brand === null) {
      return {covered: []};
    }
    return {covered: Array.from(brand.covered).sort(function (a, b) {
      return a - b;
    })};
  }

  // Cues the kit character's moves in the timed segment; called once in the page, next to Video.scenes. Each cue:
  // scene (from 1), name (one of the kit's moves), and at (seconds into the scene) or beat (a phrase, from 0). Kept
  // as given; Odie judges them when the page is submitted. Only something other than a list throws.
  // Video.moves([{scene: 2, at: 1.5, name: "bounce"}, {scene: 3, beat: 1, name: "bounce"}])
  function moves(list) {
    if (!Array.isArray(list)) {
      throw new Error('Video.moves takes a list: Video.moves([{scene: 2, at: 1.5, name: "bounce"}])');
    }
    for (const item of list) {
      moveCues.push(copyOfItem(item));
    }
  }

  // The items Video.moves was given, in order, as copies; [] when the page cued none.
  function moveCuesGiven() {
    return moveCues.map(copyOfItem);
  }

  // The character's moves playing at T, each {name, t (seconds into the move), seconds}. A move cued in scene 2 at
  // 1.0, scene 2 starting at 10 and the move lasting 0.6 s -> at T 10.3, [{name, t: 0.3, seconds: 0.6}]; at T 11, [].
  function activeMoves(T) {
    const playing = [];
    for (const cue of moveCues) {
      const seconds = brand.settings.moves[cue.name];
      const p = brand.byNumber.get(cue.scene);
      if (!seconds || !p) {
        continue;
      }
      let offset = cue.at;
      if (typeof cue.beat === "number") {
        offset = p.s.beats[cue.beat];
      }
      if (typeof offset !== "number") {
        continue;
      }
      const start = p.start + offset;
      if (T >= start && T < start + seconds) {
        playing.push({name: cue.name, t: T - start, seconds: seconds});
      }
    }
    return playing;
  }

  window.Video = {scenes: scenes, closing: closing, assets: registerAssets, lines: registerLines, sounds: sounds,
                  soundCues: soundCues,
                  timedScenes: timedScenes, extend: extend, clockAt: clockAt, colors: colors, W: W, H: H, safe: SAFE,
                  layout: layout, order: order, brand: brandKit, moves: moves, moveCues: moveCuesGiven,
                  brandReport: brandReport,
                  SANS: SANS};
})();
