# Agent Sessions

An operational journal, chained oldest to newest through `next:`. One session per
continuous stretch of work; a new one when the gate closes the last.

Filenames are `YYYY-MM-DD-HHMMSS-kebab-slug`. Frontmatter carries `date` and
`type` for this vault, plus `timestamp`, `branch` and `status`, which the
workspace session gate reads to decide whether writes are allowed.

A session log records intent, decisions and what carried forward — not a
transcript. Durable conclusions graduate to `Knowledge/` or `Architecture/ADR/`.
