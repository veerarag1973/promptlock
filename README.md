# promptlock

Version control and enterprise governance for prompts — so every prompt change is tracked, auditable, and reversible. Designed for teams that need to manage prompts at scale without losing control.

## Install

```bash
pip install promptlock
```

## 60-second quickstart

```bash
# 1. Initialise a project (creates .promptlock/)
promptlock init

# 2. Save a version
promptlock save prompts/summarize.txt -m "Initial version"

# 3. Edit the file, then save again
promptlock save prompts/summarize.txt -m "Switch to bullet point format"

# 4. View history
promptlock log prompts/summarize.txt

# 5. Diff two versions
promptlock diff prompts/summarize.txt v1 v2

# 6. Tag a version
promptlock tag prompts/summarize.txt v2 --name stable-2026-03

# 7. Rollback
promptlock rollback prompts/summarize.txt v1

# 8. Check status
promptlock status
```

No account required. Works fully offline. All history stored in `.promptlock/` in your project.

## Commands (v0.1)

| Command | Description |
|---|---|
| `promptlock init` | Initialise a new project |
| `promptlock save <file> -m "<msg>"` | Save a new version |
| `promptlock log <file>` | View version history |
| `promptlock diff <file> <v1> <v2>` | Diff two versions |
| `promptlock rollback <file> <version>` | Reactivate a previous version |
| `promptlock tag <file> <version> --name <tag>` | Tag a version |
| `promptlock status` | Show which files have unsaved changes |

## License

MIT
