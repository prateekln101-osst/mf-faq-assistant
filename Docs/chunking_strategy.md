# Chunking strategy

**Status:** Implemented in `src/chunker.py` for Phase 3 ingestion.
**Corpus inspected:** the five cleaned Groww scheme pages in `data/cleaned/` (fetched 2026-10-02). The other source URLs are not in `data/sources.csv` yet. The same rules apply when those documents are added.
**Token counts:** `sentence-transformers/all-MiniLM-L6-v2` WordPiece tokenizer, padding and truncation turned off. Counts exclude `[CLS]` and `[SEP]`. The model still spends those two special tokens inside its 256 limit, so the string that gets embedded must stay at or under **254** tokens.

## 1. Observed structure

Each cleaned file is a list of `{heading, text}` sections. Tables are already flattened to `label: value` lines. FAQ answers were recovered from the page's FAQ block, with the question as the heading.

146 sections across 5 documents.

| Document | Sections | Min tokens | Median | Max tokens |
|---|---:|---:|---:|---:|
| hdfc_large_cap | 29 | 14 | 50 | 1,000 |
| hdfc_flexi_cap | 28 | 14 | 50.5 | 1,752 |
| hdfc_elss | 27 | 4 | 55 | 1,292 |
| hdfc_small_cap | 29 | 14 | 50 | 1,741 |
| hdfc_balanced_advantage | 33 | 14 | 70 | 8,974 |
| **All** | **146** | **4** | **51** | **8,974** |

Length buckets (content tokens, heading + text):

| Tokens | Sections |
|---|---:|
| 1–40 | 44 |
| 41–80 | 45 |
| 81–150 | 33 |
| 151–200 | 11 |
| 201–254 | 1 |
| 255+ | 12 |

Mean is 183 only because five holdings tables are huge. The typical section is about 50 tokens and already fits the model.

Three shapes show up on every scheme page:

- **Key-fact block.** The first heading is the scheme name (about 88–100 tokens). It holds the live facts: risk level ("Very High Risk"), `Min. for SIP`, `Expense ratio`, AUM, and NAV, plus a few return figures. Example from Large Cap: `Expense ratio: 1.04%` and `Min. for SIP: ₹100`.
- **Repeated topic headings.** The same headings appear on all five pages: Expense ratio, Exit load, Tax, Stamp duty, Minimum investments, Returns and rankings, Investment objective, Fund house. The Expense ratio heading is a glossary definition. The number itself sits in the key-fact block and again in an FAQ. Exit load is split into a definition, a one-line rule (`Nil` on ELSS, `Exit load of 1% if redeemed within 1 year` on Large Cap), and sometimes a dated history. Benchmark is one line inside Investment objective, for example `Fund benchmark NIFTY 100 Total Return Index`.
- **FAQs.** 40 question headings. Shortest 38 tokens, median 62.5, longest 155. Every current FAQ fits in one chunk with its answer.
- **Holdings tables.** The only very long sections: 1,000 tokens (50 holdings) up to 8,974 tokens (326 holdings on Balanced Advantage). Each holding is four `label: value` lines (Name, Sector, Instruments, Assets), about 20 tokens.
- **Fund-manager bios.** Seven sections from 406 to 451 tokens. The Dhruv Muchhal bio is byte-for-byte repeated on all five pages. Most of the length is the "also manages these schemes" list.

Twelve sections exceed 254 tokens: the five holdings tables and seven manager bios. Nothing else does.

## 2. Method

Section-first chunking, then a split only when the embedded string would exceed the model limit.

1. One chunk per cleaned section when `prefix + heading + text` is 254 tokens or under. That covers 134 of 146 sections, including every FAQ and every fee, lock-in, SIP, risk, and benchmark block.
2. When a section is over the limit, split it without cutting a fact in half. Holdings split on holding records. Other long sections split on paragraph or line boundaries.
3. Prepend a context prefix to the text that is embedded and stored: `{scheme_name} | {heading}:`. The same labels ("Exit load", "Expense ratio") exist on every scheme, and a 4-token section whose body is `Nil` is useless without the scheme name and the heading.

This matches the data. Facts are already grouped under the heading a person would ask about, and those groups are short. A fixed-size window would slice an exit-load rule away from its heading and mix two schemes' identical labels.

## 3. Size and overlap

MiniLM truncates at 256 word-pieces. Anything past that is dropped with no error. The prefix and the two special tokens have to fit inside that budget, so the provisional "200 to 300 tokens" range is too high once the prefix is included.

| Rule | Value |
|---|---|
| Hard cap on the embedded string (prefix + heading + body) | 254 tokens |
| Target size when a split is required | 200 tokens of body |
| Overlap | 40 tokens, and only on those forced splits |
| Sections that already fit | No overlap. The next heading is a different fact. |

40 tokens is enough to repeat a heading line or the last `label: value` line across a forced boundary, and small enough that a 200-token piece plus overlap still fits under 254 after the prefix. Overlap is applied as whole lines, never as a mid-line cut.

## 4. Metadata on each chunk

Kept, from architecture section 3.2:

| Field | Source |
|---|---|
| `chunk_id` | `sha256(source_url + section + chunk_index)` hex, so a re-run upserts the same ids |
| `source_url` | `sources.csv` |
| `source_title` | First cleaned heading (the scheme page title) |
| `publisher`, `publisher_type` | `sources.csv` (`Groww`, `distributor` for these five) |
| `scheme_name`, `scheme_category` | `sources.csv` |
| `section` | Slug of the heading (`exit_load`, `holdings`). Two sections can share a slug; `chunk_index` separates them |
| `doc_type` | `sources.csv` (`scheme_page` today) |
| `fetched_date` | Loader, `2026-10-02` for this run |

Added:

| Field | Why |
|---|---|
| `heading` | Raw heading. The slug `exit_load` collides with the glossary, the one-line rule, and the history table. The raw heading plus `chunk_index` keeps them distinct in `chunks.txt`. |

Dropped: nothing from the architecture list. `source_url` and `scheme_name` are on every chunk.

## 5. Tables, FAQs, and near-duplicates

**Tables.** Lines are already `label: value`. A chunk boundary never falls inside a line. A holding (Name, Sector, Instruments, Assets) is one record and stays in one chunk. Records are packed up to the 200-token target, so Balanced Advantage's 326 holdings become on the order of 30 chunks rather than 326 one-holding chunks. Exit-load history rows stay whole. The current rule (`Nil`, or `Exit load of 1% if redeemed within 1 year`) is already its own short section and stays one chunk.

**FAQs.** The heading is the question and the text is the answer. They stay in one chunk. Every current FAQ is at most 155 tokens. If a later FAQ exceeds the cap, the question is repeated at the start of each piece and the answer is split on sentence boundaries.

**Near-duplicates across schemes.** Expense ratio, exit load, minimum SIP, stamp duty, and tax use the same words on all five pages. The context prefix and `scheme_name` / `scheme_category` metadata are what make "exit load of ELSS" a different chunk from "exit load of Large Cap". Copies are kept, because each page is its own citation. The repeated Dhruv Muchhal bio is the same case: five chunks, five `source_url`s, distinguished by the scheme prefix.

**Within a page.** The live expense ratio appears in the key-fact block and again in the expense-ratio FAQ. Both stay. They cite the same URL. The glossary section under the heading "Expense ratio" does not contain the percentage; the key-fact block and the FAQ do.

## 6. Risks and checks

| Risk | What we will check |
|---|---|
| A chunk over 254 embedded tokens is silently truncated by MiniLM | `chunker` prints min, median, and max token length, and the count of chunks over 254. That count should be 0. |
| An exit-load rule or a holding record is cut in half | Spot-check `data/chunks.txt`: one holdings chunk and one exit-load chunk. Every `label: value` line is intact. |
| An FAQ question is separated from its answer | Spot-check one FAQ chunk. The question and the answer are in the same chunk. |
| "Exit load" on ELSS and Large Cap retrieve as the same fact | Both chunks contain the scheme name in the prefix and in `scheme_name`. |
| Holdings chunks outnumber fee and FAQ chunks, especially Balanced Advantage | Accepted. Packing to ~200 tokens limits the damage. Later retrieval can filter on `section` when the question is about fees or lock-in. |
| The key-fact block also contains return percentages | The block is under 100 tokens, so it stays whole. Performance questions are refused later by guardrails, not by dropping source text here. |
| Return-calculator sections are stubs (the cleaned text is only the input amount) | The chunker will not fill in missing numbers. |
| Manager bios and "compare similar funds" can answer with a different scheme's name | Prefix carries this page's scheme. `compare_similar_funds` stays in the corpus so the source is complete; retrieval quality for that section is checked in Phase 4. |

`data/chunks.txt` will be the inspection file: a separator line, the metadata block, then the chunk text, for every chunk.

## Approval

No `src/chunker.py` until this document is approved. After approval, the chunker follows this document only.
