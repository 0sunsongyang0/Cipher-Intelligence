---
name: nuclei-template-planner
description: Prepare a rate-limited Nuclei template validation plan for explicitly authorized assets. Use when defenders need a reviewable target, severity, tag, concurrency, and evidence-retention plan without executing vulnerability scans.
---

# Nuclei Template Planner

1. Require explicit authorization confirmation for every plan.
2. Generate a plan and command preview only; never execute scanning.
3. Use conservative rate and concurrency defaults.
4. Preserve scope, exclusions, evidence path, and human approval requirements.
