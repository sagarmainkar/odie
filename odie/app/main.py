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
    for row in store.expire_approvals(before):
        store.audit("job", "approval_expired", tool=row["tool"], approval_id=row["id"])
        if runner is not None:
            await runner.post_message(f"I let this lapse after a day without your tap: {row['summary']}. Ask again if you still want it.")
        try:
            push.send_to_all(store, f"{persona.get(store)['name']}: approval lapsed", push_body(approval_dict(row)), url="/#chat",
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


class DeviceGate:
    """While pairing is on, every API answers only a paired browser (odie.devices); anyone else is told it's private."""

    def __init__(self, app, store: Store):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and devices.gated(scope["path"]) and devices.pairing_on(self.store):
            from starlette.requests import HTTPConnection
            if devices.device_for(self.store, HTTPConnection(scope).cookies.get(devices.COOKIE)) is None:
                if scope["type"] == "websocket":
                    from starlette.websockets import WebSocketClose
                    await WebSocketClose(code=4401)(scope, receive, send)
                else:
                    from fastapi.responses import JSONResponse
                    await JSONResponse(devices.PRIVATE, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def scheduler_enabled() -> bool:
    """ODIE_SCHEDULER=0 starts a server without background jobs: a second, test instance must never push or post."""
    import os
    return os.environ.get("ODIE_SCHEDULER", "1") != "0"


BRIEF_LIMIT = 600  # seconds: gathering, then up to a 3-minute completion on a slow local model


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

    from odie.push.send import send_to_all
    from odie.watch import check as watch

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
            try:
                from odie.threads import DESK_URL
                send_to_all(store, title, body, url=DESK_URL, tag="watch")
            except Exception:  # noqa: BLE001
                logging.getLogger("odie").warning("watch push failed", exc_info=True)
        memory = getattr(runner, "memory", None)
        index = build_index(memory.load(), max_chars=3000) if memory is not None and memory.exists() else ""
        await watch.run_check(store, now(), turn, runner.post_message, push, memory=memory, memory_index=index)
    # Each wake-up: the mail and calendar watch when it's due (every 30 minutes), then trackers (then, in 9c, parked tasks).
    # Detection (a minute or two), the turn (280 s), and reads when the model didn't: 10 minutes at most.
    bg.parts.insert(0, Part("watch", watch_part, due=lambda _now: watch.due(store, now()), limit=600))
    return bg


def start_scheduler(store: Store, runner=None, background=None):
    """Background jobs in the user's timezone: brief 07:30, reminders every minute,
    news at 06/10/14/18/22 (and right away if the stored batch is stale).
    Jobs are coroutine FUNCTIONS: APScheduler awaits those; a lambda would run in a thread and never be awaited."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    from odie.jobs.brief import run_brief
    from odie.jobs.reminders import run_due
    tz = ZoneInfo(config.settings.timezone)
    sched = AsyncIOScheduler(timezone=tz)

    async def brief_job() -> None:
        async def go() -> None:
            await run_brief(store, datetime.now(tz), post_message=runner.post_message if runner is not None else None)
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
            logs.mkdir(parents=True, exist_ok=True)
            voice_worker.current = voice_worker.VoiceWorker(log=logs / "voice.log")
            try:
                await voice_worker.current.start()  # Odie's own local voices, started with it
            except Exception:  # noqa: BLE001 (voice never decides whether Odie starts)
                logging.getLogger("odie").warning("local voice couldn't start", exc_info=True)
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
                await making_jobs.recover()  # a video (or anything else) a restart cut off is told, once, in its chat
            except Exception:  # noqa: BLE001 (never decides whether Odie starts)
                logging.getLogger("odie").warning("telling interrupted background jobs failed", exc_info=True)
        yield
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
