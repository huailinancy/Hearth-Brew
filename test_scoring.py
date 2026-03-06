import anthropic
import json
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from prompts import SYSTEM_PROMPT

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("Usage: ANTHROPIC_API_KEY=sk-ant-... python3 test_scoring.py")
    sys.exit(1)

client = anthropic.Anthropic(api_key=API_KEY)

# ── Content types (matches HTML app) ─────────────────────────────────────────
CONTENT_TYPES = [
    "New seasonal drink launch",
    "Weekly Baker's Choice reveal",
    "Board game night event",
    "Community book trade highlight",
    "Ferry commuter morning special",
    "Behind-the-scenes baking",
    "Rainy PNW day cozy vibes",
    "Regular customer spotlight",
    "Seasonal / holiday promotion",
    "General brand post",
]

PLATFORMS = ["Instagram", "Facebook", "TikTok"]

# ── Platform generation rules (mirrors HTML RULES) ────────────────────────────
PLATFORM_RULES = {
    "Instagram": """Platform: Instagram
- Output ONLY the post text — no preamble, no "Here's a caption", no labels, no markdown headers
- Write a warm, inviting caption — visual-first, describe or reference the scene
- Length: 2-3 sentences (use 4 only if each sentence is short and punchy)
- Name at least one specific Hearth & Brew item by name (e.g. "lavender honey latte", "Puget Sound Fog", "Baker's Choice brown butter bars") — never say "seasonal drink" or "fresh pastry" without naming it
- Use 1-2 emojis maximum, placed naturally (not at the start of every line)
- Hashtags: 4-6 tags — prioritise hyper-local tags: #EdmondsWA #PNWCoffee #CoffeeShop #EdmondsCoffee #PNWLife — avoid generic tags like #SmallBusiness unless all local slots are filled
- Tone: warm, slightly poetic, inviting — make someone want to be there right now""",

    "Facebook": """Platform: Facebook
- Output ONLY the post text — no preamble, no "Here's a post", no labels, no markdown headers
- Write a warm, community-focused post
- Length: 3-5 sentences — slightly more informational than other platforms
- Name at least one specific menu item by name (drink, pastry, or weekly special)
- Include a specific time or day detail when relevant (e.g. "fresh until noon", "this Saturday morning", "until they're gone by 10am")
- Include a soft call-to-action (stop by, come find us, grab one before they're gone, etc.)
- No hashtags
- Tone: friendly and welcoming — appeals to families, retirees, and longtime Edmonds locals""",

    "TikTok": """Platform: TikTok
- Output ONLY the post text — no preamble, no "Here's a post", no labels, no markdown headers
- Strictly 50-80 words — count carefully, do not exceed 80 words
- High-energy hook as the opening line (make it impossible to scroll past)
- Name at least one specific Hearth & Brew item by name in the post
- Trend-aware, conversational, Gen-Z adjacent
- End the caption with a comment/engagement CTA (e.g. "drop your order below 👇", "tag who you're bringing ☕", "comment your go-to order")
- 3-5 hashtags — prefer discovery tags (#FoodTok #CoffeeTok #EdmondsWA) over generic ones like #SmallBusiness
- End with a brief suggested video concept in parentheses""",
}

# ── Platform-aware scoring rules (mirrors HTML SCORE_PLATFORM_RULES) ──────────
SCORE_PLATFORM_RULES = {
    "Instagram": """Format rules for this post:
- Caption: 2-3 sentences (4 only if each is short and punchy)
- Must name at least one specific menu item by name — penalise if it says "seasonal drink" or "fresh pastry" without naming it
- Emojis: 1-2 maximum, placed naturally (not at the start of every line)
- Hashtags: 4-6 tags — majority must be hyper-local (#EdmondsWA #PNWCoffee #CoffeeShop #EdmondsCoffee #PNWLife) — penalise if generic tags like #SmallBusiness dominate
- Tone: warm, slightly poetic — make someone want to be there right now""",

    "Facebook": """Format rules for this post:
- Length: 3-5 sentences, slightly more informational than other platforms
- Must name at least one specific menu item by name (drink, pastry, or special)
- Should include a specific time or day detail when relevant (e.g. "fresh until noon", "this Saturday morning")
- Must include a soft call-to-action (stop by, come find us, grab one before they're gone, etc.)
- No hashtags
- Tone: friendly and welcoming — appeals to families, retirees, and longtime Edmonds locals""",

    "TikTok": """Format rules for this post:
- Length: strictly 50-80 words — penalise posts over 80 words
- Must open with a high-energy hook — the very first line should be impossible to scroll past
- Must name at least one specific Hearth & Brew item by name
- Must end the caption with a comment/engagement CTA (e.g. "drop your order below 👇", "tag who you're bringing ☕")
- Trend-aware, conversational, Gen-Z adjacent tone
- 3-5 hashtags — prefer discovery tags (#FoodTok #CoffeeTok #EdmondsWA) over generic ones like #SmallBusiness
- Ends with a suggested video concept in parentheses — this is an intentional format element, not awkward copy; do not penalise it
- For Specificity on TikTok: reward a strong, curiosity-driving hook and trend-aware angle, not just Edmonds name-drops""",
}

SCORE_LABELS = {
    "voice":       "Voice",
    "platform":    "Platform Fit",
    "specificity": "Specificity",
    "nopatterns":  "No Anti-Patterns",
    "engagement":  "Engagement",
}


def build_score_prompt(platform: str, text: str) -> str:
    rules = SCORE_PLATFORM_RULES.get(platform, f"Platform: {platform}")
    specificity_note = (
        "Does it open with a compelling hook and feel trend-relevant? Does it reference something real "
        "(a menu item, the shop, a PNW moment) rather than staying purely generic?"
        if platform == "TikTok"
        else "Does it mention a real Hearth & Brew menu item, shop feature, or Edmonds/PNW detail? Generic = low score."
    )
    return f"""You are a brand quality reviewer for Hearth & Brew, a cozy independent coffee shop in Edmonds, WA.

{rules}

Score this {platform} post on each dimension from 1 to 5:

1. On-Brand Voice (1-5): Does it sound like a warm, witty local friend? Genuine and casual — not stiff or corporate?
2. Platform Fit (1-5): Does it follow the format rules above — correct length, structure, emoji use, hashtag count, tone, and any required elements (CTA, hook, etc.)?
3. Specificity (1-5): {specificity_note}
4. No Anti-Patterns (1-5): Zero corporate jargon? No "curated", "artisanal", "elevated", "crafted experience", "bespoke", or anything that sounds like ad-agency copy?
5. Engagement Pull (1-5): Would an Edmonds local genuinely stop scrolling — does it feel real, warm, and inviting?

Post:
"{text}"

Return ONLY valid JSON, no markdown fences:
{{"voice":{{"score":0,"max":5}},"platform":{{"score":0,"max":5}},"specificity":{{"score":0,"max":5}},"nopatterns":{{"score":0,"max":5}},"engagement":{{"score":0,"max":5}},"verdict":"Strong Post","improvement":"One specific actionable suggestion"}}"""


def generate_post(topic: str, platform: str) -> str:
    instruction = (
        f'Write a social media post for: "{topic}".\n\n'
        f"{PLATFORM_RULES[platform]}"
    )
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": instruction}],
    )
    return res.content[0].text.strip()


def score_post(platform: str, text: str) -> dict:
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": build_score_prompt(platform, text)}],
    )
    raw = res.content[0].text.strip()
    raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(raw)


# ── Run ───────────────────────────────────────────────────────────────────────
summary = []

for content_type in CONTENT_TYPES:
    print(f"\n{'='*68}")
    print(f"  {content_type.upper()}")
    print(f"{'='*68}")

    for platform in PLATFORMS:
        print(f"\n  [{platform}]")
        post = generate_post(content_type, platform)
        preview = post[:140] + ("..." if len(post) > 140 else "")
        print(f"  {preview}")

        scores = score_post(platform, post)
        total = sum(
            v["score"] for v in scores.values()
            if isinstance(v, dict) and "score" in v
        )

        row = "  "
        for key, label in SCORE_LABELS.items():
            s = scores.get(key, {}).get("score", 0)
            row += f"{label}: {s}/5  "
        print(row)
        print(f"  Total: {total}/25  |  {scores.get('verdict', '-')}")
        print(f"  Tip: {scores.get('improvement', '-')}")

        summary.append({
            "content_type": content_type,
            "platform": platform,
            "total": total,
            "verdict": scores.get("verdict", "-"),
        })

# ── Summary table ─────────────────────────────────────────────────────────────
print(f"\n\n{'='*68}")
print("  SUMMARY")
print(f"{'='*68}")

verdicts = {"Strong Post": 0, "Needs Minor Tweaks": 0, "Needs Rework": 0}
for row in summary:
    filled = row["total"] // 5
    bar = "█" * filled + "░" * (5 - filled)
    print(f"  {row['content_type']:<40} {row['platform']:<12} {row['total']:>2}/25  {bar}  {row['verdict']}")
    verdicts[row["verdict"]] = verdicts.get(row["verdict"], 0) + 1

overall = sum(r["total"] for r in summary) / len(summary)
print(f"\n  Average score : {overall:.1f}/25")
print(f"  Strong Posts  : {verdicts.get('Strong Post', 0)}/{len(summary)}")
print(f"  Minor Tweaks  : {verdicts.get('Needs Minor Tweaks', 0)}/{len(summary)}")
print(f"  Needs Rework  : {verdicts.get('Needs Rework', 0)}/{len(summary)}")
print()
