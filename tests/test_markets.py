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
