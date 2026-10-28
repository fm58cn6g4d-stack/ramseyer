# 2 Free statute server

A local MCP server replaces the paid statute server. It wraps the same library the pipeline uses, so each function is built and tested once.

## Tools

| Tool | Input | Returns |
| --- | --- | --- |
| resolve\_cite | A Bluebook-style citation string | Canonical cite, node id, status, link to uscode.house.gov, release point |
| get\_section | Cite or id; format (plain, xml, operative); optional as\_of | Section text, optional subsection tree, release point |
| get\_pincite | Cite with a subsection path | Text of that unit and its parent heading |
| cross\_refs | Cite or id | Outbound references, resolved where possible |
| cited\_by | Cite or id; limit | Sections that cite it, with the citing sentence |
| definitions | Cite or id | Terms defined in the section and their scope |
| neighbors | Cite or id | Parent chapter, sibling sections, adjacent sections |
| search | Query; optional title; limit | FTS5 matches with snippets, BM25 ranked, phrase and title filters |
| changes | Cite or id; from and to release points | Added, removed and changed text |
| coverage | none | Titles loaded, release point, counts |
| act\_to\_code | Public law number and section | Code or note locations, from tab 4 |

## Design

- Library functions come first; MCP tools are thin wrappers; the CLI exposes the same functions
- stdio transport, with sample configs for Claude Desktop and Claude Code in the README
- Compact JSON with size caps; the operative format returns only the legal text, without notes, to save tokens
- Error codes: not\_found, ambiguous, repealed, out\_of\_range
- Every response includes the release point

## Non-goals

State law, case law and the Federal Register. CFR and Statutes at Large arrive in v2.

## Acceptance

50 spot checks against uscode.house.gov match exactly, and cited\_by results equal the inverted refs table.
