---
paths:
  - "knowledge/**"
---

# Writing knowledge nodes

Loaded only when you read or edit files under `knowledge/`. The full schema is in `knowledge/_schema.md`.

- One concept per file. The path is the id: `knowledge/lessons/use-uv-not-pip.md` is `lessons/use-uv-not-pip`.
- Frontmatter needs `type`, `title`, `description`, `status`, `source`, `created`, `updated`, `review_by`. Lessons also need a one-line imperative `rule` and a `trigger` list of words that appear when the problem recurs (error text, command, file name).
- Link related nodes through `relations` (`depends_on`, `supersedes`, `superseded_by`, `part_of`, `implements`, `related`, `contradicts`, `caused_by`, `fixes`, `example_of`). Use node ids, not file paths.
- Search before writing: `python .claude/kit/kg.py query "<title words>" --all`. Update an existing node instead of creating a near-duplicate.
- Separate the reusable principle from the concrete fix. A lesson that only describes one bug never matches the next one.
- Never delete a node. Set `status: superseded` and link the successor, or `status: archived`.
- After any change run `python .claude/kit/kg.py build` then `python .claude/kit/kg.py validate`, and add one line with `python .claude/kit/kg.py log "<what changed>"`.
- `index.md` and `_graph.json` are generated. Do not edit them by hand.
