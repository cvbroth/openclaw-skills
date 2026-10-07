# PP-StructureV3 expanded scan evaluation

Date: 2026-10-07. Branch: `eval/filetools-paddleocr-vl-20261006`. This report evaluates 20 physical pages from one authorized exam PDF. It does not establish whole-book accuracy or production readiness.

## Outcome

All 17 new pages completed PP-StructureV3 inference in separate, serial, offline CPU containers. The three earlier pages (physical 6, 10, 30) were reused only after matching the 220 dpi input-image hashes and prior successful receipts. There were no OOM kills, page timeouts, inference failures, or export failures in this run.

This does **not** pass the suitability gate for automatically producing a reliable structured question book. The original image, raw OCR lines, parsed layout blocks, and Markdown differ materially on two multi-choice pages: physical pages 127 and 131 have 15 and 17 raw OCR lines respectively that are not represented in parsed blocks. The page 127 Markdown lacks visible answer choices for several questions; page 131 Markdown omits parts of visible questions/options. These are layout assembly losses, not proof the recognizer never saw the text. In addition, the visibly degraded physical page 23 has substantial character/number/option-label errors. The test therefore supports continued experimental use for text extraction with mandatory source-page review, but not unattended question-structure generation.

The requested new-sample reference corpus of at least 3,000 non-whitespace characters was **not completed**. Consequently, no CER is reported for the 17 new pages. This is an explicit incomplete acceptance item; it is not replaced with model confidence, OCR-to-OCR agreement, or a fabricated zero. Existing selected-block CER for the prior 6/10/30 problem sample is reported separately below and is not representative of the 17 new pages.

## Fixed input and sample selection

Source PDF SHA-256: `0007677dc510b01ffed36bd1250fafd8a7b0101f383e3603257b45e379a6f28b` (169 pages). Only the following 20 physical pages were read/rendered. The 17 new 220 dpi images were rendered individually; the three old images were reused unchanged. Printed page numbers were read from the page images.

| Physical | Printed | Coverage/selection reason |
|---:|---:|---|
| 6 | 1 | Prior successful single-choice/title sample; exact image hash reused |
| 10 | 5 | Prior successful dense single-choice and page-boundary sample; exact image hash reused |
| 30 | 25 | Prior successful single-choice/section transition sample; exact image hash reused |
| 11 | 6 | Long stems, compact two-column choices, sidebar |
| 23 | 18 | Visibly degraded/noisy scan challenge page |
| 132 | 136 | Dense single-choice page and context for q10 continuation from p131 |
| 127 | 131 | Dense multi-choice, degraded left edge/scan artifacts |
| 168 | 175 | Dense multi-choice late-book page; starts with a prior question continuation |
| 131 | 135 | Multi-choice page, questions 3–10, chapter title and page furniture |
| 18 | 13 | Single-to-multiple-choice transition and chapter context |
| 114 | 118 | Chapter transition, title and page furniture |
| 75 | 75 | Multi-choice and long material stems |
| 61 | 56 | Dense multi-choice sequence |
| 33 | 28 | Compact multi-choice, small text and circled-number notation |
| 146 | 150 | Dense single-choice in later section |
| 13 | 8 | Single-choice with two-column options and scan-edge defect |
| 54 | 49 | Dense multi-choice and long stems |
| 63 | 58 | Multi-choice, long text and question boundary |
| 16 | 11 | q74 begins at page bottom; paired with adjacent p17 |
| 17 | 12 | q74 continuation at top; paired with adjacent p16 |

The adjacent pages 16–17 confirm the q74 cross-page boundary. Physical pages 127/132 also expose question continuation and layout loss across a selected adjacent boundary. No table, formula, or standalone illustration content was identified in these selected question pages; the sidebar/page furniture and circled numerals were included. The sample does not establish support for tables, formulas, or arbitrary figures.

Sample manifest SHA-256: `c33b545adb5e52d96b3bc2c2f7ce5b4c157cf8acee09c6472f8bb0aaf705cabf`. Private original page images and sample details remain under the ignored runtime directory.

## Runtime and resources

The fixed engine is PP-StructureV3 on PaddleOCR/PaddleX 3.4.0 and PaddlePaddle 3.2.2, using the existing text-only evaluation configuration and its explicitly pinned local PP-Chart2Table initialization model. Chart business inference, table, formula, seal, and region recognition were disabled. This is a deliberately partial configuration, not the full PP-StructureV3 pipeline. The correct immutable image ID was `sha256:dc202cf886fa3e3d239765f27df55b9b1c4b11885d11f8252dd8a4631860ae93`.

Every new page ran in its own container with 2 CPUs, 16 GiB memory and memory-swap both set to 16 GiB (no extra container swap), `network=none`, CPU device, and `cpu_threads=2`. Each attempt had 180 seconds for model loading and 300 seconds for its one page. Preflight required at least 18 GiB host `MemAvailable`; service load and memory were captured before each run. Containers had no GPU device. The per-page metrics and receipts record `device=cpu` and `cpu_threads=2`.

| Physical page | Load s | Page inference s | Process peak RSS GiB | Container peak GiB | Result |
|---:|---:|---:|---:|---:|---|
| 11 | 16.00 | 24.49 | 6.45 | 6.24 | success |
| 23 | 16.01 | 22.57 | 6.51 | 6.30 | success |
| 132 | 16.04 | 24.72 | 6.49 | 6.28 | success |
| 127 | 16.01 | 23.88 | 6.45 | 6.24 | success |
| 168 | 15.95 | 23.30 | 6.47 | 6.26 | success |
| 131 | 15.99 | 23.79 | 6.49 | 6.28 | success |
| 18 | 15.99 | 24.87 | 6.47 | 6.26 | success |
| 114 | 15.99 | 22.00 | 6.48 | 6.26 | success |
| 75 | 15.97 | 20.93 | 6.48 | 6.27 | success |
| 61 | 16.05 | 22.88 | 6.49 | 6.28 | success |
| 33 | 16.04 | 25.62 | 6.48 | 6.26 | success |
| 146 | 15.92 | 21.09 | 6.45 | 6.24 | success |
| 13 | 15.89 | 24.40 | 6.46 | 6.25 | success |
| 54 | 16.04 | 23.57 | 6.49 | 6.28 | success |
| 63 | 15.95 | 23.88 | 6.48 | 6.27 | success |
| 16 | 15.90 | 26.77 | 6.48 | 6.27 | success |
| 17 | 15.98 | 24.93 | 6.47 | 6.25 | success |

These rows are independent cold container attempts; loading cost repeats per page. Inference ranged 20.93–26.77 seconds, process peak RSS 6.45–6.51 GiB, and container peak memory 6.24–6.30 GiB. The reused pages had prior measured inference times: p6 21.02s, p10 22.79s, p30 18.37s. Their earlier run configuration and receipts were retained; no new inference was done for them. This is not a whole-book timing estimate.

The production Worker limit remains 4 GiB; this measured test process alone peaked above 6.4 GiB RSS, before accounting for other Worker processes or service overhead. PP-StructureV3 as tested does not fit that production quota. No production limit or service was changed.

## Visual and layer-by-layer review

All 20 selected source page images were visually inspected at page resolution. Native JSON was compared across `overall_ocr_res`, `parsing_res_list`, and Markdown. The literal coverage audit reports 1,092 raw OCR lines, 578 parsed blocks, 46 raw OCR line strings not found in parsed blocks, and 8 parsed blocks not found in the same order in Markdown. String matching is intentionally only a diagnostic: repeated words, line splitting, and normalization can create false matches or misses, so these counts are not semantic accuracy scores.

Largest observed losses:

- **p127 / print131:** Original image shows complete questions 106–113. The recognizer's raw OCR includes text that the parser does not assemble (15 raw strings absent from parsed blocks). Markdown has several visible questions whose answer choices or statement lists are missing, including q108/q111 and later material. This is predominantly layout assembly loss where raw recognition exists; remaining glyph errors are OCR errors.
- **p131 / print135:** Original image shows q3–9 and the start of q10, with a chapter heading between q9 and q10. The parser omits 17 raw recognized strings. Markdown loses substantial parts of visible q4/q5 and their choices. The page has two-column choice placement and a narrow noisy left edge; the output does not preserve the structure reliably.
- **p23 / print18:** Original scan is visibly low quality. Markdown includes major character and numeral substitutions and option-label confusion; the raw/parser/export layers largely agree, so the primary problem is image recognition rather than Markdown filtering. This page is not an acceptable source for automatic question transcription.
- **p11 / print6:** Original q33 is emitted as q93. Dense two-column options are sometimes concatenated, although most A–D labels remain present.
- **p132 / print136:** Markdown begins with the visible C/D tail of q10 from p131, then q11–18. Several adjacent options are concatenated and punctuation/labels vary. This requires page-boundary reconstruction and cannot be counted as standalone complete questions.
- **p168 / print175:** Page begins with a prior-question continuation before q85. Options are frequently joined together; this is a boundary and structure warning, not evidence of hallucination.
- **p16–17 / print11–12:** q74 visibly spans both pages. The text is present across page outputs, but should remain linked as a cross-page question in any later structuring.
- **p18, 33, 61, 75, 114, 146, 13, 54, 63:** OCR generally contains the visible question sequence, but review found joined two-column options, partial boundary questions, punctuation/option-label variation, and OCR character errors. The native-to-Markdown audit also flags individual Markdown ordering/gap cases on p18, p61, p33, p146 and p13. These require source review; they are not certified complete.

Question-number and A–D counts in the audit are regex candidates only; they are not asserted as verified question/option totals. Multi-select numbering resets between sections, so raw number counts cannot be interpreted globally. No answer keys were inferred, and no OCR text was corrected using a language model.

## CER and comparison boundary

The existing image-reviewed reference blocks for the prior three-page problem sample total 517 non-whitespace characters: p6 111, p10 174, p30 232. On those **selected blocks only**, the existing run recorded PP-StructureV3 CER of 2/111 (1.80%) on p6, 0/174 on p10, and 0/232 on p30; RapidOCR CER was 43/111 (38.74%), 45/174 (25.86%), and 2/232 (0.86%) respectively. These small, previously selected excerpts are not whole-page scores and do not meet the requested new-sample reference target.

For the 17 added pages, same-page RapidOCR outputs were not available, and RapidOCR was not rerun. A ≥3,000-character visually checked reference set was not completed in this round, so CER for both PP-StructureV3 and RapidOCR on the expanded sample is **not available**. The prior 517-character comparison is kept separate; it is not pooled into a misleading new-sample result. No human reference is represented as user-certified.

## Recommendation and remaining gates

PP-StructureV3 is useful for offline CPU text extraction experiments under a 16 GiB container limit, but the observed parser/export losses and degraded-scan errors make it unsuitable for unattended question/option structuring. The 4 GiB production Worker quota is below the measured resource need. Do not move this configuration into production or feed its Markdown directly into formal document generation. A subsequent development phase would need a reviewed multi-page reference set, robust retention of raw recognized fragments, and explicit handling/review of parser omissions before any production proposal. This report does not recommend a whole-book run.

Verified: 20-page source scope, page image hashes, serial CPU/offline resource limits, 17 successful new one-page runs, correct reused prior receipts, native JSON/Markdown presence, source-image visual review, and layer-loss findings.

Not verified: ≥3,000-character expanded CER, expanded-sample RapidOCR comparison, full-page semantic completeness, whole-book speed/accuracy, table/formula/image handling, user-certified transcription, and production suitability.

Private reproducibility evidence is under the ignored path `runtime/paddleocr-vl-evaluation/`: `inputs-expanded-locked/` (image manifest and images), `results/ppstructurev3-expansion-r1/` (per-page receipts, metrics, native JSON and Markdown), and `comparison/block-scores-runtime-repair.json` (prior selected-block comparison). `native-export-audit.json` SHA-256: `ae5c6905578b1f43b312602d5f1c5e7d0bc0d2562a77c817b597fe75f090faaf`. These private data files are not committed.
