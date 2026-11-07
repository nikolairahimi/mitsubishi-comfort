"""Comfort app temperature conversion contracts."""

import pytest

from mitsubishi_comfort import fahrenheit_to_setpoint, setpoint_to_fahrenheit


@pytest.mark.parametrize(
    ("fahrenheit", "celsius"),
    [
        (61, 16.0),
        (62, 16.5),
        (63, 17.0),
        (64, 17.5),
        (65, 18.0),
        (66, 18.5),
        (67, 19.5),
        (68, 20.0),
        (69, 21.0),
        (70, 21.5),
        (71, 22.0),
        (72, 22.5),
        (73, 23.0),
        (74, 23.5),
        (75, 24.0),
        (76, 24.5),
        (77, 25.0),
        (78, 25.5),
        (79, 26.0),
        (80, 26.5),
    ],
)
def test_app_setpoint_round_trip(fahrenheit: int, celsius: float) -> None:
    """Every documented app selection retains its label after a device poll."""
    assert fahrenheit_to_setpoint(fahrenheit) == celsius
    assert setpoint_to_fahrenheit(celsius) == fahrenheit


@pytest.mark.parametrize(("celsius", "fahrenheit"), [(19.0, 67), (20.5, 69)])
def test_intermediate_setpoint_labels(celsius: float, fahrenheit: int) -> None:
    assert setpoint_to_fahrenheit(celsius) == fahrenheit


@pytest.mark.parametrize(
    ("fahrenheit", "celsius"),
    [(50, 10.0), (60, 15.5), (81, 27.0), (84, 29.0), (88, 31.0)],
)
def test_arithmetic_fallback(fahrenheit: int, celsius: float) -> None:
    """Fallback values are arithmetic defaults, not confirmed app selections."""
    assert fahrenheit_to_setpoint(fahrenheit) == celsius
    assert setpoint_to_fahrenheit(celsius) == fahrenheit


@pytest.mark.parametrize(
    ("celsius", "fahrenheit"), [(15.0, 59), (28.5, 83), (30.0, 86)],
)
def test_arithmetic_display_fallback(celsius: float, fahrenheit: int) -> None:
    assert setpoint_to_fahrenheit(celsius) == fahrenheit


@pytest.mark.parametrize(
    ("fahrenheit", "celsius"),
    [(71.1, 22.0), (71.5, 22.5), (71.9, 22.5), (72.5, 23.0)],
)
def test_fractional_fahrenheit(fahrenheit: float, celsius: float) -> None:
    assert fahrenheit_to_setpoint(fahrenheit) == celsius


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_fahrenheit(temperature: float) -> None:
    with pytest.raises(ValueError, match="Temperature must be finite"):
        fahrenheit_to_setpoint(temperature)


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_celsius(temperature: float) -> None:
    with pytest.raises(ValueError, match="Temperature must be finite"):
        setpoint_to_fahrenheit(temperature)
