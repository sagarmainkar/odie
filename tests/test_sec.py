import json

import httpx

from odie.skills.stocks import sec
from odie.skills.stocks.sec import financials, instants, quarterly, quarterly_cash_flow


_QEND = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}
_QSTART = {"1": "01-01", "2": "04-01", "3": "07-01", "4": "10-01"}


def _d(frame, val, form="10-Q", fy=2026, fp="Q1", start=None, end=None):
    """A calendar-year fact; start/end follow from the frame (CY2025Q3 or CY2025) unless given."""
    y = frame[2:6]
    if start is None and len(frame) == 8:
        start, end = f"{y}-{_QSTART[frame[7]]}", f"{y}-{_QEND[frame[7]]}"
    elif start is None and len(frame) == 6:
        start, end = f"{y}-01-01", f"{y}-12-31"
    return {"frame": frame, "val": val, "form": form, "fy": fy, "fp": fp, "start": start, "end": end}


FACTS = {"us-gaap": {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
        _d("CY2025Q1", 100e6), _d("CY2025Q2", 110e6), _d("CY2025Q3", 120e6), _d("CY2025", 470e6, "10-K"),
        _d("CY2026Q1", 130e6), _d("CY2026Q2", 140e6)]}},
    "NetIncomeLoss": {"units": {"USD": [
        _d("CY2025Q1", 10e6), _d("CY2025Q2", 11e6), _d("CY2025Q3", -2e6), _d("CY2025", 30e6, "10-K"),
        _d("CY2026Q1", 13e6), _d("CY2026Q2", 14e6)]}},
    "OperatingIncomeLoss": {"units": {"USD": [_d("CY2026Q1", 20e6), _d("CY2026Q2", 21e6)]}},
    "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        _d("CY2025Q3I", 50e6), _d("CY2025Q4I", 55e6), _d("CY2026Q1I", 60e6), _d("CY2026Q2I", 58e6)]}},
    "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        {"val": 30e6, "form": "10-Q", "fy": 2026, "fp": "Q1", "start": "2026-01-01", "end": "2026-03-31"},
        {"val": 70e6, "form": "10-Q", "fy": 2026, "fp": "Q2", "start": "2026-01-01", "end": "2026-06-30"}]}},
}}


def test_quarterly_derives_q4_from_the_annual_figure():
    rev = quarterly(FACTS["us-gaap"], ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"])
    assert rev["CY2025Q4"] == 140e6  # 470 - (100 + 110 + 120)
    assert list(rev)[-1] == "CY2026Q2"


def test_negative_quarters_survive_q4_derivation():
    net = quarterly(FACTS["us-gaap"], ["NetIncomeLoss"])
    assert net["CY2025Q3"] == -2e6 and net["CY2025Q4"] == 11e6  # 30 - (10 + 11 - 2)


def test_instants_and_ytd_cash_flow():
    assert instants(FACTS["us-gaap"], "CashAndCashEquivalentsAtCarryingValue")["CY2026Q2"] == 58e6
    ocf = quarterly_cash_flow(FACTS["us-gaap"], "NetCashProvidedByUsedInOperatingActivities")
    assert ocf == {"CY2026Q1": 30e6, "CY2026Q2": 40e6}  # Q2 = YTD 70 - YTD 30


def test_financials_aligns_five_quarters_and_names_missing_series():
    f = financials(FACTS["us-gaap"])
    assert f["quarters"] == ["CY2025Q2", "CY2025Q3", "CY2025Q4", "CY2026Q1", "CY2026Q2"]
    assert f["revenue"] == [110e6, 120e6, 140e6, 130e6, 140e6]
    assert f["operating"] == [None, None, None, 20e6, 21e6]
    assert "gross profit" in f["missing"] and "revenue" not in f["missing"]


TICKERS = {"0": {"cik_str": 1107843, "ticker": "QLYS", "title": "QUALYS, INC."},
           "1": {"cik_str": 1660280, "ticker": "TENB", "title": "Tenable Holdings, Inc."}}


def _blocks(out: str) -> list:
    return json.loads(out.split("```odie-blocks\n", 1)[1].split("\n```", 1)[0])


def _sec(fail: bool = False, seen: list | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req.headers.get("user-agent", ""))
        if fail:
            return httpx.Response(503)
        if req.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json=TICKERS)
        if "CIK0001107843" in req.url.path:
            return httpx.Response(200, json={"entityName": "QUALYS, INC.", "facts": FACTS})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_analyze_by_name_builds_board_and_table(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "load_secret", lambda name: "me@example.org" if name == "ODIE_CONTACT_EMAIL" else None)
    seen: list[str] = []
    out = await sec.analyze_company("qualys", transport=_sec(seen=seen), cache_dir=tmp_path)
    assert "me@example.org" in seen[0]
    blocks = _blocks(out)
    kinds = [b["type"] for b in blocks]
    assert kinds[0] == "kpis" and kinds[-1] == "source" and "chart" in kinds
    rev = blocks[0]["items"][0]
    assert rev["label"] == "Revenue" and rev["value"] == 140.0 and rev["unit"] == "$M"
    assert "Q2 2026" in out and "write the analysis" in out.lower()


async def test_ticker_lookup_and_non_us(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "load_secret", lambda name: "me@example.org")
    assert "Qualys" in await sec.analyze_company("QLYS", transport=_sec(), cache_dir=tmp_path)
    assert await sec.analyze_company("Reliance Industries", transport=_sec(), cache_dir=tmp_path) == sec.NOT_US


async def test_sec_down_is_a_plain_message(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "load_secret", lambda name: "me@example.org")
    out = await sec.analyze_company("qualys", transport=_sec(fail=True), cache_dir=tmp_path)
    assert out.startswith("Couldn't reach SEC filings")


def test_board_handles_losses_and_margin_points():
    f = {"quarters": ["CY2025Q2", "CY2025Q3", "CY2025Q4", "CY2026Q1", "CY2026Q2"],
         "revenue": [250e6, 252e6, 260e6, 262e6, 268e6], "gross": [None] * 5, "operating": [5e6, 7e6, 9e6, 9e6, 12e6],
         "net": [1e6, 2e6, -0.7e6, 1.4e6, 3.8e6], "eps": [None] * 5, "cash": [None, 172e6, 188e6, 139e6, 125e6],
         "ocf": [None] * 5, "missing": ["gross profit", "EPS", "operating cash flow"]}
    b = sec.board("Tenable", "TENB", "0001660280", f)
    kp = {i["label"]: i for i in b[0]["items"]}
    assert kp["Net margin"]["value"] == 1.4 and kp["Net margin"]["change_unit"] == "pt"
    assert kp["Cash"]["change"] < 0
    bars = next(x for x in b if x["type"] == "chart" and "income" in x["title"].lower())
    assert bars["series"][1]["data"][1] == -0.7


def test_q4_cash_flow_comes_from_the_annual_report():
    rows = {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        {"val": 30e6, "form": "10-Q", "fy": 2025, "fp": "Q1", "start": "2025-01-01", "end": "2025-03-31"},
        {"val": 70e6, "form": "10-Q", "fy": 2025, "fp": "Q2", "start": "2025-01-01", "end": "2025-06-30"},
        {"val": 100e6, "form": "10-Q", "fy": 2025, "fp": "Q3", "start": "2025-01-01", "end": "2025-09-30"},
        {"val": 150e6, "form": "10-K", "fy": 2025, "fp": "FY", "start": "2025-01-01", "end": "2025-12-31"}]}}}
    assert quarterly_cash_flow(rows, "NetCashProvidedByUsedInOperatingActivities")["CY2025Q4"] == 50e6


def test_display_name_prefers_the_readable_ticker_title():
    assert sec.display_name("TENABLE HOLDINGS, INC.", "Tenable Holdings, Inc.") == "Tenable Holdings, Inc."
    assert sec.display_name("Qualys, Inc.", "QUALYS, INC.") == "Qualys, Inc."



def _q(start, end, val, form="10-Q", fp="Q1", fy=2025):
    return {"val": val, "form": form, "fp": fp, "fy": fy, "start": start, "end": end}


# Apple-shaped: fiscal year Oct-Sep, so its fiscal Q4 (calendar Q3) only exists inside the 10-K annual figure.
APPLE = {"Revenues": {"units": {"USD": [
    _q("2024-09-29", "2024-12-28", 124e9, fp="Q1"), _q("2024-12-29", "2025-03-29", 95e9, fp="Q2"),
    _q("2025-03-30", "2025-06-28", 94e9, fp="Q3"), _q("2024-09-29", "2025-09-27", 416e9, form="10-K", fp="FY"),
    _q("2024-09-29", "2025-03-29", 219e9, fp="Q2"),  # a six-month YTD row: must be ignored
    _q("2025-09-28", "2025-12-27", 140e9, fp="Q1", fy=2026), _q("2025-12-28", "2026-03-28", 109e9, fp="Q2", fy=2026)]}}}


def test_fiscal_q4_is_derived_for_non_calendar_years():
    rev = quarterly(APPLE, ["Revenues"])
    assert rev == {"CY2024Q4": 124e9, "CY2025Q1": 95e9, "CY2025Q2": 94e9, "CY2025Q3": 103e9, "CY2025Q4": 140e9, "CY2026Q1": 109e9}


def test_window_is_consecutive_and_gaps_are_named():
    gappy = {"Revenues": {"units": {"USD": [_q("2025-01-01", "2025-03-31", 10e6), _q("2025-04-01", "2025-06-30", 11e6),
                                            _q("2025-10-01", "2025-12-31", 13e6), _q("2026-01-01", "2026-03-31", 14e6)]}}}
    f = financials(gappy)
    assert f["quarters"] == ["CY2025Q1", "CY2025Q2", "CY2025Q3", "CY2025Q4", "CY2026Q1"]
    assert f["revenue"][2] is None and "Q3 2025" in f["gaps"]


def test_newest_revenue_tag_wins_over_a_stale_one():
    facts = {"RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [_q("2019-10-01", "2019-12-31", 3e9)]}},
             "Revenues": {"units": {"USD": [_q("2026-01-01", "2026-03-31", 44e9)]}}}
    assert list(quarterly(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"])) == ["CY2026Q1"]


def test_stale_filings_are_flagged():
    from datetime import date
    old = {"Revenues": {"units": {"USD": [_q("2019-10-01", "2019-12-31", 3e9)]}}}
    assert financials(old, today=date(2026, 10, 5))["stale"] is True
    assert financials(APPLE, today=date(2026, 6, 1))["stale"] is False


def test_table_names_gaps_and_board_survives_one_quarter():
    f = financials({"Revenues": {"units": {"USD": [_q("2026-01-01", "2026-03-31", 14e6)]}}})
    b = sec.board("Tiny", "TNY", "0000000001", f)  # must not raise with a single quarter
    assert b[0]["items"][0]["change"] is None
    t = sec.table("Tiny", "TNY", f)
    assert "No figures for" in t and "Q4 2025" in t


async def test_stale_filings_get_a_plain_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "load_secret", lambda name: "me@example.org")
    old = {"us-gaap": {"Revenues": {"units": {"USD": [_q("2019-10-01", "2019-12-31", 3e9)]}}}}

    def handler(req):
        if req.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json=TICKERS)
        return httpx.Response(200, json={"entityName": "Qualys, Inc.", "facts": old})
    out = await sec.analyze_company("QLYS", transport=httpx.MockTransport(handler), cache_dir=tmp_path)
    assert "odie-blocks" not in out and "Q4 2019" in out


async def test_corrupt_cache_is_a_miss_and_bad_responses_are_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "load_secret", lambda name: "me@example.org")
    (tmp_path / "company_tickers.json").write_text('{"0": {"cik_str": 11')  # half-written by a crash
    assert "Qualys" in await sec.analyze_company("QLYS", transport=_sec(), cache_dir=tmp_path)
    junk = httpx.MockTransport(lambda req: httpx.Response(200, text="<html>maintenance</html>"))
    out = await sec.analyze_company("TENB", transport=junk, cache_dir=tmp_path / "fresh")
    assert out.startswith("Couldn't") and not (tmp_path / "fresh" / "company_tickers.json").exists()


BIG = [("MSFT", "MICROSOFT CORP"), ("DIS", "Walt Disney Co"), ("KO", "COCA COLA CO"), ("CCEP", "Coca-Cola Europacific Partners plc"),
       ("GOOGL", "Alphabet Inc."), ("META", "Meta Platforms, Inc."), ("AAPL", "Apple Inc."), ("APLE", "Apple Hospitality REIT, Inc."),
       ("FSLR", "FIRST SOLAR, INC."), ("FHN", "FIRST HORIZON CORP"), ("ON", "ON SEMICONDUCTOR CORP"), ("NVDA", "NVIDIA CORP")]


async def _resolve(q, tmp_path):
    tickers = {str(i): {"cik_str": 1000 + i, "ticker": t, "title": n} for i, (t, n) in enumerate(BIG)}
    tr = httpx.MockTransport(lambda req: httpx.Response(200, json=tickers))
    async with httpx.AsyncClient(transport=tr) as c:
        return await sec.resolve_cik(q, c, tmp_path)


async def test_names_as_yahoo_and_people_write_them(tmp_path):
    for q, want in (("Microsoft Corporation (MSFT)", "MSFT"), ("Microsoft Corporation", "MSFT"), ("NVIDIA Corporation", "NVDA"),
                    ("Walt Disney Company (The)", "DIS"), ("Coca-Cola", "KO"), ("Coca-Cola Company (The)", "KO"),
                    ("google", "GOOGL"), ("Facebook", "META"), ("disney", "DIS"), ("Apple", "AAPL"), ("AAPL", "AAPL")):
        hit = await _resolve(q, tmp_path)
        assert isinstance(hit, tuple) and hit[1] == want, (q, hit)


async def test_ambiguous_names_return_the_choices(tmp_path):
    hit = await _resolve("First", tmp_path)
    assert isinstance(hit, list) and {t for _, t, _ in hit} == {"FSLR", "FHN"}


async def test_a_lowercase_word_is_not_taken_as_a_ticker(tmp_path):
    assert await _resolve("on", tmp_path) is None or (await _resolve("on", tmp_path))[1] == "ON"
    assert await _resolve("nothing like this", tmp_path) is None


def test_quarters_ending_late_in_a_month_label_by_their_middle():
    assert sec.cal_label("2026-07-26") == "CY2026Q2"  # NVIDIA: Apr 27 - Jul 26 is mostly calendar Q2
    assert sec.cal_label("2025-09-27") == "CY2025Q3" and sec.cal_label("2026-01-03") == "CY2025Q4"
    assert sec.cal_label("2026-03-31") == "CY2026Q1"
