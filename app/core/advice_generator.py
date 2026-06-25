"""
AI advice generation — one call per category per user per day.
Generates text for all 6 categories + a theme sentence.
Each interpretation mode produces a distinctly different voice and lens.
"""
import asyncio
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.core.modes import get_mode_config

_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


CATEGORIES = [
    ("love",          "Love & Relationships"),
    ("work",          "Work & Focus"),
    ("energy",        "Energy & Vitality"),
    ("communication", "Communication"),
    ("mood",          "Mood & Inner State"),
    ("risk",          "Watch For"),
]


def _language_name(code: str) -> str:
    return {"en": "English", "ru": "Russian"}.get(code, "English")


def _format_aspects(transit_aspects: list[dict]) -> str:
    if not transit_aspects:
        return "no major exact transits today"
    top = sorted(transit_aspects, key=lambda a: a["orb"])[:6]
    return ", ".join(
        f"{a['transiting_planet']} {a['aspect']} natal {a['natal_planet']} "
        f"(orb {a['orb']:.1f}°)"
        for a in top
    )


_REAL_LIFE_GROUNDING = (
    "Real-life grounding (CRITICAL — applies regardless of mode):\n"
    "The person using this app lives an ordinary life. They go to work or study, "
    "come home, communicate with family, a partner, friends, or colleagues. "
    "Their concerns are real and everyday: a difficult conversation, a work deadline, "
    "tiredness after a long day, money decisions, weekend plans, a tense moment at home. "
    "Ground your advice in this reality. Even in poetic or spiritual modes, the examples "
    "and situations you reference must be recognizable from ordinary daily life. "
    "Never assume the person meditates, journals, does yoga, or has a spiritual practice "
    "unless it is the explicit framework of the chosen mode.\n"
)

_RUSSIAN_RULES = (
    "Russian-specific rules (CRITICAL):\n"
    "- Always address the person using the formal ВЫ (вы/вас/вам/вами/вашу/ваш/ваше/ваши). "
    "Never use ты/тебя/тебе/твой.\n"
    "- Apply correct Russian grammatical gender to all astrological terms: "
    "Луна (feminine — натальная Луна, вашу натальную Луну), "
    "Венера (feminine), Марс (masculine — натальный Марс, вашего натального Марса), "
    "Меркурий (masculine), Юпитер (masculine), Сатурн (masculine), "
    "Уран (masculine), Нептун (masculine), Плутон (masculine), Солнце (neuter — натальное Солнце).\n"
    "- Write natural, literary Russian — avoid word-for-word calques from English structure.\n"
    "- Complete every sentence fully. Never cut off mid-sentence."
)


def _build_system_prompt(mode: str, language: str) -> str:
    """Build a rich, mode-specific system prompt for category guidance."""
    cfg = get_mode_config(mode)
    lang = _language_name(language)
    russian_block = f"\n\n{_RUSSIAN_RULES}" if language == "ru" else ""
    return (
        f"You are {cfg.persona}, writing for the app Lumina Daily.\n\n"
        f"Language: Write entirely in {lang}.\n\n"
        f"Style: {cfg.style}\n\n"
        f"Concepts and vocabulary to draw on: {cfg.concepts}\n\n"
        f"Strictly avoid: {cfg.avoid}\n\n"
        f"{_REAL_LIFE_GROUNDING}\n"
        f"Additional rules:\n"
        f"- Be specific to THIS person's natal placements and TODAY's actual aspects.\n"
        f"- Never mention degree numbers (e.g. '15° Scorpio').\n"
        f"- Vary your sentence structure and opening words — never start two consecutive "
        f"readings the same way.\n"
        f"- Length: EXACTLY 3–4 sentences. Stop after the 4th sentence. "
        f"No bullet points. No headers. No paragraph breaks. Plain prose only."
        f"{russian_block}"
    )


def _build_theme_prompt(mode: str, language: str) -> str:
    """Build a mode-aware system prompt for the daily theme sentence."""
    cfg = get_mode_config(mode)
    lang = _language_name(language)
    russian_note = (
        " Use formal ВЫ address. Apply correct grammatical gender to all planet names."
        if language == "ru" else ""
    )
    return (
        f"You are {cfg.persona}, writing for the app Lumina Daily.\n"
        f"Write exactly ONE sentence — the key theme for this person's day — "
        f"in {lang}.\n"
        f"The sentence should reflect your mode's lens: {cfg.style[:120]}…\n"
        f"No degree numbers. No jargon. Warm and direct. One sentence only.{russian_note}"
    )


_USER_TEMPLATE = (
    "Person: {name} ({gender}). "
    "Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}.\n"
    "Today's active transits: {aspect_list}.\n"
    "Moon phase: {moon_phase}.\n"
    "Life area to address: {category}.\n\n"
    "Write today's guidance for this person in this life area."
)

_THEME_USER = (
    "Person: Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}.\n"
    "Moon phase: {moon_phase}.\n"
    "Active transits: {aspect_list}.\n\n"
    "What is the single defining theme for this person's day?"
)


async def generate_category_text(
    *,
    name: str,
    gender: str,
    language: str,
    mode: str,
    sun_sign: str,
    moon_sign: str,
    rising: str,
    moon_phase: str,
    aspect_list: str,
    category_label: str,
) -> str:
    client = get_openai_client()
    system = _build_system_prompt(mode, language)
    user_msg = _USER_TEMPLATE.format(
        name=name,
        gender=gender,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        aspect_list=aspect_list,
        moon_phase=moon_phase,
        category=category_label,
    )
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.88,
        max_tokens=400,
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
    mode: str,
) -> str:
    client = get_openai_client()
    system = _build_theme_prompt(mode, language)
    user_msg = _THEME_USER.format(
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        moon_phase=moon_phase,
        aspect_list=aspect_list,
    )
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.82,
        max_tokens=90,
    )
    return response.choices[0].message.content.strip()


async def generate_transit_explanation(
    *,
    transit_tag: str,
    name: str,
    sun_sign: str,
    moon_sign: str,
    language: str,
) -> str:
    """Generate a personalized 2-sentence explanation for a specific transit tag."""
    client = get_openai_client()
    lang = _language_name(language)
    russian_note = (
        " Use formal ВЫ (вы/вас/вам). Apply correct Russian grammatical gender to all planet names."
        if language == "ru" else ""
    )
    system = (
        f"You are a concise astrologer writing directly to the person — always use second person "
        f"(you/your), never third person (he/she/they/their name). "
        f"Write exactly 2 sentences explaining how a specific planetary transit affects the reader "
        f"today, based on their natal chart. "
        f"Write in {lang}. Be specific, warm, and practical. No degree numbers. No jargon.{russian_note}"
    )
    user_msg = (
        f"Sun in {sun_sign}, Moon in {moon_sign}.\n"
        f"Transit: {transit_tag}\n\n"
        f"In 2 sentences, address the reader directly (you/your) and explain how this transit "
        f"affects them today."
    )
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.8,
        max_tokens=150,
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

    theme_coro = generate_theme(
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising=rising,
        moon_phase=moon_phase,
        aspect_list=aspect_list,
        language=language,
        mode=mode,
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
            moon_phase=moon_phase,
            aspect_list=aspect_list,
            category_label=label,
        )
        for _, label in CATEGORIES
    ]

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
