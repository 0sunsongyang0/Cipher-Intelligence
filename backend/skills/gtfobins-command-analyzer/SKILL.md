---
name: gtfobins-command-analyzer
description: Identify Unix and Linux command lines that resemble GTFOBins privilege, shell, file access, or restriction-bypass patterns. Use for defensive review of sudo logs, shell history, EDR process telemetry, and incident response evidence.
---

# GTFOBins Command Analyzer

1. Analyze supplied commands without executing them.
2. Identify binary, capability category, and observable indicators.
3. Prioritize sudo, SUID, shell spawn, file write, and download behavior.
4. Return defensive pivots and state that a match alone is not proof of compromise.
