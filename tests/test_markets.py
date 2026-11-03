import json

import httpx
import pytest

from odie.agent.tools import markets


def _chart_payload():
    return {"chart": {"result": [{"meta": {"symbol": "^NSEI", "currency": "INR", "shortName": "NIFTY 50"},
            "timestamp": [1790208000, 1790294400, 1790553600], "indicators": {"quote": [{"close": [23063.1, None, 22421.9]}]}}]}}


def test_aliases_resolve_without_network():
    assert markets.resolve_alias("nifty") == "^NSEI" and markets.resolve_alias("Sensex") == "^BSESN"
    assert markets.resolve_alias("bank nifty") == "^NSEBANK" and markets.resolve_alias("RELIANCE.NS") == "RELIANCE.NS"
    assert markets.resolve_alias("reliance") is None


async def test_history_returns_summary_and_chart_block():
    def handler(req: httpx.Request):
        assert "%5ENSEI" in str(req.url) or "^NSEI" in str(req.url)
        return httpx.Response(200, json=_chart_payload())
    out = await markets.history("nifty", "5d", transport=httpx.MockTransport(handler))
    assert "NIFTY 50" in out and "-2.78%" in out
    blocks = json.loads(out.split("```odie-blocks\n", 1)[1].split("\n```", 1)[0])
    chart = blocks[0]
    assert chart["type"] == "chart" and chart["kind"] == "line" and chart["series"][0]["data"] == [23063.1, 22421.9]
    assert len(chart["x"]) == 2 and all(b["type"] != "actions" for b in blocks)  # an index: nothing to analyse


async def test_unknown_symbol_is_searched_and_failures_are_plain():
    def handler(req: httpx.Request):
        if "/search" in req.url.path:
            return httpx.Response(200, json={"quotes": [{"symbol": "RELIANCE.NS", "shortname": "RELIANCE"}]})
        return httpx.Response(200, json=_chart_payload())
    assert "```odie-blocks" in await markets.history("reliance", "1mo", transport=httpx.MockTransport(handler))
    boom = httpx.MockTransport(lambda req: httpx.Response(503))
    assert (await markets.history("nifty", "5d", transport=boom)).startswith("Couldn't get prices")


def test_can_analyze_single_companies_on_any_exchange():
    assert all(markets.can_analyze(s) for s in ("QLYS", "AAPL", "RELIANCE.NS", "TCS.BO", "SAP.DE"))
    assert not any(markets.can_analyze(s) for s in ("^NSEI", "INR=X", "GC=F", "BTC-USD"))
    assert markets.can_analyze("TCS.NS", "EQUITY")
    assert not any(markets.can_analyze("NIFTYBEES.NS", k) for k in ("ETF", "MUTUALFUND", "INDEX"))


async def test_us_stock_gets_an_analyze_action():
    payload = {"chart": {"result": [{"meta": {"symbol": "QLYS", "currency": "USD", "shortName": "Qualys, Inc."},
               "timestamp": [1790208000, 1790294400], "indicators": {"quote": [{"close": [140.0, 142.5]}]}}]}}

    def handler(r: httpx.Request) -> httpx.Response:
        if "/search" in r.url.path:
            return httpx.Response(200, json={"quotes": [{"symbol": "QLYS", "shortname": "Qualys"}]})
        return httpx.Response(200, json=payload)
    out = await markets.history("QLYS", "1mo", transport=httpx.MockTransport(handler))
    blocks = json.loads(out.split("```odie-blocks\n", 1)[1].split("\n```", 1)[0])
    assert blocks[-1] == {"type": "actions", "items": [{"label": "Analyze", "run": "Analyze Qualys, Inc. (QLYS): last 4 quarters"}]}


@pytest.mark.parametrize("asked, fetched", [
    ("1y", "1y"), ("5d", "5d"), ("3y", "5y"), ("2 years", "2y"), ("4mo", "6mo"), ("20y", "10y"), ("last week", "1mo"),
])
def test_a_period_yahoo_lacks_gets_the_next_longer_one(asked, fetched):
    assert markets.period_for(asked) == fetched


async def test_three_years_fetches_five_not_one_month():
    asked = []

    def handler(request):
        asked.append(request.url.params.get("range"))
        return httpx.Response(200, json={"chart": {"result": [{"meta": {"shortName": "NIFTY 50"},
                                                              "timestamp": [1, 2], "indicators": {"quote": [{"close": [1.0, 2.0]}]}}]}})

    out = await markets.history("nifty", "3y", transport=httpx.MockTransport(handler))
    assert asked == ["5y"]
    assert "over 5y" in out


def _blocks(out: str) -> list:
    return json.loads(out.split("```odie-blocks\n", 1)[1].split("\n```", 1)[0])


async def test_one_symbol_draws_a_change_line():
    out = await markets.history("nifty", "5d", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_chart_payload())))
    assert _blocks(out)[0]["tone"] == "change"  # green above the first close, orange below


def test_symbols_are_split_on_commas_three_at_most():
    assert markets.symbols_in("TCS, INFY") == ["TCS", "INFY"]
    assert markets.symbols_in("nifty") == ["nifty"]
    assert markets.symbols_in("A, , B, C, D") == ["A", "B", "C"]


def test_trend_points_spread_evenly_keeping_both_ends():
    assert markets.trend_points([1, 2, 3]) == [1, 2, 3]
    thinned = markets.trend_points(list(range(119)), most=60)
    assert len(thinned) == 60 and thinned[0] == 0 and thinned[-1] == 118 and thinned[1] == 2


def test_rebased_series_start_at_zero_on_the_first_symbols_dates():
    x, series = markets.rebased([{"name": "GOOGL", "x": ["1", "2", "3"], "y": [100, 90, 80]},
                                 {"name": "MSFT", "x": ["1", "3"], "y": [200, 210]}])
    assert x == ["1", "2", "3"]
    assert series == [{"name": "GOOGL", "data": [0.0, -10.0, -20.0]}, {"name": "MSFT", "data": [0.0, None, 5.0]}]


async def test_two_symbols_get_a_card_each_and_one_percent_change_chart():
    closes = {"TCS.NS": [3290.0, 3150.0, 3082.0], "INFY.NS": [1520.0, 1600.0, 1670.0]}

    def handler(r: httpx.Request) -> httpx.Response:
        sym = r.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"chart": {"result": [{
            "meta": {"symbol": sym, "currency": "INR", "shortName": sym.split(".")[0], "instrumentType": "EQUITY"},
            "timestamp": [1790208000, 1790294400, 1790380800], "indicators": {"quote": [{"close": closes[sym]}]}}]}})
    out = await markets.history("TCS.NS, INFY.NS", "3mo", transport=httpx.MockTransport(handler))
    assert "TCS (TCS.NS)" in out and "INFY (INFY.NS)" in out  # a summary line each
    cards, chart = _blocks(out)
    assert [c["label"] for c in cards["items"]] == ["TCS", "INFY"]
    assert cards["items"][0]["trend"] == [3290.0, 3150.0, 3082.0] and cards["items"][0]["change"] == -6.32
    assert chart["kind"] == "line" and chart["unit"] == "%" and chart["figure"] is False
    assert [s["data"][0] for s in chart["series"]] == [0.0, 0.0]
    assert chart["series"][1]["data"][-1] == 9.87


async def test_a_symbol_that_fails_is_named_and_the_rest_still_drawn():
    def handler(r: httpx.Request) -> httpx.Response:
        if "/search" in r.url.path:
            return httpx.Response(200, json={"quotes": []})
        return httpx.Response(200, json=_chart_payload())
    out = await markets.history("nifty, nosuchthing", "5d", transport=httpx.MockTransport(handler))
    assert "Couldn't find a market symbol for 'nosuchthing'" in out
    assert _blocks(out)[0]["kind"] == "line"  # one found: its own board, not a comparison
