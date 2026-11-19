from dataclasses import dataclass

DEFAULT_WEIGHTS = {
    "movement_anomaly": .35, "geofence_risk": .25,
    "route_deviation": .10, "inactivity": .10,
    "historical_context": .10, "night_flag": .05, "sos": .05,
}
DEFAULT_THRESHOLDS = {"low_max": .35, "moderate_max": .65}


@dataclass
class RiskResult:
    score: float
    level: str


def calculate_risk(movement_anomaly, geofence_risk, route_deviation,
                   inactivity, historical_context, night_flag, sos, weights=None, thresholds=None):
    """Weighted sum of the seven signals. Weights and LOW/MODERATE/HIGH cut-offs come from the location config."""
    w = weights or DEFAULT_WEIGHTS
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    score = sum(w[k] * v for k, v in {
        "movement_anomaly": movement_anomaly, "geofence_risk": geofence_risk,
        "route_deviation": route_deviation, "inactivity": inactivity,
        "historical_context": historical_context, "night_flag": night_flag, "sos": sos
    }.items())
    score = max(0.0, min(1.0, score))
    if sos >= 1: level = "HIGH"
    elif score < t["low_max"]: level = "LOW"
    elif score < t["moderate_max"]: level = "MODERATE"
    else: level = "HIGH"
    return RiskResult(round(score, 4), level)
