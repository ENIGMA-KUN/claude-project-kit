---
name: recall
description: Look up project knowledge before guessing. Searches the knowledge graph for architecture, past decisions, known pitfalls, solved problems and domain terms, and follows its relations. Use when a task touches an unfamiliar module, when an error looks familiar, or when you are about to make a design choice.
when_to_use: "Unfamiliar module, recurring error, design choice, 'how do we usually...', 'why is X like this'."
effort: low
allowed-tools: Bash(python .claude/kit/kg.py *) Bash(python3 .claude/kit/kg.py *) Read Grep Glob
---

# Recall project knowledge

Query: `$ARGUMENTS` (if empty, derive search terms from the current task: module names, error text, function names, domain words).

1. Search. Error strings and symbol names work well because retrieval is lexical (BM25):

   ```
   python .claude/kit/kg.py query "<terms>" -k 5
   ```

   Add `--type lesson` (or `decision`, `architecture`, `solution`) to narrow, `--all` to include candidates and superseded nodes when you need history.

2. Read the top one to three files that look relevant. Follow their edges with `python .claude/kit/kg.py show <id>` when a `depends_on`, `supersedes` or `contradicts` edge matters for the task.

3. Use what you found, and cite the node path when it changes what you do ("per knowledge/decisions/x.md, we keep auth in middleware").

4. If a node is wrong or outdated, say so to the user and offer `/learn` to update it. If a `superseded` node is the only match, look for its successor before using it.

5. If nothing relevant exists and you then work the answer out, mention that it would make a good node and offer `/learn`.

`knowledge/index.md` lists every active node with a one-line summary if you need to browse instead of search.
