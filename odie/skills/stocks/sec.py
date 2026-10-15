"""US company results from SEC filings (XBRL companyfacts): quarterly series, a missing Q4 derived from the
annual figure, YTD cash flow turned into quarters. Pure functions first; fetching lives below."""
import json
import logging
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from odie import config
from odie.secrets import load_secret

REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
COST = ["CostOfRevenue", "CostOfGoodsAndServicesSold"]


def _rows(facts: dict, tag: str) -> list[dict]:
    units = facts.get(tag, {}).get("units", {})
    return units.get("USD") or units.get("USD/shares") or (next(iter(units.values())) if units else [])


def _day(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def cal_label(end_iso: str) -> str:
    """The calendar quarter a three-month period mostly falls in: the one holding its middle, about 45 days
    before it ends. That copes with fiscal quarters ending late in a month (NVIDIA's ends late July = Q2) or a
    few days into the next (52/53-week years)."""
    d = _day(end_iso) - timedelta(days=45)
    return f"CY{d.year}Q{(d.month - 1) // 3 + 1}"


def _quarters_of(rows: list[dict]) -> dict[str, float]:
    """Three-month values keyed by calendar quarter; a quarter that only exists inside the annual report
    (Q4 of the fiscal year, whatever month it ends) is the annual figure minus the other three."""
    dated = [r for r in rows if r.get("start") and r.get("end") and isinstance(r.get("val"), (int, float))]
    span = {id(r): (_day(r["end"]) - _day(r["start"])).days for r in dated}
    qrows = [r for r in dated if 80 <= span[id(r)] <= 100]
    q: dict[str, float] = {}
    for r in qrows:
        q[cal_label(r["end"])] = r["val"]
    for yr in (r for r in dated if 350 <= span[id(r)] <= 380):
        inside = {cal_label(r["end"]): r["val"] for r in qrows if r["start"] >= yr["start"] and r["end"] <= yr["end"]}
        last = cal_label(yr["end"])
        if len(inside) == 3 and last not in inside:
            q[last] = yr["val"] - sum(inside.values())
    return dict(sorted(q.items()))


def quarterly(facts: dict, tags: list[str]) -> dict[str, float]:
    """Quarterly values keyed CY####Q#, oldest first, from whichever tag has the newest data (companies switch
    tags over the years; ties go to the list order)."""
    best: dict[str, float] = {}
    for tag in tags:
        q = _quarters_of(_rows(facts, tag))
        if q and (not best or max(q) > max(best)):
            best = q
    return best


def _label_back(label: str, n: int) -> str:
    y, qn = int(label[2:6]), int(label[7])
    i = y * 4 + (qn - 1) - n
    return f"CY{i // 4}Q{i % 4 + 1}"


def _quarter_end(label: str) -> date:
    y, qn = int(label[2:6]), int(label[7])
    return date(y, 12, 31) if qn == 4 else date(y, 3 * qn + 1, 1) - timedelta(days=1)


def instants(facts: dict, tag: str) -> dict[str, float]:
    """Balance-sheet values at quarter ends (frames like CY2026Q2I), keyed without the I."""
    return dict(sorted((r["frame"][:-1], r["val"]) for r in _rows(facts, tag) if (r.get("frame") or "").endswith("I")))


def quarterly_cash_flow(facts: dict, tag: str) -> dict[str, float]:
    """Cash flow is filed year-to-date; a quarter is its YTD minus the previous YTD of the same fiscal year."""
    rows = [r for r in _rows(facts, tag) if r.get("form") in ("10-Q", "10-K") and r.get("start") and r.get("end")
            and (r.get("form") == "10-Q" or r.get("fp") == "FY")]
    by_year: dict[tuple, dict[str, tuple[str, float]]] = {}
    for r in rows:
        by_year.setdefault((r["fy"], r["start"]), {})[r["fp"]] = (r["end"], r["val"])
    out: dict[str, float] = {}
    for parts in by_year.values():
        prev = 0.0
        for fp in ("Q1", "Q2", "Q3", "FY"):  # the annual report's year total gives Q4
            if fp not in parts:
                break
            if fp == "FY" and "Q3" not in parts:
                break
            end, ytd = parts[fp]
            out[cal_label(end)] = ytd - prev
            prev = ytd
    return dict(sorted(out.items()))


def financials(facts: dict, today: date | None = None) -> dict:
    """Five consecutive quarters ending at the latest one (4 to show + a year-ago one for YoY), every series
    aligned to them, gaps and missing series named, and whether the newest figures are too old to analyse."""
    rev = quarterly(facts, REVENUE)
    gross = quarterly(facts, ["GrossProfit"])
    if rev and (not gross or max(gross) < max(rev)):
        cost = quarterly(facts, COST)
        derived = {k: rev[k] - cost[k] for k in rev if k in cost}
        if derived and (not gross or max(derived) > max(gross)):
            gross = derived
    series = {"revenue": rev, "gross": gross, "operating": quarterly(facts, ["OperatingIncomeLoss"]),
              "net": quarterly(facts, ["NetIncomeLoss"]), "eps": quarterly(facts, ["EarningsPerShareDiluted"]),
              "cash": instants(facts, "CashAndCashEquivalentsAtCarryingValue"),
              "ocf": quarterly_cash_flow(facts, "NetCashProvidedByUsedInOperatingActivities")}
    pool = rev or {k: 0 for v in series.values() for k in v}
    latest = max(pool) if pool else None
    quarters = [_label_back(latest, n) for n in range(4, -1, -1)] if latest else []
    names = {"revenue": "revenue", "gross": "gross profit", "operating": "operating income", "net": "net income",
             "eps": "EPS", "cash": "cash", "ocf": "operating cash flow"}
    out = {"quarters": quarters, "missing": [names[k] for k, v in series.items() if not any(q in v for q in quarters)]}
    for k, v in series.items():
        out[k] = [v.get(q) for q in quarters]
    out["gaps"] = [f"Q{q[7]} {q[2:6]}" for q, r in zip(quarters, out["revenue"]) if r is None and rev]
    out["stale"] = bool(latest) and (today or date.today()) - _quarter_end(latest) > timedelta(days=240)
    return out


NOT_US = "Not a US-listed company (or not found in SEC filings). I can analyse US-listed companies for now."
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _ua() -> dict:
    return {"User-Agent": f"Odie personal assistant ({load_secret('ODIE_CONTACT_EMAIL') or 'contact not set'})"}


async def _cached_json(client: httpx.AsyncClient, url: str, path: Path, max_age: float):
    """JSON from the cache if fresh and readable, else from SEC. Only a response that parses is cached, and it's
    written atomically, so a crash mid-write can't leave a file that breaks every later call."""
    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass  # corrupt: treat as a miss
    r = await client.get(url)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()  # ValueError for a non-JSON body (a maintenance page): caught by the caller, nothing cached
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(r.text)
    os.replace(tmp, path)
    return data


ALIASES = {"google": "GOOGL", "alphabet": "GOOGL", "facebook": "META", "disney": "DIS", "coca cola": "KO", "coke": "KO",
           "amazon": "AMZN", "berkshire": "BRK-B", "jp morgan": "JPM", "jpmorgan": "JPM"}
_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "plc", "ltd", "limited", "holdings", "holding",
             "group", "the", "sa", "nv", "ag", "llc", "lp", "class", "a", "b", "com"}


def norm_name(name: str) -> str:
    """'Walt Disney Company (The)' -> 'walt disney'; 'Amazon.com, Inc.' -> 'amazon'; 'COCA COLA CO' -> 'coca cola'."""
    words = re.sub(r"[^a-z0-9]+", " ", name.lower()).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


async def resolve_cik(company: str, client: httpx.AsyncClient, cache_dir: Path):
    """(cik10, ticker, title) for one clear match, a list of them when the name could mean several companies,
    or None. Order: a ticker in brackets or an exact upper-case ticker, an alias, the exact name, then names
    starting with it."""
    data = await _cached_json(client, TICKERS_URL, cache_dir / "company_tickers.json", 86400) or {}
    rows = list(data.values())
    by_ticker = {r["ticker"]: r for r in rows}
    hit = lambda r: (f"{int(r['cik_str']):010d}", r["ticker"], r["title"])  # noqa: E731
    raw = company.strip()
    m = re.search(r"\(([A-Z][A-Z.\-]{0,5})\)", raw)
    for t in ([m.group(1)] if m else []) + ([raw] if raw.isupper() and " " not in raw else []):
        if t in by_ticker:
            return hit(by_ticker[t])
    q = norm_name(re.sub(r"\([^)]*\)", " ", raw))
    if not q:
        return None
    if q in ALIASES and ALIASES[q] in by_ticker:
        return hit(by_ticker[ALIASES[q]])
    exact = [r for r in rows if norm_name(r["title"]) == q]
    if exact:
        return hit(exact[0])  # share classes of one company file under one CIK, so the first is fine
    starts = {r["cik_str"]: r for r in rows if norm_name(r["title"]).startswith(q + " ")}
    if len(starts) == 1:
        return hit(next(iter(starts.values())))
    if starts:
        return [hit(r) for r in list(starts.values())[:6]]
    return hit(by_ticker[raw.upper()]) if raw.upper() in by_ticker and len(raw) <= 5 else None


def display_name(entity: str, title: str) -> str:
    """SEC's entity names are often all caps; use whichever of the two reads like a name."""
    for n in (entity, title):
        if n and not n.isupper():
            return n
    return (entity or title).title()


def _label(frame: str) -> str:  # CY2026Q2 -> Q2 2026
    return f"{frame[6:]} {frame[2:6]}"


def _m(v):
    return None if v is None else round(v / 1e6, 1)


def _pct(a, b):
    return None if a is None or b in (None, 0) else round(a / b * 100, 1)


def _chg(cur, prev):
    return None if cur is None or prev in (None, 0) else round((cur - prev) / abs(prev) * 100, 1)


def board(name: str, ticker: str, cik: str, f: dict) -> list[dict]:
    q4 = f["quarters"][-4:]
    rev, net, op, gross, cash = (f[k][-4:] for k in ("revenue", "net", "operating", "gross", "cash"))
    nm = [_pct(n, r) for n, r in zip(net, rev)]
    om = [_pct(o, r) for o, r in zip(op, rev)]
    gm = [_pct(g, r) for g, r in zip(gross, rev)]
    x = [_label(q) for q in q4]
    kpis = [{"label": "Revenue", "value": _m(rev[-1]), "unit": "$M", "change": _chg(rev[-1], rev[-2]), "change_unit": "%"}]
    if nm[-1] is not None:
        kpis.append({"label": "Net margin", "value": nm[-1], "unit": "%",
                     "change": None if nm[-2] is None else round(nm[-1] - nm[-2], 1), "change_unit": "pt"})
    if om[-1] is not None:
        kpis.append({"label": "Operating margin", "value": om[-1], "unit": "%",
                     "change": None if om[-2] is None else round(om[-1] - om[-2], 1), "change_unit": "pt"})
    if cash[-1] is not None:
        kpis.append({"label": "Cash", "value": _m(cash[-1]), "unit": "$M", "change": _chg(cash[-1], cash[-2]), "change_unit": "%"})
    blocks: list[dict] = [{"type": "kpis", "items": kpis}]
    blocks.append({"type": "chart", "kind": "bar", "title": "Revenue vs net income", "x": x, "unit": "$M",
                   "series": [{"name": "Revenue", "data": [_m(v) for v in rev]}, {"name": "Net income", "data": [_m(v) for v in net]}]})
    margins = [s for s in ({"name": "Gross", "data": gm}, {"name": "Operating", "data": om}, {"name": "Net", "data": nm})
               if any(v is not None for v in s["data"])]
    if margins:
        blocks.append({"type": "chart", "kind": "line", "title": "Margins %", "x": x, "unit": "%", "series": margins})
    if any(v is not None for v in cash):
        blocks.append({"type": "chart", "kind": "bar", "title": "Cash at quarter end", "x": x, "unit": "$M",
                       "series": [{"name": "Cash", "data": [_m(v) for v in cash]}]})
    blocks.append({"type": "source", "text": f"SEC filings (10-Q / 10-K) · {ticker} · latest quarter {x[-1]}",
                   "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-&dateb=&owner=include&count=40"})
    return blocks


def table(name: str, ticker: str, f: dict) -> str:
    q = f["quarters"]
    rows = [("Revenue $M", f["revenue"], _m), ("Gross profit $M", f["gross"], _m), ("Operating income $M", f["operating"], _m),
            ("Net income $M", f["net"], _m), ("Diluted EPS $", f["eps"], lambda v: v if v is None else round(v, 2)),
            ("Cash $M", f["cash"], _m), ("Operating cash flow $M", f["ocf"], _m)]
    lines = [f"{name} ({ticker}) results from SEC filings, quarters {', '.join(_label(x) for x in q)}:"]
    for label, vals, fmt in rows:
        if any(v is not None for v in vals):
            lines.append(f"- {label}: " + ", ".join("n/a" if v is None else str(fmt(v)) for v in vals))
    for label, num in (("Gross margin %", f["gross"]), ("Operating margin %", f["operating"]), ("Net margin %", f["net"])):
        m = [_pct(a, b) for a, b in zip(num, f["revenue"])]
        if any(v is not None for v in m):
            lines.append(f"- {label}: " + ", ".join("n/a" if v is None else str(v) for v in m))
    r = f["revenue"]
    if len(q) == 5 and r[0] and r[-1]:
        lines.append(f"- Revenue growth latest quarter: QoQ {_chg(r[-1], r[-2])}%, YoY {_chg(r[-1], r[0])}%")
    if f.get("gaps"):
        lines.append(f"- No figures for: {', '.join(f['gaps'])} (not in the filings; don't estimate them)")
    if f["missing"]:
        lines.append(f"- Not reported in the filings: {', '.join(f['missing'])}")
    return "\n".join(lines)


async def analyze_company(company: str, transport: httpx.AsyncBaseTransport | None = None, cache_dir: Path | None = None) -> str:
    """The stocks skill's tool body. Never raises: every failure becomes one plain sentence for the model."""
    try:
        return await _analyze(company, transport, cache_dir or (config.settings.data_dir / "sec"))
    except (httpx.HTTPError, ValueError):
        return "Couldn't reach SEC filings just now. Try again in a minute."
    except Exception:  # noqa: BLE001
        logging.getLogger("odie").warning("quarterly_financials failed for %r", company, exc_info=True)
        return "Something went wrong reading the SEC filings for that company. Say so plainly and don't guess numbers."


async def _analyze(company: str, transport: httpx.AsyncBaseTransport | None, cache_dir: Path) -> str:
    async with httpx.AsyncClient(timeout=20, headers=_ua(), transport=transport, follow_redirects=True) as c:
        hit = await resolve_cik(company, c, cache_dir)
        if not hit:
            return NOT_US
        if isinstance(hit, list):
            names = "; ".join(f"{t} ({k})" for _, k, t in hit)
            return f"Several US-listed companies match '{company}': {names}. Ask which one is meant, then call again with its ticker."
        cik, ticker, title = hit
        data = await _cached_json(c, FACTS_URL.format(cik=cik), cache_dir / f"facts_{cik}.json", 12 * 3600)
    if not data or "us-gaap" not in data.get("facts", {}):
        return NOT_US
    f = financials(data["facts"]["us-gaap"])
    name = display_name(data.get("entityName") or "", title)
    if not any(v is not None for v in f["revenue"][-4:]):
        return f"{name} ({ticker}) has no recent quarterly revenue in its SEC filings, so I can't analyse it."
    if f["stale"]:
        return (f"The newest quarterly figures in {name}'s ({ticker}) SEC filings are for {_label(f['quarters'][-1])}, "
                "which is too old to analyse. Say so plainly.")
    return (table(name, ticker, f) + "\n\nPut this block in your reply exactly as it is:\n```odie-blocks\n"
            + json.dumps(board(name, ticker, cik, f), ensure_ascii=False)
            + "\n```\nThen write the analysis in the structure from the stocks skill, using only the numbers above.")
