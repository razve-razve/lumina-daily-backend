import swisseph as swe

from app.config import settings

# Set ephemeris path at import time so all threads see it immediately
swe.set_ephe_path(settings.ephe_path)

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

PLANETS = [
    (swe.SUN,       "Sun"),
    (swe.MOON,      "Moon"),
    (swe.MERCURY,   "Mercury"),
    (swe.VENUS,     "Venus"),
    (swe.MARS,      "Mars"),
    (swe.JUPITER,   "Jupiter"),
    (swe.SATURN,    "Saturn"),
    (swe.URANUS,    "Uranus"),
    (swe.NEPTUNE,   "Neptune"),
    (swe.PLUTO,     "Pluto"),
    (swe.TRUE_NODE, "North Node"),
    (swe.CHIRON,    "Chiron"),
]

ASPECTS = {
    "conjunction": (0,   8),
    "opposition":  (180, 8),
    "trine":       (120, 6),
    "square":      (90,  6),
    "sextile":     (60,  4),
}


def init_ephemeris() -> None:
    swe.set_ephe_path(settings.ephe_path)


def zodiac_sign(longitude: float) -> str:
    return SIGNS[int(longitude / 30) % 12]


def birth_to_julian_day(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    utc_offset_seconds: int,
) -> float:
    local_decimal = hour + minute / 60.0 + second / 3600.0
    utc_decimal = local_decimal - (utc_offset_seconds / 3600.0)
    return swe.julday(year, month, day, utc_decimal)


def _find_house(planet_lon: float, cusps: tuple) -> int:
    # cusps is 0-indexed: cusps[0]=house1 cusp ... cusps[11]=house12 cusp
    for h in range(12):
        cusp_start = cusps[h]
        cusp_end = cusps[(h + 1) % 12]
        if cusp_start <= cusp_end:
            if cusp_start <= planet_lon < cusp_end:
                return h + 1
        else:  # crosses 0° Aries
            if planet_lon >= cusp_start or planet_lon < cusp_end:
                return h + 1
    return 1


def _calculate_aspects(planets: dict) -> list[dict]:
    planet_names = list(planets.keys())
    aspects = []
    for i in range(len(planet_names)):
        for j in range(i + 1, len(planet_names)):
            p1 = planet_names[i]
            p2 = planet_names[j]
            angle = abs(planets[p1]["longitude"] - planets[p2]["longitude"]) % 360
            if angle > 180:
                angle = 360 - angle
            for aspect_name, (exact_angle, max_orb) in ASPECTS.items():
                orb = abs(angle - exact_angle)
                if orb <= max_orb:
                    aspects.append({
                        "planet1": p1,
                        "planet2": p2,
                        "aspect": aspect_name,
                        "angle": round(angle, 2),
                        "orb": round(orb, 2),
                        "applying": planets[p1]["speed"] > planets[p2]["speed"],
                    })
    return aspects


def calculate_natal_chart(jd: float, lat: float, lon: float) -> dict:
    swe.set_ephe_path(settings.ephe_path)
    flags = swe.FLG_SPEED
    planets: dict = {}

    for planet_id, planet_name in PLANETS:
        xx, _ = swe.calc_ut(jd, planet_id, flags)
        planets[planet_name] = {
            "longitude": xx[0],
            "sign": zodiac_sign(xx[0]),
            "sign_degree": round(xx[0] % 30, 4),
            "latitude": xx[1],
            "speed": xx[3],
            "retrograde": xx[3] < 0,
            "house": None,
        }

    # Placidus house system
    cusps, ascmc = swe.houses(jd, lat, lon, b"P")

    for planet_name in planets:
        planets[planet_name]["house"] = _find_house(planets[planet_name]["longitude"], cusps)

    houses = {
        "cusps": [round(c, 4) for c in cusps[0:12]],
        "ascendant": round(ascmc[0], 4),
        "midheaven": round(ascmc[1], 4),
        "asc_sign": zodiac_sign(ascmc[0]),
        "mc_sign": zodiac_sign(ascmc[1]),
    }

    return {
        "planets": planets,
        "houses": houses,
        "aspects": _calculate_aspects(planets),
        "julian_day": jd,
    }


def calculate_current_transits(jd: float) -> dict:
    swe.set_ephe_path(settings.ephe_path)
    flags = swe.FLG_SPEED
    transits: dict = {}
    for planet_id, planet_name in PLANETS:
        xx, _ = swe.calc_ut(jd, planet_id, flags)
        transits[planet_name] = {
            "longitude": round(xx[0], 4),
            "sign": zodiac_sign(xx[0]),
            "speed": round(xx[3], 6),
            "retrograde": xx[3] < 0,
        }
    return transits


def calculate_transit_aspects_to_natal(transits: dict, natal_planets: dict) -> list[dict]:
    result = []
    for t_name, t_data in transits.items():
        for n_name, n_data in natal_planets.items():
            angle = abs(t_data["longitude"] - n_data["longitude"]) % 360
            if angle > 180:
                angle = 360 - angle
            for aspect_name, (exact_angle, max_orb) in ASPECTS.items():
                orb = abs(angle - exact_angle)
                if orb <= max_orb:
                    result.append({
                        "transiting_planet": t_name,
                        "natal_planet": n_name,
                        "aspect": aspect_name,
                        "orb": round(orb, 2),
                    })
    return result


def now_julian_day() -> float:
    swe.set_ephe_path(settings.ephe_path)
    import datetime
    now = datetime.datetime.utcnow()
    decimal_hour = now.hour + now.minute / 60.0 + now.second / 3600.0
    return swe.julday(now.year, now.month, now.day, decimal_hour)


def julian_day_for_date(target_date) -> float:
    """JD anchored to NOON UTC on target_date.

    Daily scores must depend only on the calendar date — not on the minute the
    advice happens to be generated. Anchoring to a fixed noon makes a day's
    scores identical across languages and stable all day (the fast Moon moves
    ~0.5°/hour, so 'now' otherwise drifts the scores). Matches the anchor
    already used by the weekly forecast and moon-phase calculations.
    """
    swe.set_ephe_path(settings.ephe_path)
    return swe.julday(target_date.year, target_date.month, target_date.day, 12.0)


_MOON_PHASES = [
    (45,  "Waxing Crescent"),
    (90,  "First Quarter"),
    (135, "Waxing Gibbous"),
    (180, "Full Moon"),
    (225, "Waning Gibbous"),
    (270, "Last Quarter"),
    (315, "Waning Crescent"),
    (360, "New Moon"),
]


def get_moon_phase(transits: dict) -> str:
    """Return moon phase name based on Sun–Moon angle."""
    sun_lon  = transits.get("Sun",  {}).get("longitude", 0)
    moon_lon = transits.get("Moon", {}).get("longitude", 0)
    angle = (moon_lon - sun_lon) % 360
    for threshold, name in _MOON_PHASES:
        if angle < threshold:
            return name
    return "New Moon"


def get_moon_phase_for_date(year: int, month: int, day: int) -> str:
    """Calculate moon phase for any date (noon UTC). Pure astronomy — no AI, no user data."""
    swe.set_ephe_path(settings.ephe_path)
    jd = swe.julday(year, month, day, 12.0)   # noon UTC
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    sun_pos,  _ = swe.calc_ut(jd, swe.SUN,  flags)
    moon_pos, _ = swe.calc_ut(jd, swe.MOON, flags)
    angle = (moon_pos[0] - sun_pos[0]) % 360
    for threshold, name in _MOON_PHASES:
        if angle < threshold:
            return name
    return "New Moon"
