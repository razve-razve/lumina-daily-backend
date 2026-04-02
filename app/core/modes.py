"""Interpretation modes — each changes the AI tone."""

MODES = {
    "Western Classical": "Use classical astrological symbolism and house meanings.",
    "Vedic":             "Use Vedic/Jyotish perspective. Reference dharma, karma, and life purpose.",
    "Psychological":     "Frame guidance as inner experience, emotional patterns, and growth edges.",
    "Practical Daily":   "Give concrete, actionable behavioral suggestions. Be direct and specific.",
    "Guidance":          "Be encouraging, gentle, and non-predictive. Focus on possibility, not fate.",
    "Predictive":        "Be direct about likely outcomes and timing. Use confident, clear language.",
}

FREE_MODES = {"Practical Daily"}

ALL_MODE_NAMES = list(MODES.keys())


def tone_for_mode(mode: str) -> str:
    return MODES.get(mode, MODES["Practical Daily"])
