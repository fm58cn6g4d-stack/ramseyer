# 7 Ripple graph

The ripple graph shows what the amended sections touch, so a change to a term or a section number can be traced before it reaches Legislative Counsel.

## Nodes and edges

| Element | Source | Label |
| --- | --- | --- |
| Node: amended section | Dry-run results | Amended |
| Node: neighbor section | refs table | Cites or cited by |
| Edge: cites | refs table, outbound | Formal reference |
| Edge: cited by | refs table, inverted | Formal reference |
| Edge: definition use | definitions table, then a phrase search of the term inside the definition's scope | Possible (text match, not a formal reference) |
| Edge: broken by redesignation | Dry-run REDESIGNATE results | Warning |

## Metrics

In-degree per section, cross-title edges highlighted, and a count of how many amended sections each neighbor connects to.

## Rendering

- One self-contained HTML file, Cytoscape.js from cdnjs, no build step
- Node color by Code title, size by in-degree
- Clicking a node shows the section snippet, the citing sentence and a link to uscode.house.gov
- Filters: title, hop count (default 1, optional 2) and edge type
- Export of the visible edges to CSV
- A cap of about 300 nodes with a show-more control, and a list of anything hidden

## Guardrails

- Definition edges are labeled Possible everywhere they appear
- The page shows the release point and generation time
- v2: CFR edges from eCFR, and Statutes at Large references

## Tests

- Graph edges equal the refs table (symmetry check for cites and cited-by)
- A known heavily cited section returns its expected neighbors
- 50 amended sections render in a few seconds
