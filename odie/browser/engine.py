"""The browser engine: one headless browser for Odie, started on first use and closed after a while idle, with a tab
per chat thread. Pages are read as their main content, with a screenshot.

Reaching only public addresses:
- **Every request is checked before it is sent.** Odie attaches to every page, pop-up, frame and worker before it
  runs and turns on request interception there first. Only public http(s) addresses get through.
- **Pop-ups are let run and then closed;** their requests are checked like any other.
- **Where answers come from is checked too:** a host whose answer comes from this computer or the home network (DNS
  rebinding) is refused from then on. Its first request can land; nothing after it does.
- **WebSockets can't be intercepted this way.** A page's WebSocket to this computer or the home network is refused in
  page script, and Chrome's own local-network protection covers the rest.

Downloads are refused and dialogs dismissed. Password, card, PIN and one-time-code fields are never typed into."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import re
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from odie.agent.tools.web import public_url, resolve_host
from odie.browser import find
from odie.browser.cdp import CDP, CDPError
from odie.signin import sites

Policy = Callable[[str], Awaitable[bool]]
TEXT_CAP = 6000
HELD = "The user is using the browser; wait until they're done."
# A site's storage, not its cookies (those are deleted one by one: "all" by origin reached other sites' cookies too).
STORAGE = "local_storage,indexeddb,websql,cache_storage,service_workers,file_systems,storage_buckets"
VIEW = (1280, 900)
INPUT_TIMEOUT = 10  # seconds for a click or a key: a stuck page shouldn't cost 30
_FREE = ("data", "blob", "about")  # no network behind these
_OFF_LIMITS = "this computer and the home network are off limits"


class BrowserError(Exception):
    """What went wrong, in plain words for the model (and what to try instead)."""


class FencedError(BrowserError):
    """The page was stopped from leaving the sites its tab may visit (the fence)."""


BOT_CHECK_WAIT = 10  # seconds a site's bot check is given to clear (most pass by themselves in a few)
_BOT_TITLES = ("just a moment", "attention required", "are you a robot", "verify you are human", "access denied")
_BOT_TEXT = ("performing security verification", "verify you are human", "checking your browser",
             "checking if the site connection is secure", "enable javascript and cookies to continue", "press & hold")
BOT_NOTE = ("This site is showing a bot check and didn't let me in. Don't scroll or try it again: use another source "
            "(a web search, another site), or ask the user to open the page themselves.")


def is_bot_check(title: str, text: str) -> bool:
    """A site's "are you a person" page (Cloudflare's "Just a moment...", a captcha), not the page asked for."""
    t, x = (title or "").lower(), (text or "").lower()[:3000]
    return any(w in t for w in _BOT_TITLES) or any(w in x for w in _BOT_TEXT)


@dataclass
class Page:
    url: str
    title: str
    text: str
    shot: bytes
    note: str = ""
    images: list[dict] = field(default_factory=list)  # the page's own photos: [{url, label}] (odie.browser.images)
    login: bool = False  # a visible password field: the page asks someone to sign in
    signin: bool = False  # a sign-in page: a password field, or a username field where the path or title says sign in


def public_policy(resolve=resolve_host, ttl: float = 300) -> Policy:
    """Only public http(s) addresses (the web tool's own check), with each host's answer kept for `ttl` seconds. A
    lookup that failed isn't kept (the network may be back in a moment). `allow.reason(url)` says why one was refused."""
    cache: dict[str, tuple[float, bool]] = {}
    reasons: dict[str, str] = {}

    async def allow(url: str) -> bool:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        host = u.hostname.lower()
        hit = cache.get(host)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        why = await public_url(url, resolve)
        if why:
            reasons[host] = why
        if why is None or "could not be found" not in why:
            cache[host] = (time.monotonic(), why is None)
        return why is None

    allow.reason = lambda url: reasons.get((urlsplit(url).hostname or "").lower(), "")  # type: ignore[attr-defined]
    return allow


def global_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.strip("[]").split("%")[0])
    except ValueError:
        return False
    return a.is_global and not a.is_multicast


_READ = """(() => {
  const s = document.createElement("style");
  s.textContent = "nav, header, footer, aside, [role=navigation], [role=banner], [role=contentinfo], [aria-hidden=true] { display: none !important }";
  document.documentElement.appendChild(s);
  let text = "";
  for (const sel of ["main", "[role=main]", "#search", "#content", "article"]) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 200) { text = el.innerText; break; }
  }
  if (!text && document.body) text = document.body.innerText;
  s.remove();
  const shown = (i) => i.offsetParent !== null;
  const login = [...document.querySelectorAll("input[type=password]")].some(shown);
  const userish = [...document.querySelectorAll("input")].some((i) => shown(i) && i.type !== "password" && i.type !== "search"
    && (/^(username|email|tel)$/.test(i.autocomplete) || /^(email|tel)$/.test(i.type) || /(e-?mail|user|login|mobile|phone)/i.test(i.name + " " + i.id)));
  const asks = /(sign[-_ ]?in|log[-_ ]?in)/i.test(location.pathname + " " + document.title);
  return {title: document.title, url: location.href, text, login, signin: (login || userish) && asks};  // a re-auth prompt isn't one
})()"""

_VISIBLE = """const visible = (e) => { const r = e.getBoundingClientRect(), st = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && st.visibility !== "hidden" && st.display !== "none"; };
const norm = (t) => (t || "").replace(/\\s+/g, " ").trim().toLowerCase();"""

_CLICK = """((want) => {""" + _VISIBLE + """
  const w = norm(want);
  const els = [...document.querySelectorAll("a, button, [role=button], [role=link], input[type=submit], input[type=button], summary")].filter(visible);
  const label = (e) => norm(e.innerText || e.value || e.getAttribute("aria-label") || e.title);
  const hit = els.find((e) => label(e) === w) || els.find((e) => label(e).includes(w));
  const selects = [...document.querySelectorAll("select")].filter((s) => visible(s) && !s.disabled);
  if (!hit) {  // a dropdown's option, by its words (NSE's expiry date): chosen as a person would, so the page hears it
    const opts = selects.flatMap((s) => [...s.options].filter((o) => !o.disabled).map((o) => [s, o]));
    const pick = opts.find(([, o]) => norm(o.text) === w) || opts.find(([, o]) => norm(o.text).includes(w));
    if (pick) {
      const [s, o] = pick;
      s.scrollIntoView({block: "center"});
      s.focus();
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(s, o.value);  // React sees it too
      s.dispatchEvent(new Event("input", {bubbles: true}));
      s.dispatchEvent(new Event("change", {bubbles: true}));
      return {ok: true, selected: norm(o.text)};
    }
    const named = (s) => norm((s.labels && s.labels[0] && s.labels[0].innerText) || s.getAttribute("aria-label") || s.name || s.id);
    return {ok: false, options: [...new Set(els.map(label).filter((t) => t && t.length < 60))].slice(0, 25),
            dropdowns: selects.slice(0, 5).map((s) => [named(s), [...s.options].slice(0, 12).map((o) => norm(o.text))])};
  }
  if (hit.tagName === "A") hit.removeAttribute("target");
  window.__odieHit = hit; window.__odieClicked = false;  // did the press reach it? (a page that shifts makes it miss)
  hit.addEventListener("click", () => { window.__odieClicked = true; }, {once: true, capture: true});
  hit.scrollIntoView({block: "center"});
  const r = hit.getBoundingClientRect();
  return {ok: true, x: r.left + r.width / 2, y: r.top + r.height / 2};
})"""

_SECRET = r"\bpass(word|code|phrase)\b|\bpin\b(?!\s?code)|\botp\b|\bcvv\b|\bcvc\b|card\s?(number|no\b)|security code"

_FIELD = """((want) => {""" + _VISIBLE + """
  const w = norm(want);
  const fields = [...document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=checkbox]):not([type=radio]):not([type=file]), textarea")].filter(visible);
  const names = (f) => [f.labels ? [...f.labels].map((l) => l.innerText).join(" ") : "", f.placeholder, f.getAttribute("aria-label"), f.name, f.id, f.title].map(norm).filter(Boolean);
  const hit = fields.find((f) => names(f).some((n) => n === w)) || fields.find((f) => names(f).some((n) => n.includes(w)));
  if (!hit) return {ok: false, options: [...new Set(fields.map((f) => names(f)[0]).filter(Boolean))].slice(0, 15)};
  const shown = [hit.labels ? [...hit.labels].map((l) => l.innerText).join(" ") : "", hit.placeholder, hit.getAttribute("aria-label"), hit.title].map(norm).filter(Boolean);
  const said = shown.length ? shown : [norm(hit.name), norm(hit.id)];  // what a person sees decides; else its names
  if (hit.type === "password" || said.some((n) => /""" + _SECRET + """/i.test(n)) || /^(cc-(number|csc|exp(-month|-year)?)|one-time-code)$/.test(hit.autocomplete)) return {ok: false, secret: true};
  hit.scrollIntoView({block: "center"});
  hit.focus();
  if (hit.select) hit.select();
  return {ok: true};
})"""

# The login fields of a page, for a login Odie fills itself (never the model's browser_type, which refuses these fields).
_LOGIN = """((op) => {""" + _VISIBLE + """
  const inputs = [...document.querySelectorAll("input")].filter((i) => visible(i) && !i.disabled && !i.readOnly);
  const label = (f) => norm([f.labels ? [...f.labels].map((l) => l.innerText).join(" ") : "", f.placeholder,
                              f.getAttribute("aria-label"), f.name, f.id].join(" "));
  const isCode = (f) => f.type !== "password" && (f.autocomplete === "one-time-code"
    || /\\b(otp|one[- ]?time|verification|verify|2fa|mfa|authenticat)/.test(label(f)) || (/\\bcode\\b/.test(label(f)) && f.inputMode === "numeric"));
  const isPass = (f) => f.type === "password" && f.autocomplete !== "new-password";
  const isUser = (f) => f.type !== "password" && f.type !== "search" && f.type !== "hidden" && !isCode(f)
    && (/^(username|email|tel)$/.test(f.autocomplete) || /^(email|tel)$/.test(f.type) || /(e-?mail|user|login|mobile|phone)/.test(label(f)));
  const user = inputs.find(isUser), pass = inputs.find(isPass), code = inputs.find(isCode);
  if (op === "state") return {url: location.href, user: !!user, password: !!pass, code: !!code,
    newpass: inputs.some((f) => f.type === "password" && f.autocomplete === "new-password"),
    captcha: !!document.querySelector('iframe[src*="captcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="challenges.cloudflare"]'),
    asks: /(sign[-_ ]?in|log[-_ ]?in)/i.test(location.pathname + " " + document.title)};
  const f = op === "user" ? user : op === "password" ? pass : code;
  if (!f) return {ok: false};
  f.scrollIntoView({block: "center"});
  f.focus();
  if (f.select) f.select();
  const form = f.form;  // where it would really go: the resolved action (a <base> counts), every button's formaction, a target
  const buttons = form ? [...form.querySelectorAll("button, input[type=submit], input[type=image]")].filter((b) => b.type === "submit" || b.type === "image") : [];
  return {ok: true, url: location.href, target: form ? form.target : "",
          actions: form ? [form.action, ...buttons.filter((b) => b.hasAttribute("formaction")).map((b) => b.formAction)] : []};
})"""

# A page's WebSockets can't be intercepted over DevTools: refuse the ones to this computer and the home network here.
_WS_GUARD = r"""(() => {
  const W = window.WebSocket;
  if (!W || W.__odie) return;
  const local = (h) => /^(localhost|.*\.localhost|.*\.local|.*\.lan|.*\.home|127\.|10\.|192\.168\.|169\.254\.|0\.|\[?::1?\]?$|\[?f[cd][0-9a-f]{2}:|\[?fe80:|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)/i.test(h);
  function Guard(url, protocols) {
    const u = new URL(url, location.href);
    if (local(u.hostname)) throw new DOMException("Blocked: this computer and the home network are off limits", "SecurityError");
    return protocols === undefined ? new W(url) : new W(url, protocols);
  }
  Guard.prototype = W.prototype;
  Object.assign(Guard, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3, __odie: true});
  window.WebSocket = Guard;
})();"""


def _short(url: str) -> str:
    return url if len(url) <= 80 else url[:77] + "…"


class Browser:
    def __init__(self, profile: Path, binary: str | None = None, policy: Policy | None = None, idle: float = 600,
                 ip_ok: Callable[[str], bool] = global_ip, plain_http_ok: bool = False):
        self.profile = Path(profile)
        self.binary = binary
        self.policy = policy or public_policy()
        self.ip_ok = ip_ok  # where an answer came from (DNS rebinding); tests on 127.0.0.1 pass their own
        self.plain_http_ok = plain_http_ok  # tests serve login pages over http; a real login goes only over https
        self.idle = idle
        self._proc: subprocess.Popen | None = None
        self._cdp: CDP | None = None
        self._ua = ""
        self._tabs: dict[str, str] = {}  # tab (a chat thread) -> DevTools session
        self._root: dict[str, str] = {}  # a frame's or worker's session -> its tab's session
        self._attached: dict[str, asyncio.Future] = {}  # target id -> its session, once auto-attached
        self._blocked: dict[str, int] = {}  # tab session -> requests refused since the last action
        self._denied: set[str] = set()  # hosts whose answers came from this computer or the home network
        self._lock = asyncio.Lock()
        self._tab_locks: dict[str, asyncio.Lock] = {}
        self._idle_task: asyncio.Task | None = None
        self._busy = 0  # actions under way: the idle countdown starts only once none are
        self._sealed: set[str] = set()  # render tabs' sessions: every request they make is refused
        self._sealed_frames: set[str] = set()  # and their frames, for requests paused browser-wide (no session)
        self._contexts: dict[str, str] = {}  # isolated tab -> its own browser context (background work: no cookies)
        self._holds: dict[str, str] = {}  # tab -> who holds it (the user, in the live view): tools wait
        self._upi_fns: list[Callable[[str, str], None]] = []
        self._upi: dict[str, str] = {}  # tab -> the last UPI app link its page tried to open
        self._live: dict[str, tuple[Callable, Callable]] = {}  # tab -> (on_frame, on_page): the user's live view of it
        self._snapping: set[str] = set()  # live tabs whose sharp picture is being taken
        self._dirty: set[str] = set()  # and that changed meanwhile
        self._input_locks: dict[str, asyncio.Lock] = {}  # live tabs: one input or one picture at a time
        self._fences: dict[str, set[str]] = {}  # tab -> the only sites its page may go to (a private chat's steps)
        self._main: dict[str, str] = {}  # tab -> its main frame's id (a page's main frame id is its target id)
        self._fenced: dict[str, str] = {}  # tab -> the address its page was stopped from going to

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._cdp is not None and not self._cdp.closed

    # ── starting and stopping ──
    def _left_over(self) -> None:
        """A browser still holding this profile (Odie killed hard): it's ours, so it goes."""
        try:
            pid = int(os.readlink(self.profile / "SingletonLock").rsplit("-", 1)[1])
        except (OSError, ValueError, IndexError):
            return
        try:
            cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return
        if f"--user-data-dir={self.profile}" not in cmd:
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            return
        for _ in range(30):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)

    async def _start(self) -> None:
        binary = self.binary or find.browser_binary()
        if not binary:
            raise BrowserError("There's no Chrome, Edge, Chromium or Brave on this computer, so I can't open pages.")
        self.profile.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._left_over)
        port_file = self.profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        args = [binary, "--headless=new", f"--user-data-dir={self.profile}", "--remote-debugging-port=0", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--disable-component-extensions-with-background-pages",
                "--disable-sync", "--disable-background-networking", "--disable-component-update", "--disable-breakpad",
                "--disable-crash-reporter", "--mute-audio", f"--window-size={VIEW[0]},{VIEW[1]}", "about:blank"]
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(150):
            if port_file.exists() and len(port_file.read_text().split()) >= 2:
                break
            if self._proc.poll() is not None:
                self._proc = None
                raise BrowserError("The browser didn't start (another copy of Odie's browser may still be running).")
            await asyncio.sleep(0.1)
        else:
            await self.close()
            raise BrowserError("The browser didn't start in time.")
        port, path = port_file.read_text().split()[:2]
        self._cdp = await CDP.connect(f"ws://127.0.0.1:{port}{path}")
        self._cdp.on(self._event)
        version = await self._cdp.send("Browser.getVersion")
        self._ua = version.get("userAgent", "").replace("HeadlessChrome", "Chrome")
        await self._cdp.send("Browser.setDownloadBehavior", {"behavior": "deny"})
        # Every new page, pop-up and worker waits for Odie before it runs: its requests are checked from the start.
        await self._cdp.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True})
        # And browser-wide: a pop-up's first navigation starts in the browser process, before its own session is
        # set up, so only interception here is sure to see it (the per-session checks are a second layer).
        await self._cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})

    async def close(self) -> None:
        """Closes the browser and everything it started."""
        if self._idle_task and self._idle_task is not asyncio.current_task():
            self._idle_task.cancel()
        self._idle_task = None
        cdp, proc = self._cdp, self._proc
        self._cdp, self._proc = None, None
        self._tabs.clear()
        self._root.clear()
        self._attached.clear()
        self._blocked.clear()
        self._busy -= len(self._live)  # a live view keeps the browser up; it ends with the browser
        self._live.clear()
        answered = False
        if cdp:
            try:
                await cdp.send("Browser.close", timeout=3)
                answered = True
            except Exception:  # noqa: BLE001 (already gone, or hung)
                pass
            await cdp.close()
        if proc:
            if answered:
                await _exited(proc, 3)
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # whatever is left of it: renderers and helpers too
            except (ProcessLookupError, PermissionError):
                pass
            await _exited(proc, 5)

    def _stop_idle(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        self._idle_task = None

    def _start_idle(self) -> None:
        self._stop_idle()
        self._idle_task = asyncio.get_running_loop().create_task(self._idle_close())

    async def _idle_close(self) -> None:
        await asyncio.sleep(self.idle)
        async with self._lock:
            if not self._busy:
                await self.close()

    def _attached_future(self, target_id: str) -> asyncio.Future:
        if target_id not in self._attached:
            self._attached[target_id] = asyncio.get_running_loop().create_future()
        return self._attached[target_id]

    async def _guard(self, s: str, page: bool) -> None:
        """Request checks (and, on a page or frame, the WebSocket guard) on a session, before it runs."""
        assert self._cdp
        await self._cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session=s)
        if page:
            await self._cdp.send("Network.enable", session=s)
            await self._cdp.send("Page.enable", session=s)
            await self._cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": _WS_GUARD}, session=s)
            await self._cdp.send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}, session=s)

    async def _session(self, tab: str, create: bool, isolated: bool = False) -> str:
        async with self._lock:
            if not self.running:
                await self.close()
                if not create:
                    raise BrowserError("Nothing is open in the browser for this chat: open a page first.")
                await self._start()
            if tab in self._tabs:
                return self._tabs[tab]
            if not create:
                raise BrowserError("Nothing is open in the browser for this chat: open a page first.")
            assert self._cdp
            where = {}
            if isolated:  # a browser context of its own: none of the profile's cookies or storage, thrown away with the tab
                ctx = (await self._cdp.send("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
                self._contexts[tab] = ctx
                where = {"browserContextId": ctx}
            target = await self._cdp.send("Target.createTarget", {"url": "about:blank", **where})
            s = await asyncio.wait_for(self._attached_future(target["targetId"]), 10)
            await self._guard(s, page=True)
            await self._cdp.send("Network.setUserAgentOverride", {"userAgent": self._ua, "acceptLanguage": _accept_language()}, session=s)
            await self._cdp.send("Emulation.setDeviceMetricsOverride", {"width": VIEW[0], "height": VIEW[1], "deviceScaleFactor": 1,
                                                                        "mobile": False}, session=s)
            await self._cdp.send("Runtime.runIfWaitingForDebugger", session=s)
            self._tabs[tab] = s
            self._root[s] = s
            self._main[tab] = target["targetId"]
            return s

    # ── what every page does ──
    async def _attach(self, params: dict, parent: str | None) -> None:
        assert self._cdp
        s, info = params["sessionId"], params.get("targetInfo", {})
        kind, tid = info.get("type"), info.get("targetId", "")
        if kind == "page" and parent is None and not info.get("openerId"):
            if params.get("waitingForDebugger"):
                fut = self._attached_future(tid)
                if not fut.done():
                    fut.set_result(s)  # a tab Odie opened: _session guards it, then lets it run
            else:
                try:
                    await self._guard(s, page=True)  # the tab the browser started with: guarded, never used
                except (CDPError, ConnectionError, TimeoutError):
                    pass
            return
        self._root[s] = self._root.get(parent or "", parent or s)
        try:
            await self._guard(s, page=kind in ("page", "iframe"))
        except (CDPError, ConnectionError, TimeoutError):
            pass  # a worker without the Fetch domain: Chrome's local-network protection covers it
        try:
            await self._cdp.send("Runtime.runIfWaitingForDebugger", session=s)
            if kind == "page" and info.get("openerId"):  # a pop-up: it ran with its requests checked, now it goes
                await self._cdp.send("Target.closeTarget", {"targetId": tid})
        except (CDPError, ConnectionError, TimeoutError):
            pass

    async def _event(self, method: str, params: dict, session: str | None):
        cdp = self._cdp
        if cdp is None:
            return
        try:
            if method == "Fetch.requestPaused":
                url = params["request"]["url"]
                rid = params["requestId"]
                host = (urlsplit(url).hostname or "").lower()
                root = self._root.get(session or "", session or "")
                if (root in self._sealed or params.get("frameId") in self._sealed_frames) and urlsplit(url).scheme not in _FREE:
                    await cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, session=session)
                    return
                if params.get("resourceType") == "Document" and (tab := self._tab_of(session)) in self._fences \
                        and params.get("frameId") == self._main.get(tab) and sites.site_of(url) not in self._fences[tab]:
                    self._fenced[tab] = url  # a private chat's page going elsewhere: stopped, the step says how to ask
                    await cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, session=session)
                    return
                if urlsplit(url).scheme in _FREE or (host not in self._denied and await self.policy(url)):
                    await cdp.send("Fetch.continueRequest", {"requestId": rid}, session=session)
                else:
                    root = self._root.get(session or "", session or "")
                    self._blocked[root] = self._blocked.get(root, 0) + 1
                    await cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, session=session)
            elif method == "Network.responseReceived":
                r = params.get("response", {})
                ip = r.get("remoteIPAddress")
                if ip and not self.ip_ok(ip):  # the host answered from this computer or the home network
                    self._denied.add((urlsplit(r.get("url", "")).hostname or "").lower())
            elif method == "Target.attachedToTarget":
                await self._attach(params, session)
            elif method == "Page.screencastFrame":
                tab = self._tab_of(session) or ""
                try:
                    if tab in self._live:
                        await self._live_frame(tab, session, params)  # to the phone, before the next frame
                finally:
                    await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}, session=session)
            elif (method in ("Page.frameNavigated", "Page.loadEventFired") and (tab := self._tab_of(session)) in self._live
                  and session == self._tabs.get(tab)):  # the tab's own page: an embedded box from another site has its own session
                if method == "Page.frameNavigated":
                    frame = params.get("frame", {})
                    if not frame.get("parentId"):
                        await self._live[tab][1]({"url": frame.get("url", ""), "loading": True})
                else:
                    await self._live[tab][1](await self._live_page(session))
            elif method in ("Page.frameRequestedNavigation", "Page.windowOpen"):
                link = upi_link(params.get("url", ""))
                if link:  # a checkout opening a UPI app: it can't here, so the link goes to the user's phone
                    tab = self._tab_of(session)
                    if tab is not None:
                        self._upi[tab] = link
                        for fn in list(self._upi_fns):
                            try:
                                fn(tab, link)
                            except Exception:  # noqa: BLE001 (a listener's bug must not stop the browser)
                                pass
            elif method == "Page.javascriptDialogOpening":
                await cdp.send("Page.handleJavaScriptDialog", {"accept": False}, session=session)
        except (CDPError, ConnectionError, TimeoutError, KeyError):
            pass  # the tab or the browser went away mid-request

    def _tab_of(self, session: str | None) -> str | None:
        root = self._root.get(session or "", session or "")
        return next((t for t, ts in self._tabs.items() if ts == root), None)

    async def _eval(self, s: str, expression: str):
        assert self._cdp
        r = await self._cdp.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True},
                                 session=s, timeout=INPUT_TIMEOUT)
        if "exceptionDetails" in r:
            raise BrowserError("The page didn't let me do that.")
        return r.get("result", {}).get("value")

    async def _settle(self, s: str, timeout: float = 15) -> None:
        """Waits for the page to finish loading, then a moment for its scripts."""
        start = time.monotonic()
        await asyncio.sleep(0.3)
        while time.monotonic() - start < timeout:
            try:
                if await self._eval(s, "document.readyState") == "complete":
                    break
            except (BrowserError, CDPError, TimeoutError):
                pass  # between documents
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.6)

    async def _stopped(self, s: str) -> BrowserError | None:
        """The page was stopped from leaving the chat's signed-in sites (fence): back to where it was, and why."""
        stopped = self._fenced.pop(self._tab_of(s) or "", None)
        if stopped is None:
            return None
        try:
            if str(await self._eval(s, "location.href")).startswith("chrome-error://"):
                await self._eval(s, "history.back()")
        except (BrowserError, CDPError, TimeoutError):
            pass
        return FencedError(f"Stopped: the page tried to go to {sites.site_of(stopped)} ({stopped[:300]}). This chat has read a "
                            "signed-in page, so another site needs the user's tap: use browser_open with that address to ask them.")

    async def _page(self, s: str) -> Page:
        assert self._cdp
        got = await self._eval(s, _READ) or {}
        url = str(got.get("url", ""))
        if (stopped := await self._stopped(s)) is not None:
            raise stopped
        if url.startswith("chrome-error://"):
            why = "it leads to this computer or the home network" if self._blocked.get(s) else "it couldn't be reached"
            self._blocked.pop(s, None)
            raise BrowserError(f"The page didn't open: {why}.")
        shot = await self._cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 60}, session=s)
        lines = [" ".join(line.split()) for line in str(got.get("text", "")).splitlines()]
        text = "\n".join(line for line in lines if line)[:TEXT_CAP]
        n = self._blocked.pop(s, 0)
        note = f"Blocked {n} request{'s' if n != 1 else ''} to this computer or the home network." if n else ""
        try:
            from odie.browser.images import PAGE_IMAGES_JS
            images = [i for i in (await self._eval(s, PAGE_IMAGES_JS) or []) if isinstance(i, dict) and i.get("url")]
        except (BrowserError, CDPError, TimeoutError):
            images = []  # a page that won't say still gets read
        return Page(url=url, title=str(got.get("title", "")), text=text, shot=base64.b64decode(shot["data"]), note=note, images=images,
                    login=bool(got.get("login")), signin=bool(got.get("signin")))

    async def _act(self, tab: str, create: bool, fn, isolated: bool = False) -> Page:
        if tab in self._holds:
            raise BrowserError(HELD)
        self._busy += 1
        self._stop_idle()
        try:
            async with self._tab_locks.setdefault(tab, asyncio.Lock()):  # one action at a time on a tab
                s = await self._session(tab, create, isolated)
                return await fn(s)
        except (CDPError, ConnectionError, TimeoutError):
            raise BrowserError("The page stopped responding. Open it again with browser_open.") from None
        finally:
            self._busy -= 1
            if not self._busy and self.running:
                self._start_idle()

    async def close_tab(self, tab: str) -> None:
        s = self._tabs.pop(tab, None)
        self._main.pop(tab, None)
        self.fence(tab, None)
        self._tab_locks.pop(tab, None)
        self._upi.pop(tab, None)
        ctx = self._contexts.pop(tab, None)
        if s and self._cdp is not None:
            try:
                info = await self._cdp.send("Target.getTargetInfo", {}, session=s)
                await self._cdp.send("Target.closeTarget", {"targetId": info["targetInfo"]["targetId"]})
            except (CDPError, ConnectionError, TimeoutError, KeyError):
                pass
        if ctx and self._cdp is not None:
            try:
                await self._cdp.send("Target.disposeBrowserContext", {"browserContextId": ctx})
            except (CDPError, ConnectionError, TimeoutError):
                pass

    # ── signed-in browsing: holding a tab for the user, signing out, UPI links ──
    def fence(self, tab: str, allowed: set[str] | None) -> None:
        """Keep the tab's page on these sites (registrable domains), or lift it (None)."""
        if allowed:
            self._fences[tab] = set(allowed)
        else:
            self._fences.pop(tab, None)
        self._fenced.pop(tab, None)

    def hold(self, tab: str, holder: str) -> None:
        self._holds[tab] = holder

    def release(self, tab: str, holder: str | None = None) -> None:
        if holder is None or self._holds.get(tab) == holder:
            self._holds.pop(tab, None)

    def held_by(self, tab: str) -> str | None:
        return self._holds.get(tab)

    def on_upi(self, fn: Callable[[str, str], None]) -> None:
        self._upi_fns.append(fn)

    def take_upi(self, tab: str) -> str | None:
        return self._upi.pop(tab, None)

    # ── the live view (the user's turn; odie.signin.live): frames out, touch and keys in, nothing to the model ──
    async def live_start(self, tab: str, width: int, height: int, on_frame: Callable[[str, dict], Awaitable[None]],
                         on_page: Callable[[dict], Awaitable[None]]) -> None:
        """Show the tab to the user, phone-shaped (touch on, the desktop user agent kept), as JPEG frames (base64)
        acknowledged one by one, so a slow phone gets fewer. Called again, it resizes and starts over."""
        s = await self._session(tab, create=True)
        assert self._cdp
        self.fence(tab, None)  # the user drives: anywhere they like
        if tab not in self._live:
            self._busy += 1  # the browser stays up while the user drives it
            self._stop_idle()
        self._live[tab] = (on_frame, on_page)
        await self._cdp.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 2,
                                                                    "mobile": True}, session=s)
        await self._cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=s)
        try:
            await self._cdp.send("Page.stopScreencast", session=s)
        except CDPError:
            pass
        await self._cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": width * 2, "maxHeight": height * 2,
                                                      "everyNthFrame": 1}, session=s)
        await on_page(await self._live_page(s))

    async def _live_frame(self, tab: str, s: str, params: dict) -> None:
        """The screencast says the page changed; the phone gets a sharp picture of it. Headless Chrome casts at 1x (a
        desktop page shrunk onto a phone is a blur), while a screenshot keeps the 2x scale. One at a time per tab: a
        change during one is sent right after it."""
        if tab in self._snapping:
            self._dirty.add(tab)
            return
        self._snapping.add(tab)
        meta = params.get("metadata", {})
        try:
            while tab in self._live:
                self._dirty.discard(tab)
                try:
                    async with self._input_lock(tab):  # a screenshot during a tap loses the tap (headless Chrome)
                        shot = (await self._cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 60}, session=s,
                                                     timeout=INPUT_TIMEOUT))["data"]
                except (CDPError, ConnectionError, TimeoutError, KeyError, AttributeError):
                    shot = params.get("data", "")  # the cast's own picture, if a screenshot can't be had
                live = self._live.get(tab)
                if live and shot:
                    await live[0](shot, meta)
                if tab not in self._dirty:
                    break
        finally:
            self._snapping.discard(tab)

    def _input_lock(self, tab: str) -> asyncio.Lock:
        return self._input_locks.setdefault(tab, asyncio.Lock())

    async def _to_page(self, s: str, x: float, y: float) -> tuple[float, float]:
        """The phone's taps are in the shown picture's pixels; Chrome reads them in the page's own. They differ when a
        desktop page is shown shrunk (scale ~0.4) or zoomed."""
        try:
            scale, ox, oy = await self._eval(s, "[visualViewport.scale, visualViewport.offsetLeft, visualViewport.offsetTop]")
        except (BrowserError, CDPError, TimeoutError, TypeError, ValueError):
            return x, y
        scale = scale if isinstance(scale, int | float) and scale > 0 else 1
        return ox + x / scale, oy + y / scale

    async def _live_page(self, s: str) -> dict:
        try:
            got = await self._eval(s, "({url: location.href, title: document.title, loading: document.readyState !== 'complete'})")
        except (BrowserError, CDPError, TimeoutError):
            return {"loading": True}  # between documents
        return got if isinstance(got, dict) else {"loading": True}

    async def live_input(self, tab: str, msg: dict) -> None:
        """One checked input from the phone (odie.signin.live.clean), at the page's CSS coordinates."""
        s = self._tabs.get(tab)
        if s is None or tab not in self._live or self._cdp is None:
            raise BrowserError("The live view isn't on for this tab.")
        async with self._input_lock(tab):  # never while a sharp picture is being taken
            await self._live_input(s, msg)

    async def _live_input(self, s: str, msg: dict) -> None:
        assert self._cdp
        send = self._cdp.send
        t = msg["t"]
        if t == "tap":
            x, y = await self._to_page(s, msg["x"], msg["y"])
            await send("Input.synthesizeTapGesture", {"x": x, "y": y, "gestureSourceType": "touch"}, session=s, timeout=INPUT_TIMEOUT)
        elif t == "drag":  # a finger moving up scrolls the page down
            (x0, y0), (x1, y1) = await self._to_page(s, msg["x0"], msg["y0"]), await self._to_page(s, msg["x1"], msg["y1"])
            await send("Input.synthesizeScrollGesture", {"x": x0, "y": y0, "xDistance": x1 - x0, "yDistance": y1 - y0,
                                                         "gestureSourceType": "touch", "speed": 2400}, session=s, timeout=INPUT_TIMEOUT)
        elif t == "text":
            await send("Input.insertText", {"text": msg["s"]}, session=s, timeout=INPUT_TIMEOUT)
        elif t == "key":
            k = msg["k"]
            code = {"Backspace": 8, "Enter": 13, "Tab": 9}[k]
            key = {"key": k, "code": k, "windowsVirtualKeyCode": code}  # no native key code: on a Mac it becomes a real key event
            await send("Input.dispatchKeyEvent", {"type": "keyDown", **key, **({"text": "\r"} if k == "Enter" else {})}, session=s,
                       timeout=INPUT_TIMEOUT)
            await send("Input.dispatchKeyEvent", {"type": "keyUp", **key}, session=s, timeout=INPUT_TIMEOUT)
        elif t == "back":
            await self._eval(s, "history.back()")
        elif t == "reload":
            await send("Page.reload", session=s)
        elif t == "go":
            url = msg["url"] if re.match(r"^[a-z][a-z0-9+.-]*://", msg["url"], re.I) else "https://" + msg["url"]
            if urlsplit(url).scheme not in ("http", "https") or not await self.policy(url):
                raise BrowserError("That address can't be opened here.")
            await send("Page.navigate", {"url": url}, session=s)

    async def live_stop(self, tab: str) -> None:
        """The user's turn is over: no more frames, and the tab is desktop-shaped again."""
        if self._live.pop(tab, None) is None:
            return
        self._busy -= 1
        s = self._tabs.get(tab)
        try:
            if s and self._cdp is not None and self.running:
                await self._cdp.send("Page.stopScreencast", session=s)
                await self._cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False}, session=s)
                await self._cdp.send("Emulation.setDeviceMetricsOverride", {"width": VIEW[0], "height": VIEW[1], "deviceScaleFactor": 1,
                                                                            "mobile": False}, session=s)
        except (CDPError, ConnectionError, TimeoutError):
            pass  # the tab went away with the user's turn
        finally:
            if not self._busy and self.running:
                self._start_idle()

    async def sign_out(self, domains: list[str] | None = None, origins=()) -> None:
        """Signs out of these sites: their cookies, and the storage of their usual addresses plus `origins` (where they
        were seen). None signs out of everything: the browser closes and its profile (Odie's own) is wiped."""
        if domains is None:
            async with self._lock:
                await self.close()
                shutil.rmtree(self.profile, ignore_errors=True)  # every cookie and every site's storage, whatever the origin
            return
        async with self._lock:
            if not self.running:
                await self.close()
                await self._start()
        cdp = self._cdp
        assert cdp
        cookies = (await cdp.send("Storage.getCookies", {})).get("cookies", [])
        mine = [c for c in cookies if any(c.get("domain", "").lstrip(".") == d or c.get("domain", "").endswith("." + d)
                                          for d in domains)]
        usual = [f"{scheme}://{host}{d}" for d in domains for scheme in ("https", "http")
                 for host in ("", *(("www.",) if _named(d) else ()))]  # "www." + an IP isn't a host
        # Both need a page's session (at the browser level, clearDataForOrigin answers "Internal error"): a throwaway tab.
        target = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        try:
            s = await asyncio.wait_for(self._attached_future(target), 10)
            await cdp.send("Runtime.runIfWaitingForDebugger", session=s)
            for c in mine:
                await cdp.send("Network.deleteCookies", {"name": c["name"], "domain": c["domain"], "path": c.get("path", "/")},
                               session=s)
            for origin in dict.fromkeys(o for o in [*usual, *origins] if _origin_ok(o)):  # a malformed one clears every site
                await cdp.send("Storage.clearDataForOrigin", {"origin": origin, "storageTypes": STORAGE}, session=s)
        finally:
            self._attached.pop(target, None)
            try:
                await cdp.send("Target.closeTarget", {"targetId": target})
            except (CDPError, ConnectionError, TimeoutError):
                pass

    async def _past_bot_check(self, s: str) -> Page:
        """The page, read again for a while if it's a bot check (most clear by themselves); one that stays says so."""
        page = await self._page(s)
        end = time.monotonic() + BOT_CHECK_WAIT
        while is_bot_check(page.title, page.text) and time.monotonic() < end:
            await asyncio.sleep(1)
            page = await self._page(s)
        if is_bot_check(page.title, page.text):
            page.note = f"{page.note} {BOT_NOTE}".strip()
        return page

    # ── the actions ──
    async def open(self, tab: str, url: str, isolated: bool = False) -> Page:
        host = (urlsplit(url).hostname or "").lower()
        if host in self._denied or not await self.policy(url):
            why = getattr(self.policy, "reason", lambda u: "")(url)
            if "could not be found" in why:
                raise BrowserError(f"I couldn't find {host}: check the address, or try again in a moment.")
            raise BrowserError(f"I only open public web pages, not {_short(url)}: {_OFF_LIMITS}.")

        async def go(s: str) -> Page:
            assert self._cdp
            self._blocked[s] = 0
            r = await self._cdp.send("Page.navigate", {"url": url}, session=s)
            if r.get("errorText") and (stopped := await self._stopped(s)) is not None:
                raise stopped
            if r.get("errorText"):
                why = "it leads to this computer or the home network" if "BLOCKED" in r["errorText"] else r["errorText"]
                raise BrowserError(f"The page didn't open: {why}.")
            await self._settle(s)
            return await self._past_bot_check(s)
        return await self._act(tab, True, go, isolated)

    async def click(self, tab: str, text: str) -> Page:
        if not text.strip():
            raise BrowserError("Say which link or button to click, by the words on it.")

        async def go(s: str) -> Page:
            assert self._cdp
            hit = await self._eval(s, f"{_CLICK}({json.dumps(text)})") or {}
            if not hit.get("ok"):
                options = ", ".join(f'"{o}"' for o in hit.get("options", [])[:15]) or "none"
                drops = "; ".join(f'"{name}": ' + ", ".join(f'"{o}"' for o in opts) for name, opts in hit.get("dropdowns") or [])
                raise BrowserError(f'No link or button says "{text}". These do: {options}.' + (f" Dropdowns: {drops}." if drops else ""))
            if hit.get("selected"):  # a dropdown's option: chosen, no pointer needed
                await self._settle(s)
                return await self._past_bot_check(s)
            for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
                await self._cdp.send("Input.dispatchMouseEvent", {"type": kind, "x": hit["x"], "y": hit["y"], "button": "left",
                                                                  "clickCount": 1}, session=s, timeout=INPUT_TIMEOUT)
            try:
                missed = await self._eval(s, "window.__odieClicked === false")
            except (BrowserError, CDPError, TimeoutError):
                missed = False  # the page is already going: the click landed
            if missed:  # the page moved under the pointer: click the element itself
                await self._eval(s, "window.__odieHit && window.__odieHit.click()")
            await self._settle(s)
            return await self._past_bot_check(s)
        return await self._act(tab, False, go)

    async def type(self, tab: str, field: str, text: str, submit: bool = True) -> Page:
        async def go(s: str) -> Page:
            assert self._cdp
            hit = await self._eval(s, f"{_FIELD}({json.dumps(field)})") or {}
            if hit.get("secret"):
                raise BrowserError("That's a password, card, PIN or one-time-code field: I never type into those; it's the user's turn.")
            if not hit.get("ok"):
                options = ", ".join(f'"{o}"' for o in hit.get("options", [])) or "none"
                raise BrowserError(f'No field is called "{field}". These are: {options}.')
            await self._cdp.send("Input.insertText", {"text": text}, session=s, timeout=INPUT_TIMEOUT)
            if submit:
                before = await self._eval(s, "location.href")
                for kind in ("keyDown", "keyUp"):
                    await self._cdp.send("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                                    **({"text": "\r"} if kind == "keyDown" else {})}, session=s, timeout=INPUT_TIMEOUT)
                await asyncio.sleep(0.7)
                if await self._eval(s, "location.href") == before:  # Enter didn't submit (no submit button): submit the form
                    await self._eval(s, "(() => { const f = document.activeElement && document.activeElement.form; if (f) (f.requestSubmit ? f.requestSubmit() : f.submit()); })()")
            await self._settle(s)
            return await self._past_bot_check(s)
        return await self._act(tab, False, go)

    async def scroll(self, tab: str, down: bool = True) -> Page:
        async def go(s: str) -> Page:
            await self._eval(s, f"window.scrollBy(0, {1 if down else -1} * innerHeight * 0.85)")
            await asyncio.sleep(0.5)
            return await self._past_bot_check(s)
        return await self._act(tab, False, go)

    async def text(self, tab: str, cap: int = 20000) -> str:
        """The tab's readable text as it is now, up to `cap` characters (a signed-in tracker reads more than a step shows)."""
        async def go(s: str) -> str:
            got = await self._eval(s, _READ) or {}
            lines = [" ".join(line.split()) for line in str(got.get("text", "")).splitlines()]
            return "\n".join(line for line in lines if line)[:cap]
        return await self._act(tab, False, go)

    async def html(self, tab: str) -> str:
        """The open page's markup, as it is now (after its scripts ran)."""
        async def go(s: str) -> str:
            return await self._eval(s, "document.documentElement.outerHTML") or ""
        return await self._act(tab, False, go)

    # ── rendering a deck ──
    # ── a login Odie fills itself (odie.signin.box): only on its own site, over https, into login fields ──
    def _login_site_ok(self, url: str, site: str) -> bool:
        scheme = urlsplit(url).scheme
        return (scheme == "https" or (self.plain_http_ok and scheme == "http")) and sites.site_of(url) == site

    async def _login_state(self, s: str) -> dict:
        return await self._eval(s, f"{_LOGIN}('state')") or {}

    async def _fill_login(self, s: str, site: str, kind: str, value: str) -> str | None:
        """Type into the page's login field of this kind (user, password, code). None when typed, else why not."""
        assert self._cdp
        hit = await self._eval(s, f"{_LOGIN}({json.dumps(kind)})") or {}  # one snapshot: the address and the form together
        if not self._login_site_ok(str(hit.get("url", "")), site):
            return "wrong_site"
        if not hit.get("ok"):
            return "failed"
        if any(not self._login_site_ok(str(a), site) for a in hit.get("actions") or []) or hit.get("target") not in ("", "_self"):
            return "wrong_site"  # a form that posts somewhere else (or into another window) never gets the login
        await self._cdp.send("Input.insertText", {"text": value}, session=s, timeout=INPUT_TIMEOUT)
        return None

    async def _login_moved(self, s: str, before: dict, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            await asyncio.sleep(0.25)
            try:
                now = await self._login_state(s)
            except (BrowserError, CDPError, TimeoutError):
                return True  # between documents: it moved
            if any(now.get(k) != before.get(k) for k in ("url", "user", "password", "code")):
                return True
        return False

    async def _submit_login(self, s: str) -> None:
        """Enter in the field; if nothing moved, the form's own button."""
        assert self._cdp
        before = await self._login_state(s)
        for kind in ("keyDown", "keyUp"):
            await self._cdp.send("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                                                            **({"text": "\r"} if kind == "keyDown" else {})}, session=s, timeout=INPUT_TIMEOUT)
        if not await self._login_moved(s, before, 3):
            await self._eval(s, "(() => { const f = document.activeElement && document.activeElement.form; if (!f) return; "
                                "const b = f.querySelector('[type=submit], button:not([type=button])'); "
                                "if (b) b.click(); else if (f.requestSubmit) f.requestSubmit(); else f.submit(); })()")
            await self._login_moved(s, before, 5)
        await self._settle(s)

    async def _login_result(self, s: str) -> dict:
        st = await self._login_state(s)
        page = await self._page(s)
        if st.get("code"):
            return {"status": "code"}
        if st.get("captcha") or is_bot_check(page.title, page.text):
            return {"status": "captcha"}
        if st.get("password") or (st.get("user") and st.get("asks")):
            return {"status": "failed"}
        return {"status": "signed_in"}

    async def sign_in(self, tab: str, site: str, username: str, password: str) -> dict:
        """Fill a login on the tab's page (one step, or the username then the password) and send it. The values go
        only into CDP Input.insertText: never logged, never read back. {"status": signed_in, code, captcha, failed or
        wrong_site}."""
        async def go(s: str) -> dict:
            st = await self._login_state(s)
            if not self._login_site_ok(str(st.get("url", "")), site):
                return {"status": "wrong_site"}
            if st.get("newpass") or not (st.get("user") or st.get("password")):
                return {"status": "failed"}  # a sign-up or change-password form, or no login form at all
            if st.get("user"):
                if stop := await self._fill_login(s, site, "user", username):
                    return {"status": stop}
                if not st.get("password"):  # two steps: the password comes on the next page
                    await self._submit_login(s)
                    st = await self._login_state(s)
                    if st.get("code") or not st.get("password"):
                        got = await self._login_result(s)
                        return {"status": "failed"} if got["status"] == "signed_in" else got  # no password step: no sign-in
            if stop := await self._fill_login(s, site, "password", password):
                return {"status": stop}
            await self._submit_login(s)
            return await self._login_result(s)
        return await self._act(tab, False, self._fenced_to(tab, site, go))

    async def enter_code(self, tab: str, site: str, code: str) -> dict:
        """The one-time code a site sent the user, into its code field."""
        async def go(s: str) -> dict:
            if stop := await self._fill_login(s, site, "code", code):
                return {"status": stop}
            await self._submit_login(s)
            return await self._login_result(s)
        return await self._act(tab, False, self._fenced_to(tab, site, go))

    def _fenced_to(self, tab: str, site: str, go):
        """While a login is filled the tab's page can go only to the login's site: whatever a script does to the form
        as it's sent, the request to anywhere else is stopped (the fence)."""
        async def fenced(s: str):
            before = self._fences.get(tab)
            self._fences[tab] = {site}
            try:
                return await go(s)
            finally:
                if before is None:
                    self._fences.pop(tab, None)
                else:
                    self._fences[tab] = before
        return fenced

    async def look(self, tab: str) -> Page:
        """The tab's page as it is now (after a sign-in)."""
        return await self._act(tab, False, self._past_bot_check)

    async def render(self, html: str, width: int, height: int, pages: int, timeout: float = 60) -> tuple[bytes, list[bytes]]:
        """A deck's PDF and a JPEG of each page, from HTML that needs nothing from the network: rendered in a tab of
        its own browser context, sealed so every request it makes is refused."""
        self._busy += 1
        self._stop_idle()
        try:
            return await asyncio.wait_for(self._render(html, width, height, pages), timeout)
        except (CDPError, ConnectionError, TimeoutError) as e:
            raise BrowserError(f"The deck couldn't be rendered ({type(e).__name__}).") from None
        finally:
            self._busy -= 1
            if not self._busy and self.running:
                self._start_idle()

    async def _render(self, html: str, width: int, height: int, pages: int) -> tuple[bytes, list[bytes]]:
        async with self._lock:
            if not self.running:
                await self.close()
                await self._start()
        cdp = self._cdp
        assert cdp
        ctx = (await cdp.send("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
        target = frame = ""
        s = ""
        try:
            target = (await cdp.send("Target.createTarget", {"url": "about:blank", "browserContextId": ctx}))["targetId"]
            self._sealed_frames.add(target)  # a page's main frame has its target's id: sealed before it runs
            s = await asyncio.wait_for(self._attached_future(target), 10)
            self._sealed.add(s)
            self._root[s] = s
            await self._guard(s, page=True)
            await cdp.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                                  "mobile": False}, session=s)
            await cdp.send("Runtime.runIfWaitingForDebugger", session=s)
            frame = (await cdp.send("Page.getFrameTree", session=s))["frameTree"]["frame"]["id"]
            self._sealed_frames.add(frame)
            await cdp.send("Page.setDocumentContent", {"frameId": frame, "html": html}, session=s, timeout=60)
            await self._eval(s, "(async () => { await document.fonts.ready; const t = Date.now(); "
                                "while ([...document.images].some(i => !i.complete) && Date.now() - t < 10000) "
                                "await new Promise(r => setTimeout(r, 100)); })()")
            shots = []
            for i in range(pages):
                r = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 88, "captureBeyondViewport": True,
                                                              "clip": {"x": 0, "y": i * height, "width": width, "height": height, "scale": 1}},
                                   session=s, timeout=30)
                shots.append(base64.b64decode(r["data"]))
            pdf = await cdp.send("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True, "marginTop": 0, "marginBottom": 0,
                                                     "marginLeft": 0, "marginRight": 0}, session=s, timeout=60)
            return base64.b64decode(pdf["data"]), shots
        finally:
            self._sealed.discard(s)
            self._root.pop(s, None)
            self._attached.pop(target, None)
            try:
                if target:
                    await cdp.send("Target.closeTarget", {"targetId": target})
                await cdp.send("Target.disposeBrowserContext", {"browserContextId": ctx})
            except (CDPError, ConnectionError, TimeoutError):
                pass
            self._sealed_frames.discard(target)
            self._sealed_frames.discard(frame)


async def _exited(proc: subprocess.Popen, seconds: float) -> bool:
    """Waits (without blocking a thread, so it can be cancelled) for the process to end."""
    for _ in range(int(seconds * 10)):
        if proc.poll() is not None:
            return True
        await asyncio.sleep(0.1)
    return proc.poll() is not None


def _named(host: str) -> bool:
    """A domain name (amazon.in), not an IP address or a single label (localhost)."""
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return "." in host


def _origin_ok(origin: str) -> bool:
    """scheme://host[:port] with a real host: Chrome takes a malformed origin (http://www.127.0.0.1) as every site."""
    u = urlsplit(origin)
    host = u.hostname or ""
    if u.scheme not in ("http", "https") or not host or u.path not in ("", "/") or u.query or u.fragment:
        return False
    return host == "localhost" or not host.startswith("www.") or _named(host[4:])


def upi_link(url: str) -> str | None:
    """A UPI app link as upi://…: as it is, or from the Android intent:// link that carries one; None otherwise."""
    u = (url or "").strip()
    if u[:6].lower() == "upi://":
        return u
    if u[:9].lower() == "intent://":
        body, _, frag = u[9:].partition("#")
        if re.search(r"(^|;)scheme=upi(;|$)", frag, re.I):
            return "upi://" + body
    return None


def _accept_language() -> str:
    from odie import config
    loc = config.settings.locale or "en-US"
    return f"{loc},{loc.split('-')[0]};q=0.9"
