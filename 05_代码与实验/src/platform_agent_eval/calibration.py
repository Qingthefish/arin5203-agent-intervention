from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev

from .domain import Decision


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


@dataclass(frozen=True)
class LogisticCalibrator:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    bias: float

    def predict_proba(self, features: Mapping[str, float]) -> float:
        missing = set(self.feature_names) - set(features)
        if missing:
            raise ValueError(f"Missing calibration features: {sorted(missing)}")
        standardized = [
            (float(features[name]) - mean) / scale
            for name, mean, scale in zip(self.feature_names, self.means, self.scales)
        ]
        return _sigmoid(
            self.bias
            + sum(weight * value for weight, value in zip(self.weights, standardized))
        )


def fit_logistic_calibrator(
    rows: Sequence[Mapping[str, float]],
    labels: Sequence[bool | int],
    *,
    learning_rate: float = 0.05,
    iterations: int = 2000,
    l2: float = 0.01,
) -> LogisticCalibrator:
    """Fit a deterministic, dependency-free logistic model on training data."""

    if not rows or len(rows) != len(labels):
        raise ValueError("Feature rows and labels must be non-empty and aligned")
    if len({bool(label) for label in labels}) < 2:
        raise ValueError("Calibration labels must contain both classes")
    feature_names = tuple(sorted(rows[0]))
    if not feature_names:
        raise ValueError("At least one feature is required")
    if any(set(row) != set(feature_names) for row in rows):
        raise ValueError("All calibration rows must share the same feature schema")

    columns = [[float(row[name]) for row in rows] for name in feature_names]
    means = tuple(fmean(column) for column in columns)
    scales = tuple(max(pstdev(column), 1e-8) for column in columns)
    matrix = [
        [
            (float(row[name]) - mean) / scale
            for name, mean, scale in zip(feature_names, means, scales)
        ]
        for row in rows
    ]
    targets = [float(bool(label)) for label in labels]
    weights = [0.0] * len(feature_names)
    positive_rate = sum(targets) / len(targets)
    bias = math.log(positive_rate / (1.0 - positive_rate))
    for _ in range(iterations):
        predictions = [
            _sigmoid(bias + sum(weight * value for weight, value in zip(weights, row)))
            for row in matrix
        ]
        errors = [prediction - target for prediction, target in zip(predictions, targets)]
        bias -= learning_rate * fmean(errors)
        for index in range(len(weights)):
            gradient = (
                sum(error * row[index] for error, row in zip(errors, matrix))
                / len(matrix)
                + l2 * weights[index]
            )
            weights[index] -= learning_rate * gradient
    return LogisticCalibrator(
        feature_names=feature_names,
        means=means,
        scales=scales,
        weights=tuple(weights),
        bias=bias,
    )


@dataclass(frozen=True)
class RoutingThresholds:
    execute_below: float
    confirm_if_resolvable_at_least: float


def calibrated_three_way_decision(
    harm_probability: float,
    resolvable_probability: float,
    thresholds: RoutingThresholds,
) -> Decision:
    if not 0.0 <= harm_probability <= 1.0:
        raise ValueError("harm_probability must be in [0, 1]")
    if not 0.0 <= resolvable_probability <= 1.0:
        raise ValueError("resolvable_probability must be in [0, 1]")
    if harm_probability < thresholds.execute_below:
        return Decision.AUTO_EXECUTE
    if resolvable_probability >= thresholds.confirm_if_resolvable_at_least:
        return Decision.REQUEST_CONFIRMATION
    return Decision.HANDOFF


def select_three_way_thresholds(
    harm_probabilities: Sequence[float],
    resolvable_probabilities: Sequence[float],
    unsafe_labels: Sequence[bool | int],
    resolvable_labels: Sequence[bool | int],
    *,
    max_unsafe_execution_rate: float = 0.05,
    grid: Sequence[float] = tuple(index / 20 for index in range(1, 20)),
) -> RoutingThresholds:
    """Select thresholds on development data with a safety constraint.

    Feasible pairs minimize weighted routing burden. If no pair satisfies the
    requested unsafe-execution limit, the safest pair wins and cost breaks ties.
    Exact performance ties choose boundaries with the largest distance from
    development predictions, rather than an arbitrary edge of an empty gap.
    """

    lengths = {
        len(harm_probabilities),
        len(resolvable_probabilities),
        len(unsafe_labels),
        len(resolvable_labels),
    }
    if len(lengths) != 1 or not harm_probabilities:
        raise ValueError("Development arrays must be non-empty and aligned")
    if not 0.0 <= max_unsafe_execution_rate <= 1.0:
        raise ValueError("max_unsafe_execution_rate must be in [0, 1]")

    candidates: list[tuple[tuple[float, ...], float, float]] = []
    total = len(harm_probabilities)
    for execute_below in grid:
        for resolve_at_least in grid:
            thresholds = RoutingThresholds(execute_below, resolve_at_least)
            decisions = [
                calibrated_three_way_decision(harm, resolvable, thresholds)
                for harm, resolvable in zip(harm_probabilities, resolvable_probabilities)
            ]
            unsafe_exec = sum(
                decision is Decision.AUTO_EXECUTE and bool(unsafe)
                for decision, unsafe in zip(decisions, unsafe_labels)
            ) / total
            burden = sum(
                0.0
                if decision is Decision.AUTO_EXECUTE
                else 1.0
                if decision is Decision.REQUEST_CONFIRMATION
                else 3.0
                for decision in decisions
            ) / total
            # A futile confirmation is more costly than a conservative handoff:
            # it consumes a user round trip and still ends in escalation. An
            # avoidable handoff remains an error, but does not expose the state.
            route_error = sum(
                5.0
                if (
                    decision is Decision.REQUEST_CONFIRMATION
                    and bool(unsafe)
                    and not bool(resolvable)
                )
                else 1.0
                if (
                    decision is Decision.HANDOFF
                    and bool(unsafe)
                    and bool(resolvable)
                )
                else 0.0
                for decision, unsafe, resolvable in zip(
                    decisions, unsafe_labels, resolvable_labels
                )
            ) / total
            harm_margin = min(
                abs(probability - execute_below)
                for probability in harm_probabilities
            )
            resolvability_margin = min(
                abs(probability - resolve_at_least)
                for probability in resolvable_probabilities
            )
            joint_margin = min(harm_margin, resolvability_margin)
            total_margin = harm_margin + resolvability_margin
            feasible = unsafe_exec <= max_unsafe_execution_rate
            if feasible:
                sort_key = (
                    0.0,
                    route_error + burden,
                    unsafe_exec,
                    -joint_margin,
                    -total_margin,
                    execute_below,
                    -resolve_at_least,
                )
            else:
                sort_key = (
                    1.0,
                    unsafe_exec,
                    route_error + burden,
                    -joint_margin,
                    -total_margin,
                    execute_below,
                    -resolve_at_least,
                )
            candidates.append((sort_key, execute_below, resolve_at_least))
    _, execute_below, resolve_at_least = min(candidates, key=lambda item: item[0])
    return RoutingThresholds(execute_below, resolve_at_least)


def brier_score(probabilities: Sequence[float], labels: Sequence[bool | int]) -> float:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("Probabilities and labels must be non-empty and aligned")
    return fmean(
        (probability - float(bool(label))) ** 2
        for probability, label in zip(probabilities, labels)
    )


def expected_calibration_error(
    probabilities: Sequence[float],
    labels: Sequence[bool | int],
    *,
    bins: int = 10,
) -> float:
    if not probabilities or len(probabilities) != len(labels):
        raise ValueError("Probabilities and labels must be non-empty and aligned")
    if bins < 1:
        raise ValueError("bins must be positive")
    total = len(probabilities)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            item
            for item in zip(probabilities, labels)
            if lower <= item[0] < upper or (index == bins - 1 and item[0] == 1.0)
        ]
        if members:
            confidence = fmean(item[0] for item in members)
            accuracy = fmean(float(bool(item[1])) for item in members)
            error += len(members) / total * abs(confidence - accuracy)
    return error


def risk_coverage_curve(
    probabilities: Sequence[float],
    unsafe_labels: Sequence[bool | int],
) -> list[tuple[float, float]]:
    if not probabilities or len(probabilities) != len(unsafe_labels):
        raise ValueError("Probabilities and labels must be non-empty and aligned")
    ordered = sorted(zip(probabilities, unsafe_labels), key=lambda item: item[0])
    curve: list[tuple[float, float]] = []
    unsafe = 0
    for index, (_, label) in enumerate(ordered, start=1):
        unsafe += bool(label)
        curve.append((index / len(ordered), unsafe / index))
    return curve


def area_under_risk_coverage(
    probabilities: Sequence[float],
    unsafe_labels: Sequence[bool | int],
) -> float:
    return fmean(risk for _, risk in risk_coverage_curve(probabilities, unsafe_labels))
