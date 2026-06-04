"""
AA-121: Jaccard threshold calibration for Stage E cross-platform deduplication.

18 pairs: 6 tours × 3 platform combinations (TikTok/FB Post/FB Ad).
Run: python3 scripts/calibrate_jaccard.py
"""
import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def tokenize(text: str) -> set:
    return set(re.findall(r'\b\w+\b', text.lower()))


def jaccard(text_a: str, text_b: str) -> float:
    a, b = tokenize(text_a), tokenize(text_b)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Hardcoded content — extracted verbatim from samples/social_content_korea.md
# ---------------------------------------------------------------------------

TOURS = {
    "Korea by Bike (Seoul→Busan 9D)": {
        "tiktok": (
            "Seoul's skyline at dusk from a bike seat hits different "
            "Day 2: DMZ in the morning. 35km Han River ride by sunset. "
            "Day 5: 55km along the East Sea — cliffs on your left, ocean on your right. "
            "Day 6: Gyeongju at night. Empty streets. Lit tombs. Just you and a thousand years. "
            "9 days. Seoul to Busan. The route we've refined over 6 years. "
            "Link in bio for the full day-by-day."
        ),
        "fb_post": (
            "Day 2 of our Korea by Bike tour starts seven metres "
            "underground at the Korean border. "
            "By sunset, you're riding 35km along the Han River watching Seoul light up. "
            "That's the thing about cycling Korea — the DMZ and the skyline are the same day. "
            "The pine forests and the East Sea coast are the same week. "
            "The hot pot on Day 1 and the farewell dinner on Day 8 feel like different trips, "
            "except your legs remember all of it. "
            "9 days. Seoul to Busan. Every detail in our free day-by-day PDF."
        ),
        "fb_ad": (
            "You've compared 6 Korea cycling tours. They all blur together. "
            "Same stock photos of the Four Rivers path. Same vague scenic coastline descriptions. "
            "No one tells you which day is hardest, which restaurant to skip, "
            "or what happens when the DMZ visit gets cancelled. "
            "We've been riding Seoul to Busan for 6 years. "
            "Our 9-day route breaks from the standard "
            "Four Rivers path on Day 4 to add the East Sea coast, Gyeongju at night, "
            "and a DMZ morning that shapes the entire trip. "
            "The day-by-day PDF includes distances, terrain, and the stops we've tested across "
            "dozens of departures. Free download, no pitch."
        ),
    },

    "Sanmani Trail (Jirisan Dulegil)": {
        "tiktok": (
            "You walk for 7 days through Korean villages nobody visits. "
            "Then you arrive at a 400-year-old market "
            "where farmers still sell what the mountain grows. "
            "The Sanmani Trail isn't a hike. It's a pilgrimage through paths Korean foragers "
            "walked for centuries. "
            "10 days. Jirisan's foothills. Link in bio."
        ),
        "fb_post": (
            "During the Korean War, civilians fled into Jirisan's valleys to survive. "
            "Centuries before that, the Sanmani — mountain foragers — walked these same paths, "
            "harvesting wild ginseng and carrying herbs to market. "
            "The Jirisan Dulegil follows their foothill routes. Not to the summit. "
            "Through the villages, the farm tracks, the forest paths that kept people alive. "
            "10 days of walking. 8–20km per day. Ending at Hwagae Market, "
            "where those paths still converge. "
            "We've led 12 departures on this trail. The story is the route."
        ),
        "fb_ad": (
            "If you've walked the Camino, you should know about Jirisan. "
            "Korea's first national park has a foothill circuit that takes 10 days — "
            "village to village, through paths walked by mountain foragers for centuries. "
            "It's not a summit hike. It's a multi-day walk through living communities, "
            "ending at a marketplace that's been trading since the Joseon dynasty. "
            "No other operator tells the Sanmani story — the foragers who shaped these paths, "
            "the refugees who survived because of them. We've been leading this trail since 2022. "
            "Day-by-day PDF with distances, elevation, and village stops. Free download."
        ),
    },

    "Jeju Island Coastal Cycling (4D)": {
        "tiktok": (
            "230km around a volcanic island in 4 days. "
            "Day 2: 90km along the south coast. The hardest day. Also the most beautiful. "
            "Day 3: Ferry to Udo Island. Two hours cycling a place most tourists never reach. "
            "Jeju's coastal bike path. Built for exactly this."
        ),
        "fb_post": (
            "Jeju Island has a 230km bike path that circles the entire coast. "
            "Four days. Volcanic cliffs, emerald water, fishing villages, and one morning hiking "
            "a crater that rose from the sea 5,000 years ago. "
            "Day 2 is 90 kilometres — the longest and hardest. "
            "Day 3 is a ferry to Udo Island for a two-hour loop nobody forgets. "
            "The full coastal circuit. Guided. Supported."
        ),
        "fb_ad": (
            "Jeju Island built a dedicated bike path around its entire coast. "
            "230 kilometres of paved, car-free trail with the East Sea on one side "
            "and volcanic hills on the other. "
            "Most visitors see Jeju from a tour bus. This four-day circuit puts you on the coast "
            "road, through fishing villages, past the Seongsan crater, "
            "and onto Udo Island by ferry. "
            "Our guide team has ridden this circuit dozens of times. "
            "The day-by-day PDF includes distances, elevation, and the stops worth making."
        ),
    },

    "Coast to Coast Korea (5D)": {
        "tiktok": (
            "West Sea to East Sea. 320km. 5 days. "
            "Day 2: 99km along the Bukhangang River. The longest day. "
            "Day 4: Climb over Seoraksan. 1,300m of elevation. Then the coast appears. "
            "Korea coast to coast on a bike. It's exactly what it sounds like."
        ),
        "fb_post": (
            "Five days to cross South Korea by bicycle. "
            "Start at Incheon on the West Sea. Finish at Sokcho on the East Sea. "
            "In between: 320km through Seoul, along the Bukhangang River, into the mountains, "
            "and over a Seoraksan pass with 1,300 metres of climbing. "
            "Day 4 is the day you earn. Day 5 is the day you celebrate — "
            "either hiking Seorak National Park or visiting the DMZ by vehicle. "
            "Fully supported. Private guide. Luggage in the van."
        ),
        "fb_ad": (
            "There's a cycling route that crosses South Korea from coast to coast in five days. "
            "Incheon to Sokcho. West Sea to East Sea. "
            "320 kilometres through Seoul, along river valleys, and over the Seoraksan mountain "
            "pass — 1,300 metres of climbing in a single day. "
            "It's not a casual tour. It's a structured challenge with full support: "
            "guide, vehicle, accommodation, "
            "and a post-ride day in Seorak National Park or the DMZ. "
            "Our day-by-day PDF breaks down every stage — distances, elevation, terrain, "
            "and what to expect."
        ),
    },

    "Namhae Island (3D)": {
        "tiktok": (
            "Day 1: Sea kayaking through a national marine park. Bonfire on the beach. "
            "Day 2: Summit hike. Views over every island in the bay. "
            "Day 3: Terraced rice fields stepping down to the sea. "
            "3 days on a Korean island most foreigners have never heard of."
        ),
        "fb_post": (
            "Koreans call Namhae Treasure Island. Most foreign visitors have never heard of it. "
            "Three days: sea kayaking through a marine national park, "
            "a summit hike above the bay, "
            "and two nights in working fishing and farming villages — not hotels. "
            "Darangee Village has terraced rice fields that step down to the coastline. "
            "You sleep in a farmer's house and wake up to the sound of the tide. "
            "From Seoul. Private guide. Back in 3 days."
        ),
        "fb_ad": (
            "Three days off the standard Korea tourist trail. "
            "Namhae Island sits off South Korea's southern coast — a place of fishing villages, "
            "terraced rice fields, and a marine national park best seen from a kayak. "
            "Most Korea tours skip it entirely. Ours starts with 2.5 hours of sea kayaking, "
            "climbs Mt. Geum for views over the bay, and ends with a morning on Darangee beach "
            "before the drive back to Seoul. "
            "You stay in the villages — not near them."
        ),
    },

    "Seoul to Jeju (12D)": {
        "tiktok": (
            "Day 5: Sleep on a heated stone floor in a Buddhist temple. "
            "Wake at dawn for chanting. "
            "Day 6: Cycle past royal tombs in Gyeongju at sunset. "
            "Day 10: Climb a volcanic crater on Jeju with the sea on three sides. "
            "12 days. Seoul to Jeju. Everything Korea has."
        ),
        "fb_post": (
            "Seoul to Jeju in 12 days covers more of Korea than most people see in a month. "
            "DMZ. Seoraksan National Park. A temple stay at Golgulsa with pre-dawn chanting. "
            "Cycling through Gyeongju's royal tombs at dusk. Busan's coastal temples. "
            "And Jeju — volcanic craters, the Olle Trail, "
            "and a yacht trip before the farewell BBQ. "
            "Taekwondo class on Day 1. K-pop dance class on Day 3. "
            "Nobody said adventure can't be fun. "
            "Guided throughout. Domestic flight included."
        ),
        "fb_ad": (
            "Most Korea tours show you Seoul and Busan. "
            "This one goes from the DMZ to a volcanic island. "
            "12 days: taekwondo and K-pop in Seoul, a temple overnight at Golgulsa, "
            "cycling Gyeongju's ancient tombs, Busan's cliffside temples, "
            "and a full Jeju Island circuit ending with a yacht trip and farewell BBQ. "
            "It covers hiking, cycling, cultural sites, and two coastlines — without rushing. "
            "The full 12-day itinerary PDF breaks down every day. Free download."
        ),
    },
}

# Manual labels: 'distinct' or 'too_similar'
# Rationale documented in docs/implementation-notes/AA-121.md
MANUAL_LABELS = {
    # Tour 1 — Korea by Bike
    # TikTok: SSS/sensory hook. FB Post: contrast principle (underground→river).
    # FB Ad: PAS/research fatigue. All three use different angles/frameworks.
    ("Korea by Bike (Seoul→Busan 9D)", "tiktok", "fb_post"): "distinct",
    ("Korea by Bike (Seoul→Busan 9D)", "tiktok", "fb_ad"): "distinct",
    ("Korea by Bike (Seoul→Busan 9D)", "fb_post", "fb_ad"): "distinct",

    # Tour 2 — Sanmani Trail
    # TikTok: curiosity/"pilgrimage" reframe. FB Post: Korean War history/narrative.
    # FB Ad: Camino comparison/PAS. All three use completely different hooks and angles.
    ("Sanmani Trail (Jirisan Dulegil)", "tiktok", "fb_post"): "distinct",
    ("Sanmani Trail (Jirisan Dulegil)", "tiktok", "fb_ad"): "distinct",
    ("Sanmani Trail (Jirisan Dulegil)", "fb_post", "fb_ad"): "distinct",

    # Tour 3 — Jeju Island Cycling
    # TikTok: bullet stats. FB Post: narrative/sensory.
    # FB Ad: "most visitors from a tour bus" contrast.
    # FB Post vs FB Ad share facts but differ in angle (narrative vs informational authority).
    ("Jeju Island Coastal Cycling (4D)", "tiktok", "fb_post"): "distinct",
    ("Jeju Island Coastal Cycling (4D)", "tiktok", "fb_ad"): "distinct",
    ("Jeju Island Coastal Cycling (4D)", "fb_post", "fb_ad"): "distinct",

    # Tour 4 — Coast to Coast
    # FB Post and FB Ad both open by stating "5 days to cross Korea" then list identical landmarks
    # (Incheon, West/East Sea, 320km, Bukhangang, Seoraksan, 1300m, DMZ) in the same order.
    # Different CTA targets (tour link vs PDF) but same angle — flagged as too_similar.
    ("Coast to Coast Korea (5D)", "tiktok", "fb_post"): "distinct",
    ("Coast to Coast Korea (5D)", "tiktok", "fb_ad"): "distinct",
    ("Coast to Coast Korea (5D)", "fb_post", "fb_ad"): "too_similar",

    # Tour 5 — Namhae Island
    # TikTok: bullet/day format. FB Post: "Treasure Island" emotional storytelling.
    # FB Ad: "off the standard trail" informational. All three use distinct angles.
    ("Namhae Island (3D)", "tiktok", "fb_post"): "distinct",
    ("Namhae Island (3D)", "tiktok", "fb_ad"): "distinct",
    ("Namhae Island (3D)", "fb_post", "fb_ad"): "distinct",

    # Tour 6 — Seoul to Jeju 12D
    # FB Post and FB Ad both enumerate the same 8+ activities (taekwondo, K-pop,
    # Golgulsa, Gyeongju, Busan temples, Jeju, yacht trip, farewell BBQ) with nearly
    # identical coverage. Different openers but same angle — flagged as too_similar.
    ("Seoul to Jeju (12D)", "tiktok", "fb_post"): "distinct",
    ("Seoul to Jeju (12D)", "tiktok", "fb_ad"): "distinct",
    ("Seoul to Jeju (12D)", "fb_post", "fb_ad"): "too_similar",
}

PLATFORM_PAIRS = [
    ("tiktok", "fb_post"),
    ("tiktok", "fb_ad"),
    ("fb_post", "fb_ad"),
]


# ---------------------------------------------------------------------------
# Build scored pairs
# ---------------------------------------------------------------------------

def build_pairs():
    pairs = []
    for tour_name, platforms in TOURS.items():
        for plat_a, plat_b in PLATFORM_PAIRS:
            text_a = platforms[plat_a]
            text_b = platforms[plat_b]
            score = jaccard(text_a, text_b)
            label = MANUAL_LABELS[(tour_name, plat_a, plat_b)]
            pairs.append({
                "tour": tour_name,
                "platform_a": plat_a,
                "platform_b": plat_b,
                "score": score,
                "label": label,
            })
    return pairs


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate(pairs, thresholds):
    results = []
    for t in thresholds:
        tp = fp = fn = tn = 0
        for p in pairs:
            predicted = p["score"] >= t
            actual = p["label"] == "too_similar"
            if predicted and actual:
                tp += 1
            elif predicted and not actual:
                fp += 1
            elif not predicted and actual:
                fn += 1
            else:
                tn += 1
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)
        results.append({
            "threshold": t,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
        })
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pairs = build_pairs()

    # --- Per-pair scores ---
    print("\n=== All 18 pair scores ===")
    header = f"{'Tour':<35} {'PlatA':<10} {'PlatB':<10} {'Score':>6}  {'Label'}"
    print(header)
    print("-" * len(header))
    for p in pairs:
        mark = " *** TOO_SIMILAR" if p["label"] == "too_similar" else ""
        print(
            f"{p['tour']:<35} {p['platform_a']:<10} {p['platform_b']:<10} "
            f"{p['score']:>6.3f}  {p['label']}{mark}"
        )

    # --- Calibration sweep ---
    thresholds = [round(t * 0.05, 2) for t in range(1, 13)]  # 0.05 .. 0.60
    results = calibrate(pairs, thresholds)

    print("\n=== Calibration sweep ===")
    col = (
        f"{'Threshold':>9} {'Precision':>9} {'Recall':>7}"
        f" {'F1':>6} {'TP':>4} {'FP':>4} {'FN':>4}"
    )
    print(col)
    print("-" * len(col))
    for r in results:
        flag = " <-- meets criteria" if r["recall"] >= 0.90 and r["precision"] >= 0.85 else ""
        print(
            f"{r['threshold']:>9.2f} {r['precision']:>9.3f} {r['recall']:>7.3f} "
            f"{r['f1']:>6.3f} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4}{flag}"
        )

    # --- Recommendation ---
    candidates = [
        r for r in results
        if r["recall"] >= 0.90 and r["precision"] >= 0.85
    ]
    print()
    if candidates:
        best = max(candidates, key=lambda r: r["f1"])
        print(f"Recommended threshold: {best['threshold']:.2f}")
        print(
            f"  Precision={best['precision']:.3f}  Recall={best['recall']:.3f}  "
            f"F1={best['f1']:.3f}  TP={best['tp']}  FP={best['fp']}  FN={best['fn']}"
        )
    else:
        # Fallback: highest recall while keeping precision as high as possible
        best_recall = max(results, key=lambda r: (r["recall"], r["precision"]))
        print("No threshold met both criteria (recall>=0.90 AND precision>=0.85).")
        print(f"Best recall candidate: threshold={best_recall['threshold']:.2f}  "
              f"Precision={best_recall['precision']:.3f}  "
              f"Recall={best_recall['recall']:.3f}")
        print("Consider loosening precision floor or reviewing manual labels.")

    # --- Class distribution ---
    n_similar = sum(1 for p in pairs if p["label"] == "too_similar")
    n_distinct = len(pairs) - n_similar
    print(f"\nDataset: {len(pairs)} pairs — {n_similar} too_similar / {n_distinct} distinct")


if __name__ == "__main__":
    main()
