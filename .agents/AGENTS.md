# Skills

Shared agent skills for this repo. Every skill is a directory under `skills/`
containing a `SKILL.md` with YAML frontmatter (`name`, `description`).

Tools discover these through symlinks rather than copies, so there is one source
of truth:

- Claude Code — `.claude/skills` → `.agents/skills`
- Codex — reads the root `AGENTS.md` natively
- Antigravity — `.agent/rules/rules.md` → root `AGENTS.md`

## Available skills

- **Strict maintainability review** — abstraction quality, oversized files,
  condition growth: `skills/thermo-nuclear-code-quality-review/SKILL.md`
- **Adding a competition** — the extension point this codebase is built around:
  `skills/adding-a-competition/SKILL.md`

## Conventions

- `AGENTS.md` is the source of truth; `CLAUDE.md` beside it is a symlink to it.
  Never edit `CLAUDE.md` — it is the same file.
- Every `AGENTS.md` needs a tracked sibling `CLAUDE.md` symlink, and must stay
  under 200 lines. `just check-agents` enforces both.
