"""avatar.js's helpers in a real browser: s.avatar(id) puts a speaker's 3D model on the stage and moves its face and
head with their voice, and s.level(id) is that speaker's smoothed loudness. A tiny glTF made in code stands in for a
real model: one triangle, one face shape named "aa", on a node named "Head"."""
from odie.browser import RENDER_ARGS
from odie.browser.engine import Browser
from odie.video import avatars, dialogue, page
from tests.test_video_kit import BIN, needs_browser
from tests.tiny_glb import tiny_glb

# Mira is quiet for her line's first 0.2 s, loud for 0.4 s (from 0.7 s into the video), then quiet; Tobi's line has no
# loudness known yet (as in the page check).
LINES = [
    {"index": 0, "speaker": "mira", "scene": 1, "t": 0.5, "dur": 1.0, "amplitude": [0] * 10 + [1] * 20 + [0] * 20},
    {"index": 1, "speaker": "tobi", "scene": 1, "t": 2.0, "dur": 1.0, "amplitude": []},
]
ONE_SCENE = {"starts": [0.0], "lengths": [4.0]}
KEEPS_MIRA = ('<script>Video.scenes([{setup(s) { this.a = s.avatar("mira"); window.__a = this.a; window.__s = s; },'
              ' draw(t, s) { this.a.update(t); window.__w = this.a.weights(); }}]);</script>')
HEAD = "__avatars.models.get('mira').gltf.scene.getObjectByName('Head')"


def tiny_model(tmp_path) -> avatars.Model:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "mira.glb"
    path.write_bytes(tiny_glb())
    return avatars.Model(speaker="mira", name="Mira", path=path, size=path.stat().st_size)


async def opened(expressions, tmp_path, body=KEEPS_MIRA, timings=ONE_SCENE):
    """Opens a sealed page with Mira's tiny model and the lines, hands the model over before any frame, then gives
    back what each expression returns, in order, and the errors the page raised."""
    model = tiny_model(tmp_path)
    html = page.assemble(body, timings, avatar_script=avatars.page_script([model]),
                         lines_script=dialogue.lines_script(LINES))
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            await avatars.hand_over(p, avatars.load([model]))
            values = []
            for expression in expressions:
                values.append(await p.eval(expression))
            errors = list(p.errors)
    finally:
        await b.close()
    return values, errors


async def evaluated(expressions, tmp_path, body=KEEPS_MIRA, timings=ONE_SCENE):
    """What each expression returns on a page that raised no error."""
    values, errors = await opened(expressions, tmp_path, body, timings)
    assert errors == []
    return values


def level_at(T, speaker):
    return f"__avatars.frame({T}).then(() => __s.level('{speaker}'))"


@needs_browser
async def test_the_mouth_opens_with_the_speakers_loudness(tmp_path):
    loud, quiet, other = await evaluated(["__avatars.frame(1.0).then(() => __w.aa)",
                                          "__avatars.frame(0.2).then(() => __w.aa)",
                                          "__avatars.frame(2.5).then(() => __w.aa)"], tmp_path)
    assert loud > 0.5 and quiet == 0 and other == 0  # tobi speaking: mira's mouth stays shut


@needs_browser
async def test_the_face_shape_on_the_model_follows_the_weight(tmp_path):
    # the tiny model's mesh is the Head node itself, with its one face shape "aa" at index 0
    loud, quiet = await evaluated([f"__avatars.frame(1.0).then(() => {HEAD}.morphTargetInfluences[0])",
                                   f"__avatars.frame(0.2).then(() => {HEAD}.morphTargetInfluences[0])"], tmp_path)
    assert loud > 0.5 and quiet == 0


@needs_browser
async def test_level_is_smoothed_and_leads_the_sound(tmp_path):
    # The loud run starts 0.2 s into Mira's line, at 0.7 s. At T 0.66 the mouth reads 40 ms ahead, at 0.70, and
    # averages 0.65, 0.675, 0.70, 0.725, 0.75 with weights 1, 2, 3, 2, 1: (0 + 0 + 3 + 2 + 1) / 9.
    rising, loud, before, unknown, nobody = await evaluated([
        level_at(0.66, "mira"), level_at(0.9, "mira"), level_at(0.2, "mira"), level_at(2.5, "tobi"),
        level_at(1.0, "anna")], tmp_path)
    assert abs(rising - 6 / 9) < 0.01
    assert loud == 1.0
    assert before == 0
    assert unknown == 0.5  # no loudness known while Tobi's line plays: half open, as s.mouth does
    assert nobody == 0


@needs_browser
async def test_level_takes_the_speaker_in_any_case(tmp_path):
    [loud] = await evaluated([level_at(0.9, "Mira")], tmp_path)
    assert loud == 1.0


@needs_browser
async def test_a_frame_looks_the_same_whatever_was_drawn_before(tmp_path):  # Review Focus 2
    state = "({w: __w, head: " + HEAD + ".quaternion.toArray(), root: __a.root.quaternion.toArray()})"
    after_early = await evaluated(["__avatars.frame(0.1)", "__avatars.frame(0.2)",
                                   f"__avatars.frame(1.37).then(() => {state})"], tmp_path / "a")
    after_late = await evaluated(["__avatars.frame(3.0)", f"__avatars.frame(1.37).then(() => {state})"],
                                 tmp_path / "b")
    assert after_early[-1] == after_late[-1]
    assert after_early[-1]["head"] != [0, 0, 0, 1]  # the head has moved from rest: the frame isn't trivially still


@needs_browser
async def test_the_head_moves_with_time_from_its_rest_pose(tmp_path):
    rest, moved, again = await evaluated([
        f"{HEAD}.quaternion.toArray()",
        f"__avatars.frame(1.0).then(() => {HEAD}.quaternion.toArray())",
        f"__avatars.frame(1.0).then(() => {HEAD}.quaternion.toArray())"], tmp_path)
    assert rest == [0, 0, 0, 1]
    assert moved != rest  # idle sway and a nod with the voice
    assert again == moved


@needs_browser
async def test_a_blink_closes_the_eyes_shortly_after_the_scene_starts(tmp_path):
    shut, opened_eyes = await evaluated(["__avatars.frame(0.96).then(() => __w.blink)",
                                         "__avatars.frame(0.5).then(() => __w.blink)"], tmp_path)
    assert shut > 0.99  # the first blink starts at 0.9 s and is shut 0.06 s later
    assert opened_eyes == 0


@needs_browser
async def test_a_speaker_without_a_model_is_told_in_words(tmp_path):  # Review Focus 5
    body = '<script>Video.scenes([{setup(s) { this.t = s.avatar("Tobi"); }, draw(t, s) {}}]);</script>'
    _, errors = await opened([], tmp_path, body=body)
    assert errors
    assert "No 3D model for tobi: only mira has one." in errors[0]


@needs_browser
async def test_smile_and_brows_are_held_until_changed(tmp_path):
    resting, asked, held = await evaluated([
        "__avatars.frame(0.2).then(() => [__w.smile, __w.brows])",
        "__a.smile(0.8); __a.brows(-0.5); __avatars.frame(1.0).then(() => [__w.smile, __w.brows])",
        "__avatars.frame(0.2).then(() => [__w.smile, __w.brows])",
    ], tmp_path)
    assert resting == [0.3, 0]  # a hint of a smile while quiet, unless the writer set one
    assert asked == [0.8, -0.5]  # the tiny model has no smile or brow shape: still reported, nothing throws
    assert held == [0.8, -0.5]


@needs_browser
async def test_update_before_the_model_is_loaded_says_so(tmp_path):
    model = tiny_model(tmp_path)
    html = page.assemble(KEEPS_MIRA, ONE_SCENE, avatar_script=avatars.page_script([model]),
                         lines_script=dialogue.lines_script(LINES))
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            said = await p.eval("try { __a.update(0); 'drawn' } catch (e) { e.message }")
    finally:
        await b.close()
    assert "Mira's 3D model isn't loaded" in said


@needs_browser
async def test_shot_puts_the_camera_on_the_head(tmp_path):
    body = ('<script>Video.scenes([{setup(s) { this.a = s.avatar("mira", {x: 0.4, z: -1, turn: 0.5});'
            ' window.__s = s; }, draw(t, s) { this.a.update(t); this.a.shot("bust"); }}]);</script>')
    check = ("__avatars.frame(1.0).then(() => {"
             " const camera = __s.three.camera;"
             f" const head = {HEAD}.getWorldPosition(new THREE.Vector3());"
             " const toHead = head.sub(camera.position).normalize();"
             " const looking = camera.getWorldDirection(new THREE.Vector3());"
             " return [toHead.distanceTo(looking), camera.fov, camera.position.distanceTo("
             f"{HEAD}.getWorldPosition(new THREE.Vector3()))]; }})")
    [[miss, fov, distance]] = await evaluated([check], tmp_path, body=body)
    assert miss < 1e-3
    assert fov == 22
    assert 1.4 < distance < 1.7


@needs_browser
async def test_one_speaker_in_two_scenes_shares_one_model(tmp_path):
    body = ('<script>Video.scenes(['
            '{setup(s) { this.a = s.avatar("mira"); window.__s1 = s; }, draw(t, s) { this.a.update(t); }},'
            '{setup(s) { this.a = s.avatar("mira", {x: 1}); window.__a2 = this.a; window.__s2 = s; },'
            ' draw(t, s) { this.a.update(t); }}]);</script>')
    model = "__avatars.models.get('mira').gltf.scene"
    in_second, in_first = await evaluated([
        f"__avatars.frame(2.5).then(() => {model}.parent === __a2.root && __a2.root.parent === __s2.three.scene)",
        f"__avatars.frame(0.5).then(() => {model}.parent.parent === __s1.three.scene)",
    ], tmp_path, body=body, timings={"starts": [0.0, 2.0], "lengths": [2.0, 2.0]})
    assert in_second and in_first
