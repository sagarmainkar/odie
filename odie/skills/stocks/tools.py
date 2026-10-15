"""Tools the stocks skill brings: shown to the model only while the skill is loaded."""
from google.adk.tools import FunctionTool

from odie.agent.tools.markets import make_market_tools
from odie.skills.stocks import report
from odie.skills.stocks.sec import analyze_company


async def quarterly_financials(company: str) -> str:
    """A US-listed company's last 4 quarters from SEC filings: revenue, margins, profit, cash, with a ready-made
    ```odie-blocks board to paste unchanged. company: a name or ticker, e.g. Qualys, QLYS, Tenable, Apple."""
    return await analyze_company(company)


def build_report(company: str, ticker: str, currency: str, scale: str, quarters: list[str], revenue: list[float],
                 net_profit: list[float], expenses: list[float] | None = None, interest: list[float] | None = None,
                 operating_profit: list[float] | None = None, eps: list[float] | None = None, source_url: str = "",
                 filings_url: str = "") -> str:
    """Check quarterly results you read from a web page (any company outside the US) and get a ready-made
    ```odie-blocks board to paste unchanged. Numbers exactly as the page shows them, in its unit.
    quarters: 5 labels oldest first, like "Jun 2025" (the latest 4 plus the one a year before the latest).
    currency: a symbol, e.g. ₹ or €. scale: the page's unit, "Cr", "M" or "B". Every list has one value per quarter.
    expenses/interest/operating_profit: as the table names them (a bank's Financing Profit is operating_profit).
    source_url: the page you read. filings_url: the exchange filings page if the page links one.
    If a check fails it says which; re-read the table and call again."""
    return report.build_report(company, ticker, currency, scale, quarters, revenue, net_profit, expenses, interest,
                               operating_profit, eps, source_url, filings_url)


TOOLS = [*make_market_tools(), FunctionTool(quarterly_financials), FunctionTool(build_report)]
