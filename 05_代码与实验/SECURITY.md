# Security Policy

## Research-preview boundary

Agent Memory Crash Test is a testing and research tool. A passing report is not
a production safety certification and does not replace authorization controls,
transaction checks, identity enforcement, sandboxing, or human review.

The reference registry is deterministic and local. It does not model network
partitions, stale replicas, concurrent revocation, compromised issuers,
availability failures, or time-of-check/time-of-use races.

## Reporting a vulnerability

Please open a GitHub issue for ordinary bugs. For a vulnerability that could
make a failing memory or authorization case appear to pass, contact the
maintainers privately before publishing exploit details. Include the smallest
reproducible contract, observed decision, expected decision, and tool version.

Do not include credentials, personal data, or private production traces in a
report.
