"""Mitsubishi Comfort app setpoint conversions."""

from __future__ import annotations

import math

# Confirmed Comfort app mapping; temperatures outside this range use arithmetic.
_FAHRENHEIT_TO_SETPOINT: dict[int, float] = {
    61: 16.0,
    62: 16.5,
    63: 17.0,
    64: 17.5,
    65: 18.0,
    66: 18.5,
    67: 19.5,
    68: 20.0,
    69: 21.0,
    70: 21.5,
    71: 22.0,
    72: 22.5,
    73: 23.0,
    74: 23.5,
    75: 24.0,
    76: 24.5,
    77: 25.0,
    78: 25.5,
    79: 26.0,
    80: 26.5,
}
_SETPOINT_TO_FAHRENHEIT: dict[float, int] = {
    celsius: fahrenheit for fahrenheit, celsius in _FAHRENHEIT_TO_SETPOINT.items()
}
# These intermediate Celsius settings share the next Fahrenheit label in the app.
_SETPOINT_TO_FAHRENHEIT.update({19.0: 67, 20.5: 69})


def fahrenheit_to_setpoint(temperature: float) -> float:
    """Convert a Fahrenheit request to a Celsius device setpoint.

    The app selects whole Fahrenheit degrees. Round fractional requests to
    the nearest whole degree, with half degrees rounded up. Use the app's
    table for 61–80 °F; elsewhere, use arithmetic rounded to 0.5 °C.
    Non-finite temperatures raise ValueError.
    """
    if not math.isfinite(temperature):
        raise ValueError("Temperature must be finite")
    fahrenheit = math.floor(temperature + 0.5)
    if fahrenheit in _FAHRENHEIT_TO_SETPOINT:
        return _FAHRENHEIT_TO_SETPOINT[fahrenheit]
    celsius = (fahrenheit - 32) / 1.8
    return round(celsius * 2) / 2


def setpoint_to_fahrenheit(temperature: float) -> int:
    """Convert a Celsius setpoint to the app's whole-degree Fahrenheit label.

    Use arithmetic rounding outside the known table. This helper describes
    thermostat setpoints, not a general-purpose sensor unit conversion.
    Non-finite temperatures raise ValueError.
    """
    if not math.isfinite(temperature):
        raise ValueError("Temperature must be finite")
    if temperature in _SETPOINT_TO_FAHRENHEIT:
        return _SETPOINT_TO_FAHRENHEIT[temperature]
    return round(temperature * 1.8 + 32)
