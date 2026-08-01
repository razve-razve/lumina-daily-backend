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
    return {"en": "English", "ru": "Russian", "pt": "Portuguese (Brazilian)"}.get(code, "English")


# Model routing (July 2026): gpt-5.6-luna matches/beats gpt-4o on grounded advice
# across all modes & languages at ~1/10 the cost (verified: 3 blind rounds + a
# 12-sample language-purity scan). Exception — No Filter's roast humor lands
# sharper on gpt-4o, so that Pro mode stays on gpt-4o.
_DEFAULT_MODEL = "gpt-5.6-luna"


def _model_for(mode: str, language: str) -> str:
    """gpt-4o for No Filter (roast humor lands sharper) AND for Russian (Luna's
    Russian has unnatural collocations — 'направить амбиции в результат',
    'закрыть сроки'). Luna (cheap) for English & Portuguese, where its output
    is clean and matches/beats gpt-4o."""
    if mode == "No Filter" or language == "ru":
        return "gpt-4o"
    return _DEFAULT_MODEL


def _completion_kwargs(model: str, max_out: int, temperature: float) -> dict:
    """GPT-5.x models require `max_completion_tokens` and reject a custom
    temperature (fixed at 1); older models use `max_tokens` + temperature.

    `reasoning_effort="low"` is CRITICAL for gpt-5.x: at default effort the model
    can spend the ENTIRE token budget on reasoning and return empty content
    (finish_reason=length, 0 output tokens) — which surfaced as blank category
    cells. Advice generation is a creative task, not a reasoning one, so low
    effort both fixes the empties and cuts latency/cost. ("minimal" is rejected
    by Luna; "low" is the floor.)"""
    if model.startswith("gpt-5"):
        return {"model": model, "max_completion_tokens": max_out, "reasoning_effort": "low"}
    return {"model": model, "max_tokens": max_out, "temperature": temperature}


# What made Luna's output win the blind tests: address by name + concrete,
# no-filler sentences. Applied to every mode EXCEPT No Filter, whose prompt is
# already tuned and runs on gpt-4o.
_STYLE_ADDENDUM = (
    "\n\nStyle (critical):\n"
    "- Open by addressing the person by their first name, then a comma.\n"
    "- Give ONE clear, doable action for the day — not a checklist crammed into every "
    "sentence. Concrete and grounded, but light and readable: no filler, no vague uplift, "
    "no wellness clichés, and no piling on multiple to-dos."
)


def _style_addendum(mode: str) -> str:
    return "" if mode == "No Filter" else _STYLE_ADDENDUM


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
    "\n"
    "Relationships — NEVER ASSUME (CRITICAL):\n"
    "- Do NOT assume the reader is in a relationship. Many readers are single. For love/"
    "relationship advice, keep it open: 'someone you're close to', 'a person you're dating "
    "or interested in', 'the people you love' — so it fits single and partnered readers alike.\n"
    "- NEVER assume the gender of the reader's partner or love interest. Do not write "
    "'партнёрша'/'girlfriend'/'boyfriend' or gender the other person. Use neutral wording "
    "('партнёр', 'близкий человек', 'тот, кто вам дорог'). This must work for readers of any "
    "gender or sexual orientation.\n"
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

# "No Filter" mode: irony demands informal address — formal ВЫ kills the joke.
_RUSSIAN_RULES_INFORMAL = (
    "Russian-specific rules (CRITICAL):\n"
    "- Address the person using the informal ТЫ (ты/тебя/тебе/твой/твою). "
    "Never use formal вы — this mode is a close friend talking, not a consultant.\n"
    "- Apply correct Russian grammatical gender to all astrological terms: "
    "Луна (feminine — натальная Луна, твою натальную Луну), "
    "Венера (feminine), Марс (masculine), Меркурий (masculine), Юпитер (masculine), "
    "Сатурн (masculine), Уран (masculine), Нептун (masculine), Плутон (masculine), "
    "Солнце (neuter).\n"
    "- Write natural, living Russian with real ирония — no calques from English humor.\n"
    "- Complete every sentence fully. Never cut off mid-sentence."
)


def _russian_rules_for(mode: str) -> str:
    return _RUSSIAN_RULES_INFORMAL if mode == "No Filter" else _RUSSIAN_RULES


def _build_system_prompt(mode: str, language: str) -> str:
    """Build a rich, mode-specific system prompt for category guidance."""
    cfg = get_mode_config(mode)
    lang = _language_name(language)
    russian_block = f"\n\n{_russian_rules_for(mode)}" if language == "ru" else ""
    # No Filter lands harder short — a punchline, not an essay
    length_rule = (
        "- Length: EXACTLY 2–3 sentences. Short and punchy — every extra word "
        "weakens the joke. Stop after the 3rd sentence. "
        if mode == "No Filter"
        else "- Length: 3–4 sentences. Keep them readable — no long run-on sentences that "
        "pile clause on clause, but give enough substance to feel worth reading. "
        "Stop after the 4th sentence. "
    )
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
        f"- Mention AT MOST ONE astrological aspect in the whole reading, and in plain "
        f"words. Do NOT list several transits — naming three or four planets/aspects turns "
        f"the advice into a technical report. The reader wants guidance for their day, not "
        f"an astrology lesson: lead with the real-life action, let the astrology stay in the "
        f"background.\n"
        f"- Vary your sentence structure and opening words — never start two consecutive "
        f"readings the same way.\n"
        f"{length_rule}"
        f"No bullet points. No headers. No paragraph breaks. Plain prose only."
        f"{_style_addendum(mode)}"
        f"{russian_block}"
    )


def _build_theme_prompt(mode: str, language: str) -> str:
    """Build a mode-aware system prompt for the daily theme sentence."""
    cfg = get_mode_config(mode)
    lang = _language_name(language)
    russian_note = (
        (" Use informal ТЫ address." if mode == "No Filter" else " Use formal ВЫ address.")
        + " Apply correct grammatical gender to all planet names."
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


def _score_directive(score: Optional[int]) -> str:
    """Tell the model the computed 1–10 score so the words match the number the
    user sees (was: score 4 'energy low' but text 'your energy is high')."""
    if score is None:
        return ""
    if score <= 3:
        tone = "a genuinely difficult, draining day in this area — be honest about that; do NOT claim things are great"
    elif score <= 5:
        tone = "a mixed, so-so day here — neither great nor terrible"
    elif score <= 7:
        tone = "a solid, favorable day in this area"
    else:
        tone = "an excellent, strong day in this area"
    return (
        f"\nThis life area scores {score}/10 today, meaning {tone}. "
        f"Your reading's tone MUST match this number — never contradict it."
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
    score: Optional[int] = None,
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
    ) + _score_directive(score)
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]
    response = await client.chat.completions.create(
        messages=messages,
        **_completion_kwargs(_model_for(mode, language), max_out=1000, temperature=0.88),
    )
    text = (response.choices[0].message.content or "").strip()
    # Safety net: an empty category cell is unacceptable. If the model ever
    # returns nothing (e.g. reasoning ate the budget), retry once on gpt-4o.
    if not text:
        response = await client.chat.completions.create(
            messages=messages,
            **_completion_kwargs("gpt-4o", max_out=400, temperature=0.88),
        )
        text = (response.choices[0].message.content or "").strip()
    return text


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
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ]
    response = await client.chat.completions.create(
        messages=messages,
        # generous cap: gpt-5 reasoning tokens share this budget with the output
        **_completion_kwargs(_model_for(mode, language), max_out=700, temperature=0.82),
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:  # never ship an empty theme — fall back to gpt-4o
        response = await client.chat.completions.create(
            messages=messages,
            **_completion_kwargs("gpt-4o", max_out=90, temperature=0.82),
        )
        text = (response.choices[0].message.content or "").strip()
    return text


async def generate_weekly_text(
    *,
    name: str,
    language: str,
    mode: str,
    sun_sign: str,
    moon_sign: str,
    rising: str,
    week_range: str,
    day_scores_line: str,
    aspect_list: str,
) -> str:
    """One weekly forecast text — a single call per user per week (Redis-cached)."""
    client = get_openai_client()
    cfg = get_mode_config(mode)
    lang = _language_name(language)
    russian_block = f"\n\n{_russian_rules_for(mode)}" if language == "ru" else ""
    system = (
        f"You are {cfg.persona}, writing for the app Lumina Daily.\n\n"
        f"Language: Write entirely in {lang}.\n\n"
        f"Style: {cfg.style}\n\n"
        f"Strictly avoid: {cfg.avoid}\n\n"
        f"{_REAL_LIFE_GROUNDING}\n"
        f"Task: Write the WEEKLY forecast — an overview of the person's week ahead.\n"
        f"- Open with the week's overall theme in one sentence.\n"
        f"- Name specific weekdays when giving timing advice (e.g. 'Wednesday is best "
        f"for the hard conversation', 'protect your energy on Friday') — use the "
        f"day scores provided, higher = better.\n"
        f"- Cover work and relationships at least once each.\n"
        f"- Length: EXACTLY 5-6 sentences. No bullet points. No headers. Plain prose only."
        f"{russian_block}"
    )
    user_msg = (
        f"Person: {name}. Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}.\n"
        f"Week: {week_range}.\n"
        f"Day scores (1-10, higher = smoother day): {day_scores_line}.\n"
        f"Strongest transits this week: {aspect_list}.\n\n"
        f"Write this person's weekly forecast."
    )
    response = await client.chat.completions.create(
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ],
        **_completion_kwargs(_model_for(mode, language), max_out=1200, temperature=0.85),
    )
    return response.choices[0].message.content.strip()


_COMPAT_SPHERES = [
    ("summary",       "Overall compatibility — the essence of how these two people fit together"),
    ("romance",       "Romance & Attraction — chemistry, tenderness, physical pull"),
    ("friendship",    "Friendship & Fun — shared joy, ease of spending time together"),
    ("communication", "Communication — how they talk, listen, and understand each other"),
    ("conflict",      "Friction & Growth — where tension arises and what it teaches them"),
]


async def generate_compatibility_texts(
    *,
    user_name: str,
    partner_name: str,
    language: str,
    user_sun: str, user_moon: str,
    partner_sun: str, partner_moon: str,
    aspect_list: str,
    sphere_scores: dict,
    overall: int,
) -> dict[str, str]:
    """5 texts (summary + 4 spheres), parallel calls — one-time cost per pair."""
    client = get_openai_client()
    lang = _language_name(language)
    russian_block = f"\n\n{_RUSSIAN_RULES}" if language == "ru" else ""

    system = (
        f"You are a warm, insightful astrologer writing a compatibility reading for "
        f"the app Lumina Daily. You write about TWO real people and how their charts "
        f"interact — specific, honest, never generic.\n\n"
        f"Language: Write entirely in {lang}.\n\n"
        f"Rules:\n"
        f"- Speak to the reader ({user_name}) directly as 'you'; call the other person "
        f"by name ({partner_name}).\n"
        f"- Ground everything in the actual inter-chart aspects provided.\n"
        f"- Be honest about friction — sugarcoating makes the reading worthless — but "
        f"frame tension as workable, never doom.\n"
        f"{_REAL_LIFE_GROUNDING}"
        f"- Length: EXACTLY 3-4 sentences. Plain prose only."
        f"{russian_block}"
    )

    async def one(sphere_key: str, sphere_desc: str) -> tuple[str, str]:
        score_note = (
            f"Overall compatibility: {overall}%."
            if sphere_key == "summary"
            else f"This sphere's score: {sphere_scores.get(sphere_key, 5)}/10."
        )
        user_msg = (
            f"{user_name}: Sun in {user_sun}, Moon in {user_moon}.\n"
            f"{partner_name}: Sun in {partner_sun}, Moon in {partner_moon}.\n"
            f"Inter-chart aspects: {aspect_list}.\n"
            f"{score_note}\n\n"
            f"Write the reading for: {sphere_desc}."
        )
        response = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            # Compatibility has no "mode" — always the cheap default model.
            **_completion_kwargs(_model_for("", language), max_out=1000, temperature=0.85),
        )
        return sphere_key, response.choices[0].message.content.strip()

    results = await asyncio.gather(*[one(k, d) for k, d in _COMPAT_SPHERES])
    return dict(results)


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

    # Compute the SAME scores the app will display, so each reading's tone matches
    # its number (score 4 "energy" must not say "your energy is high"). "risk"
    # (Watch For) has no shown score, so no directive for it.
    from app.core.scoring import score_categories
    scores = score_categories(transit_aspects)

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
            score=None if key == "risk" else scores.get(key),
        )
        for key, label in CATEGORIES
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
