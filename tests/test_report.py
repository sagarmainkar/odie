import json
from datetime import date

from odie.skills.stocks.report import build_report, check

TODAY = date(2026, 10, 5)
Q = ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"]
# TCS, screener.in, ₹ crore
TCS = dict(company="Tata Consultancy Services", ticker="TCS.NS", currency="₹", scale="Cr", quarters=Q,
           revenue=[63437, 65799, 67087, 70698, 72275], expenses=[46562, 47821, 48818, 51422, 53719],
           operating_profit=[16875, 17978, 18269, 19276, 18556], net_profit=[12819, 12131, 10720, 13784, 13420],
           eps=[35.27, 33.37, 29.45, 37.92, 36.90], source_url="https://www.screener.in/company/TCS/consolidated/")
# HDFC Bank: revenue − interest − expenses = financing profit
BANK = dict(company="HDFC Bank", ticker="HDFCBANK.NS", currency="₹", scale="Cr", quarters=Q,
            revenue=[87372, 86994, 87067, 87182, 90575], interest=[47709, 46741, 45821, 45220, 47626],
            expenses=[64497, 45161, 54145, 44028, 58292], operating_profit=[-24833, -4908, -12899, -2066, -15342],
            net_profit=[17090, 20364, 20691, 21074, 20383], eps=[10.60, 12.76, 12.87, 13.22, 12.50])


def _board(text: str) -> list[dict]:
    return json.loads(text.split("```odie-blocks\n")[1].split("\n```")[0])


def test_good_numbers_pass():
    assert check(**{k: v for k, v in TCS.items() if k not in ("company", "ticker", "currency", "scale", "source_url")}, today=TODAY) is None


def test_bank_layout_passes():
    assert check(**{k: v for k, v in BANK.items() if k not in ("company", "ticker", "currency", "scale")}, today=TODAY) is None


def _bad(**over):
    args = {k: v for k, v in TCS.items() if k not in ("company", "ticker", "currency", "scale", "source_url")}
    args.update(over)
    return check(**args, today=TODAY)


def test_needs_five_quarters():
    assert "5 quarters" in _bad(quarters=Q[1:], revenue=TCS["revenue"][1:], expenses=None, operating_profit=None,
                                net_profit=TCS["net_profit"][1:], eps=None)


def test_quarters_must_be_consecutive_oldest_first():
    assert "consecutive" in _bad(quarters=list(reversed(Q)))
    assert "consecutive" in _bad(quarters=["Jun 2025", "Sep 2025", "Mar 2026", "Jun 2026", "Sep 2026"])


def test_bad_quarter_label():
    assert "label" in _bad(quarters=["Q1 FY26", *Q[1:]])


def test_lists_must_line_up():
    assert "revenue" in _bad(revenue=TCS["revenue"][:4])


def test_mislabelled_row_is_caught():
    # expenses swapped with net profit: revenue − expenses no longer gives operating profit
    assert "operating profit" in _bad(expenses=TCS["net_profit"])


def test_profit_bigger_than_revenue():
    assert "net profit" in _bad(net_profit=[v * 10 for v in TCS["revenue"]], expenses=None, operating_profit=None, eps=None)


def test_eps_sign():
    assert "EPS" in _bad(eps=[-1, 33.37, 29.45, 37.92, 36.90])


def test_old_page():
    old = ["Jun 2024", "Sep 2024", "Dec 2024", "Mar 2025", "Jun 2025"]
    assert "old" in _bad(quarters=old)


def test_report_board_and_table():
    out = build_report(**TCS, today=TODAY)
    assert "Tata Consultancy Services (TCS.NS)" in out and "₹ Cr" in out
    assert "cash" in out.lower()  # tells the model cash isn't in this source
    b = _board(out)
    kpis = {k["label"]: k for k in b[0]["items"]}
    assert kpis["Revenue"]["value"] == 72275 and kpis["Revenue"]["unit"] == "₹Cr"
    assert kpis["Revenue"]["change"] == 2.2
    assert kpis["Net margin"]["value"] == 18.6
    assert kpis["EPS"]["value"] == 36.9
    bars = b[1]
    assert bars["x"] == ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026"] and bars["unit"] == "₹Cr"
    assert bars["series"][0]["data"][-1] == 72275
    assert b[-1]["type"] == "source" and b[-1]["url"].startswith("https://www.screener.in/") and "screener.in" in b[-1]["text"]


def test_report_yoy_in_table():
    out = build_report(**TCS, today=TODAY)
    assert "YoY 13.9%" in out


def test_report_failure_is_one_sentence():
    out = build_report(**{**TCS, "expenses": TCS["net_profit"]}, today=TODAY)
    assert "```" not in out and "operating profit" in out


def test_bank_board_has_no_operating_margin():
    out = build_report(**BANK, today=TODAY)
    b = _board(out)
    assert "Operating margin" not in {k["label"] for k in b[0]["items"]}
    assert [s["name"] for s in b[2]["series"]] == ["Net"]
    assert "Financing profit" in out and "Operating margin %" not in out


def test_report_names_the_five_headings():
    out = build_report(**TCS, today=TODAY)
    for h in ("Growth", "Profitability", "Cash & balance sheet", "Risks / watch", "Bottom line"):
        assert h in out.split("```")[-1]
