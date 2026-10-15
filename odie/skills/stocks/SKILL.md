---
name: stocks
description: Stock, index, currency or gold prices and charts; how a listed company is doing; analysis of any listed company's last 4 quarters of results (US from SEC filings, others such as Indian companies from their published results).
metadata:
  title: Markets
  summary: "Prices and charts for stocks, indices, currencies and gold, and a company's last four quarters."
  adk_additional_tools: [market_history, quarterly_financials, build_report]
---
# Stocks

**Prices and "how is X doing":** call `market_history` with the name or ticker and a period (default 1mo for
"how is it doing", 5d for "this week"). Reply with one or two sentences on the move, then put its
```odie-blocks block in your reply exactly as it is. The app draws the chart and, for a single company, an Analyze
button.

**"Analyze <company> (<TICKER>): last 4 quarters"** (the Analyze button sends this). A ticker with an exchange
suffix (RELIANCE.NS, TCS.BO, SAP.DE) or a company outside the US goes to **Companies outside the US** below. For a
US company, call `quarterly_financials` with the ticker in brackets, or with the company name if no ticker was given. Start
the analysis by naming the company and ticker the tool reports. If that isn't the company the user meant (for
example the question was about an Indian company and the tool found a US one with a similar name), say so instead of
analysing it. If the tool lists several matches, ask which one. Put its ```odie-blocks board in your reply exactly as it is, then write the analysis. This is the
main part, so make it worth reading. Write it like a sharp equity analyst explaining to a smart friend:

- **Growth**: the revenue trend across the quarters, QoQ and YoY for the latest one, and whether it is
  speeding up or slowing.
- **Profitability**: gross, operating and net margin levels and direction, and operating leverage (are
  profits growing faster than revenue?).
- **Cash & balance sheet**: the cash trend and operating cash flow, and what likely moved them (buybacks,
  acquisitions, burn) when the numbers suggest it.
- **Risks / watch**: two or three concrete things to watch next quarter.
- **Bottom line**: one or two plain sentences.

Rules:
- Use only the numbers in the tool's table. Name any figure or quarter that's missing; never estimate one.
- Bold the key numbers. Keep paragraphs short.
- No buy, sell or price-target advice.
- If `quarterly_financials` says the company isn't US-listed, use **Companies outside the US** instead.

**Companies outside the US:** read the latest results table from the web, then call `build_report`.

1. Find the table:
   - **India (.NS / .BO, or an Indian company):** `web_fetch` `https://www.screener.in/company/<SYMBOL>/consolidated/`
     (SYMBOL is the ticker without .NS/.BO, e.g. TCS). If its Quarterly Results table is empty, use the same URL
     without `consolidated/`. If the page isn't found, `web_search` "screener.in <company name>" and fetch the
     company link it gives.
   - **Elsewhere:** `web_search` for the company's quarterly results or investor-relations page and `web_fetch` a
     page with a quarterly results table. News articles are not a table; don't build from them.
   - If no proper table turns up, say so in one sentence with the best link you found. Never guess numbers.
2. Read the last 5 quarter columns (oldest first) from the Quarterly Results table. On screener.in some row
   names come back blank; the rows are always in this order:
   - Companies: Sales (= revenue), Expenses, Operating Profit, OPM %, Other Income, Interest, Depreciation,
     Profit before tax, Tax %, Net Profit, EPS.
   - Banks: Revenue, Interest, Expenses, Financing Profit (= operating_profit), Financing Margin %, Other
     Income, Depreciation, Profit before tax, Tax %, Net Profit, EPS.
   Figures there are ₹ crore: currency "₹", scale "Cr". Pass `interest` only for banks.
3. Call `build_report` with the numbers exactly as the table shows them, `source_url` = the page you read and
   `filings_url` = its BSE or NSE link if it shows one. If it reports a problem, re-read the table and call it
   once more. If it fails again, say you couldn't read the numbers reliably and give the link.
4. Put its ```odie-blocks board in your reply exactly as it is, then write the same analysis as above. Quarterly
   cash isn't in these tables: in **Cash & balance sheet**, say that in one line and mention the exchange filings
   link if there is one.
