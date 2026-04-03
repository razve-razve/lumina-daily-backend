"""
AI advice generation — one call per category per user per day.
Generates text for all 6 categories + a theme sentence.
"""
import asyncio
import json

from typing import Optional
from openai import AsyncOpenAI

from app.config import settings
from app.core.modes import tone_for_mode

_client = None  # type: Optional[AsyncOpenAI]


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


CATEGORIES = [
    ("love",          "Love & Relationships"),
    ("work",          "Work & Focus"),
    ("energy",        "Energy"),
    ("communication", "Communication"),
    ("mood",          "Mood"),
    ("risk",          "Watch For"),
]

_SYSTEM_TEMPLATE = (
    "You are an astrology advisor for the app Lumina Daily. "
    "Write personalized daily guidance in {language}. "
    "Mode: {mode}. Tone: {tone} "
    "Be warm, specific, and varied. "
    "Never repeat phrases used in the last 7 days. "
    "Do not mention specific degree numbers or technical jargon. "
    "Length: 2–4 sentences."
)

_USER_TEMPLATE = (
    "User: {name}, {gender}, Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}.\n"
    "Today's aspects: {aspect_list}.\n"
    "Category: {category}.\n"
    "Write today's guidance."
)

_THEME_SYSTEM = (
    "You are an astrology advisor. Write exactly one sentence — the key theme for this person's day "
    "based on their natal chart and today's planetary transits. No jargon, no degree numbers. "
    "Warm and direct. Reply with the sentence only."
)

_THEME_USER = (
    "Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}. "
    "Today's moon phase: {moon_phase}. "
    "Key transits: {aspect_list}. "
    "What is the main theme for today?"
)


def _format_aspects(transit_aspects: list[dict]) -> str:
    if not transit_aspects:
        return "no major exact transits"
    top = sorted(transit_aspects, key=lambda a: a["orb"])[:6]
    return ", ".join(
        f"{a['transiting_planet']} {a['aspect']} natal {a['natal_planet']} (orb {a['orb']}°)"
        for a in top
    )


def _language_name(code: str) -> str:
    return {"en": "English", "ru": "Russian"}.get(code, "English")


async def generate_category_text(
    *,
    name: str,
    gender: str,
    language: str,
    mode: str,
    sun_sign: str,
    moon_sign: str,
    rising: str,
    aspect_list: str,
    category_label: str,
) -> str:
    client = get_openai_client()
    system = _SYSTEM_TEMPLATE.format(
        language=_language_name(language),
        mode=mode,
        tone=tone_for_mode(mode),
    )
    user_msg = _USER_TEMPLATE.format(
        name=name,
        gender=gender,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        aspect_list=aspect_list,
        category=category_label,
    )
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.85,
        max_tokens=200,
    )
    return response.choices[0].message.content.strip()


async def generate_theme(
    *,
    sun_sign: str,
    moon_sign: str,
    rising: str,
    moon_phase: str,
    aspect_list: str,
    language: str,
) -> str:
    client = get_openai_client()
    user_msg = _THEME_USER.format(
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        moon_phase=moon_phase,
        aspect_list=aspect_list,
    )
    system = _THEME_SYSTEM + f" Reply in {_language_name(language)}."
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.8,
        max_tokens=80,
    )
    return response.choices[0].message.content.strip()


async def generate_all_advice(
    *,
    name: str,
    gender: str,
    language: str,
    mode: str,
    natal_chart: dict,
    transit_aspects: list[dict],
    moon_phase: str,
) -> dict:
    """
    Generate theme + all 6 category texts concurrently.
    Returns dict with keys: theme, love_text, work_text, energy_text,
    communication_text, mood_text, risk_text.
    """
    planets = natal_chart.get("planets", {})
    sun_sign  = planets.get("Sun",  {}).get("sign", "unknown")
    moon_sign = planets.get("Moon", {}).get("sign", "unknown")
    rising    = natal_chart.get("houses", {}).get("asc_sign", "unknown")
    aspect_list = _format_aspects(transit_aspects)

    # Build all coroutines
    theme_coro = generate_theme(
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        moon_phase=moon_phase,
        aspect_list=aspect_list,
        language=language,
    )

    category_coros = [
        generate_category_text(
            name=name,
            gender=gender,
            language=language,
            mode=mode,
            sun_sign=sun_sign,
            moon_sign=moon_sign,
            rising=rising,
            aspect_list=aspect_list,
            category_label=label,
        )
        for _, label in CATEGORIES
    ]

    # Run all 7 calls concurrently
    results = await asyncio.gather(theme_coro, *category_coros)

    theme_text = results[0]
    texts = {key: results[i + 1] for i, (key, _) in enumerate(CATEGORIES)}

    return {
        "theme":              theme_text,
        "love_text":          texts["love"],
        "work_text":          texts["work"],
        "energy_text":        texts["energy"],
        "communication_text": texts["communication"],
        "mood_text":          texts["mood"],
        "risk_text":          texts["risk"],
    }
