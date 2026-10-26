// avatar.js: the 3D characters of a dialogue video (odie.video.avatars). Odie puts this file on the page only when a
// speaker's cast sheet names a 3D model (.vrm or .glb), after three.js's GLTFLoader and three-vrm; a page without
// one never has it. The model's bytes never sit in the page: Odie hands them over after the tab opens, in pieces
// (__avatars.bytes), and waits for __avatars.ready() before the first frame.
//
// Every frame must be a pure function of its time, so the four render tabs, each starting at a different frame,
// draw frame T the same way whatever they drew before.
//
// window.__avatars:
//   expect({mira: {name: "Mira", kind: "vrm", bytes: 10776032}})  the models to wait for (Odie, in the page)
//   bytes("mira", 0, "Z2xURg...")                                  one piece of a model's file, at its place
//   ready() -> Promise<{failed: {mira: "error text"}}>             parses each model once; never rejects
//   frame(T)                                                       waits for ready(), then draws frame T
//   models: Map("mira" -> {gltf, vrm (null for a plain glTF), name, kind})   the parsed models, for the helpers
//   time                                                           the time of the frame being drawn
//
// The writer's helpers, on every scene's s (see "The writer's helpers" below):
//   s.level("mira")                          Mira's smoothed loudness in this frame, 0..1
//   s.avatar("mira", {x, y, z, turn, scale}) Mira's 3D character in this scene; its update(t) in every draw moves her
//                                            mouth with her voice, blinks, sways, breathes and swings her hair
(function () {
  "use strict";

  const expected = new Map();  // id -> {name, kind, data: Uint8Array of the whole file, received, problem}
  const models = new Map();    // id -> {gltf, vrm, name, kind}, once parsed
  let parsing = null;          // the one promise ready() gives, once asked

  // parseSeconds: how long a model may take to parse before the page stops waiting and calls it a failure, so Odie
  // hears why well before its own 120 s limit on a page command (a test may lower it). time: the frame being drawn.
  const api = {parseSeconds: 60, time: 0, models: models};

  // The models Odie will hand over, each with room for its whole file. expect({mira: {name: "Mira", kind: "glb",
  // bytes: 104}}) -> a 104-byte buffer waiting for Mira's bytes.
  function expect(list) {
    for (const id of Object.keys(list)) {
      const model = list[id];
      expected.set(id, {name: model.name, kind: model.kind, data: new Uint8Array(model.bytes), received: 0,
                        problem: null});
    }
  }

  // One piece of a model's file, base64, put at its place: bytes("mira", 4194304, "...") fills Mira's buffer from
  // byte 4194304 on. A piece that runs past the end (the file grew after Odie checked it) is kept as that model's
  // problem, told by ready(), instead of thrown here.
  function bytes(id, offset, text) {
    const model = expected.get(id);
    if (!model) {
      throw new Error("No 3D model was expected for " + id);
    }
    const raw = atob(text);
    if (offset + raw.length > model.data.length) {
      model.problem = "the file is bigger than when it was checked (" + model.data.length + " bytes); was it changed?";
      return;
    }
    for (let i = 0; i < raw.length; i++) {
      model.data[offset + i] = raw.charCodeAt(i);
    }
    model.received += raw.length;
  }

  // A model made ready to draw: a VRM 0.x turned to face the camera like a VRM 1.0, its skeletons combined (one
  // skeleton for all its meshes); and no mesh is skipped for being off camera (a skinned mesh's bounds don't follow
  // its bones, so it would vanish at the wrong moments).
  function prepare(gltf) {
    const vrm = gltf.userData.vrm || null;
    if (vrm) {
      THREE_VRM.VRMUtils.rotateVRM0(vrm);
      THREE_VRM.VRMUtils.combineSkeletons(gltf.scene);
    }
    gltf.scene.traverse(function (object) {
      if (object.isMesh) {
        object.frustumCulled = false;
      }
    });
    return vrm;
  }

  // Whether a file starts as every .vrm and .glb does, with the four letters "glTF": a VRoid export -> true; a JPEG
  // renamed mira.glb (it starts with 0xFF 0xD8) -> false.
  function isGlb(data) {
    const start = String.fromCharCode(data[0], data[1], data[2], data[3]);
    return start === "glTF";
  }

  // One model parsed, as a promise that always resolves: null when it worked (the model is then in `models`), else
  // the reason in words. Whatever goes wrong settles it: bytes missing ("only 100 of 150 bytes arrived"), a file that
  // isn't a glTF binary at all (a JPEG renamed .glb), the loader throwing at once or calling back with an error (a
  // truncated download: "Invalid typed array length: 660"), or the loader never calling back ("didn't finish within
  // 60 s").
  function parseOne(id, model) {
    return new Promise(function (resolve) {
      let settled = false;
      let giveUp = null;
      function settle(problem) {
        if (!settled) {
          settled = true;
          clearTimeout(giveUp);
          resolve(problem);
        }
      }
      function failed(error) {
        let text = String(error);  // a thrown string, or "Error: ..." as a last resort
        if (error instanceof Error && error.message) {
          text = error.message;
        }
        settle(text);
      }
      function parsed(gltf) {
        try {
          const vrm = prepare(gltf);
          models.set(id, {gltf: gltf, vrm: vrm, name: model.name, kind: model.kind});
          settle(null);
        } catch (error) {
          failed(error);
        }
      }
      if (model.problem) {
        settle(model.problem);
        return;
      }
      if (model.received < model.data.length) {
        settle("only " + model.received + " of " + model.data.length + " bytes arrived");
        return;
      }
      if (!isGlb(model.data)) {
        settle('it isn\'t a glTF binary file (a .vrm or .glb starts with "glTF")');
        return;
      }
      giveUp = setTimeout(function () {
        settle("it didn't finish within " + api.parseSeconds + " s");
      }, api.parseSeconds * 1000);
      try {
        const loader = new THREE.GLTFLoader();
        loader.register(function (parser) {
          return new THREE_VRM.VRMLoaderPlugin(parser);
        });
        loader.parse(model.data.buffer, "", parsed, failed);
      } catch (error) {
        failed(error);
      }
    });
  }

  // Every expected model parsed, once (later calls give the same promise): {failed: {}} when all worked, else
  // {failed: {mira: "only 100 of 150 bytes arrived"}}. Never rejects, so Odie always hears which model and why.
  function ready() {
    if (parsing === null) {
      const ids = Array.from(expected.keys());
      const each = ids.map(function (id) {
        return parseOne(id, expected.get(id));
      });
      parsing = Promise.all(each).then(function (problems) {
        const failed = {};
        ids.forEach(function (id, i) {
          if (problems[i] !== null) {
            failed[id] = problems[i];
          }
        });
        return {failed: failed};
      });
    }
    return parsing;
  }

  // Frame T of a page with 3D characters: its time kept for the helpers, then drawn once the models are parsed.
  // frame(1.5) -> what __frame(1.5) gives (true, or a promise of it).
  function frame(T) {
    api.time = T;
    return ready().then(function () {
      return window.__frame(T);
    });
  }

  api.expect = expect;
  api.bytes = bytes;
  api.ready = ready;
  api.frame = frame;
  window.__avatars = api;

  // ---- The writer's helpers: s.level(id) and s.avatar(id) ----
  //
  // Every value here is a pure function of the frame: the voice is read at the frame's time T (api.time, as s.mouth
  // reads it), blinks and idle motion at the scene's t (what draw is given), and each update sets every face weight
  // and bone it drives from rest, so frame T looks the same whatever a tab drew before it.

  const STEP = 0.02;           // seconds per loudness value (odie.video.dialogue.LOUDNESS_STEP)
  const LEAD = 0.04;           // the mouth moves this much before the sound: lips shape a sound just ahead of it
  const SPREAD = 0.025;        // seconds between the five reads that are averaged into a level
  const UNKNOWN_LEVEL = 0.5;   // a line whose loudness isn't known yet (the page check): the mouth half open
  const SPRING_WARMUP = 0.5;   // seconds of hair swing run before each frame, from rest
  const SPRING_STEP = 1 / 60;  // seconds per step of that run
  const ARM_DOWN = 1.2;        // radians the upper arms turn down from a VRM's T-pose
  const LOOK_LIMIT = 0.35;     // radians the head turns at most toward what it looks at
  const BLINK_FIRST = 0.9;     // seconds into the scene of the first blink
  const BLINK_CLOSING = 0.06;  // seconds the eyelids take to shut
  const BLINK_OPENING = 0.10;  // seconds they take to open again

  // How each shot frames a character, around where the head rests: the camera's field of view (degrees), how far in
  // front of the head it stands and how far above it (metres), and how far above the head it aims (below, when
  // negative). The metres grow with the character's scale. "bust" aims straight at the head bone.
  const SHOTS = {
    face: {fov: 20, distance: 0.8, rise: 0.02, aim: 0.06},
    bust: {fov: 22, distance: 1.55, rise: 0.05, aim: 0},
    waist: {fov: 26, distance: 2.1, rise: -0.1, aim: -0.2},
    full: {fov: 30, distance: 3.6, rise: -0.3, aim: -0.7},
  };

  // A plain glTF's face shapes, by morph target name (compared without case, after the last "."; a name ending in
  // "*" takes any name that starts with it). A VRM uses its expression presets instead.
  const GLTF_SHAPES = {
    aa: ["aa", "A", "jawOpen", "mouthOpen", "Fcl_MTH_A", "v_aa"],
    ih: ["ih", "I", "Fcl_MTH_I", "v_ih"],
    ou: ["ou", "U", "mouthFunnel", "Fcl_MTH_U", "v_ou"],
    ee: ["ee", "E", "Fcl_MTH_E", "v_e"],
    oh: ["oh", "O", "mouthPucker", "Fcl_MTH_O", "v_oh"],
    blink: ["blink", "eyesClosed", "Fcl_EYE_Close", "eyeBlinkLeft", "eyeBlinkRight"],
    smile: ["happy", "mouthSmile", "mouthSmileLeft", "mouthSmileRight", "Fcl_MTH_Fun"],
    browsUp: ["browInnerUp", "Fcl_BRW_Surprised"],
    browsDown: ["browDown*", "Fcl_BRW_Angry"],
  };

  // A VRM's brow-only face shapes, when its face mesh has them (VRoid's Fcl_BRW_Surprised): they lift or lower just
  // the brows, where the "surprised" and "angry" presets move the whole face.
  const VRM_BROWS = {up: ["*BRW_Surprised"], down: ["*BRW_Angry"]};

  // A VRM's mouth-only smile, when its face mesh has one (VRoid's Fcl_MTH_Fun, ARKit's mouthSmile): it curves just the
  // mouth, where the "happy" preset moves the whole face and also holds back blinks and the mouth while it shows.
  const VRM_SMILE = ["Fcl_MTH_Fun", "mouthSmile", "mouthSmileLeft", "mouthSmileRight"];

  // ---- The line timeline, kept with each line's running loudness ----

  let lines = [];  // [{speaker, t, dur, text, amplitude, sums}]: Video.lines as Odie gave it

  // Odie gives the page its lines once, with Video.lines([...]) (after this file): video.js keeps them for s.mouth,
  // and a copy is kept here, each line with its running loudness sums, for the vowel guess (see visemeMix).
  const givenLines = Video.lines;
  Video.lines = function (list) {
    givenLines(list);
    lines = list.map(keptLine);
  };

  // A line as kept here: the speaker in lower case, as the script's are, and `sums`, the running total of its
  // loudness. Amplitude [0, 0.5, 1] -> sums [0, 0, 0.5, 1.5].
  function keptLine(line) {
    const amplitude = line.amplitude || [];
    const sums = [0];
    for (let i = 0; i < amplitude.length; i++) {
      sums.push(sums[i] + amplitude[i]);
    }
    return {speaker: String(line.speaker).toLowerCase(), t: line.t, dur: line.dur, text: line.text || "",
            amplitude: amplitude, sums: sums};
  }

  // Decides whether a line is playing at T: a line at 0.5 for 1.0 s -> T 0.5 or 1.4 yes; T 1.5 (its end) no.
  function isPlaying(line, T) {
    return T >= line.t && T < line.t + line.dur;
  }

  // A line's loudness `local` seconds into it, read between its 20 ms steps (linear); 0 past its last value.
  // Amplitude [0, 1] -> local 0.01 (half way between them) -> 0.5.
  function rawLevel(line, local) {
    const amplitude = line.amplitude;
    const x = local / STEP;
    const i = Math.floor(x);
    if (i < 0 || i >= amplitude.length) {
      return 0;
    }
    const here = amplitude[i];
    let next = 0;
    if (i + 1 < amplitude.length) {
      next = amplitude[i + 1];
    }
    return here + (next - here) * (x - i);
  }

  // How loud a speaker is at the very moment T: their playing line's loudness there, UNKNOWN_LEVEL all through a
  // line whose loudness isn't known yet, 0 while they aren't speaking. Mira's line at 0.5, loud from 0.7 -> T 0.8 -> 1;
  // T 0.6 -> 0; while Tobi speaks -> 0 for Mira.
  function levelAtMoment(id, T) {
    let level = 0;
    for (const line of lines) {
      if (line.speaker !== id || !isPlaying(line, T)) {
        continue;
      }
      if (line.amplitude.length === 0) {
        level = UNKNOWN_LEVEL;
      } else {
        level = rawLevel(line, T - line.t);
      }
    }
    return level;
  }

  // A speaker's smoothed loudness at T (0..1): read LEAD seconds ahead of the sound and averaged over ±50 ms (five
  // reads SPREAD apart, weighted 1, 2, 3, 2, 1), so a jaw glides instead of jittering. level("mira", 1.0) in her
  // loudest run -> 1.0; 40 ms before that run, half way in -> about 0.67; while Tobi speaks -> 0.
  function levelAt(id, T) {
    let total = 0;
    let weights = 0;
    for (let k = -2; k <= 2; k++) {
      const weight = 3 - Math.abs(k);
      total += weight * levelAtMoment(id, T + LEAD + k * SPREAD);
      weights += weight;
    }
    return total / weights;
  }

  // The vowel letters each mouth shape stands for.
  const VOWEL_SHAPE = {a: "aa", i: "ih", y: "ih", u: "ou", w: "ou", e: "ee", o: "oh"};

  // The mouth shape mix at T, {aa, ih, ou, ee, oh} summing to 1, from the vowel letters near where the voice is in the
  // line's text. Where the voice is comes from the running share of the line's loudness: loud parts are vowels, so
  // moving through the text with the loudness lands on vowels better than moving with the clock. Vowels within 3
  // letters count, nearer ones more. Not speaking, or no vowel near -> all aa (the jaw). "You should sleep" a third
  // of the way through its loudness -> mostly ou ("should"), a little ee.
  function visemeMix(id, T) {
    const mix = {aa: 0, ih: 0, ou: 0, ee: 0, oh: 0};
    for (const line of lines) {
      if (line.speaker !== id || !isPlaying(line, T)) {
        continue;
      }
      const sums = line.sums;
      let total = sums[sums.length - 1];
      if (total === 0) {
        total = 1;
      }
      const step = Math.floor((T + LEAD - line.t) / STEP);
      const i = Math.min(sums.length - 1, Math.max(0, step));
      const text = line.text.toLowerCase();
      const at = (sums[i] / total) * text.length;
      for (let j = Math.floor(at) - 3; j <= Math.floor(at) + 3; j++) {
        const shape = VOWEL_SHAPE[text[j]];
        if (shape === undefined) {
          continue;
        }
        mix[shape] += Math.max(0, 1 - Math.abs(j + 0.5 - at) / 3.5);
      }
    }
    const sum = mix.aa + mix.ih + mix.ou + mix.ee + mix.oh;
    if (sum === 0) {
      return {aa: 1, ih: 0, ou: 0, ee: 0, oh: 0};
    }
    for (const shape of Object.keys(mix)) {
      mix[shape] /= sum;
    }
    return mix;
  }

  // ---- Blinks and idle motion: pure functions of the scene's t ----

  // A number in 0..1 that looks random but is always the same for the same n.
  function hash(n) {
    const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  // Each speaker's own blink rhythm: the sum of their id's letter codes. "mira" -> 425.
  function seedOf(id) {
    let seed = 0;
    for (let i = 0; i < id.length; i++) {
      seed += id.charCodeAt(i);
    }
    return seed;
  }

  // The eyelids at t: 0 open, 1 shut. The first blink at BLINK_FIRST, then one every 2.5 to 4.5 s (the gap from
  // hash), each shutting in 0.06 s and opening in 0.10 s. t 0.5 -> 0; t 0.93 -> 0.5 (half shut); t 0.96 -> 1.
  function blinkAt(t, seed) {
    let start = BLINK_FIRST;
    for (let n = 0; start < t + 1; n++) {
      const into = t - start;
      if (into >= 0 && into < BLINK_CLOSING) {
        return into / BLINK_CLOSING;
      }
      if (into >= BLINK_CLOSING && into < BLINK_CLOSING + BLINK_OPENING) {
        return 1 - (into - BLINK_CLOSING) / BLINK_OPENING;
      }
      start += 2.5 + 2 * hash(n + seed);
    }
    return 0;
  }

  // The idle motion at t, as turns [x nods forward, y turns to her left, z tilts] in radians: a slow sway of the head
  // with a small nod as loud as the voice (`level`), the neck along with it, and a breath in the spine.
  function idleAt(t, level) {
    return {
      head: [0.03 * Math.sin(1.3 * t) + 0.06 * level, 0.07 * Math.sin(0.6 * t + 0.5), 0.03 * Math.sin(0.8 * t)],
      neck: [0.01 * Math.sin(0.9 * t), 0.03 * Math.sin(0.45 * t), 0],
      spine: [0.012 * Math.sin(1.6 * t), 0, 0],
    };
  }

  // ---- What a model offers: its head, its face shapes, where its head rests ----

  // A morph target's own name: what follows the last "." ("Face_Blendshape.Fcl_MTH_A" -> "Fcl_MTH_A").
  function shortName(name) {
    return name.slice(name.lastIndexOf(".") + 1);
  }

  // Decides whether a morph target's name is one of `wanted`, without case, after the last ".". "Face.Fcl_MTH_A"
  // against ["aa", "Fcl_MTH_A"] -> true; "browDownLeft" against ["browDown*"] -> true; "Fcl_BRW_Surprised" against
  // ["*BRW_Surprised"] -> true; "mouthSmile" against ["aa"] -> false.
  function nameMatches(name, wanted) {
    const own = shortName(name).toLowerCase();
    for (const pattern of wanted) {
      const word = pattern.toLowerCase().replace(/\*/g, "");
      if (pattern.startsWith("*") && own.endsWith(word)) {
        return true;
      }
      if (pattern.endsWith("*") && own.startsWith(word)) {
        return true;
      }
      if (own === word) {
        return true;
      }
    }
    return false;
  }

  // Every face shape in the model whose name is one of `wanted`, as [{mesh, index}] (a face is often several meshes,
  // one per material, each with the same shapes). None -> [] (that shape is skipped).
  function morphsNamed(root, wanted) {
    const found = [];
    root.traverse(function (object) {
      const dictionary = object.morphTargetDictionary;
      if (!dictionary) {
        return;
      }
      for (const name of Object.keys(dictionary)) {
        if (nameMatches(name, wanted)) {
          found.push({mesh: object, index: dictionary[name]});
        }
      }
    });
    return found;
  }

  // A plain glTF's head: the first node whose name says head ("Head", "J_Bip_C_Head", "mixamorig:Head"), or null.
  function headNodeOf(root) {
    let head = null;
    root.traverse(function (object) {
      if (head === null && object !== root && /head/i.test(object.name)) {
        head = object;
      }
    });
    return head;
  }

  // The point the camera and other characters aim at, in the frame of the Group that will hold the model: its head
  // as it rests, or, for a model without a head, the top middle of its bounding box.
  function anchorOf(root, head) {
    if (head !== null) {
      return head.getWorldPosition(new THREE.Vector3());
    }
    const box = new THREE.Box3().setFromObject(root);
    const middle = box.getCenter(new THREE.Vector3());
    return new THREE.Vector3(middle.x, box.max.y, middle.z);
  }

  // What the helpers need from a model, worked out once, the first time a character is drawn, while the model still
  // rests on no stage (its world is the frame of the Group that will hold it): its head, the point to aim at, and its
  // face shapes (a plain glTF: each shape's morph targets; a VRM: only its mouth-only smile and brow-only shapes, the
  // rest are presets).
  // A plain glTF's head keeps its rest turn and its parent's resting orientation in userData, so every frame turns it
  // from rest (see turnFromRest).
  function rigOf(model) {
    if (model.rig) {
      return model.rig;
    }
    const root = model.gltf.scene;
    root.updateMatrixWorld(true);
    const rig = {head: null, anchor: null, shapes: {}, smile: [], brows: {up: [], down: []}};
    if (model.vrm) {
      rig.head = model.vrm.humanoid.getRawBoneNode("head");
      rig.smile = morphsNamed(root, VRM_SMILE);
      rig.brows.up = morphsNamed(root, VRM_BROWS.up);
      rig.brows.down = morphsNamed(root, VRM_BROWS.down);
    } else {
      rig.head = headNodeOf(root);
      for (const shape of Object.keys(GLTF_SHAPES)) {
        rig.shapes[shape] = morphsNamed(root, GLTF_SHAPES[shape]);
      }
      if (rig.head !== null) {
        rig.head.userData.rest = rig.head.quaternion.clone();
        rig.head.userData.parentRest = rig.head.parent.getWorldQuaternion(new THREE.Quaternion());
      }
    }
    rig.anchor = anchorOf(root, rig.head);
    model.rig = rig;
    return rig;
  }

  // ---- Posing: every bone set from rest ----

  const euler = new THREE.Euler();
  const turnBy = new THREE.Quaternion();
  const parentInverse = new THREE.Quaternion();

  // Sets a plain glTF bone to its rest pose turned by (x, y, z) radians about the model's own axes (x nods forward,
  // y turns, z tilts), whatever way the bone itself is rotated at rest.
  function turnFromRest(bone, x, y, z) {
    const parentRest = bone.userData.parentRest;
    turnBy.setFromEuler(euler.set(x, y, z));
    parentInverse.copy(parentRest).invert();
    bone.quaternion.copy(parentInverse).multiply(turnBy).multiply(parentRest).multiply(bone.userData.rest);
  }

  // Sets a VRM's normalized humanoid bone (identity at rest, in the model's axes) to a turn of (x, y, z) radians.
  // A VRM 0.x faces the other way inside its own scene (rotateVRM0 turned the scene round), so its x and z turns are
  // mirrored: arms down is z -1.2 on a VRM 1.0's left upper arm and +1.2 on a VRM 0.x's. A bone the model lacks is
  // skipped.
  function turnNormalized(vrm, name, x, y, z) {
    const bone = vrm.humanoid.getNormalizedBoneNode(name);
    if (!bone) {
      return;
    }
    if (vrm.meta && vrm.meta.metaVersion === "0") {
      x = -x;
      z = -z;
    }
    bone.quaternion.setFromEuler(euler.set(x, y, z));
  }

  // A VRM's body at one moment: every normalized bone back to rest, then the idle sway, the turn toward what it looks
  // at, and the arms down from the T-pose.
  function poseVRM(vrm, idle, look) {
    vrm.humanoid.resetNormalizedPose();
    turnNormalized(vrm, "spine", idle.spine[0], idle.spine[1], idle.spine[2]);
    turnNormalized(vrm, "neck", idle.neck[0], idle.neck[1], idle.neck[2]);
    turnNormalized(vrm, "head", idle.head[0] + look.pitch, idle.head[1] + look.yaw, idle.head[2]);
    turnNormalized(vrm, "leftUpperArm", 0, 0, -ARM_DOWN);
    turnNormalized(vrm, "rightUpperArm", 0, 0, ARM_DOWN);
  }

  // A VRM's face: every preset this file uses is set, each update, so none keeps a value from an earlier frame.
  // The smile goes to the mouth-only smile shape when the face has one, else to the "happy" preset; brows go to the
  // brow-only shapes when the face has them, else to the "surprised" (up) and "angry" (down) presets at half strength,
  // as those move the whole face. The shapes are set after the VRM's own update (see setOwnShapes). A VRoid model
  // (it has Fcl_MTH_Fun) smiling 0.3 -> Fcl_MTH_Fun 0.3 and "happy" 0, so its blinks still close fully; a VRM
  // without such a shape -> "happy" 0.3.
  function setExpressions(vrm, rig, face) {
    const presets = vrm.expressionManager;
    if (!presets) {
      return;
    }
    presets.setValue("aa", face.aa);
    presets.setValue("ih", face.ih);
    presets.setValue("ou", face.ou);
    presets.setValue("ee", face.ee);
    presets.setValue("oh", face.oh);
    presets.setValue("blink", face.blink);
    let happy = 0;
    if (rig.smile.length === 0) {
      happy = face.smile;
    }
    presets.setValue("happy", happy);
    let surprised = 0;
    let angry = 0;
    if (rig.brows.up.length === 0) {
      surprised = 0.5 * Math.max(0, face.brows);
    }
    if (rig.brows.down.length === 0) {
      angry = 0.5 * Math.max(0, -face.brows);
    }
    presets.setValue("surprised", surprised);
    presets.setValue("angry", angry);
  }

  // Sets each of these face shapes to `weight`.
  function setShapes(morphs, weight) {
    for (const morph of morphs) {
      morph.mesh.morphTargetInfluences[morph.index] = weight;
    }
  }

  // A VRM's own mouth-only smile and brow-only shapes (when it has them): the smile, then the brows up for brows
  // above 0, down for brows below.
  function setOwnShapes(rig, face) {
    setShapes(rig.smile, face.smile);
    setShapes(rig.brows.up, Math.max(0, face.brows));
    setShapes(rig.brows.down, Math.max(0, -face.brows));
  }

  // A plain glTF's face: each shape it has, set; shapes it lacks are skipped.
  function setGltfFace(rig, face) {
    for (const shape of ["aa", "ih", "ou", "ee", "oh", "blink", "smile"]) {
      setShapes(rig.shapes[shape], face[shape]);
    }
    setShapes(rig.shapes.browsUp, Math.max(0, face.brows));
    setShapes(rig.shapes.browsDown, Math.max(0, -face.brows));
  }

  // MToon materials scroll their textures a little with every VRM update, adding up from frame to frame; this puts
  // each scroll back where it is at t, from its speed (0 for nearly every model), so it never depends on the past.
  function holdMaterialsAt(vrm, t) {
    for (const material of vrm.materials || []) {
      if (material.isMToonMaterial) {
        material.uvAnimationScrollXOffset = t * material.uvAnimationScrollXSpeedFactor;
        material.uvAnimationScrollYOffset = t * material.uvAnimationScrollYSpeedFactor;
        material.uvAnimationRotationPhase = t * material.uvAnimationRotationSpeedFactor;
      }
    }
  }

  // ---- A character: one speaker's model, placed in one scene ----

  // Names the speakers who have a model, for a writer who asked for one who hasn't. ["mira"] -> "only mira has one";
  // ["mira", "tobi"] -> "only mira and tobi have one"; ["anna", "mira", "tobi"] -> "only anna, mira and tobi have one".
  function whoHasOne(ids) {
    if (ids.length === 0) {
      return "no speaker has one";
    }
    if (ids.length === 1) {
      return "only " + ids[0] + " has one";
    }
    const allButLast = ids.slice(0, -1).join(", ");
    return "only " + allButLast + " and " + ids[ids.length - 1] + " have one";
  }

  // An angle kept within LOOK_LIMIT either way: 0.2 -> 0.2; 1.0 -> 0.35; -1.0 -> -0.35.
  function withinLookLimit(angle) {
    return Math.min(LOOK_LIMIT, Math.max(-LOOK_LIMIT, angle));
  }

  class Avatar {
    // Mira's character in one scene: `root` holds her model there, at (x, y, z), turned `turn` radians about the
    // vertical (0 faces the home camera), `scale` times her size. Her model joins this root at each update, so the
    // same model can stand in several scenes.
    constructor(id, options, camera) {
      this.id = id;
      this.root = new THREE.Group();
      this.root.position.set(options.x || 0, options.y || 0, options.z || 0);
      this.root.rotation.y = options.turn || 0;
      this.root.scale.setScalar(options.scale || 1);
      options.scene.add(this.root);
      this.camera = camera;
      this.smileAsked = null;  // the writer's smile (null: the resting smile, gone while speaking)
      this.browsAsked = 0;
      this.looking = null;     // {x, y, z}, another Avatar, or null
      this.lastWeights = {aa: 0, ih: 0, ou: 0, ee: 0, oh: 0, blink: 0, smile: 0, brows: 0};
    }

    // Whether this is a VRM (expression presets, a humanoid, spring hair) rather than a plain glTF. Before the model
    // is parsed, from its file: mira.vrm -> true.
    get isVRM() {
      const model = models.get(this.id);
      if (model) {
        return model.vrm !== null;
      }
      return expected.get(this.id).kind === "vrm";
    }

    // Decides whether this character can be drawn yet: Mira's model parsed -> the model; not parsed yet (a frame drawn
    // with __frame(T) before the hand-over) -> the error "Mira's 3D model isn't loaded: ...".
    model() {
      const model = models.get(this.id);
      if (!model) {
        const name = expected.get(this.id).name;
        throw new Error(name + "'s 3D model isn't loaded: frames with 3D characters are drawn with " +
                        "__avatars.frame(T), which waits for it.");
      }
      return model;
    }

    // The writer's smile, held until changed: smile(0.8) -> 0.8; smile(2) -> 1; smile(null) or smile() -> back to the
    // automatic resting smile (0.3 * (1 - amount): 0.3 while quiet, fading as the mouth opens), not 0.
    smile(amount) {
      if (amount === null || amount === undefined) {
        this.smileAsked = null;
        return;
      }
      this.smileAsked = Math.min(1, Math.max(0, amount));
    }

    brows(amount) {
      this.browsAsked = Math.min(1, Math.max(-1, amount));
    }

    look(target) {
      this.looking = target;
    }

    weights() {
      return Object.assign({}, this.lastWeights);
    }

    // Where the head rests on the stage now: the model's anchor carried by this root's placement. It never follows
    // the idle sway, so a camera or another character aiming at it is the same whichever was drawn first.
    headOnStage() {
      const rig = rigOf(this.model());
      this.root.updateWorldMatrix(true, false);
      return rig.anchor.clone().applyMatrix4(this.root.matrixWorld);
    }

    // The point this character looks at, on the stage, or null. Another character -> where their head rests.
    lookPoint() {
      const target = this.looking;
      if (target === null || target === undefined) {
        return null;
      }
      if (target instanceof Avatar) {
        return target.headOnStage();
      }
      return new THREE.Vector3(target.x || 0, target.y || 0, target.z || 0);
    }

    // How far the head turns toward the look point, in radians, each at most LOOK_LIMIT: yaw to her left (+) or
    // right, pitch down (+) or up. Nothing to look at -> 0, 0. Someone straight to her left -> yaw 0.35.
    lookTurn(point) {
      if (point === null) {
        return {yaw: 0, pitch: 0};
      }
      const toward = point.clone().sub(this.headOnStage());
      const unturn = this.root.getWorldQuaternion(new THREE.Quaternion()).invert();
      toward.applyQuaternion(unturn);  // now in her own frame: +z ahead of her, +x to her left
      const flat = Math.hypot(toward.x, toward.z);
      const yaw = Math.atan2(toward.x, toward.z);
      const pitch = Math.atan2(-toward.y, flat);
      return {yaw: withinLookLimit(yaw), pitch: withinLookLimit(pitch)};
    }

    // The face for this frame: the mouth from the voice at the frame's time T (openness from the level, shape from
    // the vowels near), the blink at the scene's t, the smile (the writer's, or a hint of one that fades while
    // speaking) and the brows.
    faceAt(t, T) {
      const level = levelAt(this.id, T);
      const mix = visemeMix(this.id, T);
      const amount = Math.min(1, Math.pow(level, 0.75) * 1.15);
      let smile = 0.3 * (1 - amount);
      if (this.smileAsked !== null) {
        smile = this.smileAsked;
      }
      return {
        aa: amount * (0.55 + 0.45 * mix.aa),  // the jaw always carries some of the opening
        ih: amount * 0.8 * mix.ih,
        ou: amount * 0.9 * mix.ou,
        ee: amount * 0.8 * mix.ee,
        oh: amount * 0.9 * mix.oh,
        blink: blinkAt(t, seedOf(this.id)),
        smile: smile,
        brows: this.browsAsked,
      };
    }

    // One frame of this character, t being draw's t: the model joins this root, then face, blink, idle motion, arms,
    // eyes and hair are set for this moment. Throws when the model isn't parsed.
    update(t) {
      const model = this.model();
      const rig = rigOf(model);
      if (model.gltf.scene.parent !== this.root) {
        this.root.add(model.gltf.scene);
      }
      const T = api.time;
      const face = this.faceAt(t, T);
      const point = this.lookPoint();
      const look = this.lookTurn(point);
      if (model.vrm) {
        this.updateVRM(model.vrm, rig, t, T, face, point, look);
      } else {
        this.updateGltf(rig, t, T, face, look);
      }
      this.lastWeights = face;
    }

    // A plain glTF: its face shapes, and its head turned from rest.
    updateGltf(rig, t, T, face, look) {
      setGltfFace(rig, face);
      if (rig.head !== null) {
        const idle = idleAt(t, levelAt(this.id, T));
        turnFromRest(rig.head, idle.head[0] + look.pitch, idle.head[1] + look.yaw, idle.head[2]);
      }
    }

    // A VRM: its presets set, then its body posed. Spring hair can't simply be set, it swings from where it was; so
    // it starts from rest posed SPRING_WARMUP seconds before t and is run at 1/60 s steps up to t, the body posed at
    // each step, and the frame then sees the same hair however the tab got here. A last update(0) at t applies the
    // pose, face and eyes without moving the hair. The VRM's own smile and brow shapes and its texture scrolls go last,
    // over the update.
    updateVRM(vrm, rig, t, T, face, point, look) {
      const self = this;
      function poseAt(when) {
        const voice = levelAt(self.id, T - (t - when));  // the voice as it was `t - when` seconds before this frame
        poseVRM(vrm, idleAt(when, voice), look);
      }
      // The posed bones put into the model, the bones its constraints drive (a VRoid sleeve's aim bones follow the arm)
      // set from them, and every world position brought up to date. The constraints run here as well as in
      // vrm.update because the hair is reset from this pose, and a sleeve's spring bones hang from constraint bones
      // that would otherwise still hold the last frame's pose (or the T-pose, on a tab's first frame).
      function settle() {
        vrm.humanoid.update();
        self.root.updateWorldMatrix(true, true);
        if (vrm.nodeConstraintManager) {
          vrm.nodeConstraintManager.update();
          self.root.updateWorldMatrix(true, true);
        }
      }
      function step(seconds) {
        settle();
        if (vrm.lookAt && point !== null) {
          vrm.lookAt.lookAt(point);
        } else if (vrm.lookAt) {
          vrm.lookAt.reset();
        }
        vrm.update(seconds);
      }
      setExpressions(vrm, rig, face);
      if (vrm.springBoneManager) {
        poseAt(t - SPRING_WARMUP);
        settle();
        vrm.springBoneManager.reset();
        const steps = Math.round(SPRING_WARMUP / SPRING_STEP);
        for (let k = 1; k <= steps; k++) {
          poseAt(t - SPRING_WARMUP + k * SPRING_STEP);
          step(SPRING_STEP);
        }
      }
      poseAt(t);
      step(0);
      setOwnShapes(rig, face);
      holdMaterialsAt(vrm, t);
    }

    // Puts the scene's camera on this character: "face" (the face fills the frame), "bust" (head and shoulders),
    // "waist" or "full" (head to toe). It aims around where the head rests (a model without a head: the top of its
    // bounding box), from in front of the character, whichever way it is turned. Call it in draw: the camera is put
    // back every frame.
    shot(kind) {
      const framing = SHOTS[kind];
      if (!framing) {
        throw new Error('shot takes "face", "bust", "waist" or "full", not "' + kind + '"');
      }
      const head = this.headOnStage();
      const scale = this.root.getWorldScale(new THREE.Vector3()).y;
      const turned = this.root.getWorldQuaternion(new THREE.Quaternion());
      const facing = new THREE.Vector3(0, 0, 1).applyQuaternion(turned);  // the way she faces, level
      facing.y = 0;
      facing.normalize();
      const camera = this.camera;
      camera.position.copy(head).addScaledVector(facing, framing.distance * scale);
      camera.position.y += framing.rise * scale;
      camera.fov = framing.fov;
      camera.updateProjectionMatrix();
      camera.lookAt(head.x, head.y + framing.aim * scale, head.z);
    }
  }

  Video.extend({
    helpers(s) {
      // That speaker's smoothed loudness in this frame (see levelAt); it reads the frame's time, as s.mouth does.
      s.level = function (id) {
        return levelAt(String(id).toLowerCase(), api.time);
      };
      // That speaker's 3D character in this scene (see Avatar). A speaker without a model -> an error naming who has
      // one: s.avatar("tobi") -> "No 3D model for tobi: only mira has one."
      s.avatar = function (id, options) {
        const speaker = String(id).toLowerCase();
        if (!expected.has(speaker)) {
          const ids = Array.from(expected.keys()).sort();
          throw new Error("No 3D model for " + speaker + ": " + whoHasOne(ids) + ".");
        }
        const placement = Object.assign({scene: s.three.scene}, options || {});
        return new Avatar(speaker, placement, s.three.camera);
      };
    },
  });
})();
