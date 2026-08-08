---
name: firewall-blocklist-builder
description: Build a deduplicated and reviewable network blocklist from confirmed case indicators. Use when analysts need firewall, DNS, proxy, or EDR containment material from malicious IP addresses, domains, and URLs.
---

# Firewall Blocklist Builder

1. Accept only reviewed malicious or suspicious indicators.
2. Normalize and deduplicate values while preserving indicator type.
3. Exclude file hashes from network blocklists and report them separately.
4. Mark generated output as a draft requiring change approval and rollback planning.
