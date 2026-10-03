"""Typed boundary errors defined by docs/SHARED_CONTRACTS.md section 4.

Orchestration catches only these defined failures. Programming errors are
never relabelled as business results.
"""

from __future__ import annotations


class CarbonOptError(Exception):
    """Base class for all defined CarbonOpt boundary errors."""


class ContractValidationError(CarbonOptError, ValueError):
    """Invalid column/type/range/unit/config. Carries the offending field."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


class UnsupportedHorizon(CarbonOptError, ValueError):
    """Requested horizon is not advertised by the forecast provider."""

    def __init__(self, horizon_months: int, supported: tuple[int, ...]) -> None:
        self.horizon_months = horizon_months
        self.supported = tuple(supported)
        super().__init__(
            f"horizon_months={horizon_months} is not supported; "
            f"supported horizons: {list(self.supported)}"
        )


class ProviderError(CarbonOptError, RuntimeError):
    """A provider failed at its public boundary. Never replaced by mock output."""


class ForecastConfigurationError(ProviderError):
    """Invalid or leaking feature/forecast configuration (WS1)."""


class ForecastError(ProviderError):
    """Model training or prediction failed (WS1)."""


class SimulationError(ProviderError):
    """The action simulator failed (WS2)."""


class OptimizationError(ProviderError):
    """Unexpected solver failure (WS2). Infeasibility is NOT an error."""


class RiskError(ProviderError):
    """Risk evaluation failed (WS3, optional capability)."""


class UnsupportedMockInput(ProviderError):
    """A fixture/shape stub was asked for an input it does not cover.

    Shape stubs must not pretend to compute arbitrary requests
    (docs/TESTING_AND_MOCKS.md section 2).
    """


class ProviderConfigurationError(CarbonOptError, RuntimeError):
    """Services could not be wired, e.g. a required P0 provider is missing in
    real mode. Raised at service creation, before any computation."""

    def __init__(self, message: str, *, missing: tuple[str, ...] = ()) -> None:
        self.missing = tuple(missing)
        super().__init__(message)


class CapabilityUnavailable(CarbonOptError, RuntimeError):
    """An optional capability was requested but is not available."""
