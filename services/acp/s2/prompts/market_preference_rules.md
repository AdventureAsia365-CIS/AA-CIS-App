# Market Preference Rules

## Purpose

This file guides the Market Preference Engine.

The Market Preference Engine uses competitor tour data to understand how the market packages tours in a specific country.

This output is for internal Adventure Asia use only.

It should help Adventure Asia understand:

- common tour durations
- common price ranges
- price per day
- popular activities
- difficulty levels
- travel styles
- destination packaging
- seasonality signals
- start and end locations
- market expectations

The goal is not to copy competitors.

The goal is to understand what the market already accepts and understands.

---

## Core Rule

Competitor tours are market reference points.

Do not compare Adventure Asia tours one-to-one with competitor tours.

Do not write public content using competitor wording.

Do not copy competitor titles, descriptions, itinerary language, highlights, or selling phrases.

Use competitor data only to identify market patterns.

---

## Adventure Asia Positioning

Adventure Asia is a premium curated soft-adventure brand.

Adventure Asia is not:

- backpacker group travel
- budget adventure travel
- mass-market package tours
- ultra-luxury excess

Adventure Asia serves experienced professionals and higher-income travellers who want:

- cultural depth
- active but comfortable travel
- smooth logistics
- expert local planning
- private-feeling journeys
- curated adventure across Asia
- local knowledge without chaos
- adventure with quality and confidence

Adventure Asia sits between mass adventure travel and ultra-luxury bespoke travel.

---

## Competitor Reference Logic

Use competitors as reference points only.

| Brand | What it tells us | How Adventure Asia uses it |
|---|---|---|
| Intrepid | Mass adventure demand | Identify countries, activities, and keywords with proven volume |
| G Adventures | Group-tour keyword demand | Understand popular group-tour themes and search language |
| Exodus | Active holiday demand | Understand cycling, trekking, and hiking demand |
| Remote Lands | Premium expectation reference | Understand high-end positioning and premium traveller expectations |
| Adventure Asia | Premium soft adventure | Create refined, curated content linked to AA tours |

---

## Data to Analyse

From each competitor tour page, analyse:

- country
- competitor name
- tour URL
- tour title
- duration
- price
- currency
- price per day
- main activities
- activity category
- difficulty level
- travel style
- group/private/luxury/tailor-made signals
- start city
- end city
- highlights
- itinerary summary
- seasonality signals
- included/excluded notes
- scrape date

---

## Analysis Tasks

### 1. Duration Pattern

Group tours into duration bands:

- 1–3 days
- 4–6 days
- 7–10 days
- 11–14 days
- 15+ days

Explain which duration bands appear most often.

### 2. Price Pattern

Analyse:

- lowest price
- highest price
- average price
- price per day
- price range by competitor
- price range by activity
- premium vs mid-market vs budget signals

Do not judge AA as expensive or cheap unless there is enough evidence.

Use neutral language such as:

- “market price reference”
- “premium price signal”
- “mid-market reference”
- “price band visible in competitor data”

### 3. Activity Pattern

Group activities into useful categories:

- cycling
- trekking
- hiking
- cultural touring
- food and local life
- wildlife
- river / boat / kayaking
- wellness / retreat
- photography
- family adventure
- multi-activity
- luxury cultural journey

Explain which activities appear most often.

### 4. Difficulty Pattern

Classify difficulty where possible:

- soft
- easy
- moderate
- active
- challenging
- unknown

If difficulty is not clearly available, mark as `unknown`.

Do not guess too strongly.

### 5. Travel Style Pattern

Classify travel style where possible:

- group tour
- private tour
- tailor-made
- luxury
- active holiday
- cultural journey
- family-friendly
- small group
- unknown

### 6. Market Packaging Insight

Explain how the market packages the destination.

Look for:

- common trip length
- common activity combinations
- common start/end cities
- repeated travel themes
- common promises
- comfort level
- logistics signals
- whether the country is sold as active, cultural, luxury, or mixed

### 7. Internal AA Implication

Translate market pattern into internal implication for Adventure Asia.

Good examples:

- “The market already understands Taiwan as a cycling destination. AA can use this as background when creating content around active but comfortable cycling journeys.”
- “Competitor tours often package Nepal around trekking. AA can position around trekking plus cultural depth and smoother logistics.”
- “Laos appears less crowded in competitor coverage. AA may have an opportunity to build early visibility around soft adventure and river-based travel.”

Bad examples:

- “AA should copy this itinerary.”
- “AA should be cheaper than Intrepid.”
- “AA should write the same blog as Exodus.”
- “AA should compare itself directly with Remote Lands.”

---

## Output Requirements

Create two outputs:

```text
output/market_preference/market_preference_internal.xlsx
output/market_preference/market_preference_summary.md

# Valid Output Requirement

Do not create a summary unless competitor data has been extracted and cleaned.

The report must include actual values for:
- competitor
- URL
- tour title
- duration
- price or price missing flag
- price per day or calculation unavailable flag
- activities
- difficulty or unknown
- travel style or unknown

If these fields are mostly empty, write an error report instead of a market preference report.