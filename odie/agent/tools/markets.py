"""Market prices (index or stock history) from Yahoo Finance's public chart endpoint, returned as a short summary plus a
ready-to-paste ```odie-blocks block (chart, plus Analyze for a US stock), so the model doesn't have to write numbers itself. Only the symbol leaves the mini."""
from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from google.adk.tools import FunctionTool

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh) Odie/1.0"}
# Yahoo's ranges (the periods it accepts) and the bar size for each, shortest first.
RANGES = {"1d": "5m", "5d": "1d", "1mo": "1d", "3mo": "1d", "6mo": "1d", "1y": "1wk", "2y": "1wk", "5y": "1mo",
          "10y": "1mo"}
DAYS = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827, "10y": 3653}
_PERIOD = re.compile(r"^\s*(\d+)\s*(d|days?|w|wk|weeks?|m|mo|months?|y|yr|years?)\s*$", re.IGNORECASE)
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}
ALIASES = {"nifty": "^NSEI", "nifty 50": "^NSEI", "nifty50": "^NSEI", "sensex": "^BSESN", "bank nifty": "^NSEBANK",
           "banknifty": "^NSEBANK", "nifty bank": "^NSEBANK", "nifty it": "^CNXIT", "s&p 500": "^GSPC", "sp500": "^GSPC",
           "nasdaq": "^IXIC", "dow": "^DJI", "gold": "GC=F", "usdinr": "INR=X", "usd inr": "INR=X", "bitcoin": "BTC-USD"}


def can_analyze(sym: str, kind: str | None = None) -> bool:
    """A single company on any exchange has quarterly results to analyse; an index, currency, commodity, crypto or fund
    doesn't. kind: Yahoo's instrumentType when it gives one."""
    if kind:
        return kind.upper() == "EQUITY"
    return bool(sym) and not (sym.startswith("^") or sym.endswith(("=X", "=F", "-USD")))


def resolve_alias(name: str) -> str | None:
    n = " ".join((name or "").lower().split())
    if n in ALIASES:
        return ALIASES[n]
    s = (name or "").strip()
    return s if (s.startswith("^") or "." in s or "=" in s or "-" in s) and " " not in s else None


async def _search(c: httpx.AsyncClient, name: str) -> str | None:
    r = await c.get(SEARCH, params={"q": name, "quotesCount": 6, "newsCount": 0}, headers=HEADERS)
    r.raise_for_status()
    quotes = r.json().get("quotes") or []
    indian = [q for q in quotes if str(q.get("symbol", "")).endswith((".NS", ".BO"))]
    best = (indian or quotes)[:1]
    return best[0]["symbol"] if best else None


def period_for(asked: str) -> str:
    """Picks the Yahoo range to fetch for the period the model asked for: the asked one when Yahoo has it, else the
    shortest range that covers it, so a longer ask never comes back shorter. Anything unreadable gets 1mo. Worked
    examples: "1y" -> "1y";  "3y" -> "5y" (Yahoo has no 3y);  "2 years" -> "2y";  "4mo" -> "6mo";  "20y" -> "10y" (the
    longest);  "last week" -> "1mo" (unreadable; the docstring asks for 5d)."""
    if asked in RANGES:
        return asked
    match = _PERIOD.match(asked or "")
    if not match:
        return "1mo"
    days = int(match.group(1)) * _UNIT_DAYS[match.group(2)[0].lower()]
    for period, covers in DAYS.items():
        if covers >= days:
            return period
    return "10y"


async def history(symbol: str, period: str = "5d", transport: httpx.AsyncBaseTransport | None = None) -> str:
    period = period_for(period)
    try:
        async with httpx.AsyncClient(timeout=15, transport=transport) as c:
            sym = resolve_alias(symbol) or await _search(c, symbol)
            if not sym:
                return f"Couldn't find a market symbol for '{symbol}'."
            r = await c.get(CHART.format(sym=sym), params={"range": period, "interval": RANGES[period]}, headers=HEADERS)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
        return f"Couldn't get prices for '{symbol}' just now ({type(e).__name__}). Try again in a minute."
    meta = res.get("meta", {})
    tz = ZoneInfo(meta.get("exchangeTimezoneName") or "Asia/Kolkata")
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    points = [(t, v) for t, v in zip(res.get("timestamp") or [], closes) if v is not None]
    if len(points) < 2:
        return f"Not enough price data for {sym} over {period}."
    fmt = "%H:%M" if period == "1d" else "%-d %b" if period in ("5d", "1mo", "3mo") else "%b %Y"
    x = [datetime.fromtimestamp(t, tz).strftime(fmt) for t, _ in points]
    y = [round(v, 2) for _, v in points]
    first, last = y[0], y[-1]
    change = (last - first) / first * 100
    name = meta.get("shortName") or meta.get("longName") or sym
    cur = "pts" if sym.startswith("^") else (meta.get("currency") or "")  # an index is points, not rupees
    chart = {"type": "chart", "kind": "line", "title": f"{name} · {period}", "x": x, "series": [{"name": "Close", "data": y}],
             "unit": cur, "source": "Yahoo Finance"}
    blocks = [chart]
    if can_analyze(sym, meta.get("instrumentType")):
        blocks.append({"type": "actions", "items": [{"label": "Analyze", "run": f"Analyze {name} ({sym}): last 4 quarters"}]})
    return (f"{name} ({sym}) over {period}: {first:,.2f} on {x[0]} to {last:,.2f} on {x[-1]} ({change:+.2f}%). "
            f"High {max(y):,.2f}, low {min(y):,.2f} ({'points' if cur == 'pts' else cur}). Source: Yahoo Finance (may be delayed).\n"
            "To show the chart, put this block in your reply exactly as it is:\n"
            f"```odie-blocks\n{json.dumps(blocks, ensure_ascii=False)}\n```")


def make_market_tools(transport: httpx.AsyncBaseTransport | None = None) -> list[FunctionTool]:
    async def market_history(symbol: str, period: str = "5d") -> str:
        """Price history for a stock, index, currency or commodity, with a chart. symbol: a name or ticker, e.g. NIFTY,
        SENSEX, BANK NIFTY, RELIANCE, TCS.NS, AAPL, gold, USDINR. period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y or 10y
        ("last week" = 5d; any other, like 3y, gets the next longer one).
        Returns a summary and a ```odie-blocks block to paste into the reply unchanged so the app draws the chart."""
        return await history(symbol, period, transport=transport)
    return [FunctionTool(market_history)]
