# Contributing

Thanks for contributing.

## Before You Start

- Do not commit login state or local secrets (`data/`, `.env*`).
- Open an issue or discussion first for larger changes.
- Keep changes scoped and include tests where practical.

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests
python3 -m py_compile scripts/url_reader.py
./.venv/bin/python -m unittest tests/test_format_rules.py
```

## Pull Requests

- Describe the problem and the user-facing impact.
- Include before/after examples for note output changes.
- If you touch formatting logic, run:
  - `./.venv/bin/python scripts/url_reader.py audit-xhs-format`

## Licensing of Contributions

By submitting a contribution, you agree that:

1. Your contribution may be distributed under the project's community license (`AGPL-3.0-or-later`).
2. The maintainer may include your contribution in commercially licensed editions of this project.

If you cannot agree to the above, please do not submit a contribution.
