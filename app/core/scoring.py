"""
Category scoring (1–10) based on transit aspects to natal planets.

Each category watches a specific set of natal planets.
Aspect strength = 10 at exact, 1 at orb limit (linear scale).
Final score = average of strengths for all triggered aspects, clamped to 1–10.
If no aspects are found for a category, score defaults to 5.
"""

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
            raw = sum(values) / len(values)   # average, range roughly -10 to +10
            # Map -10→1, 0→5, +10→10
            normalized = (raw + 10) / 20 * 9 + 1
            scores[category] = max(1, min(10, round(normalized)))

    return scores


def build_transit_tags(transit_aspects: list[dict], transits: dict) -> list[str]:
    """
    Build human-readable transit highlight tags for the Today screen.
    E.g. ["Venus trine Moon", "Mercury℞"]
    """
    tags = []

    # Retrograde planets
    for planet, data in transits.items():
        if data.get("retrograde"):
            tags.append(f"{planet}\u211e")  # ℞ symbol

    # Top 4 tightest aspects
    sorted_aspects = sorted(transit_aspects, key=lambda a: a["orb"])[:4]
    for asp in sorted_aspects:
        tags.append(f"{asp['transiting_planet']} {asp['aspect']} {asp['natal_planet']}")

    return tags
