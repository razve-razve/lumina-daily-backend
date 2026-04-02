# Lumina Daily — Product Specification
**Version 1.0 — MVP**
**Status: In Development**

---

## 1. Overview

**App name:** Lumina Daily  
**Tagline:** "Your sky, every morning."  
**Platforms:** iOS (iPhone first)  
**Languages:** English, Russian  
**Target launch:** App Store (worldwide)

Lumina Daily is a personalized astrology companion app. Users create a profile with their birth data once. Every morning, the app delivers fresh AI-generated astrological guidance across 6 life categories, personalized to each user's natal chart and today's planetary transits.

---

## 2. Core User Flow

```
Install → Onboarding → Natal Profile Generated → Daily Advice (every morning)
```

1. User installs the app
2. Selects language (English / Russian)
3. Completes onboarding (name, gender, date/time/place of birth)
4. App generates their natal chart (server-side, Swiss Ephemeris)
5. User sees their natal profile summary
6. User selects their preferred interpretation mode
7. User enables push notifications
8. Every morning: server generates advice → push notification sent → user opens app → reads guidance

---

## 3. Onboarding Screens

### Screen 1 — Welcome
- Lumina Daily logo + tagline
- "Get started" button
- Language selector (EN / RU)

### Screen 2 — Name
- Input: "What should we call you?" (name or nickname)
- Validation: 1–30 characters

### Screen 3 — Gender
- Options: Female / Male / Non-binary / Prefer not to say
- Used for grammatical gender in Russian text generation

### Screen 4 — Date of Birth
- iOS native DatePicker (wheel style)
- Range: 1920 – today minus 13 years

### Screen 5 — Time of Birth
- iOS native TimePicker
- Toggle: "I don't know my exact birth time"
- If unknown: use 12:00 noon as default, flag in profile, note in advice that Rising sign may be approximate

### Screen 6 — Place of Birth
- Search field with autocomplete (Google Places API)
- Shows city + country in results
- On select: stores city name, latitude, longitude
- Resolves historical timezone automatically (TimeZoneDB API)

### Screen 7 — Generating Profile
- Animated loading screen ("Reading your stars…")
- Backend call: calculate natal chart
- Duration: 2–4 seconds (or real API time)

### Screen 8 — Profile Ready
- Shows: Sun sign, Moon sign, Rising sign
- One-sentence personality summary
- "Continue" button

### Screen 9 — Choose Your Mode
- Carousel of interpretation modes (see Section 6)
- Brief description of each
- User selects one (can change later in Settings)

### Screen 10 — Notifications
- "Get your daily guidance at the right time"
- Time picker (default: 8:00 AM)
- "Enable notifications" button
- "Maybe later" skip option

---

## 4. Main Screens

### Tab 1 — TODAY
**Purpose:** Daily guidance hub. The screen users open every morning.

**Components:**
- Status bar with date + moon phase badge
- Greeting: "Good morning, [Name]"
- Active mode pill (e.g. "✦ Psychological")
- Hero card:
  - Today's key theme (one sentence)
  - Active transit tags (e.g. "Venus trine Moon", "Mercury direct")
- Score strip: Love / Work / Energy / Mood (scores 1–10, mini bar)
- 6 category cards (expandable):
  - Love & Relationships
  - Work & Focus
  - Energy
  - Communication
  - Mood
  - Watch For (risks/tensions)
- Each card: title, score pill, 3–4 sentence advice text

**Behavior:**
- Content generated once per day per user per mode
- If mode is changed: regenerates for new mode
- Pull to refresh: shows last generated time
- Long press card: save to history (Phase 2)

---

### Tab 2 — CHART
**Purpose:** User's permanent natal profile.

**Components:**
- Simplified natal wheel (visual, non-interactive MVP)
- Sun / Moon / Rising cards
- Dominant element (Fire / Earth / Air / Water)
- Dominant modality (Cardinal / Fixed / Mutable)
- Planet placements list (planet, sign, house, retrograde flag)
- "What this means" — plain language summary per placement

---

### Tab 3 — EXPLORE
**Purpose:** Switch interpretation modes; understand what each means.

**Components:**
- Mode cards (carousel or list):
  - Western Classical
  - Vedic
  - Psychological
  - Practical Daily
  - Guidance (soft)
  - Predictive (direct)
- Each mode: name, 2-sentence description, example quote
- Active mode highlighted
- Tap to switch → Today screen content regenerates

---

### Tab 4 — CALENDAR *(MVP: simple version)*
**Purpose:** Basic month view of daily energy scores.

**Components:**
- Month calendar
- Each day: colored dot indicating overall energy score
- Tap day: shows cached advice summary for that day (if generated)
- Future days: "Available on the day"

---

### Tab 5 — PROFILE
**Purpose:** Settings, birth data, preferences, subscription.

**Components:**
- Name + sign summary
- Edit birth data
- Language toggle (EN / RU)
- Notification time setting
- Interpretation mode shortcut
- Subscription status
- Privacy policy link
- Delete account option

---

## 5. Astrology Engine

### Birth Data Required
```
date_of_birth       (YYYY-MM-DD)
time_of_birth       (HH:MM, 24h)
time_known          (boolean)
latitude            (float)
longitude           (float)
timezone_id         (string, e.g. "Europe/Moscow")
utc_offset_at_birth (integer, seconds)
```

### Timezone Resolution
1. User types city name → Google Places Autocomplete API
2. Returns: place name, lat, lng
3. Backend calls TimeZoneDB API with lat/lng + birth date
4. Returns historical timezone offset (accounts for DST, historical changes)
5. Stores both timezone_id and utc_offset_at_birth

### Natal Chart Calculation
- Library: `pyswisseph` (Python wrapper for Swiss Ephemeris)
- Calculates: all 10 planets + ASC/MC in signs and houses
- House system: Placidus (default), with option to switch to Whole Sign for Vedic mode
- Stores result as JSON in user profile (calculated once, never changes)

### Daily Transit Calculation
- Run daily at 02:00 UTC for all users
- Calculate today's planetary positions
- For each user: compute aspects between transits and natal planets
- Aspect orbs: conjunction ±8°, opposition ±8°, trine ±6°, square ±6°, sextile ±4°
- Generate aspect list with strength score (exact = 10, at orb limit = 1)

### Category Scoring (1–10)
Each category scored from transit aspects:

| Category | Key planets considered |
|---|---|
| Love | Venus, Moon, Mars (natal + transit) |
| Work | Sun, Saturn, Mercury, MC |
| Energy | Mars, Sun, 1st house ruler |
| Communication | Mercury, 3rd house ruler |
| Mood | Moon, ASC ruler |
| Risk/Watch For | Saturn, Mars squares/oppositions, retrograde planets |

Score formula: sum of aspect strengths × weight per planet → normalized to 1–10.

### AI Text Generation
**Provider:** OpenAI GPT-4o or Anthropic Claude API  
**Trigger:** Daily batch job (02:00–04:00 UTC)  
**Input per user per category:**

```
System prompt:
"You are an astrology advisor for the app Lumina Daily. 
Write personalized daily guidance in {language}. 
Mode: {mode}. Tone: {tone_description}.
Be warm, specific, and varied. Never repeat phrases used in the last 7 days.
Do not mention specific degree numbers or technical jargon.
Length: 2-4 sentences."

User prompt:
"User: {name}, {gender}, Sun in {sun_sign}, Moon in {moon_sign}, Rising {rising}.
Today's aspects: {aspect_list}.
Category: {category}.
Write today's guidance."
```

**Output:** Plain text, 2–4 sentences, stored in database.

### Interpretation Mode Prompt Modifiers

| Mode | Tone instruction added to prompt |
|---|---|
| Western Classical | "Use classical astrological symbolism and house meanings." |
| Vedic | "Use Vedic/Jyotish perspective. Reference dharma, karma, and life purpose." |
| Psychological | "Frame guidance as inner experience, emotional patterns, and growth edges." |
| Practical Daily | "Give concrete, actionable behavioral suggestions. Be direct and specific." |
| Guidance (soft) | "Be encouraging, gentle, and non-predictive. Focus on possibility, not fate." |
| Predictive | "Be direct about likely outcomes and timing. Use confident, clear language." |

---

## 6. Backend Architecture

### Stack
```
Language:     Python 3.11+
Framework:    FastAPI
Database:     PostgreSQL (via Supabase — managed, free tier available)
Cache:        Redis (via Upstash — managed, free tier available)
Ephemeris:    pyswisseph
AI:           OpenAI API (GPT-4o) or Anthropic API
Push:         Firebase Cloud Messaging (FCM)
Hosting:      Railway.app
Scheduler:    APScheduler (runs daily batch job)
```

### Key API Endpoints

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
GET    /api/v1/auth/apple          (Sign in with Apple)

POST   /api/v1/profile/create
PUT    /api/v1/profile/update
GET    /api/v1/profile/natal       (returns natal chart JSON)

GET    /api/v1/advice/today        (returns today's advice for user)
GET    /api/v1/advice/date?date=   (returns cached advice for past date)

POST   /api/v1/places/search       (proxies Google Places)
POST   /api/v1/timezone/resolve    (returns historical timezone for lat/lng + date)

PUT    /api/v1/settings/mode       (change interpretation mode)
PUT    /api/v1/settings/notifications
DELETE /api/v1/account             (GDPR delete)
```

### Database Tables

```sql
users
  id, email, apple_id, created_at, language, subscription_status

profiles
  id, user_id, name, gender, 
  date_of_birth, time_of_birth, time_known,
  city_name, latitude, longitude, timezone_id, utc_offset_at_birth,
  natal_chart_json, interpretation_mode,
  notification_time, fcm_token

daily_advice
  id, user_id, date, mode, language,
  theme, moon_phase,
  love_score, love_text,
  work_score, work_text,
  energy_score, energy_text,
  communication_score, communication_text,
  mood_score, mood_text,
  risk_text,
  transit_tags,
  generated_at
```

### Daily Batch Job (runs 02:00 UTC)
```
1. Calculate today's planetary positions (once, shared)
2. Fetch all active users
3. For each user:
   a. Load natal chart from profile
   b. Compute personal transit aspects
   c. Score 6 categories
   d. Check Redis cache — skip if today's advice already exists
   e. Build prompt per category
   f. Call AI API (rate-limited, queued)
   g. Store result in daily_advice table + Redis cache
   h. Send push notification via FCM
4. Log completion + any errors
```

---

## 7. iOS App Architecture

### Stack
```
Language:       Swift 5.9+
UI:             SwiftUI
Architecture:   MVVM
Networking:     async/await + URLSession
Local storage:  SwiftData
Push:           Firebase iOS SDK
Auth:           Sign in with Apple
Subscriptions:  RevenueCat SDK
Analytics:      Mixpanel (or PostHog — open source option)
Localization:   Xcode String Catalogs (.xcstrings)
Min iOS:        17.0
```

### Folder Structure
```
LuminaDaily/
├── App/
│   ├── LuminaDailyApp.swift
│   └── AppEnvironment.swift
├── Features/
│   ├── Onboarding/
│   ├── Today/
│   ├── Chart/
│   ├── Explore/
│   ├── Calendar/
│   └── Profile/
├── Core/
│   ├── Models/
│   ├── Services/
│   │   ├── APIService.swift
│   │   ├── AuthService.swift
│   │   ├── NotificationService.swift
│   │   └── AnalyticsService.swift
│   └── Storage/
├── DesignSystem/
│   ├── Colors.swift
│   ├── Typography.swift
│   └── Components/
└── Resources/
    ├── Localizable.xcstrings
    └── Assets.xcassets
```

---

## 8. Localization

### Supported Languages
- English (en) — default
- Russian (ru)

### Rules
- All UI strings stored in `Localizable.xcstrings`
- AI advice generated natively in the target language — never translated
- Russian uses grammatical gender (sourced from profile gender field)
- Tone in Russian: literary, warm, slightly poetic — never clinical
- Tone in English: wise, warm, approachable — never generic

### Key string categories
```
onboarding.*       — all onboarding screens
today.*            — today screen labels
categories.*       — Love, Work, Energy, etc.
chart.*            — natal chart screen
explore.*          — mode descriptions
profile.*          — settings screen
notifications.*    — push notification copy
errors.*           — error messages
```

---

## 9. Monetization

### Model: Freemium + Annual Subscription

**Free tier:**
- Full onboarding + natal profile
- Today's theme sentence
- 2 categories per day (Love + Energy, rotating)
- 1 interpretation mode (Practical Daily)

**Premium (Lumina Plus):**
- All 6 categories every day
- All 6 interpretation modes
- Full calendar view
- Advice history
- Personalized notification time

**Pricing:**
- Monthly: $7.99 / month
- Annual: $44.99 / year (~$3.75/month)
- 7-day free trial on annual plan

**Implementation:** RevenueCat SDK (handles App Store billing, webhooks, entitlements)

**Paywall trigger:** After onboarding, when user tries to expand a locked category card.

---

## 10. Privacy & Security

- All birth data encrypted at rest (AES-256, via Supabase)
- JWT authentication, refreshed every 24 hours
- Sign in with Apple supported (no email required)
- GDPR compliant: full data export + delete account
- Russian 152-FZ compliant: data processing disclosure in onboarding
- No data sold to third parties — stated clearly in onboarding and privacy policy
- FCM tokens rotated on app launch
- API calls authenticated — no public endpoints

---

## 11. Third-Party Services & Costs (Monthly Estimate)

| Service | Purpose | Est. monthly cost |
|---|---|---|
| Railway.app | Backend hosting | $5–20 |
| Supabase | PostgreSQL database | Free – $25 |
| Upstash | Redis cache | Free – $10 |
| Google Places API | Birth place search | Free (under quota) |
| TimeZoneDB API | Historical timezone | Free |
| OpenAI API | Advice text generation | ~$0.02/user/day |
| Firebase | Push notifications | Free |
| RevenueCat | Subscription management | Free (under $2.5k MRR) |
| Apple Developer | App Store | $99/year |

**Total at 500 active users:** ~$50–100/month  
**Total at 5,000 active users:** ~$300–600/month

---

## 12. MVP Scope (What We Build First)

### In scope
- All 10 onboarding screens
- Today screen with all 6 categories
- Chart screen (static natal profile)
- Explore screen (mode switching)
- Profile + Settings screen
- Backend: natal calculation, daily batch, AI generation
- Push notifications
- English + Russian localization
- Freemium model with RevenueCat
- Sign in with Apple

### Out of scope (Phase 2)
- Calendar with transit overlay
- Compatibility reports
- Advice history / journal
- Monthly forecasts
- iOS Widget
- WatchOS app
- Vedic mode (complex — added in Phase 2)
- Voice reading

---

## 13. Build Order

```
Week 1–2:   Backend setup (Railway, Supabase, Swiss Ephemeris)
Week 2–3:   Natal chart calculation endpoint — tested + verified
Week 3–4:   Daily transit + scoring logic
Week 4–5:   AI prompt engineering — all 6 categories, EN + RU
Week 5–6:   Daily batch job + push notifications
Week 6–8:   iOS onboarding flow
Week 8–10:  iOS Today screen
Week 10–11: iOS Chart + Explore + Profile screens
Week 11–12: RevenueCat integration
Week 12–13: End-to-end testing
Week 13–14: TestFlight beta
Week 14–15: Bug fixes + App Store submission
Week 15–16: Launch
```
