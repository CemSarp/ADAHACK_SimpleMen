# Contract fixture kit, revision v1

Synthetic contract examples used by the tests, the mock providers and the WS2 CLI
(`docs/TESTING_AND_MOCKS.md` §1). `risk_sample_mock_simulator.json` is a golden 1,000-trial
Monte Carlo run over the behavioral mock simulator.

Fixtures are immutable per revision: change numerical expectations only with
domain-owner review, never by regenerating snapshots to silence a failing test.

All payloads carry `provenance.is_mock = true`. They describe contract shapes and hand-derived
illustrative arithmetic, not a trained forecast, a completed search or calibrated economics.
