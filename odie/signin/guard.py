"""The private-turn guard (spec Part 3): once a chat turn has read a page where the user is signed in, anything that
would leave for another site (a web search, a page fetch, another site, a photo search) waits for the user's tap; and
on a signed-in site, a click or submit that may order, pay, book or send always does. These are ADK require_confirmation
predicates, as run_shell's; the cards are written by code (card())."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from odie.agent import turn
from odie.agent.context import session_id_of
from odie.signin import sites, state

CONSEQUENTIAL = re.compile(r"\b(buy|place (your )?order|pay|proceed to pay(ment)?|book|reserve|confirm|check ?out|send|post|"
                           r"delete|remove|cancel order|subscribe|transfer|donate|submit|apply|claim|redeem)\b", re.I)
CHECKOUT = re.compile(r"pay|checkout|upi|order|book|confirm", re.I)
LAST_URL: dict[str, str] = {}   # tab -> the page it showed last (a click's site)
LAST_SHOT: dict[str, str] = {}  # tab -> that page's screenshot (media id), for the card
READ: dict[str, list[str]] = {}  # tab -> the signed-in pages it read, newest last: a tracker's page comes from here
READ_KEEP = 20


def note_read(tab: str, url: str) -> None:
    got = [u for u in READ.get(tab, []) if u != url]
    READ[tab] = (got + [url])[-READ_KEEP:]
WHY_LEAVE = "Odie read your signed-in {sites} in this chat; this would reach another site, and could carry what it read."
PRIVATE_KEY = "browser.private."  # + a chat's session id: the signed-in sites it has read (their text is in its context)
ALLOWED_KEY = "browser.allowed."  # + a chat's session id: the other sites the user okayed in it (a tap, or named)
WHY_ACT = "On a site you're signed in to, this may order, pay, book or send."
WHY_FOREIGN = "Odie read your signed-in {sites} in this chat, and this page is another site: what's clicked or typed here reaches it."


def remember(store, session_id: str, site: str) -> None:
    """This chat read a signed-in page: the rest of it is private (the page's text stays in the model's context)."""
    if store is None or not session_id or not site:
        return
    got = private_of(store, session_id)
    if site not in got:
        store.set_setting(PRIVATE_KEY + session_id, sorted(got | {site}))


def private_of(store, session_id: str) -> set:
    """The signed-in sites this chat has read. Example: read amazon.in orders earlier -> {"amazon.in"}; none -> set()."""
    if store is None or not session_id:
        return set()
    saved = store.get_setting(PRIVATE_KEY + session_id)
    if not saved:
        return set()
    return set(saved)


def allow(store, session_id: str, site: str) -> None:
    """The user okayed another site in this private chat: its pages and clicks stop asking for the rest of it."""
    if store is None or not session_id or not site:
        return
    got = allowed_of(store, session_id)
    if site not in got:
        store.set_setting(ALLOWED_KEY + session_id, sorted(got | {site}))


def allowed_of(store, session_id: str) -> set:
    """The other sites the user okayed in this chat. Example: tapped Approve to open flipkart.com -> {"flipkart.com"}."""
    if store is None or not session_id:
        return set()
    saved = store.get_setting(ALLOWED_KEY + session_id)
    if not saved:
        return set()
    return set(saved)


def forget_all(store) -> None:
    for key in (PRIVATE_KEY, ALLOWED_KEY):
        store.execute("delete from settings where key like ?", (key + "%",))  # the keys have no LIKE wildcards


_URL = re.compile(r"https?://[^\s<>\"'`]+", re.I)
_DOMAIN = re.compile(r"(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?![\w-])", re.I)


def _typed_urls() -> list[str]:
    return [u.rstrip(".,;:!?)]}") for u in _URL.findall(turn.USER_TEXT.get() or "")]


def named_sites() -> set:
    """The sites the user typed in this chat turn's own words, as a link or a domain ("linkedin.com"): a page can't
    write those words, so opening them is what the user asked for. A bare name ("LinkedIn") names none: lookalikes."""
    said = turn.USER_TEXT.get() or ""
    found = {sites.site_of(u) for u in _typed_urls()} | {sites.site_of(d) for d in _DOMAIN.findall(_URL.sub(" ", said))}
    return {s for s in found if s}


def _same_address(a: str) -> str:
    u = urlsplit(a.strip())
    return f"{(u.hostname or '').lower()}{u.path.rstrip('/')}?{u.query}"


def typed_address(url: str) -> bool:
    """This exact address is one the user typed in this chat turn."""
    return any(_same_address(url) == _same_address(u) for u in _typed_urls())


def _free(store, tab: str) -> set:
    """Where a private chat may go without a tap: its signed-in sites, the ones the user okayed, the ones just named."""
    return turn.private_sites() | allowed_of(store, tab) | named_sites()


def _on(store) -> bool:
    """Is signed-in browsing switched on in Settings? With no store (some tests, some background paths) it counts as off.
    Example: the user ticked "I accept the risk" -> True; never turned on, or store=None -> False."""
    if store is None:
        return False
    return state.is_on(store)


def tab_of(tool_context) -> str:
    """Which browser tab a tool call belongs to: each chat has its own tab, named by the chat's session id.
    Example: a call inside chat "abc123" -> "abc123"; a call with no session (tool_context=None) -> "chat"."""
    session_id = session_id_of(tool_context)
    if not session_id:
        return "chat"
    return session_id


# The *_needs_tap predicates below answer one question each: should this tool call wait for the user's tap?
# "Private chat" means: in this chat turn Odie has read a page where the user is signed in (turn.private_sites()).


def query_needs_tap(store) -> bool:
    """A web search (or anything that sends words out) asks only in a private chat, with signed-in browsing on.
    Example: the chat read your amazon.in orders, then web_search("kettle reviews") -> True (the card);
    a chat that read no signed-in page -> False; signed-in browsing off -> False."""
    if not _on(store):
        return False
    chat_is_private = bool(turn.private_sites())
    return chat_is_private


def url_needs_tap(store, url: str, tab: str = "") -> bool:
    """Opening an address asks in a private chat, unless its site is one the chat may go to freely (_free).
    Example: the chat read amazon.in, then browser_open("https://www.amazon.in/orders") -> False (same site);
    browser_open("https://evil.example/") -> True; any address in a chat that read no signed-in page -> False."""
    if not _on(store):
        return False
    chat_is_private = bool(turn.private_sites())
    if not chat_is_private:
        return False
    site = sites.site_of(url)
    return site not in _free(store, tab)


def fetch_needs_tap(store, url: str) -> bool:
    """A page fetch may go through a fetch service, which sees the address: only the exact one the user typed is free.
    Example: in a private chat, the user typed "summarise https://news.example/a" -> web_fetch of that address: False;
    web_fetch("https://news.example/b") -> True, even though it's the same site."""
    if not query_needs_tap(store):
        return False
    user_typed_it = typed_address(url)
    return not user_typed_it


def foreign(tab: str, store=None) -> bool:
    """In a private chat, the tab is on a site that isn't one of the chat's signed-in, okayed or named sites.
    Example: the chat read amazon.in and the tab now shows evil.example -> True; the tab shows amazon.in -> False;
    a chat that read no signed-in page -> False."""
    chat_is_private = bool(turn.private_sites())
    if not chat_is_private:
        return False
    tab_site = sites.site_of(LAST_URL.get(tab, ""))
    return tab_site not in _free(store, tab)


def click_needs_tap(store, tab: str, words: str) -> bool:
    """A click asks when the tab is on a foreign site (foreign), or when, on a signed-in site, its words sound like
    ordering, paying, booking or sending (CONSEQUENTIAL).
    Example: on signed-in amazon.in, a click on "Place your order" -> True; on "Next page" -> False;
    any click while the tab is on a foreign site in a private chat -> True."""
    if not _on(store):
        return False
    if foreign(tab, store):
        return True  # what's clicked on another site reaches it
    on_signed_in_site = sites.is_signed_in(store, LAST_URL.get(tab, ""))
    if not on_signed_in_site:
        return False
    sounds_consequential = bool(CONSEQUENTIAL.search(words or ""))
    return sounds_consequential


def type_needs_tap(store, tab: str, field: str, submit: bool) -> bool:
    """Typing asks when the tab is on a foreign site (it sees every key), or when, on a signed-in site, the text is
    submitted and either the field sounds consequential or the page is a checkout one (CHECKOUT, on its path).
    Example: on signed-in amazon.in/checkout, typing a coupon with submit=True -> True; the same with submit=False -> False;
    typing a search on amazon.in/s with submit=True into the "Search" field -> False."""
    if not _on(store):
        return False
    if foreign(tab, store):
        return True  # a page on another site sees every key typed into it
    if not submit:
        return False  # nothing is sent until the text is submitted
    url = LAST_URL.get(tab, "")
    if not sites.is_signed_in(store, url):
        return False
    field_sounds_consequential = bool(CONSEQUENTIAL.search(field or ""))
    page_is_checkout = bool(CHECKOUT.search(urlsplit(url).path))
    return field_sounds_consequential or page_is_checkout


def fence_for(tab: str, opening: str | None = None, store=None) -> set | None:
    """Where a browser step in a private chat may take the tab: the signed-in, okayed and named sites, plus the page
    it's on, or the address being opened (browser_open asked first when that's another site). None outside one.
    Example: a chat that read amazon.in, its tab on amazon.in -> {"amazon.in"} (plus any okayed or named sites);
    the same chat opening "https://flipkart.com" after the tap -> {"amazon.in", "flipkart.com"}; a chat that read no
    signed-in page -> None (no fence)."""
    chat_is_private = bool(turn.private_sites())
    if not chat_is_private:
        return None
    if opening is not None:
        address = opening
    else:
        address = LAST_URL.get(tab, "")
    here = sites.site_of(address)
    allowed = _free(store, tab)
    if here:
        allowed = allowed | {here}
    return allowed


def _marked(fn):
    """Tag a predicate as one of this guard's own, so a background check knows it may ask it.
    Outside a chat nothing is private, so these predicates say "no tap" and a background check can still use the web
    and the browser. Any other predicate (say run_shell's) is unknown to background_asks, so the tool counts as asking.
    Example: for_query(store) is marked -> a tracker's web_search runs; run_shell's needs_tap isn't -> refused."""
    fn._signin = True  # background checks ask it instead of refusing the tool (odie.trackers.guard)
    return fn


def background_asks(tool, args: dict, tool_context) -> bool:
    """For a background check's guard: does this tool need the user's tap? The guard's own predicates are asked
    (outside a chat nothing is private, so the web and the browser stay usable); any other predicate means yes.
    Example: web_search (a marked predicate, nothing private) -> False; run_shell (its own predicate) -> True;
    a tool built with require_confirmation=True -> True; one with none -> False."""
    conf = getattr(tool, "_require_confirmation", False)
    if not callable(conf):
        return bool(conf)
    if not getattr(conf, "_signin", False):
        return True
    try:
        return bool(conf(**(args or {}), tool_context=tool_context))
    except Exception:  # noqa: BLE001 (a predicate that can't tell asks)
        return True


# The factories below build the require_confirmation predicate for each guarded tool (ADK calls it with the tool's
# own arguments, plus tool_context). Each is _marked so background checks may ask it.


def for_query(store):
    """web_search, find_images and find_clips: ask in a private chat (query_needs_tap)."""
    def needs_tap(**_) -> bool:
        return query_needs_tap(store)
    return _marked(needs_tap)


def for_url(store):
    """browser_open: ask in a private chat when the address is on another site (url_needs_tap)."""
    def needs_tap(url: str = "", tool_context=None, **_) -> bool:
        return url_needs_tap(store, url, tab_of(tool_context))
    return _marked(needs_tap)


def for_fetch(store):
    """web_fetch: ask in a private chat unless it's the exact address the user typed (fetch_needs_tap)."""
    def needs_tap(url: str = "", **_) -> bool:
        return fetch_needs_tap(store, url)
    return _marked(needs_tap)


def speech_needs_tap(store) -> bool:
    """speak with a cloud voice sends the text out (OpenAI); Odie's local voices send nothing.
    Example: in a private chat with an OpenAI voice -> True; with a local voice -> False; outside one -> False."""
    if not query_needs_tap(store):
        return False
    from odie import voice
    engine_name = voice.get_tts(store)[0]
    engine = voice.ENGINES.get(engine_name, {})
    is_local = engine.get("local", False)
    return not is_local


def for_speech(store):
    """speak: ask in a private chat when the voice is a cloud one (speech_needs_tap)."""
    def needs_tap(**_) -> bool:
        return speech_needs_tap(store)
    return _marked(needs_tap)


def for_click(store):
    """browser_click: ask on a foreign site, or for an order/pay/book/send click on a signed-in one (click_needs_tap)."""
    def needs_tap(text: str = "", tool_context=None, **_) -> bool:
        return click_needs_tap(store, tab_of(tool_context), text)
    return _marked(needs_tap)


def for_type(store):
    """browser_type: ask on a foreign site, or for a consequential submit on a signed-in one (type_needs_tap)."""
    def needs_tap(field: str = "", submit: bool = True, tool_context=None, **_) -> bool:
        return type_needs_tap(store, tab_of(tool_context), field, submit)
    return _marked(needs_tap)


GUARDED = frozenset({"web_search", "web_fetch", "browser_open", "find_images", "find_clips", "browser_click", "browser_type",
                     "speak"})


def card(tool: str, args: dict, tab: str, store) -> tuple[str, dict]:
    """What the tap card says: exactly what would leave, or what would happen."""
    where = ", ".join(sorted(turn.private_sites())) or "a site"
    site = sites.site_of(LAST_URL.get(tab, ""))
    if tool == "web_search":
        return f"Search the web for: {args.get('query', '')}", {"why": WHY_LEAVE.format(sites=where)}
    if tool == "find_images":
        return f"Search for photos of: {args.get('query', '')}", {"why": WHY_LEAVE.format(sites=where)}
    if tool == "find_clips":
        return f"Search for video clips of: {args.get('query', '')}", {"why": WHY_LEAVE.format(sites=where)}
    if tool in ("web_fetch", "browser_open"):
        return f"Open {args.get('url', '')}", {"why": WHY_LEAVE.format(sites=where)}
    if tool == "speak":
        return f"Read aloud with OpenAI's voice: {args.get('script', '')[:300]}", {"why": WHY_LEAVE.format(sites=where)}
    why = WHY_FOREIGN.format(sites=where) if foreign(tab, store) else WHY_ACT
    if tool == "browser_click":
        return f'Click "{args.get("text", "")}" on {site}', {"why": why, "site": site, "shot": LAST_SHOT.get(tab)}
    submit = " and submit" if args.get("submit", True) else ""
    return (f'Type "{str(args.get("text", ""))[:300]}" into "{args.get("field", "")}"{submit} on {site}',  # what would leave
            {"why": why, "site": site, "shot": LAST_SHOT.get(tab)})
