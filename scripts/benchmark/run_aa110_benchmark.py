#!/usr/bin/env python3
"""AA-110: Benchmark GPT-4o vs Bedrock Sonnet 4.5 for Facebook Post (Stage D Writing).

Generates Facebook posts for 5 Vietnam tours using both models sequentially,
saves raw outputs to /tmp/aa110_benchmark/raw/<model>/<tour_slug>.json,
and creates a scoring CSV template for manual review by Nghiep + Ms. Thu.

Usage:
  python scripts/benchmark/run_aa110_benchmark.py --dry-run
  python scripts/benchmark/run_aa110_benchmark.py
  python scripts/benchmark/run_aa110_benchmark.py --tours halong-bay-luxury-cruise sapa-trekking-adventure
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SKILL_MD_PATH = (
    Path(__file__).parents[2]
    / "docs/AI-gent-for automation works"
    / "stage4.2_ Social-media contents_v2"
    / "SKILL.md"
)

OUTPUT_DIR = Path("/tmp/aa110_benchmark")
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
GPT4O_MODEL_ID = "gpt-4o"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

VIETNAM_TOURS: list[dict[str, Any]] = [
    {
        "slug": "halong-bay-luxury-cruise",
        "name": "Ha Long Bay Luxury Junk Cruise",
        "destination": "Ha Long Bay, Quang Ninh Province, Vietnam",
        "duration": "3 days / 2 nights",
        "highlights": [
            "Private cabin on a traditional wooden junk with panoramic bay views",
            "Kayaking through limestone karst formations at dawn",
            "Chef-prepared seafood dinners on deck at sunset",
            "Cave exploration at Thien Canh Son with guided interpretation",
            "Tai Chi session on the sundeck at first light",
        ],
        "price_range": "USD 850–1,200 per person",
        "target_audience": "Senior professionals 40-60 seeking private, unhurried luxury on water",
    },
    {
        "slug": "hoi-an-cultural-immersion",
        "name": "Hoi An Tailored Cultural Immersion",
        "destination": "Hoi An Ancient Town, Quang Nam, Vietnam",
        "duration": "4 days / 3 nights",
        "highlights": [
            "Private lantern-lit evening walk through UNESCO-listed ancient town",
            "Bespoke ao dai tailoring session with a third-generation master tailor",
            "Hands-on Vietnamese cooking class at a heritage garden villa",
            "Sunrise cycling through Cam Thanh coconut water village",
            "Curator-guided tour of private Japanese Merchant House collections",
        ],
        "price_range": "USD 600–900 per person",
        "target_audience": "Culturally curious professionals valuing artisan craft and historical depth",
    },
    {
        "slug": "sapa-trekking-adventure",
        "name": "Sapa Highland Trekking Circuit",
        "destination": "Sapa, Lao Cai Province, Northern Vietnam",
        "duration": "3 days / 2 nights",
        "highlights": [
            "Guided ridge walk along Muong Hoa Valley with terraced rice field views",
            "Overnight homestay with H'mong family — authentic home-cooked dinner included",
            "Private rice terrace photography session at harvest season",
            "Mountain guide interpretation of local agricultural and textile traditions",
            "Fansipan summit option (cable car) for 360-degree highland panorama",
        ],
        "price_range": "USD 400–650 per person",
        "target_audience": "Active professionals 45-60 seeking physical engagement with cultural depth",
    },
    {
        "slug": "ho-chi-minh-food-tour",
        "name": "Ho Chi Minh City Culinary Circuit",
        "destination": "Ho Chi Minh City (Saigon), Vietnam",
        "duration": "2 days / 1 night",
        "highlights": [
            "Private market walk through Ben Thanh and Binh Tay with a Vietnamese chef",
            "Pho broth masterclass at a family-run restaurant established in 1965",
            "Rooftop aperitif at a 1930s French colonial heritage building",
            "Guided street food progression through Districts 1, 3, and 4",
            "Behind-the-scenes visit to a small-batch banh mi bakery",
        ],
        "price_range": "USD 350–550 per person",
        "target_audience": "Food-focused professionals who value provenance, craft, and culinary history",
    },
    {
        "slug": "mekong-delta-eco-journey",
        "name": "Mekong Delta Private Eco Journey",
        "destination": "Mekong Delta, Can Tho Province, Vietnam",
        "duration": "2 days / 1 night",
        "highlights": [
            "Private longtail boat charter through narrow canal networks at sunrise",
            "Guided visit to Cai Rang floating market before tourist hours",
            "Overnight at a restored French colonial river lodge with garden access",
            "Orchard walk with local farmer explaining dragon fruit and pomelo cultivation",
            "River sunset with Vietnamese iced coffee tasting and local storytelling",
        ],
        "price_range": "USD 300–500 per person",
        "target_audience": "Professionals seeking slow-travel rhythm, water landscapes, and genuine local connection",
    },
]

SCORE_COLUMNS = [
    "hook_strength",
    "brand_voice",
    "specificity",
    "CTA_clarity",
    "platform_fit",
    "proof_presence",
    "rhythm",
    "audience_alignment",
    "differentiator_present",
    "CMS_ready",
]
SCORING_COLUMNS = ["tour", "model"] + SCORE_COLUMNS + ["total_avg", "notes"]


def load_skill_text() -> str:
    if SKILL_MD_PATH.exists():
        return SKILL_MD_PATH.read_text(encoding="utf-8")
    # Minimal fallback if SKILL.md path not available
    return (
        "You are a strategic English content writer for Adventure Asia, a premium travel brand targeting "
        "senior professionals 40-60. Write Facebook posts that are calm, assured, specific, and human. "
        "Never produce generic AI-style marketing copy. Use concrete details from the brief. "
        "CTA must be 'Design This Journey' — never 'Book Now'."
    )


def build_user_prompt(tour: dict[str, Any]) -> str:
    highlights_text = "\n".join(f"  - {h}" for h in tour["highlights"])
    brief = (
        f"Brand: Adventure Asia\n"
        f"Audience: {tour['target_audience']}\n"
        f"Channel: Facebook Post\n"
        f"Goal: Generate engaged comments and qualified inquiries\n"
        f"Topic/offer: {tour['name']} — {tour['destination']} ({tour['duration']})\n"
        f"Tone/style: Calm, assured, well-traveled, selective, precise. Premium without being ostentatious.\n"
        f"CTA: Design This Journey\n"
        f"Must include: Specific highlights drawn from the itinerary, price range ({tour['price_range']})\n"
        f"Must avoid: Deals / Cheap / Book Now / stunning / breathtaking / unforgettable / "
        f"hidden gem / bucket list / epic / fun / exciting / amazing / vibrant / "
        f"immersive experiences / package / dream trip / once in a lifetime\n"
        f"Tour highlights to draw from:\n{highlights_text}"
    )
    return (
        "Write the final Facebook post content only. "
        "Do not include strategy explanations, angle headers, or formula labels.\n\n"
        "Apply Facebook channel rules: direct, clear, human language with a strong opening and short paragraphs.\n"
        "Use the Adventure Asia brand voice: calm, assured, curated, premium, precise.\n"
        "End with 'Design This Journey' as the CTA.\n\n"
        f"{brief}"
    )


def call_gpt4o(system_prompt: str, user_prompt: str, api_key: str) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    payload = {
        "model": GPT4O_MODEL_ID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI error {exc.code}: {exc.read().decode()}") from exc
    latency_ms = int((time.time() - t0) * 1000)

    content = body["choices"][0]["message"]["content"].strip()
    usage = body.get("usage", {})
    return {
        "model": GPT4O_MODEL_ID,
        "content": content,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "latency_ms": latency_ms,
    }


def call_bedrock_sonnet(system_prompt: str, user_prompt: str, aws_profile: str) -> dict[str, Any]:
    import boto3

    session = boto3.Session(profile_name=aws_profile, region_name="us-west-1")
    client = session.client("bedrock-runtime")
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "temperature": 0.7,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    t0 = time.time()
    response = client.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(payload),
        contentType="application/json",
        accept="application/json",
    )
    latency_ms = int((time.time() - t0) * 1000)

    body = json.loads(response["body"].read())
    content = body["content"][0]["text"].strip()
    usage = body.get("usage", {})
    return {
        "model": BEDROCK_MODEL_ID,
        "content": content,
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "latency_ms": latency_ms,
    }


def make_mock_result(model_label: str, tour: dict[str, Any]) -> dict[str, Any]:
    slug = tour["slug"]
    return {
        "model": model_label,
        "content": (
            f"[DRY RUN — {model_label}] Mock Facebook post for '{tour['name']}' ({slug}). "
            "Ha Long Bay at first light is not a backdrop — it is the entire itinerary. "
            "Two nights aboard a private wooden junk, limestone formations at eye level, "
            "a chef whose seafood menu changes with the morning catch. From USD 850 per person. "
            "Design This Journey."
        ),
        "prompt_tokens": 480,
        "completion_tokens": 95,
        "latency_ms": 42,
    }


def run_benchmark(tours: list[dict[str, Any]], dry_run: bool, aws_profile: str) -> None:
    skill_text = load_skill_text()
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if not dry_run and not openai_key:
        print("ERROR: OPENAI_API_KEY is not set. Export it or use --dry-run.")
        raise SystemExit(1)

    raw_dir = OUTPUT_DIR / "raw"
    for slug in ("gpt4o", "bedrock-sonnet-45"):
        (raw_dir / slug).mkdir(parents=True, exist_ok=True)

    scoring_rows: list[dict[str, str]] = []
    lines: list[str] = []
    mode_label = "DRY RUN" if dry_run else "LIVE"
    lines.append("=" * 80)
    lines.append(f"AA-110 BENCHMARK  |  GPT-4o vs Bedrock Sonnet 4.5  |  {mode_label}")
    lines.append(f"Channel: Facebook Post  |  Tours: {len(tours)}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 80)

    model_configs = [
        ("GPT-4o", "gpt4o"),
        ("Bedrock Sonnet 4.5", "bedrock-sonnet-45"),
    ]

    for tour in tours:
        slug = tour["slug"]
        user_prompt = build_user_prompt(tour)
        lines.append(f"\n[Tour] {tour['name']}  ({slug})")
        lines.append(f"       {tour['destination']} | {tour['duration']} | {tour['price_range']}")

        for model_label, model_slug in model_configs:
            if dry_run:
                result = make_mock_result(model_label, tour)
            elif model_slug == "gpt4o":
                print(f"  -> Calling GPT-4o for {slug} ...", flush=True)
                result = call_gpt4o(skill_text, user_prompt, openai_key)
            else:
                print(f"  -> Calling Bedrock Sonnet 4.5 for {slug} ...", flush=True)
                result = call_bedrock_sonnet(skill_text, user_prompt, aws_profile)

            result.update({
                "tour_slug": slug,
                "tour_name": tour["name"],
                "destination": tour["destination"],
                "timestamp": datetime.now().isoformat(),
                "system_prompt_chars": len(skill_text),
                "user_prompt_chars": len(user_prompt),
            })

            out_path = raw_dir / model_slug / f"{slug}.json"
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

            preview = result["content"][:200].replace("\n", " ")
            lines.append(
                f"  [{model_label:20s}] latency={result['latency_ms']:>5}ms  "
                f"tokens={result['prompt_tokens']}+{result['completion_tokens']}  "
                f"| {preview}..."
            )

            scoring_rows.append({
                "tour": tour["name"],
                "model": model_label,
                **{col: "" for col in SCORE_COLUMNS},
                "total_avg": "",
                "notes": "",
            })

        if not dry_run:
            time.sleep(2)

    csv_path = OUTPUT_DIR / "scoring_sheet.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORING_COLUMNS)
        writer.writeheader()
        writer.writerows(scoring_rows)

    lines.append("\n" + "=" * 80)
    lines.append("OUTPUT FILES")
    lines.append(f"  Raw JSON   : {raw_dir}/{{gpt4o,bedrock-sonnet-45}}/<tour_slug>.json")
    lines.append(f"  Scoring CSV: {csv_path}")
    lines.append(f"  Rows in CSV: {len(scoring_rows)} ({len(tours)} tours x 2 models)")
    lines.append("=" * 80)

    output = "\n".join(lines)
    print(output)

    log_path = OUTPUT_DIR / "run_log.txt"
    log_path.write_text(output, encoding="utf-8")
    print(f"\nLog saved: {log_path}")


def parse_args() -> argparse.Namespace:
    all_slugs = [t["slug"] for t in VIETNAM_TOURS]
    parser = argparse.ArgumentParser(
        description="AA-110: Benchmark GPT-4o vs Bedrock Sonnet 4.5 for Facebook Post writing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/benchmark/run_aa110_benchmark.py --dry-run\n"
            "  python scripts/benchmark/run_aa110_benchmark.py\n"
            "  python scripts/benchmark/run_aa110_benchmark.py --tours halong-bay-luxury-cruise\n"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip API calls; use mock output.")
    parser.add_argument("--aws-profile", default="pqnghiep-admin", help="AWS CLI profile for Bedrock.")
    parser.add_argument(
        "--tours",
        nargs="+",
        metavar="SLUG",
        choices=all_slugs + ["all"],
        default=["all"],
        help=f"Tour slugs to run. Default: all. Available: {', '.join(all_slugs)}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = VIETNAM_TOURS if "all" in args.tours else [t for t in VIETNAM_TOURS if t["slug"] in args.tours]
    if not selected:
        print("No tours matched. Check --tours values.")
        raise SystemExit(1)
    run_benchmark(selected, dry_run=args.dry_run, aws_profile=args.aws_profile)


if __name__ == "__main__":
    main()
