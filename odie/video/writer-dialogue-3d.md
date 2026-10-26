## 3D characters

A speaker the cast lists as "a 3D model" is drawn only with `s.avatar("<id>")`: never redraw them in 2D.
Make one character per speaker per scene, no more. Speakers without a model are drawn in code, as above, in the same scene.

- **Make it in `setup`:** `this.mira = s.avatar("mira", {x: -0.5, turn: 0.3})` (`turn`: radians about y; 0 faces the
  camera). In every `draw` of their scenes, call `this.mira.update(t)` early, after setting
  the reactions (next bullet): it reads them then.
- **The stage:** characters are about 1.6 m tall, standing at y = 0. Frame them in `draw` with
  `this.mira.shot("bust")` (or `"face"`, `"waist"`, `"full"`), or set the camera yourself.
- **Layers:** `s.ctx` is drawn in FRONT of three.js, so a full-stage fill on it hides the character. Build the
  backdrop in three.js (`s.three.scene.background`, planes, meshes); keep `s.ctx` for what is in front (a 2D speaker, captions).
- **Reactions:** `smile(0..1)` (`smile(null)`: the automatic smile), `brows(-1..1)` and `look(other)` (the listener
  looks at the speaker; `look(null)` looks ahead; look only at things in front of them, a target behind swings the
  eyes the wrong way). They are held until changed, and every frame must depend only on its time, so set them in
  `setup`, or on every `draw` from `t`, for example `this.mira.smile(t > 2 && t < 3 ? 1 : null)`. Never only inside
  an `if` in `draw`.
- **Automatic:** the mouth, blinks and breathing. `s.level(id)` is that speaker's loudness now (0..1), for anything
  that should follow a voice, such as a glow.

```js
setup(s) { this.mira = s.avatar("mira", {x: -0.5, turn: 0.3}); this.tobi = s.avatar("tobi", {x: 0.5, turn: -0.3}); },
draw(t, s) {
  this.tobi.look(this.mira); this.tobi.smile(t > 4 ? 0.6 : null);
  this.mira.update(t); this.tobi.update(t);
  this.mira.shot("bust");  // a close-up of Mira; Tobi is off-screen
}
```
