## PR Reviewer Guide

Merge recommendation: changes_required
Security concerns: Possible SQL injection in the new query builder

### Findings
- [high] `src/db.py:42` — string-concatenated query with user input
- `scripts/run.sh:7` [low]: missing quote around variable
- Sin fichero ni línea: esto no es un hallazgo localizable
