"""Scalar coercion and validation helpers shared by contract types and validators."""

from __future__ import annotations

import math
import numbers
from contextlib import contextmanager
from typing import Any, Iterator

import numpy as np

from src.contracts.errors import ContractValidationError


def is_real_number(value: Any) -> bool:
    """True for int/float/NumPy numbers; False for bool, str, None and containers."""
    return isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_))


def require_finite(field: str, value: Any) -> float:
    """Return ``value`` as a finite built-in float (``-0.0`` is normalised to ``0.0``)."""
    if not is_real_number(value):
        raise ContractValidationError(field, f"must be a real number; got {type(value).__name__}")
    try:
        number = float(value)
    except OverflowError:
        raise ContractValidationError(field, "must be finite; value overflows float") from None
    if not math.isfinite(number):
        raise ContractValidationError(field, f"must be finite; got {number!r}")
    return number + 0.0


def require_nonnegative(field: str, value: Any) -> float:
    number = require_finite(field, value)
    if number < 0.0:
        raise ContractValidationError(field, f"must be >= 0; got {number!r}")
    return number


def require_unit_interval(field: str, value: Any) -> float:
    number = require_finite(field, value)
    if not 0.0 <= number <= 1.0:
        raise ContractValidationError(
            field,
            f"must be a fraction within [0, 1]; got {number!r} (0-100 percentages are not accepted)",
        )
    return number


def require_int(
    field: str, value: Any, *, minimum: int | None = None, maximum: int | None = None
) -> int:
    """Return a built-in int; floats (even integral ones) and bools are rejected."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Integral):
        raise ContractValidationError(field, f"must be an integer; got {type(value).__name__}")
    return _check_int_range(field, int(value), minimum, maximum)


def require_whole_number(field: str, value: Any, *, minimum: int | None = None) -> int:
    """Accept ints or integral floats (JSON numbers such as ``120.0``) and return an int."""
    if isinstance(value, (bool, np.bool_)):
        raise ContractValidationError(field, "must be a whole number; got bool")
    if isinstance(value, numbers.Integral):
        return _check_int_range(field, int(value), minimum, None)
    number = require_finite(field, value)
    if not number.is_integer():
        raise ContractValidationError(field, f"must be a whole number; got {number!r}")
    return _check_int_range(field, int(number), minimum, None)


def _check_int_range(field: str, number: int, minimum: int | None, maximum: int | None) -> int:
    if minimum is not None and number < minimum:
        raise ContractValidationError(field, f"must be >= {minimum}; got {number}")
    if maximum is not None and number > maximum:
        raise ContractValidationError(field, f"must be <= {maximum}; got {number}")
    return number


def require_str(field: str, value: Any, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(field, f"must be a string; got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise ContractValidationError(field, "must be a nonempty string")
    return value


def require_bool(field: str, value: Any) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ContractValidationError(field, f"must be a boolean; got {type(value).__name__}")
    return bool(value)


@contextmanager
def field_prefix(prefix: str) -> Iterator[None]:
    """Re-raise nested validation errors with a dotted path prefix."""
    try:
        yield
    except ContractValidationError as exc:
        raise ContractValidationError(f"{prefix}.{exc.field}", exc.reason) from None
