"""Quarterly results the model read from a web page (any country but the US): check them, then draw the same board
the SEC path draws. The checks catch the usual misreads (a row taken for another, quarters out of order, an old page)
so the model re-reads instead of analysing wrong numbers."""
from __future__ import annotations

import json
from datetime import date, datetime
from urllib.parse import urlparse

from odie.skills.stocks.sec import _chg, _pct

N = 5  # four quarters to show plus the year-ago one for YoY
MAX_AGE_DAYS = 200


def _end(label: str) -> date | None:
    """'Jun 2026' (or 'June 2026') -> the quarter's month, as its first day."""
    for f in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(label.strip(), f).date()
        except ValueError:
            continue
    return None


def check(quarters: list[str], revenue: list[float], net_profit: list[float], expenses: list[float] | None = None,
          interest: list[float] | None = None, operating_profit: list[float] | None = None, eps: list[float] | None = None,
          source_url: str = "", filings_url: str = "", today: date | None = None) -> str | None:
    """None if the numbers hang together, else one sentence on what's wrong."""
    if len(quarters) != N:
        return f"Give exactly {N} quarters (the latest 4 and the one a year before the latest), oldest first; got {len(quarters)}."
    ends = [_end(q) for q in quarters]
    if None in ends:
        bad = quarters[ends.index(None)]
        return f"Quarter label '{bad}' isn't like 'Jun 2026'; use the month the quarter ends and the year."
    months = [e.year * 12 + e.month for e in ends]
    if any(b - a != 3 for a, b in zip(months, months[1:])):
        return "The quarters must be consecutive (3 months apart), oldest first: " + ", ".join(quarters) + "."
    for name, vals in (("revenue", revenue), ("net_profit", net_profit), ("expenses", expenses), ("interest", interest),
                       ("operating_profit", operating_profit), ("eps", eps)):
        if vals is not None and len(vals) != N:
            return f"{name} has {len(vals)} values but there are {N} quarters; one value per quarter, same order."
    if expenses is not None and operating_profit is not None:
        for i, q in enumerate(quarters):
            calc = revenue[i] - expenses[i] - (interest[i] if interest else 0)
            if abs(calc - operating_profit[i]) > max(abs(revenue[i]) * 0.01, 2):
                return (f"For {q}, revenue − expenses{' − interest' if interest else ''} = {calc:,.0f}, but operating profit is "
                        f"{operating_profit[i]:,.0f}. A row is probably mislabelled; re-read the table's row order.")
    for i, q in enumerate(quarters):
        if revenue[i] <= 0 or abs(net_profit[i]) >= revenue[i]:
            return f"For {q}, net profit {net_profit[i]:,.0f} isn't smaller than revenue {revenue[i]:,.0f}; check which row is revenue."
        if eps is not None and eps[i] * net_profit[i] < 0:
            return f"For {q}, EPS {eps[i]} and net profit {net_profit[i]:,.0f} have opposite signs; check the EPS row."
    age = ((today or date.today()) - ends[-1]).days
    if age > MAX_AGE_DAYS:
        return f"The latest quarter, {quarters[-1]}, is too old ({age} days); this is probably an old page. Find the current results."
    return None


def _site(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host or "the company's published results"


def build_report(company: str, ticker: str, currency: str, scale: str, quarters: list[str], revenue: list[float],
                 net_profit: list[float], expenses: list[float] | None = None, interest: list[float] | None = None,
                 operating_profit: list[float] | None = None, eps: list[float] | None = None, source_url: str = "",
                 filings_url: str = "", today: date | None = None) -> str:
    problem = check(quarters, revenue, net_profit, expenses, interest, operating_profit, eps, today=today)
    if problem:
        return problem
    unit = f"{currency}{scale}"
    x = quarters[1:]
    rev, net = revenue[1:], net_profit[1:]
    bank = interest is not None  # a bank's financing profit isn't an operating margin; judge it on net margin
    om = [_pct(o, r) for o, r in zip(operating_profit[1:], rev)] if operating_profit and not bank else None
    nm = [_pct(n, r) for n, r in zip(net, rev)]
    kpis = [{"label": "Revenue", "value": rev[-1], "unit": unit, "change": _chg(rev[-1], rev[-2]), "change_unit": "%"}]
    if om:
        kpis.append({"label": "Operating margin", "value": om[-1], "unit": "%", "change": round(om[-1] - om[-2], 1), "change_unit": "pt"})
    kpis.append({"label": "Net margin", "value": nm[-1], "unit": "%", "change": round(nm[-1] - nm[-2], 1), "change_unit": "pt"})
    if eps:
        kpis.append({"label": "EPS", "value": round(eps[-1], 2), "unit": currency, "change": _chg(eps[-1], eps[-2]), "change_unit": "%"})
    blocks: list[dict] = [{"type": "kpis", "items": kpis},
                          {"type": "chart", "kind": "bar", "title": "Revenue vs net profit", "x": x, "unit": unit,
                           "series": [{"name": "Revenue", "data": rev}, {"name": "Net profit", "data": net}]}]
    margins = [s for s in ({"name": "Operating", "data": om}, {"name": "Net", "data": nm}) if s["data"]]
    blocks.append({"type": "chart", "kind": "line", "title": "Margins %", "x": x, "unit": "%", "series": margins})
    blocks.append({"type": "source", "text": f"{_site(source_url)} · {ticker} · latest quarter {x[-1]}", **({"url": source_url} if source_url else {})})

    u = f"{currency} {scale}"
    lines = [f"{company} ({ticker}) quarterly results ({u}) from {_site(source_url)}, quarters {', '.join(quarters)}:"]
    for label, vals in (("Revenue", revenue), ("Expenses", expenses), ("Interest", interest),
                        ("Financing profit" if bank else "Operating profit", operating_profit),
                        ("Net profit", net_profit), (f"EPS {currency}", eps)):
        if vals:
            lines.append(f"- {label}: " + ", ".join(f"{v:,}" for v in vals))
    if operating_profit and not bank:
        lines.append("- Operating margin %: " + ", ".join(str(_pct(o, r)) for o, r in zip(operating_profit, revenue)))
    lines.append("- Net margin %: " + ", ".join(str(_pct(n, r)) for n, r in zip(net_profit, revenue)))
    lines.append(f"- Revenue growth latest quarter: QoQ {_chg(revenue[-1], revenue[-2])}%, YoY {_chg(revenue[-1], revenue[0])}%")
    lines.append(f"- Net profit growth latest quarter: QoQ {_chg(net_profit[-1], net_profit[-2])}%, YoY {_chg(net_profit[-1], net_profit[0])}%")
    lines.append("- Quarterly cash and balance-sheet figures aren't in this source: say so in the Cash section instead of guessing.")
    if bank:
        lines.append("- This is a bank: judge profitability on net margin and net profit growth; financing profit here is "
                     "after provisions and isn't an operating margin, so don't present it as one.")
    if filings_url:
        lines.append(f"- Exchange filings: {filings_url}")
    return ("\n".join(lines) + "\n\nPut this block in your reply exactly as it is:\n```odie-blocks\n"
            + json.dumps(blocks, ensure_ascii=False)
            + "\n```\nThen write the analysis under exactly these bold headings, using only the numbers above: "
            "**Growth**, **Profitability**, **Cash & balance sheet**, **Risks / watch**, **Bottom line**.")
