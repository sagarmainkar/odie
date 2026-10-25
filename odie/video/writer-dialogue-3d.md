## 3D characters

A speaker the cast lists as "a 3D model" is drawn only with `s.avatar("<id>")`: never redraw them in 2D, never add a
second look. Make one character per speaker per scene, no more. Speakers without a model are drawn in code, as above, in the same
scene. Captions as usual.

- **Make it in `setup`:** `this.mira = s.avatar("mira", {x: -0.5, turn: 0.3})` (`turn` is radians about y; 0 faces
  the camera). In every `draw` of a scene they appear in, call `this.mira.update(t)` early, right after the
  reactions below (it reads them when it runs).
- **The stage:** characters are about 1.6 m tall and stand at y = 0. Frame them with `this.mira.shot("bust")` (or
  `"face"`, `"waist"`, `"full"`) in `draw`, or set the camera yourself.
- **Reactions:** `smile(0..1)`, `brows(-1..1)` and `look(other)` (the listener looks at the speaker; `look(null)`
  looks ahead). They are held until changed, and every frame must depend only on its time, so set them in `setup`,
  or on every `draw` from `t`, for example `this.mira.smile(t > 2 && t < 3 ? 1 : 0)`. Never only inside an `if` in
  `draw`.
- **Automatic:** the mouth, blinks and breathing. `s.level(id)` is that speaker's loudness now (0..1), for anything
  else that should follow a voice, such as a glow.

```js
setup(s) { this.mira = s.avatar("mira", {x: -0.5, turn: 0.3}); this.tobi = s.avatar("tobi", {x: 0.5, turn: -0.3}); },
draw(t, s) {
  this.tobi.look(this.mira); this.tobi.smile(t > 4 ? 0.6 : 0);
  this.mira.update(t); this.tobi.update(t);
  this.mira.shot("bust");
}
```
