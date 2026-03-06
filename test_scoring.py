import anthropic
import json
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from prompts import SYSTEM_PROMPT, PLATFORM_TEMPLATES

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if not API_KEY:
    print("Usage: ANTHROPIC_API_KEY=sk-ant-... python3 test_scoring.py")
    sys.exit(1)

client = anthropic.Anthropic(api_key=API_KEY)

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

PLATFORMS = ["instagram", "twitter", "facebook"]

SCORE_PROMPT = lambda platform, text: f"""You are a brand quality reviewer for Hearth & Brew, a cozy independent coffee shop in Edmonds, WA.

Score this {platform} post on each dimension from 1 to 5:

1. On-Brand Voice (1–5): Does it sound like a warm, witty local friend? Genuine and casual — not stiff or corporate?
2. Platform Fit (1–5): Is the length, format, tone, and hashtag use right for {platform}?
3. Specificity (1–5): Does it mention a real menu item, shop feature, or Edmonds/PNW detail? Generic = low score.
4. No Anti-Patterns (1–5): Zero corporate jargon? No "curated", "artisanal", "elevated", "crafted experience", "bespoke"?
5. Engagement Pull (1–5): Would an Edmonds local genuinely stop scrolling — does it feel real and inviting?

Post: "{text}"

Return ONLY valid JSON, no markdown fences:
{{"voice":{{"score":0,"max":5}},"platform":{{"score":0,"max":5}},"specificity":{{"score":0,"max":5}},"nopatterns":{{"score":0,"max":5}},"engagement":{{"score":0,"max":5}},"verdict":"Strong Post","improvement":"One specific actionable suggestion"}}"""

LABELS = {
    "voice":       "Voice",
    "platform":    "Platform Fit",
    "specificity": "Specificity",
    "nopatterns":  "No Anti-Patterns",
    "engagement":  "Engagement",
}

def generate_post(topic, platform):
    instruction = PLATFORM_TEMPLATES[platform].format(topic=topic)
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": instruction}],
    )
    return res.content[0].text.strip()

def score_post(platform, text):
    res = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": SCORE_PROMPT(platform, text)}],
    )
    raw = res.content[0].text.strip().lstrip("```json").rstrip("```")
    return json.loads(raw)

summary = []

for content_type in CONTENT_TYPES:
    print(f"\n{'='*64}")
    print(f"  {content_type.upper()}")
    print(f"{'='*64}")

    for platform in PLATFORMS:
        print(f"\n  [{platform.capitalize()}]")
        post = generate_post(content_type, platform)
        print(f"  {post[:120]}{'...' if len(post) > 120 else ''}")

        scores = score_post(platform, post)
        total = sum(v["score"] for v in scores.values() if isinstance(v, dict) and "score" in v)

        row = "  "
        for key, label in LABELS.items():
            s = scores.get(key, {}).get("score", 0)
            row += f"{label}: {s}/5  "
        print(row)
        print(f"  Total: {total}/25  |  {scores.get('verdict','—')}")
        print(f"  Tip: {scores.get('improvement','—')}")

        summary.append({
            "content_type": content_type,
            "platform": platform,
            "total": total,
            "verdict": scores.get("verdict", "—"),
        })

print(f"\n\n{'='*64}")
print("  SUMMARY")
print(f"{'='*64}")
for row in summary:
    bar = "█" * (row["total"] // 5) + "░" * (5 - row["total"] // 5)
    print(f"  {row['content_type']:<38} {row['platform']:<10} {row['total']:>2}/25  {bar}  {row['verdict']}")

overall = sum(r["total"] for r in summary) / len(summary)
print(f"\n  Average score: {overall:.1f}/25")
print()
