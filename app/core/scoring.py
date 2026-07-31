"""
Category scoring (1–10) based on transit aspects to natal planets.

Each category watches a specific set of natal planets.
Aspect strength = 10 at exact, 1 at orb limit (linear scale).

Score formula (calibrated July 2026 — old plain average clustered 58% of all
scores at 5–6, making them meaningless):
- Strong aspects dominate weak ones: the raw value blends the plain average
  with a strength-weighted average, so one exact trine isn't drowned out by
  three weak background squares.
- tanh squash calibrated to the realistic raw range (±5) spreads scores
  across the full 1–10 scale while keeping 1s and 10s rare.
If no aspects are found for a category, score defaults to 5.
"""

import math

from app.core.ephemeris import ASPECTS

# Which natal planets each category cares about
CATEGORY_PLANETS: dict[str, list[str]] = {
    "love":          ["Venus", "Moon", "Mars"],
    "work":          ["Sun", "Saturn", "Mercury"],
    "energy":        ["Mars", "Sun"],
    "communication": ["Mercury"],
    "mood":          ["Moon"],
    "risk":          ["Saturn", "Mars"],
}

# Favorable vs unfavorable aspects for each category (affects score direction)
CHALLENGING_ASPECTS = {"opposition", "square", "quincunx"}
FLOWING_ASPECTS     = {"trine", "sextile", "semi-sextile", "conjunction"}

# Slow outer planets sit in near-exact aspects for WEEKS, which froze daily
# scores (esp. mood/communication, watched by a single natal planet) — a Pluto
# square to your Moon pinned mood at 2 for a week. Since this is a DAILY score,
# down-weight slow planets so they set a background tint while fast personal
# planets (Sun/Moon/Mercury/Venus/Mars) drive day-to-day variation.
# (July 2026 fix, weight 0.4 validated on 14-day simulations.)
_SLOW_PLANETS = {"Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "North Node", "South Node"}
_SLOW_WEIGHT = 0.4


def _aspect_strength(orb: float, aspect_name: str) -> float:
    """Linear strength: exact = 10, at max orb = 1."""
    _, max_orb = ASPECTS[aspect_name]
    if max_orb == 0:
        return 10.0
    return max(1.0, 10.0 - (orb / max_orb) * 9.0)


def score_categories(transit_aspects: list[dict]) -> dict[str, int]:
    """
    Given a list of transit-to-natal aspects, return a score 1–10 per category.
    Flowing aspects push score up, challenging aspects push score down from 5.
    """
    buckets: dict[str, list[float]] = {cat: [] for cat in CATEGORY_PLANETS}

    for asp in transit_aspects:
        natal_planet = asp["natal_planet"]
        aspect_name  = asp["aspect"]
        orb          = asp["orb"]
        strength     = _aspect_strength(orb, aspect_name)

        # Down-weight slow outer planets so a weeks-long transit tints, not freezes
        if asp["transiting_planet"] in _SLOW_PLANETS:
            strength *= _SLOW_WEIGHT

        for category, planets in CATEGORY_PLANETS.items():
            if natal_planet in planets:
                if aspect_name in CHALLENGING_ASPECTS:
                    buckets[category].append(-strength)
                else:
                    buckets[category].append(strength)

    scores: dict[str, int] = {}
    for category, values in buckets.items():
        if not values:
            scores[category] = 5  # neutral default
        else:
            plain = sum(values) / len(values)
            weighted = sum(v * abs(v) for v in values) / sum(abs(v) for v in values)
            raw = 0.5 * (plain + weighted)
            normalized = 5.5 + 4.6 * math.tanh(raw / 5.0)
            scores[category] = max(1, min(10, round(normalized)))

    return scores


def build_transit_tags(transit_aspects: list[dict], transits: dict) -> list[str]:
    """
    Build human-readable transit highlight tags for the Today screen.
    E.g. ["Venus trine Moon", "Mercury℞"]
    """
    tags = []

    # Retrograde planets (skip North/South Node — always retrograde, not informative)
    always_retrograde = {"North Node", "South Node"}
    for planet, data in transits.items():
        if data.get("retrograde") and planet not in always_retrograde:
            tags.append(f"{planet} ℞")

    # Top 4 tightest aspects
    sorted_aspects = sorted(transit_aspects, key=lambda a: a["orb"])[:4]
    for asp in sorted_aspects:
        tags.append(f"{asp['transiting_planet']} {asp['aspect']} {asp['natal_planet']}")

    return tags
