# Changelog

## Unreleased — 2026-10-22

- Added a deterministic two-phase prepare/commit freshness gate that binds the approved action, transition, policy and evidence versions, then revalidates them immediately before the simulated mutation.
- Added serializable commit-section semantics and fail-closed handling for new holds, authority revocation or expiry, changed parameters, unavailable registries and duplicate commit attempts.
- Added a frozen development-only configuration, plan-only deterministic runner, five comparison modes, thirteen conditions and 30 focused tests; the formal versioned run remains pending.

## 0.1.1 — 2026-10-21

- Reject non-Boolean authentication, transferability, integrity and policy flags instead of coercing strings or numbers.
- Reject unknown fields, missing required policy/state fields and invalid snapshot references during contract loading.
- Require the critical event to support a proof card and matched noise to support none.
- Keep report filenames inside the selected output directory even when an imported suite ID contains path separators.
- Return a clear CLI input error for invalid contracts or selections.
- Clarify canonical-record, simulated-state and proof-source-selector assumptions in the documentation.

## 0.1.0 — 2026-10-21

- Added a declarative memory crash-test contract.
- Added full-evidence, action-critical deletion, and byte-matched noise siblings.
- Added provenance-typed proof validation and Execute / Confirm / Handoff routing.
- Added deterministic external state replay and harmful-mutation detection.
- Added optional point-in-time durable proof registry lookup.
- Added JSON and JUnit reports with nonzero CI exit status on regressions.
- Added an installable CLI, starter-contract generator, JSON Schema, and copy-ready CI workflow template.

This release is a research preview, not a production safety certification.
