# Contract fixture kit, revision v1

Byte-identical copies of the synthetic examples in `carbonopt-ai-docs/examples/`, placed at the
C0 fixture location named in `docs/TESTING_AND_MOCKS.md` §1. Only the files WS2 consumes or
produces are copied; benchmark fixtures stay with WS3.

`tests/contracts/test_contracts_foundation.py` fails if a copy drifts from its documentation
source. Fixtures are immutable per revision: change numerical expectations only with
domain-owner review, never by regenerating snapshots to silence a failing test.

All payloads carry `provenance.is_mock = true`. They describe contract shapes and hand-derived
illustrative arithmetic, not a trained forecast, a completed search or calibrated economics.
