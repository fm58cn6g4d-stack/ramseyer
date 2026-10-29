# billmap red-team review (2026-10-29)

An independent review of billmap at commit `94712c0` (branch `claude/billmap-red-team`). I did not consult the
builder. I read `docs/`, `CLAUDE.md`, `records/`, the code in `src/billmap/` and `scripts/`, and the tests. The unit
tests pass (226). I did not rebuild the OLRC or GovInfo indexes. Instead I ran billmap's real
parse → resolve → dry-run pipeline (`dryrun.predict.run_bill`, the same function the gates use) on adversarial drafts,
against a small synthetic index with placeholder statute text: `redteam/synthetic.py` (22 cases;
`.venv/bin/python redteam/synthetic.py [case]`). Every "Confirmed" item below can be reproduced with that script or a
one-line parse.

## The short version for Espen

- **Today CLEAN means "every instruction billmap saw for this section applied literally to the text it chose."** It
  does not mean "this section is right." I built six ordinary drafting patterns that return CLEAN and give the wrong
  text. The worst: "striking “X” the first (second, last) place it appears" is read as "each place it appears", and
  every occurrence is changed (F1). A chapter-wide or title-wide "each place it appears" substitution is silently not
  applied, and the sections it should have changed still report CLEAN (F2).
- **"Never drop" does not hold end to end.** An instruction with a verb the grammar does not know ("by replacing “A”
  with “B”", or the imperative "strike “A” and insert “B”") disappears with no UNPARSED item. The M4 accounting gate
  cannot see this, because its "independent" counter uses the same verb list as the parser (F4).
- **The headline unseen-law rate, 1.51% substantive false-clean, is optimistic and fragile.**
  - 83% of the test half comes from two laws: the FY2025 NDAA (558 of 853 targets) and the FAA reauthorization (150).
    The tuning corpus is dominated by the FY2026 NDAA. Both are title 10 work by the same committees.
  - Some fixes were motivated by test-half laws.
  - The metric cannot see the worst error, an edit applied to the wrong section. On the GovInfo set, such an edit
    cannot even be CLEAN, because the baseline index holds only the answer-key sections (F5, F6).
  - The 95% interval on 5 of 332 is about 0.6% to 3.5% before clustering by law.
- **Enacted laws are the easiest possible input.** Legislative Counsel drafted them and the enrolling clerks checked
  them. Real drafts carry the errors the tool exists to catch: stale quotes, wrong cites, label gaps, typos. Several of
  those come back CLEAN (F8, F10, F11). Nothing yet measures how well billmap *detects* drafting errors, which is the
  core value for staff.
- **What I would tell you before you rely on it:**
  - Use billmap today as a fast first pass that finds sections and flags many problems.
  - Do not treat CLEAN as "verified." Read every changed section in a comparative print.
  - Look separately at every instruction that has no result.
  - Fix F1–F4 and F7 before any real-draft use. They are small, contained changes.
  - Add a drafting-error detection benchmark before more coverage work.

## Findings, ranked

Severity is for the stated purpose: mapping and checking *draft* bills.

### F1. Ordinal occurrences are applied to every occurrence, as CLEAN. Critical, confirmed

- **What:** `OCC` in `src/billmap/parse/grammar.py:28-30` nests the `nth` group inside the `occ` group. `_occ`
  (`grammar.py:452`) tests `occ` first, so "the first / second / third / last place it appears" always returns `each`.
- **Evidence:** `parse_text` gives `occurrence='each'` for all four ordinal forms. Case `second_place_it_appears`:
  "striking “Board” the second place it appears and inserting “Commission”" changes all three occurrences, and the
  section is **CLEAN**.
- **Why it matters:**
  - Ordinal edits are routine in drafts.
  - `docs/12-testing.md` lists "the first place it appears, and other ordinal occurrences" as a known hard case that
    needs a named test. There is no such test, and the P12 fixtures hold only "each place".
- **Remedy:** separate the groups. Add positive fixtures for first, second and last, and a dry-run test.

### F2. Chapter-wide and title-wide text edits are silently not applied; other sections stay CLEAN. Critical, confirmed

- **What:** `run_bill` (`src/billmap/dryrun/predict.py:39-90`) places an instruction on a section only in these cases:
  - the resolution has a `section_id`;
  - the op is a REPEAL of a chapter;
  - the op adds whole sections.
- "Chapter 1 of title 98 is amended by striking “Board” each place it appears and inserting “Commission”" resolves
  CODIFIED to the chapter node. It falls through every branch: no section, no `Result`. Yet `applied`
  (`predict.py:103`) counts it as applied because the outcome is CODIFIED. So the self-check `unapplied_mentions` never
  looks at it.
- **Evidence:** cases `chapter_wide_substitution` and `title_wide_substitution`. The chapter-wide instruction gets
  "NO RESULT". Section 101, edited by another instruction of the same bill, is **CLEAN** and still says "Board"
  throughout.
- **Why it matters:**
  - Conforming substitutions across a chapter or title are common in drafts (renamed offices and programs).
  - The oracle catches this only when OLRC classified the section to the law *and* another instruction also touched it.
- **Remedy:**
  - Fan chapter- and title-level text edits out to every section in the unit, with the scope recorded.
  - Until then, give such instructions an explicit status (e.g. TARGET_UNSUPPORTED). Mark every section in that unit
    that is otherwise CLEAN as WARN.
  - Make "CODIFIED but no section reached" count as unapplied.

### F3. Act-wide substitutions do not lower the Act's CLEAN sections. High, confirmed

- **What:** "The Placeholder Act (Public Law 150-7) is amended by striking “Administrator” each place it appears …"
  resolves UNKNOWN ("Act named without a section").
- `unapplied_mentions` (`src/billmap/dryrun/verify.py:74-80`) flags a section in only two cases:
  - an unapplied instruction names the section's number;
  - the instruction's target is a "blanket" qualifier.
- **Evidence:** case `act_wide_substitution`. 99 U.S.C. 1, which carries the Act's section 301, is **CLEAN** and still
  says "Administrator".
- **Remedy:**
  - Treat any unapplied instruction whose target is an Act as touching every section that layer 1 maps to that Act.
  - Lower those sections to WARN, and list the instruction in an "applies Act-wide, not executed" bucket.

### F4. Instructions with an unfamiliar verb vanish; the accounting gate shares the blind spot. High, confirmed

- **What:** an instruction exists only where `OP_START` (`src/billmap/parse/ops.py:11`) finds one of its verbs:
  striking, inserting, adding, redesignating, transferring, moving, repealing, or amending … to read.
- `parse_text` (`src/billmap/parse/__init__.py:78`) marks a node AMENDATORY when it contains "amended", but emits
  nothing if no verb matched.
- **Evidence:** zero instructions and no UNPARSED item for:
  - "is amended by replacing “A” with “B”";
  - "by deleting “A”";
  - "by substituting “B” for “A”";
  - "is amended so as to strike";
  - the imperative list "(1) In subsection (a), strike “A” and insert “B”." (amendment-style drafting).
- Case `unknown_verb`: the bill has two instructions, and billmap reports one.
- `scripts/m4_gate.py`'s "count in" comes from `xml_counts`, which calls the same `count_ops`
  (`src/billmap/parse/xmltext.py:172`). So "0 per-location mismatches" proves agreement on segmentation and quotes,
  not that nothing was dropped. The milestone record admits that 57 instructions were once invisible to both.
- **Remedy:**
  - Emit UNPARSED, with its text, for every AMENDATORY node with zero instructions, and for every "amended" clause
    with no recognized verb.
  - Add imperative verbs (strike, insert, add, redesignate).
  - Make the gate's counter genuinely independent. For example, count `<quote>` / `<quoted-block>` elements, which
    every textual instruction must consume. The markup already provides them.

### F5. The held-out test half is neither clean nor independent, and too concentrated to support the 1.51% figure. High, confirmed

| Evidence | Detail |
| --- | --- |
| Concentration | Test half: 43 laws, 853 targets. **118-159 (FY2025 NDAA) 558 and 118-63 (FAA reauthorization) 150 make up 83%.** Title 10 is 445 targets. The tuning corpus is dominated by 119-60 (FY2026 NDAA, title 10: 705 rows). The dev half is a different mix (titles 42, 16, 38, 33) and scores lower (28.8% vs 38.9% CLEAN share). The gap is a title and drafting-style effect, not noise. |
| Fixes from test-half laws | `src/billmap/parse/normalize.py:60` accepts "United Sates Code" "so drafted in Pub. L. 118-159 § 566(b)" (odd number, so test half; commit `d7d4620`, after the split). `src/billmap/dryrun/engine.py:1115` drops repeal stubs per "118-63 § 218" (commit `5426daa`, made on the 152-target first build before the even/odd split existed; the split arrived in `5d50ab4`). |
| Test-half failures steering work | `records/milestones.md` lists the causes of the 7 test-half false-cleans ("an inserted subsection numbered “c.” …") as "the classes to address next". The next round added the inline-enumerator self-check, which lowered exactly that test-half case (42 U.S.C. 2235): 7 → 5 is partly this. A change was reverted because it created a test-half false-clean (5 U.S.C. 6323(b)(1)). Each step is small and reported honestly, but together the test half has been used for model selection. |
| Statistical width | 5 of 332 → 95% Wilson interval **0.64%–3.48%**; 7 of 326 → 1.04%–4.37%. Errors cluster by law and drafting style, so the true uncertainty is wider. The dev half's 0 of 123 is in-sample after fixes; its interval is 0%–3.0% even taken at face value. |

**Remedy:**

- Freeze a new, untouched test set and never read its failures. Candidates:
  - other years' GovInfo editions;
  - the Internet Archive release points, fetched from a machine that can reach them.
- Split by law family or committee, not by public-law parity. At minimum, report non-NDAA results separately.
- Report results per law, with intervals.
- Record every look at the test set in the milestone record.

### F6. The false-clean metric cannot see wrong-section edits; on GovInfo they cannot even be CLEAN. High, confirmed

- **What, in the harness:** the harness (`src/billmap/oracle/harness.py:137-145`) grades only sections in the law's
  classification rows. A prediction for any other section is "extra" or "unexpected_change" and never enters the
  false-clean rate, whatever its status. An edit applied to the wrong section is the error `docs/12-testing.md` calls
  the worst. It shows up only indirectly, as a "missed" correct section.
- **What, in the GovInfo build:** `scripts/build_govinfo_heldout.py:121-135` downloads and indexes **only the target
  sections** of each edition. So when billmap resolves an instruction to a non-target section, the baseline lookup
  fails, the engine returns TARGET_MISSING, and the result can never be CLEAN. In real use the section exists and the
  edit could well be CLEAN.
  - The current GovInfo baseline (`tests/oracle/m6b_govinfo_baseline.json`) has 110 "extra" predictions and 2
    unexpected changes, against 464 CLEAN. Their real status is unknown.
  - The same build also drops every section touched by more than one law in the window (`build_govinfo_heldout.py:89-97`).
    That removes the most heavily amended, hardest sections.
- **Remedy:**
  - Index whole titles for the GovInfo editions, as the tuning oracle does.
  - Count CLEAN predictions on non-target sections that change text as false-cleans, or report them beside the rate.
  - Report the excluded multi-law sections as a separate, harder stratum (predict through all laws in the window).

### F7. Amendments with a delayed effective date are never dry-run. High, confirmed

- **What:** `predict.py:144-147` gives these instructions WARN "not applied" and skips the engine. This reproduces
  OLRC's practice of setting delayed amendments out in a note, which is right for the oracle. It is wrong for a drafting
  tool: the staffer still needs to know whether the quoted text exists.
- **Evidence:** case `delayed_effective_hides_not_found`. "striking “$7,500”" (absent from the section), with "The
  amendments made by this section shall take effect 1 year after …", is reported as WARN "not applied". The NOT_FOUND
  is never reported.
- **Why it matters:** delayed effective dates are very common in drafts. The oracle convention has changed the product's
  meaning here.
- **Remedy:** always run the engine. Report the edit's own status, plus an "effective later; the Code will show it in a
  note" advisory. Keep the oracle convention in the harness, not in the product path.

### F8. Stale quotes match inside longer numbers, and STALE_BASELINE does not exist. Medium, confirmed

- **What:** `find_all`'s word boundary (`src/billmap/dryrun/engine.py:301`) treats "," as a boundary. So "$1,000"
  matches inside "$1,000,000".
- **Evidence:** case `stale_amount_substring`. "striking “$1,000” and inserting “$2,000”" on text reading "$1,000,000"
  gives "$2,000,000", **CLEAN**. This is exactly the stale-draft situation.
- **Related:** STALE_BASELINE, which `docs/06-dry-run.md` calls "likely the check committee staff will value most", is
  declared in the status enums but never produced. `keep_prior = 4` release points are configured, but nothing reads
  them.
- **Remedy:**
  - Treat a digit or comma-and-digit continuation as part of a number when checking boundaries.
  - Implement STALE_BASELINE: on NOT_FOUND, or when a quote matches only as a prefix of a longer number, search the prior
    release points.

### F9. Sentence qualifiers use a naive splitter; misses are mislabelled CONFLICT. Medium, confirmed

- **What:** `_sentence_range` (`engine.py:608`) splits at ". " before a capital letter, so "U.S. Government" ends a
  sentence. `_status_for_missing` (`engine.py:670`) reports CONFLICT ("an earlier instruction in this bill changed it")
  whenever the text exists anywhere in the original unit. It ignores the sentence and matter-preceding qualifiers.
- **Evidence:**
  - Case `sentence_split_wrong_sentence`: the "third sentence" edit lands in the second real sentence, **CLEAN**.
  - Case `sentence_split_abbreviation`: CONFLICT is reported, with no earlier instruction in the bill.
  - Case `qualifier_misdiagnosed_as_conflict`: same misdiagnosis.
- **Remedy:**
  - Use an abbreviation-aware splitter: U.S., U.S.C., Sec., No., et seq., initials.
  - Make a qualified edit WARN when the sentence count is uncertain.
  - Report "found outside the qualified scope" as its own reason.

### F10. A second witness is optional: Code-cite targets have none, and one-witness Act targets stay CLEAN. Medium, confirmed

- **Code cites:** a target drafted as a Code cite is trusted as written (`src/billmap/resolve/resolver.py`, `_usc`).
  Case `wrong_section_same_words`: a draft that names § 103 when it meant § 102 is CLEAN, because the struck words also
  occur in § 103. No tool can know intent. But the section heading, or the Act section in the source credit, could
  serve as a cheap plausibility witness where the draft gives one.
- **Act targets:** an Act target with no parenthetical and no classification row is CODIFIED with the flag "single
  source: source credits only" (`resolver.py:220`). It stays CLEAN (case `act_target_single_witness`), because only
  "needs review" lowers status (`predict.py:152`).
  - Layer 2 (classification tables) only covers 119th-Congress Acts, so for drafts amending older Acts the only second
    witness is the drafter's parenthetical.
  - Early drafts often omit or garble parentheticals. The share of one-witness CLEANs will be higher on drafts than in
    the oracle.
- **Remedy:**
  - Cap one-witness resolutions at WARN, or at least report them as their own bucket.
  - Measure how many oracle CLEANs were one-witness.

### F11. Structural mistakes pass as CLEAN, and the oracle cannot see nesting. Medium, confirmed

- **Wrong label in a replacement:** "striking subsection (b) and inserting “(c) …”" is **CLEAN** (case
  `replace_unit_label_mismatch`). `_in_order` accepts the gap (a), (c). A label that does not continue the sequence is a
  classic drafting error.
- **Duplicate label:** adding "(b)" where (b) exists is WARN only because of an unrelated punctuation advisory (case
  `add_end_duplicate_label`). The duplicate is never named: `structure_problems` runs only on CLEAN sections.
- **No reference check after redesignation:** `docs/06-dry-run.md` requires a references check after REDESIGNATE
  ("broken references"). None is implemented. Redesignations return CLEAN.
- **Nesting is invisible to the oracle:** the oracle compares `text_of` plain text (`src/billmap/data/indexer.py:45`),
  which drops depth. A unit built at the wrong level with the same words "matches". That matters for the comparative
  print and for any later instruction addressed by path.
- **Remedy:**
  - Run the structure checks on every status and name what they find.
  - Check that a replacement block's label equals the replaced label, and that an added label continues the sequence.
  - Compare unit paths as well as text in the harness.

### F12. Hand labels are keyed by section, so they hide future regressions. Medium, confirmed

- **What:** `tests/oracle/labels.json` maps "law + section" to `editorial`. The harness (`harness.py:127`) applies that
  label to *any* later mismatch in the section, whatever the difference.
- **Example:** 10 U.S.C. 2218 and 46 U.S.C. 70001 are long sections. A new substantive error in either would be counted
  editorial forever.
- **Checks on the labels themselves:** I reviewed the eight labels against their documented reasons. Each reason is
  plausible: OLRC slips, a missing "$", a comma dropped with a footnote, a provision OLRC set in from another Act.
- **The automatic detector (`scripts/m6_gate.py:61-78`):** it ignores footnote markers (including any all-digit
  `<sup>`), heading letter case, and any date (or any "date of enactment of the … Act") where the prediction says "the
  date of the enactment of this Act". These are defensible editorial classes. But the date rule accepts *any* date, and
  the heading rule hides case errors that the tool's own heading-case logic is supposed to get right.
- **Remedy:**
  - Store each label with the predicted-text hash and R_after hash it was checked against, and expire it when either
    changes.
  - Report detector-excused CLEANs by class.

### F13. Known bad source sections are not flagged in dry-runs. Low to medium, confirmed by reading the code

- **What:** `billmap sync` records 81 sections whose XML differs in content from the XHTML edition, including 19 U.S.C.
  2702(b)'s missing country list. Only the statute server's `get_section` warns about them (`src/billmap/statute.py:156`).
  `predict.py` never consults `edition_diffs`, so a CLEAN can rest on text known to be incomplete.
- **Related:** `Prediction` and `Result` carry no release point. Rule 3 says every output carries it.
- **Remedy:**
  - Lower CLEAN to WARN on sections in `edition_diffs`.
  - Stamp the release point on every result.

### F14. Several outcomes produce no result at all, and there is no user-facing dry-run yet. Medium, confirmed

- **What:** instructions that resolve NOTE (Act text kept in notes), UNCODIFIED, SPLIT or UNKNOWN get a `Trace` with
  `result=None` (see `run_bill`). So do F2's chapter- and title-wide edits. The gate counts them only as
  `unattributed:<outcome>`.
- **Why it matters:**
  - No CLI command runs a draft through the dry-run. `billmap parse` and `billmap resolve` exist; `analyze` is M12.
  - So "never drop" currently lives in gate traces, not in anything a user sees.
  - The planned report (`docs/11-packaging.md`) has three buckets: Clean, Needs review, Broken. It has no bucket for
    "not executed against the Code" (notes, uncodified Act text, unsupported targets, delayed dates).
- **Remedy:**
  - Give every instruction a terminal status (e.g. NOT_EXECUTED, with a reason).
  - Make the report's first table "instructions in the draft = instructions with a status", by bill location.

### F15. The oracle resolves against the future Code. Suspicion, not measured

- **What:** the gates build the `Resolver` on the pinned current index (119-134) and the current Popular Name table,
  even for 2024 laws checked against the 2023 edition. Source credits then already reflect the law under test and later
  laws.
- Real drafts are resolved against the current Code, so the product is fine. The *measurement*, however, gives the
  resolver information a drafter's tool would not have. It mostly helps Act sections renumbered or added in the window.
- **Remedy:** for each oracle law, resolve against R_before (as the engine already does), or measure the difference
  once.

### F16. The parser is measured only on perfectly formatted input. Medium, structural

- **What:** M4 to M6 parse text rendered from enrolled XML (`src/billmap/parse/xmltext.py:138`). Enumerators, quotes and
  line breaks are exact.
- **Why it matters:** Word drafts lose automatic numbering when pasted, split instructions with soft line breaks, and
  carry tracked changes. `docs/04-draft-parser.md` lists these hazards. The parser's segmentation depends heavily on
  enumerators, so the 0.915 deterministic coverage is an upper bound.
- **Remedy:** before M8, run the oracle again on degraded renderings of the same laws:
  - numbering stripped;
  - line breaks moved;
  - quotes straightened;
  - introduced-version text (below).

## Answers to the seven questions

### 1. Is the oracle test a sound proxy for drafts?

It is a sound test of one thing: *executing well-formed instructions the way OLRC does.* That is necessary but not
sufficient. It misses four things.

**(a) Drafting-error detection.** This is the point of a dry-run for staff. Enacted text has almost no stale quotes,
wrong cites, label gaps or ordinal slips, so recall on those is unmeasured. F1, F8, F10 and F11 show it is weak today.

**(b) Draft-stage formatting** (F16).

**(c) OLRC conventions baked into the product.** Some engine work mimics editorial choices:
- heading case;
- "this Act" printed as "this chapter";
- bracketed cites dropped;
- Act references translated into Code form;
- delayed amendments not applied.

These raise the match rate but are not what a drafter needs. One of them, the delayed-date skip (F7), removes a check.

**(d) Overlapping laws.** GovInfo drops sections touched by more than one law. The tuning corpus avoids corpus overlaps
but not overlaps with non-corpus laws.

Missing draft-specific checks:
- whether the draft is current against today's Code (STALE_BASELINE);
- conflicts between instructions in the same bill (only a "found at baseline but gone" heuristic exists, and it
  misfires, F9).

The substantive/editorial split itself is defensible as a *class* split. Its implementation has the weaknesses in F12.

**Recommended addition:** a drafting-error benchmark. Take enacted instructions and inject realistic errors:
- a stale amount;
- a neighbouring section number;
- the wrong ordinal;
- a mismatched replacement label;
- a quote with one word changed;
- a delayed effective date;
- a chapter-wide substitution.

Measure detection rate (non-CLEAN with the right reason) and false-alarm rate. `docs/12-testing.md` already asks for
mutation tests ("break a quote and expect NOT_FOUND; swap a section number …"). They exist only as a harness self-test
(`scripts/m3_gate.py:43`), not against the engine.

**Also:** use *introduced* versions of later-enacted bills (Congress.gov has them). Run them against the Code at their
introduction date and classify the failures by hand. That is the closest public proxy for real drafts.

### 2. Overfitting and leakage

There is leakage, and it is honestly recorded in pieces but never summarized (F5).

- The tuning corpus was fit to 0 substantive false-cleans, an in-sample figure.
- The 10-law release-point held-out set had 10 targets and 0 CLEANs. It says nothing about false-clean.
- The GovInfo halves are by parity of public-law number. That is not independence: the test half is mostly one NDAA,
  like the tuning corpus.
- Test-half laws drove at least two code changes and one revert, and the test half's failure classes steered a
  self-check.

Treat 1.51% as "roughly 1–4%, measured on NDAA-style title-10 drafting, optimistic." Expect worse on other titles: the
dev half's error *classes* differ.

### 3. What CLEAN guarantees, and ways it is wrong

Guaranteed:
- each instruction the parser emitted for the section matched its quoted text uniquely (or "each");
- the edit was applied at the place found;
- no review rule fired.

Not guaranteed:
- that all of the bill's instructions affecting the section were emitted and placed (F2, F3, F4);
- that the occurrence is the right one (F1);
- that the right sentence was used (F9);
- that the section is the one the drafter meant (F10);
- that the quote is current rather than a prefix of newer text (F8);
- that the structure is right (F11);
- that the source text is complete (F13).

Reproductions of CLEAN and wrong (all in `redteam/synthetic.py`):

| Case | What happens |
| --- | --- |
| `second_place_it_appears` | Every occurrence changed |
| `chapter_wide_substitution` | The chapter edit is dropped; section 101 is CLEAN |
| `title_wide_substitution` | The title edit is dropped; section 102 is CLEAN |
| `act_wide_substitution` | The Act-wide edit is dropped; 99 U.S.C. 1 is CLEAN |
| `stale_amount_substring` | "$1,000" → "$2,000,000" |
| `sentence_split_wrong_sentence` | The edit lands in the wrong sentence |
| `wrong_section_same_words` | The wrong section is edited |
| `act_target_single_witness` | One witness, still CLEAN |
| `replace_unit_label_mismatch` | (b) replaced by (c), leaving a gap |
| `unknown_verb` | The other edit is CLEAN; the dropped instruction is not reported |

The split edits in `engine.py` (`_split`) fall back to WARN when later units would have to move, which is conservative.
The self-checks in `verify.py` are useful but narrow: they fired 5 times in all sets.

### 4. Silent failure and "never drop"

Confirmed losses:
- unknown and imperative verbs (F4);
- CODIFIED chapter- and title-level text edits (F2);
- NOTE, UNCODIFIED, SPLIT and UNKNOWN instructions, which get no result (F14).

These are mitigated in the gate traces, but no user output exists yet.

Checked and sound:
- Quoted blocks that contain amendatory words are not parsed as instructions (case
  `quoted_block_with_instruction_words`).
- "Sections 101, 102, and 103 … are each amended … each place it appears" fans out correctly
  (`several_sections_each_place`).
- Partially read instructions are WARN.
- Ambiguous anchors give AMBIGUOUS.
- The listed-repeal fan-out keeps unknown items as UNKNOWN.
- Blanket targets are reported.

Root-from-context resolutions are flagged. Since d7d4620 a section "of" an unknown law no longer takes its root from
context, which is the right call.

### 5. Data-layer risks that could flatter the scores

The main one is the GovInfo build: target-only baseline index and multi-law sections excluded (F6).

The XHTML→USLM converter (98.2% exact on 119-134) applies the same conversion to the before and after editions. So its
errors mostly cancel, or turn into NOT_FOUND / TARGET_MISSING. They lower scores rather than flatter them, with one
exception: structure errors are invisible to the plain-text comparison (F11).

Classification-table truth:
- a section OLRC changed but did not classify to the law cannot be scored (F6);
- `parse_classification_table` raises on unfit lines rather than skipping them, which is good.

Release-point pinning is sound and recorded. Note that the index (119-134) is already behind the live release (119-136).

### 6. The plan ahead (M7–M12)

**Before M8 (comparative print):**
- Fix F1–F4, F7 and F14, and add the drafting-error benchmark.
- A polished redline built from an edit list that silently lacks instructions is more dangerous than no redline. People
  trust prints.
- Make "every instruction has a status" a gate of M8.
- STALE_BASELINE (F8) should come before the print. The plan itself calls it the most valuable check.

**M7 (Word ingestion):** it is the real input path and the biggest unmeasured risk (F16). Waiting for real drafts is
reasonable for the docx code, but the robustness measurement can start now on degraded public text and introduced bills.

**M11 (model fallback, `docs/10-model-fallback.md`):** "verify deterministically" in the plan means:
- quotes appear in the target;
- cites exist;
- the op is in the enum.

That checks *consistency*, not *correctness*. A model proposal can pass all three and still be wrong: wrong occurrence,
wrong unit, wrong op, wrong section with the same words (exactly F1, F9, F10). Recommendations:
- A model-assisted reading should never be CLEAN. Cap it at WARN, with "model reading" visible.
- Evaluate on a labelled residue set. Measure *verified-but-wrong* as the primary metric, not "verified rate".
- The promotion rule ("≥3 occurrences and ≥90% of proposals verified") promotes on the same weak signal. Promote on
  human-confirmed correctness instead.
- A rule must also come with oracle cases containing the shape. Otherwise "CI blocks any rule that lowers accuracy"
  cannot see it.
- Privacy: the instruction text sent to the model is from unpublished drafts. Keep the confirmation and the `--no-model`
  default as planned.

**M9 (ripple graph) and M10 (flags):** both are lower risk. They read data rather than assert correctness, and they
already plan "possible" labelling and evidence quotes. Possibly over-built relative to the core check. Defer them behind
the items above.

**M12 (packaging):** add an "instructions not executed" bucket and a per-run invariant (count in = statuses out).

### 7. Fitness for purpose today

What you can rely on:
- Section finding for well-formed, LC-style drafts that cite the U.S. Code directly.
- NOT_FOUND / AMBIGUOUS / TARGET_MISSING as real signals.
- The resolver's refusal to guess on conflicting Act evidence. Zero silent mis-resolutions on the M5 sample; I found
  nothing contradicting this for drafts with parentheticals.

What you cannot rely on:
- CLEAN as proof of correctness;
- completeness: that every instruction was considered;
- delayed-effective-date amendments having been checked;
- the 1.51% rate transferring to non-defense titles or to real drafts.

Before using it on the American Passenger Rail Network Act or other real drafts:
1. Fix F1, F2, F3, F4 and F7. Each is a small, contained change.
2. Produce a per-instruction table with a status for every instruction.
3. Read every changed section in a redline, CLEAN included.
4. Treat any instruction without a status as unchecked.

## What I checked and found sound

- **Harness design:**
  - every classified target is counted;
  - missed sections are never CLEAN;
  - WARN is never counted as clean;
  - pending (delayed) amendments are separated;
  - the self-test with oracle, identity and mutated predictors is a good sanity check.
- **Resolver:**
  - the drafted parenthetical acts as a cross-witness;
  - duplicate section numbers and ranges return ambiguous, never a guess;
  - positive-law titles are excluded from layer 1, a careful and correct decision;
  - SPLIT is reported rather than picked.
- **Engine matching:**
  - word-bounded (apart from F8);
  - quote and whitespace folding;
  - case-insensitive matches downgraded to WARN;
  - "found more than once without each" gives AMBIGUOUS;
  - footnote handling and spacing rules are grounded in observed Code examples.
- **Records:** unusually honest. Raw rates are reported beside substantive ones, failures against targets are stated
  plainly, test-half looks and reverts are disclosed, and verify-first findings are documented with sources.
- **Determinism and statute text:** no statute text is hardcoded. Text comes from the index, and tests use synthetic
  text.

## Files

- `redteam/synthetic.py`: the reproducing harness. It builds `var/redteam/synthetic.sqlite` from synthetic USLM
  (placeholder text only) and runs `run_bill` on 22 draft snippets.
- Output from my run: `var/redteam/synthetic_output.txt` (not committed).
- Wilson intervals were computed with the standard formula from the counts in `records/milestones.md`.
