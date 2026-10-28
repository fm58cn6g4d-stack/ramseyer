-- billmap index schema (docs/02-data-layer.md). One database holds several release points.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS release_points (
    id          INTEGER PRIMARY KEY,
    label       TEXT NOT NULL UNIQUE,      -- "119-134"
    date        TEXT,                      -- as printed by OLRC, "October 20, 2026"
    source_url  TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    loaded_at   TEXT NOT NULL,
    complete    INTEGER NOT NULL DEFAULT 0  -- 1 only after every title loaded and checked
);

CREATE TABLE IF NOT EXISTS titles (
    rp          INTEGER NOT NULL REFERENCES release_points(id),
    title       TEXT NOT NULL,             -- "4", "5a"
    member      TEXT NOT NULL,             -- zip member, "usc05A.xml"
    publication TEXT,                      -- docPublicationName, "Online@119-134"
    positive_law INTEGER,                  -- from meta property is-positive-law
    currency    TEXT,                      -- per-title "current through" from the download page
    node_id     INTEGER,
    sections    INTEGER NOT NULL,
    PRIMARY KEY (rp, title)
);

CREATE TABLE IF NOT EXISTS nodes (
    id          INTEGER PRIMARY KEY,
    rp          INTEGER NOT NULL REFERENCES release_points(id),
    title       TEXT NOT NULL,
    parent_id   INTEGER REFERENCES nodes(id),
    section_id  INTEGER,                   -- enclosing section (self for a section), NULL above sections
    kind        TEXT NOT NULL,             -- USLM element name: title, chapter, section, subsection, ...
    identifier  TEXT NOT NULL,             -- first USLM identifier
    num         TEXT,                      -- printed designation, "§ 1." or "(a)"
    heading     TEXT,
    path        TEXT NOT NULL,             -- "(a)(2)(B)" below a section, "" for a section, "ch1/schI" above
    status      TEXT NOT NULL,             -- current, repealed, omitted, transferred, renumbered, reserved, vacant, unknown
    text_plain  TEXT NOT NULL,             -- operative text of the unit and its descendants (no notes, credits
                                           -- or tables of contents); above a section only num and heading
    xml_line    INTEGER,                   -- source line in the title XML member
    ord         INTEGER NOT NULL,          -- document order within the release point
    synthetic   INTEGER NOT NULL DEFAULT 0 -- 1: OLRC gave no identifier; billmap built one with a "~" step
);
CREATE INDEX IF NOT EXISTS nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS nodes_section ON nodes(section_id);
CREATE INDEX IF NOT EXISTS nodes_rp_kind ON nodes(rp, kind);

-- Every identifier, including each one of a multi-section node ("/us/usc/t2/s3 /us/usc/t2/s4").
CREATE TABLE IF NOT EXISTS node_ident (
    rp          INTEGER NOT NULL,
    identifier  TEXT NOT NULL,
    node_id     INTEGER NOT NULL REFERENCES nodes(id),
    PRIMARY KEY (rp, identifier, node_id)
);

CREATE TABLE IF NOT EXISTS section_xml (
    node_id     INTEGER PRIMARY KEY REFERENCES nodes(id),
    xml_zlib    BLOB NOT NULL               -- the section element exactly as published, zlib-compressed
);

CREATE TABLE IF NOT EXISTS refs (
    id          INTEGER PRIMARY KEY,
    rp          INTEGER NOT NULL,
    src_id      INTEGER NOT NULL REFERENCES nodes(id),   -- innermost indexed unit holding the ref
    dst_id      INTEGER REFERENCES nodes(id),            -- NULL when unresolved; see reason
    dst_raw     TEXT NOT NULL,                           -- href as published
    kind        TEXT NOT NULL,             -- usc, pl, act, stat, other
    context     TEXT NOT NULL,             -- text, note, credit
    anchor_text TEXT,
    reason      TEXT NOT NULL              -- resolved | <why not>
);
CREATE INDEX IF NOT EXISTS refs_src ON refs(src_id);
CREATE INDEX IF NOT EXISTS refs_dst ON refs(dst_id);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES nodes(id),   -- owning node: a section, or a chapter etc.
    note_type   TEXT NOT NULL,             -- USLM topic ("referencesInText", ...) or "footnote" / "untyped"
    heading     TEXT,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS notes_section ON notes(section_id);

CREATE TABLE IF NOT EXISTS source_credits (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES nodes(id),
    pl          TEXT,                      -- "117-58"; NULL for pre-public-law Acts (see act_ref)
    pl_section  TEXT,                      -- href remainder after the law, "dA/tIII/s301/b"
    act_ref     TEXT,                      -- /us/act/... href when the credit cites an Act by date/chapter
    date        TEXT,                      -- ISO date following the ref, when present
    raw         TEXT NOT NULL              -- full credit text
);
CREATE INDEX IF NOT EXISTS credits_pl ON source_credits(pl, pl_section);

CREATE TABLE IF NOT EXISTS definitions (
    id          INTEGER PRIMARY KEY,
    section_id  INTEGER NOT NULL REFERENCES nodes(id),   -- unit holding the definition
    term        TEXT NOT NULL,
    scope_kind  TEXT NOT NULL,             -- section, chapter, title, ... as written ("In this chapter")
    scope_id    INTEGER REFERENCES nodes(id),            -- NULL when the scope unit could not be found
    reason      TEXT NOT NULL,             -- resolved | <why not>
    evidence    TEXT NOT NULL              -- the matched sentence fragment
);
CREATE INDEX IF NOT EXISTS definitions_term ON definitions(term);

CREATE TABLE IF NOT EXISTS text_hash (
    node_id     INTEGER PRIMARY KEY REFERENCES nodes(id),
    rp          INTEGER NOT NULL,
    hash        TEXT NOT NULL              -- sha256 of text_plain
);

CREATE TABLE IF NOT EXISTS load_issues (
    id          INTEGER PRIMARY KEY,
    rp          INTEGER NOT NULL,
    title       TEXT,
    kind        TEXT NOT NULL,
    detail      TEXT NOT NULL
);

-- Sections only; external content keeps a single copy of the text.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_nodes USING fts5(
    heading, text_plain, content='nodes', content_rowid='id', tokenize='porter unicode61'
);
