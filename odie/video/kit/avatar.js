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
})();
