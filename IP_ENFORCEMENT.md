# IP Enforcement Playbook

This document describes a practical process to detect and preserve evidence for
possible unauthorized commercial usage.

## 1. What to collect

- Generated note frontmatter fields:
  - `generator`
  - `generator_version`
  - `license_mode`
  - `fingerprint_id`
- Hidden trace comment at the end of each note (`XOP-Trace`)
- Proof export CSV (`export-xhs-proof`)
- File hash (`file_sha256` in CSV)

## 2. Weekly routine

1. Run format audit:
   `./.venv/bin/python scripts/url_reader.py audit-xhs-format`
2. Export proof report:
   `./.venv/bin/python scripts/url_reader.py export-xhs-proof`
3. Archive proof report with date:
   `xhs_proof_report_YYYYMMDD.csv`

## 3. External monitoring suggestions

- Search for unique fingerprint tokens (`xop-` prefix + your sample IDs)
- Search for unique trace marker: `XOP-Trace`
- Search for unique generator string: `xhs-obsidian-pipeline`
- Monitor products/pages that replicate your exact note schema

## 4. Evidence preservation checklist

When you find a suspicious service:

1. Save full-page screenshots (with URL bar visible)
2. Save HTML source and downloaded output files if possible
3. Record timestamps and access path
4. Run hash on collected files and keep immutable copies
5. Compare against your `export-xhs-proof` records

## 5. Escalation path

1. Send compliance notice with specific evidence and license references
2. Offer commercial licensing path if business-fit exists
3. Escalate to legal counsel for formal takedown/claims if unresolved

