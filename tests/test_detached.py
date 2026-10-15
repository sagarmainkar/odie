"""A chat turn keeps running when the phone stops watching (app backgrounded), and says so when it finishes."""
import asyncio

from odie.app.detached import detached


async def slow_turn(log):
    for e in ({"type": "token", "text": "Hel"}, {"type": "token", "text": "lo"}, {"type": "done", "text": "Hello there."}):
        await asyncio.sleep(0.01)
        log.append(e["type"])
        yield e


async def test_turn_finishes_after_the_watcher_leaves():
    log, orphaned = [], []
    watch = detached(slow_turn(log), on_orphaned_done=orphaned.append)
    first = await watch.__anext__()
    assert first["text"] == "Hel"
    await watch.aclose()                      # the phone went away mid-answer
    for _ in range(50):
        if orphaned:
            break
        await asyncio.sleep(0.01)
    assert log == ["token", "token", "done"]  # the turn still ran to the end (and was saved by the runner)
    assert orphaned == ["Hello there."]       # so Odie can push the answer


async def test_watched_turn_streams_everything_and_does_not_push():
    log, orphaned = [], []
    got = [e["type"] async for e in detached(slow_turn(log), on_orphaned_done=orphaned.append)]
    assert got == ["token", "token", "done"] and orphaned == []


async def test_turn_survives_the_watching_task_being_cancelled():
    # What sse-starlette does when the phone disconnects: it cancels the task that reads the stream.
    log, orphaned = [], []
    watch = detached(slow_turn(log), on_orphaned_done=orphaned.append)

    async def reader():
        async for _ in watch:
            pass
    t = asyncio.create_task(reader())
    await asyncio.sleep(0.015)
    t.cancel()
    for _ in range(50):
        if orphaned:
            break
        await asyncio.sleep(0.01)
    assert log == ["token", "token", "done"] and orphaned == ["Hello there."]
