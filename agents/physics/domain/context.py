"""Build trusted numeric contexts from parsed physics questions."""

from __future__ import annotations

import re
from typing import Any

from .quantities import expand_quantity_aliases, put_quantity
from .symbols import _normalize_text, canonical_quantity_symbol


_NUMBER_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:(?:[eE][+-]?\d+)|(?:\s*(?:x|\*)\s*10\s*(?:\^|\*\*)?\s*[+-]?\d+))?"
_LENGTH_SCALES = {"m": 1.0, "cm": 1e-2, "mm": 1e-3}
_CHARGE_SCALES = {"c": 1.0, "uc": 1e-6, "muc": 1e-6, "microc": 1e-6, "nc": 1e-9, "pc": 1e-12}


def _parse_number_token(token: str) -> float | None:
    text = _normalize_text(str(token or "")).lower().strip().replace(",", "")
    compact = re.sub(r"\s+", "", text)
    scientific = re.fullmatch(
        r"(?P<coeff>[+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:x|\*)10(?:\^|\*\*)?(?P<exp>[+-]?\d+)",
        compact,
    )
    if scientific:
        return float(scientific.group("coeff")) * (10.0 ** int(scientific.group("exp")))
    try:
        return float(compact)
    except ValueError:
        return None


def _scaled_length(value: str, unit: str) -> float | None:
    numeric = _parse_number_token(value)
    scale = _LENGTH_SCALES.get(str(unit or "").lower())
    if numeric is None or scale is None:
        return None
    return numeric * scale


def _scaled_charge(value: str, unit: str) -> float | None:
    numeric = _parse_number_token(value)
    key = re.sub(r"\s+", "", _normalize_text(str(unit or "")).lower())
    scale = _CHARGE_SCALES.get(key)
    if numeric is None or scale is None:
        return None
    return numeric * scale


def _put_trusted_quantity(quantities: dict[str, float], symbol: str, value: float) -> None:
    canonical = canonical_quantity_symbol(symbol)
    if canonical:
        quantities[canonical] = float(value)


def _raw_text(parsed_question: dict[str, Any]) -> str:
    parts = [str(parsed_question.get("question") or "")]
    parts.extend(str(item) for item in parsed_question.get("relations") or [])
    return _normalize_text(" ".join(parts)).lower()


def _add_trusted_text_quantities(quantities: dict[str, float], parsed_question: dict[str, Any]) -> None:
    text = _raw_text(parsed_question)
    domain = str(parsed_question.get("domain") or "").lower()
    capacitor_context = "capacitor" in text or "capacitance" in domain
    electrostatic_context = "electric" in domain or "charge" in domain or "điện tích" in text

    if electrostatic_context:
        charge_unit = r"(?:micro\s*c|muc|uc|nc|pc|c)"
        chained = re.finditer(
            rf"\b(?P<symbols>q(?:_?test|\d+)?(?:\s*=\s*q(?:_?test|\d+)?)+)\s*=\s*"
            rf"(?P<value>{_NUMBER_PATTERN})\s*(?P<unit>{charge_unit})\b",
            text,
            flags=re.IGNORECASE,
        )
        for match in chained:
            charge = _scaled_charge(match.group("value"), match.group("unit"))
            if charge is None:
                continue
            for symbol in re.split(r"\s*=\s*", match.group("symbols")):
                _put_trusted_quantity(quantities, symbol, charge)

        explicit = re.finditer(
            rf"\b(?P<symbol>q(?:_?test|\d+)?)\s*=\s*(?P<value>{_NUMBER_PATTERN})\s*(?P<unit>{charge_unit})\b",
            text,
            flags=re.IGNORECASE,
        )
        for match in explicit:
            charge = _scaled_charge(match.group("value"), match.group("unit"))
            if charge is not None:
                _put_trusted_quantity(quantities, match.group("symbol"), charge)

    current_match = re.search(
        rf"\bi\s*\(\s*t\s*\)\s*=\s*(?P<amp>{_NUMBER_PATTERN})\s*\*?\s*(?:sin|cos)\s*\(",
        text,
    )
    if current_match and any(term in text for term in ("maximum", "peak", "max", "amplitude", "magnetic field energy")):
        amplitude = _parse_number_token(current_match.group("amp"))
        if amplitude is not None:
            put_quantity(quantities, "I_max", abs(amplitude))

    radius_match = re.search(
        rf"\b(?:radius|r)\b(?:\s+of)?\s*(?:=|is|:)?\s*(?P<value>{_NUMBER_PATTERN})\s*(?P<unit>mm|cm|m)\b",
        text,
    )
    if radius_match:
        radius = _scaled_length(radius_match.group("value"), radius_match.group("unit"))
        if radius is not None:
            put_quantity(quantities, "r", radius)

    if capacitor_context:
        separation_match = re.search(
            rf"\b(?:plate\s+separation|separation|distance|d)\b(?:\s+of)?\s*(?:=|is|:)?\s*(?P<value>{_NUMBER_PATTERN})\s*(?P<unit>mm|cm|m)\b",
            text,
        )
        if separation_match:
            separation = _scaled_length(separation_match.group("value"), separation_match.group("unit"))
            if separation is not None:
                put_quantity(quantities, "d", separation)

        voltage_match = re.search(
            rf"\b(?:voltage|potential difference|u|v)\b(?:\s+across\s+\w+)?\s*(?:=|is|:)?\s*(?P<value>{_NUMBER_PATTERN})\s*v\b",
            text,
        )
        if voltage_match:
            voltage = _parse_number_token(voltage_match.group("value"))
            if voltage is not None:
                put_quantity(quantities, "U", voltage)

        if any(term in text for term in ("air", "vacuum")):
            put_quantity(quantities, "epsilon_r", 1.0)


def build_calculation_input(parsed_question: dict[str, Any]) -> dict[str, Any]:
    """Build trusted numeric context from parsed quantities, geometry, and comparison."""
    quantities: dict[str, float] = {}
    raw_quantities = parsed_question.get("quantities") or {}
    if isinstance(raw_quantities, dict):
        for symbol, value in raw_quantities.items():
            put_quantity(quantities, symbol, value)
    elif isinstance(raw_quantities, list):
        for quantity in raw_quantities:
            if isinstance(quantity, dict):
                value = quantity.get("si_value")
                put_quantity(quantities, quantity.get("symbol"), quantity.get("value") if value is None else value)

    generic_uncertainties: list[Any] = []
    for given in parsed_question.get("givens") or []:
        if not isinstance(given, dict):
            continue
        value = given.get("si_value")
        put_quantity(quantities, given.get("symbol"), given.get("value") if value is None else value)
        uncertainty = given.get("uncertainty") or {}
        if isinstance(uncertainty, dict):
            uncertainty_value = uncertainty.get("si_value")
            if uncertainty_value is None:
                uncertainty_value = uncertainty.get("value")
            symbol = str(given.get("symbol") or "").strip()
            put_quantity(quantities, f"delta_{symbol}", uncertainty_value)
            generic_uncertainties.append(uncertainty_value)
    if len(generic_uncertainties) == 1:
        put_quantity(quantities, "uncertainty", generic_uncertainties[0])
        put_quantity(quantities, "absolute_uncertainty", generic_uncertainties[0])

    geometry = parsed_question.get("geometry") or {}
    if isinstance(geometry, dict):
        for field in ("segments", "derived_distances"):
            for item in geometry.get(field) or []:
                if isinstance(item, dict):
                    value = item.get("si_value")
                    put_quantity(quantities, item.get("symbol"), item.get("value") if value is None else value)

    comparison = parsed_question.get("comparison") or {}
    if isinstance(comparison, dict):
        comparison_value = comparison.get("given_si_value")
        if comparison_value is None:
            comparison_value = comparison.get("given_value")
        comparison_symbol = comparison.get("given_quantity_symbol")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(comparison_symbol or "").strip()):
            comparison_unit = str(comparison.get("given_si_unit") or comparison.get("unit") or "").lower()
            if "hz" in comparison_unit:
                comparison_symbol = "f"
            elif "rad" in comparison_unit:
                comparison_symbol = "omega"
            elif comparison_unit in {"v", "volt", "volts"}:
                comparison_symbol = "U"
        put_quantity(quantities, comparison_symbol, comparison_value)

    _add_trusted_text_quantities(quantities, parsed_question)

    raw_target = parsed_question.get("target") or parsed_question.get("objective") or ""
    if isinstance(raw_target, dict):
        target = str(raw_target.get("symbol") or "")
        unit = str(raw_target.get("unit") or "")
    else:
        target = str(raw_target)
        unit = str(parsed_question.get("unit") or parsed_question.get("objective_unit") or "")
    return {"quantities": expand_quantity_aliases(quantities), "target": target, "unit": unit}
