# Sample project: orders-service

A fictional FastAPI billing service after one month with the kit. The source files are stubs; the point is the `knowledge/` folder, which shows what `/kit-init`, `/learn` and `/curate` produce over time.

| Node | Came from |
|------|-----------|
| `architecture/*` (4) | `/kit-init` scanning the repo |
| `decisions/three-layer-architecture`, `decisions/uuid-public-ids` | an ADR and the `/kit-init` interview |
| `concepts/active-customer` | the `/kit-init` interview |
| `lessons/never-query-db-from-routes` | a correction during a code review |
| `lessons/store-timestamps-in-utc`, `solutions/flaky-timezone-test` | a debugging session, saved with `/learn` |
| `lessons/use-uv-not-pip` | a correction ("no, we use uv") |
| `_inbox/2026-11-20-hook-blocks-pip` | `/curate`: the uv lesson was recalled but the mistake recurred, so it proposes a hook |

Try the engine on it from the kit root:

```bash
python template/.claude/kit/kg.py --root examples/sample-project query "pip install fails with ModuleNotFoundError"
python template/.claude/kit/kg.py --root examples/sample-project show lessons/never-query-db-from-routes
python template/.claude/kit/kg.py --root examples/sample-project validate
python template/.claude/kit/kg.py --root examples/sample-project mermaid
```

Start reading at [knowledge/index.md](knowledge/index.md) and [knowledge/log.md](knowledge/log.md).
