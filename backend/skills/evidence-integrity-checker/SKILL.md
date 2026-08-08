---
name: evidence-integrity-checker
description: Assess whether investigation evidence is complete and ready for signing. Use for checking review status, content hashes, duplicate artifacts, confidence, source trust, and unresolved evidence gaps before a case conclusion is approved.
---

# Evidence Integrity Checker

1. Check every evidence item for review state and content hash.
2. Detect duplicate hashes and low-confidence or low-trust evidence.
3. Return blocking issues separately from warnings.
4. Mark signing readiness false whenever any blocking issue remains.
