"""
Synastry — compatibility between two natal charts.

Overlays two charts and scores inter-chart aspects per relationship sphere,
using the same aspect math and tanh calibration as daily category scoring.
Computed once per pair and stored — natal charts never change.
"""
from __future__ import annotations

import math

from app.core.ephemeris import ASPECTS, calculate_transit_aspects_to_natal
from app.core.scoring import CHALLENGING_ASPECTS

# Which planets matter for each relationship sphere.
# An inter-chart aspect counts for a sphere if EITHER side's planet is watched.
SPHERE_PLANETS: dict[str, set[str]] = {
    "romance":       {"Venus", "Mars", "Moon"},
    "friendship":    {"Sun", "Moon", "Jupiter"},
    "communication": {"Mercury"},
    "conflict":      {"Mars", "Saturn", "Pluto"},
}

# Personal planets move fast → aspects between them are individual, not generational.
_PERSONAL = {"Sun", "Moon", "Mercury", "Venus", "Mars"}


def _aspect_strength(orb: float, aspect_name: str) -> float:
    _, max_orb = ASPECTS[aspect_name]
    if max_orb == 0:
        return 10.0
    return max(1.0, 10.0 - (orb / max_orb) * 9.0)


def compute_synastry(user_planets: dict, partner_planets: dict) -> dict:
    """
    Returns:
        aspects        — inter-chart aspects (user planet ↔ partner planet)
        sphere_scores  — {romance, friendship, communication, conflict}: 1-10
        overall        — 0-100 percent
    """
    # Reuse transit-aspect math: partner chart plays the "transits" role.
    raw_aspects = calculate_transit_aspects_to_natal(partner_planets, user_planets)

    # Keep aspects where at least one side is a personal planet — otherwise
    # slow outer planets produce the same "generational" aspects for everyone.
    aspects = [
        a for a in raw_aspects
        if a["transiting_planet"] in _PERSONAL or a["natal_planet"] in _PERSONAL
    ]

    buckets: dict[str, list[float]] = {s: [] for s in SPHERE_PLANETS}
    for a in aspects:
        strength = _aspect_strength(a["orb"], a["aspect"])
        signed = -strength if a["aspect"] in CHALLENGING_ASPECTS else strength
        for sphere, planets in SPHERE_PLANETS.items():
            if a["transiting_planet"] in planets or a["natal_planet"] in planets:
                if sphere == "conflict":
                    # Conflict sphere: MORE tension aspects = LOWER score
                    # (low score = "watch out"), so invert the sign convention.
                    buckets[sphere].append(-signed)
                else:
                    buckets[sphere].append(signed)

    sphere_scores: dict[str, int] = {}
    for sphere, values in buckets.items():
        if not values:
            sphere_scores[sphere] = 5
            continue
        plain = sum(values) / len(values)
        weighted = sum(v * abs(v) for v in values) / sum(abs(v) for v in values)
        raw = 0.5 * (plain + weighted)
        normalized = 5.5 + 4.6 * math.tanh(raw / 5.0)
        sphere_scores[sphere] = max(1, min(10, round(normalized)))

    # Overall percent: conflict inverted back (high conflict score = smooth = good)
    overall_avg = (
        sphere_scores["romance"]
        + sphere_scores["friendship"]
        + sphere_scores["communication"]
        + sphere_scores["conflict"]
    ) / 4
    overall = max(5, min(99, round(overall_avg * 10)))

    # Strongest aspects for the AI prompt (tightest orb first)
    top_aspects = sorted(aspects, key=lambda a: a["orb"])[:8]

    return {
        "aspects": [
            {
                "partner_planet": a["transiting_planet"],
                "user_planet": a["natal_planet"],
                "aspect": a["aspect"],
                "orb": a["orb"],
            }
            for a in top_aspects
        ],
        "sphere_scores": sphere_scores,
        "overall": overall,
    }
