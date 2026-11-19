"""FastAPI application: API routes plus the built PWA as static files."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from odie import config, devices
from odie.app.origin import OriginGate
from odie.app.routes import router
from odie.push.vapid import load_or_create_vapid
from odie.store.db import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def expire_approvals(store: Store, runner=None) -> None:
    """Approvals untapped for a day lapse: a line in Chat and a push that says what, never the private details."""
    from datetime import UTC, datetime, timedelta

    from odie import persona
    from odie.app.runner import push_body
    from odie.push import send as push
    from odie.store.db import approval_dict
    before = (datetime.now(UTC) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    from odie import personalities
    for row in store.expire_approvals(before):
        store.audit("job", "approval_expired", tool=row["tool"], approval_id=row["id"])
        # A personality's card lapses in its own thread, and its push says only who: the summary is that thread's.
        owner_id, owner = personalities.whose_thread(store, row["session_id"])
        if owner_id != personalities.ODIE and owner is None:
            continue  # its personality was deleted: the card lapses without a word
        said = f"I let this lapse after a day without your tap: {row['summary']}. Ask again if you still want it."
        if runner is not None and owner is None:
            await runner.post_message(said)
        if runner is not None and owner is not None:
            await runner.post_message(said, session_id=row["session_id"])
        try:
            if owner is None:
                title, body = f"{persona.get(store)['name']}: approval lapsed", push_body(approval_dict(row))
            else:
                title, body = personalities.quiet_push(owner.name, "lapsed")
            push.send_to_all(store, title, body, url="/#chat",
                             tag=f"expired-{row['id']}")
        except Exception:  # noqa: BLE001
            logging.getLogger("odie").warning("expiry push failed", exc_info=True)


def addon_job(job, store: Store, runner):
    """An add-on job as a coroutine function (APScheduler awaits those); a failure is logged, never raised."""
    async def run() -> None:
        try:
            await job.run(store, runner)
        except Exception:  # noqa: BLE001
            logging.getLogger("odie").warning("add-on job %s failed", job.id, exc_info=True)
    return run


def mount_addon_routes(app: FastAPI) -> None:
    """Each add-on's routes under /api. A route the app already has (same method and path) is refused, never replaced."""
    from fastapi.routing import APIRoute, APIRouter

    from odie import addons
    from odie.app.routes import router as core  # the app keeps included routers nested: read the core one itself
    owner = {(m, r.path): "the core" for r in [*core.routes, *app.routes] if isinstance(r, APIRoute) for m in r.methods}
    for a in addons.active():
        if a.router is None:
            continue
        try:
            keep = APIRouter()
            for r in a.router.routes:
                taken = [owner[(m, "/api" + r.path)] for m in r.methods if (m, "/api" + r.path) in owner] if isinstance(r, APIRoute) else []
                if taken:
                    logging.getLogger("odie").warning("add-on %s: %s %s is %s's route; not mounted", a.name, sorted(r.methods), r.path, taken[0])
                else:
                    keep.routes.append(r)
                    if isinstance(r, APIRoute):
                        owner.update({(m, "/api" + r.path): a.name for m in r.methods})
            app.include_router(keep, prefix="/api")
        except Exception:  # noqa: BLE001
            logging.getLogger("odie").warning("add-on %s: its routes couldn't be mounted", a.name, exc_info=True)


async def _launch_voice_worker(store: Store, logs) -> None:
    """Odie's own voice server at launch: the worker is always made, so choosing Kokoro later starts it on demand, but
    it is started now only when read-aloud uses it (voice.worker_wanted). Kokoro chosen -> started; Phonon or OpenAI
    chosen -> made, not started: one process less."""
    from odie import voice, voice_worker
    logs.mkdir(parents=True, exist_ok=True)
    voice_worker.current = voice_worker.VoiceWorker(log=logs / "voice.log")
    if not voice.worker_wanted_at_launch(store):
        return
    await _start_voice_worker()


async def _start_voice_worker() -> None:
    from odie import voice_worker
    try:
        await voice_worker.current.start()
    except Exception:  # noqa: BLE001 (voice never decides whether Odie starts)
        logging.getLogger("odie").warning("local voice couldn't start", exc_info=True)


async def _learn_phonon(store: Store) -> None:
    """Asks Ollama once at launch whether it has Phonon and which voices, so read-aloud's default engine knows before
    Settings is first opened. With no engine chosen, the default is known only now: no Phonon -> Kokoro is the default,
    so Odie's own voice server starts here (launch left it alone); Phonon -> it never starts. A missing or slow Ollama
    is fine: Odie asks again when Settings opens."""
    from odie import voice, voice_worker
    try:
        if await voice.phonon_available():
            await voice.phonon_voices()
        await voice.settle_worker(store)
        if voice_worker.current is not None and voice.worker_wanted(store):
            await _start_voice_worker()
    except Exception:  # noqa: BLE001 (voice never decides whether Odie starts)
        logging.getLogger("odie").info("couldn't ask Ollama about Phonon", exc_info=True)


class DeviceGate:
    """While pairing is on, every API answers only a paired browser (odie.devices); anyone else is told it's private."""

    def __init__(self, app, store: Store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and devices.gated(scope["path"]) and devices.pairing_on(self.store):
            from starlette.requests import HTTPConnection
            device = devices.device_for(self.store, HTTPConnection(scope).cookies.get(devices.COOKIE))
            if device is None:
                if scope["type"] == "websocket":
                    from starlette.websockets import WebSocketClose
                    await WebSocketClose(code=4401)(scope, receive, send)
                else:
                    from fastapi.responses import JSONResponse
                    await JSONResponse(devices.PRIVATE, status_code=401)(scope, receive, send)
                return
            if devices.is_terminal(device) and not self.terminal_allowed(scope):
                await self.refuse_terminal(scope, receive, send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    def terminal_allowed(scope) -> bool:
        """The odie command's key: only its own calls (devices.terminal_may), never a websocket."""
        if scope["type"] != "http":
            return False
        query = scope.get("query_string", b"").decode("latin-1")
        return devices.terminal_may(scope["method"], scope["path"], query)

    @staticmethod
    async def refuse_terminal(scope, receive, send) -> None:
        if scope["type"] == "websocket":
            from starlette.websockets import WebSocketClose
            await WebSocketClose(code=4403)(scope, receive, send)
            return
        from fastapi.responses import JSONResponse
        await JSONResponse({"detail": "The terminal may only chat and read threads."}, status_code=403)(scope, receive, send)


def scheduler_enabled() -> bool:
    """ODIE_SCHEDULER=0 starts a server without background jobs: a second, test instance must never push or post."""
    import os
    return os.environ.get("ODIE_SCHEDULER", "1") != "0"


BRIEF_LIMIT = 900  # seconds: the morning round makes the brief and the hello, two model calls, each gathering first


def watch_pushed(store: Store, runner, title: str, body: str, owner: str = "") -> None:
    """The watch found something the owner must see (an urgent mail, an app that stopped working): a push to the
    phone, which opens Today's Needs you, and a `watch` event on the bus, so an open app that gets no web push (the
    Mac) hears it too. A push that fails is logged and never keeps the bus quiet.
      "Deck from xyz", "made from the PDF" -> push "Deck from xyz" to /#today, event {type: watch, title, body, ts}"""
    import time

    from odie.push import send as push
    url = pulse_url(owner)
    try:
        push.send_to_all(store, title, body, url=url, tag="watch")
    except Exception:  # noqa: BLE001
        logging.getLogger("odie").warning("watch push failed", exc_info=True)
    runner.bus.emit({"type": "watch", "title": title, "body": body, "ts": time.time()})


def pulse_url(owner: str) -> str:
    """Where a push opens: the Pulse of whose it is. Everyday Odie -> "/#today"; Mira -> "/#today?personality=<her id>"
    (the app picks her on opening it)."""
    if not owner:
        return "/#today"
    return f"/#today?personality={owner}"


def background_for(store: Store, runner):
    """The background agent for this server: in 9a its one part is the trackers that are due (each on its own
    schedule). Each check is cut at 5 minutes by background_turn, and one run checks up to trackers.PER_RUN, so the
    part's own limit covers all of them."""
    from odie import trackers as trackers_mod
    from odie.background import Background, Part

    async def trackers() -> None:
        if runner is not None and hasattr(runner, "run_trackers"):
            await runner.run_trackers()
    bg = Background([Part("trackers", trackers, limit=trackers_mod.PER_RUN * 300 + 30)])

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import clock as loops_clock
    from odie.watch import check as watch
    from odie.watch import owner as watch_owner

    def now():
        return datetime.now(ZoneInfo(config.settings.timezone))

    async def watch_part() -> None:
        if runner is None or not hasattr(runner, "background_turn"):
            return
        from odie.memory.index import build_index

        async def turn(prompt, tools, instruction):
            return await runner.background_turn(prompt, timeout=280, tools=tools, instruction=instruction, guard=watch.guard,
                                                free=watch.MAY_WRITE, skills=watch.calendar_skills(store))

        def push(title, body):
            watch_pushed(store, runner, title, body)
        memory = getattr(runner, "memory", None)
        index = build_index(memory.load(), max_chars=3000) if memory is not None and memory.exists() else ""
        await watch.run_check(store, now(), turn, push, memory=memory, memory_index=index, think=consolidate_for(runner, ""))
    # Each wake-up: the mail and calendar watch when it's due (every 30 minutes), then trackers (then, in 9c, parked tasks).
    # Detection (a minute or two), the turn (280 s), and reads when the model didn't: 10 minutes at most.
    bg.parts.insert(0, Part("watch", watch_part, due=lambda _now: watch.due(store, now()), limit=600))

    async def personality_watch_part() -> None:
        await personality_watch(store, runner, now())
    # A personality with Proactive intelligence on checks its own mail the same way, one personality per wake-up.
    bg.add(Part("watch:personalities", personality_watch_part,
                due=lambda _now: watch_owner.next_due(store, now()) is not None, limit=600))

    async def loops_part() -> None:
        await run_loops(store, runner, now())
    # Then the loops whose time has come (odie.loops.clock): facts, one model call each, within the day's budget.
    bg.add(Part("loops", loops_part, due=lambda _now: bool(loops_clock.due(store, now())), limit=600))

    async def ladder_part() -> None:
        run_ladder(store, runner, now())
    # And the follow-up ladder (odie.loops.ladder): code only, every wake-up (a push the day before, a nudge card).
    bg.add(Part("ladder", ladder_part, limit=60))
    return bg


def run_ladder(store: Store, runner, now) -> list:
    """The follow-up ladder's tick (odie.loops.ladder): its pushes open the owner's Pulse."""
    from odie.loops import ladder

    def push_for(pid: str):
        if runner is None:
            return None

        def push(title, body):
            watch_pushed(store, runner, title, body, owner=pid)
        return push
    return ladder.run(store, now, push_for)


async def run_loops(store: Store, runner, now) -> list:
    """Stage 4 for the due loops (odie.loops.clock): each thinks with its owner's brain, with no tools at all."""
    from odie.loops import clock
    if runner is None or not hasattr(runner, "background_turn"):
        return []

    def think_for(pid: str):
        async def think(prompt: str, instruction: str) -> str:
            return await runner.background_turn(prompt, timeout=120, instruction=instruction, bare=True, owner=pid)
        return think

    def push_for(pid: str):
        def push(title, body):
            watch_pushed(store, runner, title, body, owner=pid)
        return push
    return await clock.run(store, now, think_for, push_for)


async def personality_watch(store: Store, runner, now) -> str | None:
    """One personality's own mail and calendar check (odie.watch.owner), the one waiting longest: on its own brain,
    with its own apps, its own memory and Watch for, its card and threads kept apart. Returns whose check ran, or
    None when none is due or there is no runner to think with."""
    from odie.watch import check as watch
    from odie.watch import owner as watch_owner
    pid = watch_owner.next_due(store, now)
    if pid is None or runner is None or not hasattr(runner, "background_turn"):
        return None

    async def turn(prompt, tools, instruction):
        return await runner.background_turn(prompt, timeout=280, tools=tools, instruction=instruction, guard=watch.guard,
                                            free=watch.MAY_WRITE, skills=watch.calendar_skills(store, pid), owner=pid)

    def push(title, body):
        watch_pushed(store, runner, title, body, owner=pid)
    memory = runner.memory_of(pid)
    index = runner.memory_index(pid)
    await watch.run_check(store, now, turn, push, memory=memory, memory_index=index, owner=pid,
                          think=consolidate_for(runner, pid))
    return pid


def consolidate_for(runner, pid: str):
    """Stage 2's model call for this owner (odie.loops.consolidate): its brain, no tools at all, so it can only
    answer; code writes the answer to the ledger."""
    async def think(prompt: str, instruction: str) -> str:
        return await runner.background_turn(prompt, timeout=120, instruction=instruction, bare=True, owner=pid)
    return think


def start_scheduler(store: Store, runner=None, background=None):
    """Background jobs in the user's timezone: the morning round (brief and hello) 07:30, reminders every minute,
    news at 06/10/14/18/22 (and right away if the stored batch is stale).
    Jobs are coroutine FUNCTIONS: APScheduler awaits those; a lambda would run in a thread and never be awaited."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from odie.jobs.reminders import run_due
    from odie.morning import round as morning
    tz = ZoneInfo(config.settings.timezone)
    sched = AsyncIOScheduler(timezone=tz)

    async def brief_job() -> None:
        async def go() -> None:
            await morning.morning_round(store, datetime.now(tz), runner=runner)
        if background is None:
            await go()
        else:
            from odie.background import Part
            await background.exclusive(Part("brief", go, limit=BRIEF_LIMIT))  # never beside a running tick

    async def reminders_job() -> None:
        if runner is not None:
            await run_due(store, runner, datetime.now(tz).isoformat(timespec="minutes"))

    async def expiry_job() -> None:
        from datetime import UTC, timedelta
        if runner is not None:
            await runner.reconcile_approvals()
        await expire_approvals(store, runner)

    sched.add_job(brief_job, CronTrigger(hour=7, minute=30, timezone=tz), id="brief", misfire_grace_time=3600, coalesce=True)
    from odie.jobs.brief import missed_today
    started_at = datetime.now(tz)
    # The computer was off at 07:30 (the brief is owed), or Odie starts with no hello yet today (the hello is owed):
    # run the round soon, after the first watch check.
    if missed_today(store, started_at) or morning.hello_due(store, started_at):
        from datetime import timedelta

        from apscheduler.triggers.date import DateTrigger
        sched.add_job(brief_job, DateTrigger(run_date=datetime.now(tz) + timedelta(minutes=2), timezone=tz),
                      id="brief_missed", misfire_grace_time=600)
    sched.add_job(reminders_job, IntervalTrigger(minutes=1, timezone=tz), id="reminders", misfire_grace_time=120, coalesce=True)
    sched.add_job(expiry_job, IntervalTrigger(minutes=10, timezone=tz), id="expiry", misfire_grace_time=600, coalesce=True)

    if background is not None:  # the background agent: trackers (and, later, the watch and parked tasks), one at a time
        from datetime import timedelta

        from apscheduler.triggers.date import DateTrigger
        sched.add_job(background.tick, IntervalTrigger(minutes=5, timezone=tz), id="background", misfire_grace_time=240,
                      coalesce=True, max_instances=1)
        sched.add_job(background.tick, DateTrigger(run_date=datetime.now(tz) + timedelta(seconds=60), timezone=tz),
                      id="background_now", misfire_grace_time=600)

    async def news_job() -> None:
        from odie.news.fetch import refresh_news
        try:
            await refresh_news(store)
        except Exception:  # noqa: BLE001
            logging.getLogger("odie").warning("news refresh failed", exc_info=True)

    sched.add_job(news_job, CronTrigger(hour="6,10,14,18,22", minute=0, timezone=tz), id="news", misfire_grace_time=1800, coalesce=True)

    async def workers_watchdog_job():
        from odie.workers import watchdog
        try:
            await watchdog.check(store)  # fails a Worker past its budget, silent 10 minutes, or refused 3 times alike
        except Exception:  # noqa: BLE001
            logging.getLogger("odie").warning("workers watchdog failed", exc_info=True)
    sched.add_job(workers_watchdog_job, IntervalTrigger(minutes=1, timezone=tz), id="workers_watchdog",
                  misfire_grace_time=120, coalesce=True)
    from odie import addons
    for a in addons.active():
        for j in a.jobs:
            if sched.get_job(j.id) is not None:
                logging.getLogger("odie").warning("add-on %s: job id %s is taken; not scheduled", a.name, j.id)
                continue
            try:
                sched.add_job(addon_job(j, store, runner), CronTrigger(**j.cron, timezone=tz), id=j.id, misfire_grace_time=j.misfire,
                              coalesce=True, max_instances=1)
            except Exception:  # noqa: BLE001
                logging.getLogger("odie").warning("add-on %s: job %s couldn't be scheduled", a.name, j.id, exc_info=True)
    from odie.news.fetch import is_stale, news_batch
    if is_stale(news_batch(store), datetime.now(UTC)):
        sched.add_job(news_job, id="news_now", misfire_grace_time=600)  # once, right away, even if startup is slow
    sched.start()
    return sched


def create_app(runner=None, store: Store | None = None) -> FastAPI:
    s = config.settings
    from odie import home
    home.ensure(home.Layout(s.home, s.data_dir, s.config_dir))
    store = store or Store(s.db_path)
    store.init_schema()
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import migrate
    migrate.run_once(store, datetime.now(ZoneInfo(s.timezone)))  # phase 3: the watch's threads and cards become loops
    devices.hide_pairing_queries_in_access_log()  # the setup link's token never lands in logs/server.log

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store
        from odie.signin.live import LiveViews
        app.state.live = LiveViews(store)  # signed-in browsing's live view (the user's turn)
        from odie.signin import box as signin_box
        app.state.signin_box = signin_box.for_store(store)  # Odie's own sign-in box (spec "Sign in for me")
        app.state.vapid_public_key = load_or_create_vapid(s.vapid_path)["public_key"]
        if runner is None:
            from odie import tracing
            from odie.app.runner import OdieRunner
            tracing.setup()  # real server only; tests pass their own runner
            app.state.runner = OdieRunner(store)
            # in the background: a slow or hung server must not delay Odie starting (each is retried if it failed)
            app.state.plugins_task = asyncio.create_task(app.state.runner.load_plugins())
            from odie.models import refresh_fallback_at_startup
            app.state.fallback_task = asyncio.create_task(refresh_fallback_at_startup(store))  # the model used if none is chosen
        else:
            app.state.runner = runner
        if devices.offer_setup(store):
            logging.getLogger("odie").info("No device is paired yet: the installer opens the link in %s", devices.setup_file())
        from odie import embed_worker, machine, voice_worker
        logs = (s.home / "logs") if s.home else s.data_dir
        if runner is None and machine.local_voice_wanted():  # the real server, on a Mac that runs Odie's own voice
            await _launch_voice_worker(store, logs)
        if runner is None:  # whether Ollama has Phonon, and its voices, in the background: Ollama never delays Odie starting
            app.state.phonon_task = asyncio.create_task(_learn_phonon(store))
        if runner is None and machine.local_embeddings_wanted():
            logs.mkdir(parents=True, exist_ok=True)
            embed_worker.current = embed_worker.EmbedWorker(log=logs / "embed.log")  # started on demand by the embedder…
            from odie.vault import settings as vault_settings
            if (vault_settings.get(store)["embeddings"] or {}).get("provider") == "gemma":  # …and now, when the vault uses it
                try:
                    await embed_worker.current.start()
                except Exception:  # noqa: BLE001 (embeddings never decide whether Odie starts)
                    logging.getLogger("odie").warning("local embeddings couldn't start", exc_info=True)
        from odie import addons
        addons.call("start")
        from odie.vault.worker import VaultWorker
        app.state.vault_worker = VaultWorker(store)
        app.state.vault_worker.start()  # indexes only when a vault folder is set
        try:
            app.state.runner.vault_worker = app.state.vault_worker  # memory writes re-index their note
        except AttributeError:
            pass
        from odie.app.events import EventBus
        app.state.bus = getattr(app.state.runner, "bus", None) or EventBus()
        app.state.background = None
        if runner is None and scheduler_enabled():
            app.state.background = background_for(store, app.state.runner)
        app.state.scheduler = (start_scheduler(store, app.state.runner, app.state.background)
                               if runner is None and scheduler_enabled() else None)
        if runner is None:
            try:
                await app.state.runner.reconcile_approvals()
            except Exception:  # noqa: BLE001
                logging.getLogger("odie").warning("reconcile at startup failed", exc_info=True)
            try:
                from odie.making import jobs as making_jobs
                await making_jobs.recover(store)  # a job a restart cut off (a user skill's too) is told, once, in its chat
            except Exception:  # noqa: BLE001 (never decides whether Odie starts)
                logging.getLogger("odie").warning("telling interrupted background jobs failed", exc_info=True)
            try:
                from odie.workers import router as workers_router
                await workers_router.recover()  # a Worker a restart cut off is told in the chat that started it
            except Exception:  # noqa: BLE001 (never decides whether Odie starts)
                logging.getLogger("odie").warning("recovering workers failed", exc_info=True)
        yield
        if runner is None:
            try:
                from odie.workers import router as workers_router
                await workers_router.stop_all()  # Workers end with Odie; recover() at the next start says so
            except Exception:  # noqa: BLE001 (never blocks shutdown)
                logging.getLogger("odie").warning("stopping workers failed", exc_info=True)
        try:
            from odie.making import jobs as making_jobs
            await making_jobs.stop()  # first: a render in progress ends before its browser is closed under it
        except Exception:  # noqa: BLE001 (never blocks shutdown)
            logging.getLogger("odie").warning("stopping the background worker failed", exc_info=True)
        fallback_task = getattr(app.state, "fallback_task", None)
        if fallback_task is not None:
            fallback_task.cancel()
        await app.state.live.close()
        from odie.browser import close_shared
        await close_shared()
        if voice_worker.current is not None:
            await voice_worker.current.stop()
            voice_worker.current = None
        if embed_worker.current is not None:
            await embed_worker.current.stop()
            embed_worker.current = None
        await app.state.vault_worker.stop()
        if app.state.background is not None:
            await app.state.background.stop()
        if app.state.scheduler:
            app.state.scheduler.shutdown(wait=False)
        await app.state.runner.close()

    from odie.plugins.mcp import install_log_masking
    install_log_masking()  # links with keys in them (Zapier's) never reach the log
    app = FastAPI(title="Odie", lifespan=lifespan)
    app.add_middleware(DeviceGate, store=store)
    app.add_middleware(OriginGate)  # outermost: a request from a Host Odie doesn't own, or a change from another page, stops here
    app.include_router(router)
    mount_addon_routes(app)

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        """The installed app is named after the assistant (the build's manifest has the default name)."""
        from fastapi.responses import JSONResponse
        from odie import persona
        try:
            m = json.loads((s.web_dist / "manifest.webmanifest").read_text())
        except (OSError, ValueError):
            m = {"display": "standalone", "start_url": "/", "scope": "/"}
        name = persona.get(store)["name"]
        return JSONResponse({**m, "name": name, "short_name": name}, media_type="application/manifest+json")

    if s.web_dist.exists():
        app.mount("/", StaticFiles(directory=str(s.web_dist), html=True), name="web")
    return app


# Run with: uvicorn odie.app.main:create_app --factory
