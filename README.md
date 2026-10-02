# Mutual Fund FAQ Assistant

Facts-only. No investment advice.

A closed-corpus chatbot for factual questions about five HDFC Mutual Fund Direct Plan schemes. Each answer is at most three sentences, cites exactly one source, and ends with the date the sources were fetched.

## Sources

All six pages are on hdfcfund.com. The five scheme rows replace the earlier Groww distributor pages. HDFC Equity Fund on Groww is the scheme HDFC now publishes as HDFC Flexi Cap Fund.

| id | scheme | publisher | type | document | url |
|---|---|---|---|---|---|
| hdfc_large_cap | HDFC Large Cap Fund (Direct Plan) | HDFC Mutual Fund | amc | scheme_page | https://www.hdfcfund.com/explore/mutual-funds/hdfc-large-cap-fund/direct |
| hdfc_flexi_cap | HDFC Flexi Cap Fund (Direct Plan) | HDFC Mutual Fund | amc | scheme_page | https://www.hdfcfund.com/explore/mutual-funds/hdfc-flexi-cap-fund/direct |
| hdfc_elss | HDFC ELSS Tax Saver Fund (Direct Plan) | HDFC Mutual Fund | amc | scheme_page | https://www.hdfcfund.com/explore/mutual-funds/hdfc-elss-tax-saver-fund/direct |
| hdfc_small_cap | HDFC Small Cap Fund (Direct Plan) | HDFC Mutual Fund | amc | scheme_page | https://www.hdfcfund.com/explore/mutual-funds/hdfc-small-cap-fund/direct |
| hdfc_balanced_advantage | HDFC Balanced Advantage Fund (Direct Plan) | HDFC Mutual Fund | amc | scheme_page | https://www.hdfcfund.com/explore/mutual-funds/hdfc-balanced-advantage-fund/direct |
| hdfc_capital_gains_guide | HDFC Mutual Fund | HDFC Mutual Fund | amc | guide | https://www.hdfcfund.com/learn/blog/how-get-capital-gain-statement-mutual-fund-schemes-india |

## Sample answers

These are real replies from `pipeline.answer` on 2 October 2026.

**What is the expense ratio of HDFC Large Cap Fund?**

The expense ratio (Total Expense Ratio) of the HDFC Large Cap Fund (Direct Plan) is 1.04 percent.
Source: https://www.hdfcfund.com/explore/mutual-funds/hdfc-large-cap-fund/direct
Last updated from sources: 2026-10-02

**What is the lock-in period of the ELSS fund?**

The lock-in period for the HDFC ELSS Tax Saver Fund (Direct Plan) is 3 years.
Source: https://www.hdfcfund.com/explore/mutual-funds/hdfc-elss-tax-saver-fund/direct
Last updated from sources: 2026-10-02

**How do I download my capital-gains statement?**

You can download the capital-gain statement online by logging into the website of CAMS, KFintech, or the mutual-fund platform where you hold the HDFC fund, using your PAN and registered email ID. After logging in, locate the statements or reports section and download the capital-gain statement. It is best to do this after the financial year ends (post-March) for use during ITR filing.
Source: https://www.hdfcfund.com/learn/blog/how-get-capital-gain-statement-mutual-fund-schemes-india
Last updated from sources: 2026-10-02

**Should I invest in HDFC Small Cap Fund?**

I can only share factual scheme information, not investment advice.
Learn more: https://www.amfiindia.com/investor-corner
Last updated from sources: 2026-10-02

**What returns will HDFC Flexi Cap Fund give?**

I can't calculate or compare returns. The scheme factsheet is the place for performance figures.
Source: https://www.hdfcfund.com/explore/mutual-funds/hdfc-flexi-cap-fund/direct
Last updated from sources: 2026-10-02

## Known limits

- The corpus is these six HDFC pages. Questions about other fund houses, or about SID/KIM text that is not on the scheme page, are out of scope.
- hdfcfund.com returns HTTP 403 to the loader. Each page was saved from a browser render, and a later load reuses that snapshot when the live request fails. A refresh needs a new snapshot.
- The assistant does not give investment advice and does not calculate or compare returns, even when a scheme page shows them.
- An advice refusal cites AMFI's investor page. That URL is not a row in `data/sources.csv`.
- Answers use one link and at most three sentences. They can be out of date; the date line is the day the pages were fetched.
- Personal details in a question are blocked and are not stored.

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m src.loader
python -m src.ingest --rebuild
python -m streamlit run src/app.py
```

Put `GROQ_API_KEY` in `.env`. After a rebuild, restart Streamlit so it loads the new index.

Facts-only. No investment advice.
