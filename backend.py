"""
Hearth & Brew — FastAPI Backend
================================
Handles all external API calls server-side so API keys never touch the browser.

Run:
    pip install fastapi uvicorn httpx python-dotenv pillow python-multipart
    uvicorn backend:app --reload --port 8000

All keys go in a .env file next to this file:
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_API_KEY=sk-...
    RUNWAY_API_KEY=...
    FB_PAGE_ACCESS_TOKEN=...
    FB_PAGE_ID=...
    IG_USER_ID=...
    TIKTOK_ACCESS_TOKEN=...
"""

import os, uuid, json, re, base64, sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── API keys (set in .env) ────────────────────────────────────────────────────
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY", "")
RUNWAY_KEY    = os.getenv("RUNWAY_API_KEY", "")
FB_TOKEN      = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
FB_PAGE_ID    = os.getenv("FB_PAGE_ID", "")
IG_USER_ID    = os.getenv("IG_USER_ID", "")
TIKTOK_TOKEN  = os.getenv("TIKTOK_ACCESS_TOKEN", "")

# ── Storage ───────────────────────────────────────────────────────────────────
MEDIA_DIR = Path("media_uploads")
MEDIA_DIR.mkdir(exist_ok=True)
DB_PATH = Path("hearth_brew.db")


# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                type          TEXT NOT NULL,
                mime_type     TEXT NOT NULL,
                file_path     TEXT NOT NULL,
                thumbnail_b64 TEXT,
                tags          TEXT NOT NULL DEFAULT '[]',
                used          INTEGER NOT NULL DEFAULT 0,
                uploaded_at   TEXT NOT NULL
            )
        """)
        conn.commit()

init_db()


# ── Prompts ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are the social media voice for Hearth & Brew, a cozy independent coffee shop
located on a side street off Main St in downtown Edmonds, Washington — near the
ferry terminal and the fountain.

About Hearth & Brew:
- House-roasted small-batch drip coffee and a full espresso bar
- Fresh-baked pastries every morning: croissants, scones, muffins, cinnamon rolls,
  sourdough loaves — baked in-house, available while they last
- A weekly "Baker's Choice" surprise — a rotating special that keeps regulars guessing
- Light lunch menu: quiches, grain bowls, seasonal soups
- Seasonal drink specials: lavender honey latte, maple oat latte, Puget Sound fog,
  cold brew and iced options
- Non-coffee drinks: hot chocolate, chai, matcha, full tea selection
- A board game lounge with classics like Catan, Scrabble, Ticket to Ride, card games,
  and puzzles for all ages
- A community book trade — bookshelves lining the walls where customers swap reads
- Cozy sit-down area: mismatched wooden tables, soft lighting, exposed brick

Brand personality:
- Community-rooted: knows regulars by name, supports Edmonds events
- Quality-focused: small-batch roasting, scratch baking, local suppliers
- Warm and welcoming: feels like your living room
- Unpretentious: not corporate, not snobby — just really good coffee and honest food
- A little quirky: chalkboard puns, surprise pastries, book swaps
- Encourages people to slow down and linger, not rush

Brand voice rules:
- Write like a warm, witty friend texting someone about their favorite spot
- Use "we" and "our" naturally
- Casual, genuine, occasionally funny — never stiff or formal
- Light PNW humor and local references are welcome
- Use specific menu items, shop features, or local Edmonds details whenever possible

NEVER use: corporate jargon, buzzwords like "curated", "artisanal", "crafted experience",
"elevated", "bespoke", or anything that sounds like a press release or ad agency copy.
NEVER sound try-hard, trendy, or like a national chain.

Target audience: Edmonds locals and regulars, families, retirees, work-from-home crowd,
ferry commuters, weekend visitors exploring downtown, board game and book lovers."""

PLATFORM_RULES = {
    "Instagram": """Platform: Instagram
- Output ONLY the post text — no preamble, no "Here's a caption", no labels, no markdown headers
- Write a warm, inviting caption — visual-first, describe or reference the scene
- Length: 2-3 sentences (use 4 only if each sentence is short and punchy)
- Name at least one specific Hearth & Brew item by name (e.g. "lavender honey latte", "Puget Sound Fog", "Baker's Choice brown butter bars") — never say "seasonal drink" or "fresh pastry" without naming it
- Use 1-2 emojis maximum, placed naturally (not at the start of every line)
- Hashtags: 4-6 tags — prioritise hyper-local tags: #EdmondsWA #PNWCoffee #CoffeeShop #EdmondsCoffee #PNWLife — avoid generic tags like #SmallBusiness unless all local slots are filled
- Tone: warm, slightly poetic, inviting — make someone want to be there right now
- On a new line after the hashtags append ONLY this JSON: {"hashtags":["#tag1",...],"sound":null}""",

    "Facebook": """Platform: Facebook
- Output ONLY the post text — no preamble, no "Here's a post", no labels, no markdown headers
- Write a warm, community-focused post
- Length: 3-5 sentences — slightly more informational than other platforms
- Name at least one specific menu item by name (drink, pastry, or weekly special)
- Include a specific time or day detail when relevant (e.g. "fresh until noon", "this Saturday morning", "until they're gone by 10am")
- Include a soft call-to-action (stop by, come find us, grab one before they're gone, etc.)
- No hashtags
- Tone: friendly and welcoming — appeals to families, retirees, and longtime Edmonds locals
- On a new line at the end append ONLY this JSON: {"hashtags":[],"sound":null}""",

    "TikTok": """Platform: TikTok
- Output ONLY the post text — no preamble, no "Here's a post", no labels, no markdown headers
- Strictly 50-80 words — count carefully, do not exceed 80 words
- High-energy hook as the opening line (make it impossible to scroll past)
- Name at least one specific Hearth & Brew item by name in the post
- Trend-aware, conversational, Gen-Z adjacent
- End the caption with a comment/engagement CTA (e.g. "drop your order below 👇", "tag who you're bringing ☕", "comment your go-to order")
- 3-5 hashtags — prefer discovery tags (#FoodTok #CoffeeTok #EdmondsWA) over generic ones like #SmallBusiness
- End with a brief suggested video concept in parentheses
- On a new line after the hashtags append ONLY this JSON: {"hashtags":["#FoodTok",...],"sound":"Suggest a specific trending TikTok audio/song — be specific with artist and track name"}""",
}

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

PLATFORM_IMAGE_STYLES = {
    "Instagram": "square 1:1, warm golden-hour photography, shallow depth of field, latte art visible, cozy café atmosphere",
    "Facebook":  "landscape 4:3, warm community feel, inviting and familiar, natural light",
    "TikTok":    "vertical 9:16, vibrant and trendy, Gen-Z aesthetic, bold colors and dynamic composition",
}

RUNWAY_VIDEO_PROMPT = (
    "Photorealistic footage inside Hearth & Brew café, exposed brick walls, mismatched wooden tables, "
    "warm Edison-bulb glow, gentle steam rising, natural PNW window light, cinematic slow motion, "
    "lived-in and welcoming, real café atmosphere"
)


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


# ── Media matching (mirrors JS logic) ─────────────────────────────────────────
def tokenize(text: str) -> list:
    if not text:
        return []
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).split()

def token_sim(a_tokens: list, b_tokens: list) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    hits = 0
    for a in a_tokens:
        for b in b_tokens:
            if (a == b or a.startswith(b) or b.startswith(a) or
                    (len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4])):
                hits += 1
                break
    return hits / len(a_tokens)

def find_matching_media(items: list, platform: str,
                        content_type: str = None,
                        description: str = None,
                        tone: str = None) -> list:
    media_type = "video" if platform == "TikTok" else "image"
    ct_norm    = content_type.lower() if content_type else None
    desc_toks  = tokenize(description)
    tone_toks  = tokenize(tone)

    scored = []
    for item in items:
        if item["type"] != media_type:
            continue
        score = 0.0
        for tag in (item.get("tags") or []):
            tag_norm = tag.lower()
            tag_toks = tokenize(tag)
            if ct_norm and tag_norm == ct_norm:
                score += 3                          # exact content-type match
            score += token_sim(tag_toks, desc_toks) * 2
            score += token_sim(tag_toks, tone_toks) * 1
        scored.append((score, item))

    scored = [(s, i) for s, i in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored and not ct_norm:
        return [i for i in items if i["type"] == media_type]
    return [i for _, i in scored]


# ── DB helpers ────────────────────────────────────────────────────────────────
def row_to_dict(row) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags", "[]"))
    d["used"] = bool(d.get("used", 0))
    return d


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Hearth & Brew API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media_uploads", StaticFiles(directory=str(MEDIA_DIR)), name="media_uploads")


# ── Request / Response models ─────────────────────────────────────────────────
class GenerateRequest(BaseModel):
    content_type: str
    platforms: list
    description: Optional[str] = None
    tone: Optional[str] = None

class ScoreRequest(BaseModel):
    platform: str
    text: str

class ImagePromptRequest(BaseModel):
    content_type: str
    platform: str
    description: Optional[str] = None

class GenerateImageRequest(BaseModel):
    prompt: str
    platform: str

class GenerateVideoRequest(BaseModel):
    image_url: str

class PublishRequest(BaseModel):
    platform: str
    text: str
    image_url: Optional[str] = None

class MediaUpdateRequest(BaseModel):
    tags: Optional[list] = None
    used: Optional[bool] = None

class FindMediaRequest(BaseModel):
    platform: str
    content_type: Optional[str] = None
    description: Optional[str] = None
    tone: Optional[str] = None


# ════════════════════════════════════════════════════════
#  GENERATE POSTS
# ════════════════════════════════════════════════════════
@app.post("/api/generate")
async def generate_posts(req: GenerateRequest):
    rules_block = "\n".join(
        f"{p}: {PLATFORM_RULES[p]}" for p in req.platforms if p in PLATFORM_RULES
    )
    extra_note = f"\nAdditional details: {req.description}" if req.description else ""
    tone_note  = f"\nTone: {req.tone}" if req.tone and req.tone != "Default brand voice" else ""

    prompt = (
        f'Write social media posts for: "{req.content_type}".{extra_note}{tone_note}\n\n'
        f"Rules per platform (each platform text must end with a JSON metadata block on the last line):\n"
        f"{rules_block}\n\n"
        f"Return ONLY valid JSON, no markdown fences:\n"
        f'{{{", ".join(f\'"{p}":"..."\' for p in req.platforms)}}}\n\n'
        f"IMPORTANT: The value for each platform must be the full post text including the JSON metadata block "
        f'appended at the very end (on its own line).'
    )

    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1800,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if not res.is_success:
        raise HTTPException(status_code=res.status_code, detail=res.text)

    raw = res.json()["content"][0]["text"].strip()
    raw = re.sub(r"^```json?\n?", "", raw)
    raw = re.sub(r"```$", "", raw)
    parsed = json.loads(raw)

    meta_re = re.compile(r'\{[^}]*"hashtags"[^}]*\}$', re.MULTILINE)
    result = {}
    for plat, full_text in parsed.items():
        m = meta_re.search(full_text)
        meta = {"hashtags": [], "sound": None}
        text = full_text
        if m:
            try:
                meta = json.loads(m.group())
            except Exception:
                pass
            text = full_text[: m.start()].strip()
        result[plat] = {
            "text": text,
            "hashtags": meta.get("hashtags") or [],
            "sound": meta.get("sound"),
        }
    return result


# ════════════════════════════════════════════════════════
#  SCORE A POST
# ════════════════════════════════════════════════════════
@app.post("/api/score")
async def score_post(req: ScoreRequest):
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": build_score_prompt(req.platform, req.text)}],
            },
        )
    if not res.is_success:
        return None
    raw = res.json()["content"][0]["text"].strip()
    raw = re.sub(r"^```json?\n?", "", raw).rstrip("```").strip()
    try:
        return json.loads(raw)
    except Exception:
        return None


# ════════════════════════════════════════════════════════
#  GENERATE IMAGE PROMPT (Claude → DALL-E prompt text)
# ════════════════════════════════════════════════════════
@app.post("/api/image-prompt")
async def generate_image_prompt(req: ImagePromptRequest):
    style = PLATFORM_IMAGE_STYLES.get(req.platform, "square 1:1, warm café photography")
    extra = f". Details: {req.description}" if req.description else ""

    prompt = f"""You are a visual creative director for Hearth & Brew, a cozy independent coffee shop in Edmonds, WA.

Generate a detailed, photorealistic image generation prompt (for DALL-E 3) for a social media post about: "{req.content_type}"{extra}.

Platform: {req.platform} — style guidance: {style}

The image MUST look like a real photograph taken inside or around Hearth & Brew:
- Interior: exposed brick walls, mismatched wooden tables, soft warm Edison-bulb lighting, bookshelves lining the walls, chalkboard menu in the background
- Pastries and coffee should look freshly made and inviting
- No illustrated or AI-looking art — photorealistic only
- Natural depth of field, slightly imperfect angles — real photography feel

Return ONLY the image prompt text (70-110 words). Start directly with the scene. No preamble, no quotes."""

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
    if not res.is_success:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    return {"prompt": res.json()["content"][0]["text"].strip()}


# ════════════════════════════════════════════════════════
#  GENERATE IMAGE (DALL-E 3)
# ════════════════════════════════════════════════════════
@app.post("/api/generate-image")
async def generate_image(req: GenerateImageRequest):
    if not OPENAI_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured in .env")

    size_map = {"Instagram": "1024x1024", "Facebook": "1792x1024", "TikTok": "1024x1792"}
    size = size_map.get(req.platform, "1024x1024")
    full_prompt = (
        f"{req.prompt}, photorealistic photograph, not illustrated, not rendered, "
        "real café interior with exposed brick and mismatched wooden tables, warm Edison-bulb lighting, "
        "shallow depth of field, shot on a mirrorless camera, high resolution"
    )

    async with httpx.AsyncClient(timeout=90) as client:
        res = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": full_prompt, "n": 1,
                  "size": size, "quality": "standard", "response_format": "b64_json"},
        )
    data = res.json()
    if not res.is_success:
        raise HTTPException(status_code=res.status_code,
                            detail=data.get("error", {}).get("message", res.text))
    return {"image_b64": data["data"][0]["b64_json"]}


# ════════════════════════════════════════════════════════
#  GENERATE TIKTOK VIDEO (RunwayML image-to-video)
# ════════════════════════════════════════════════════════
@app.post("/api/generate-video")
async def generate_video(req: GenerateVideoRequest):
    if not RUNWAY_KEY:
        raise HTTPException(status_code=400, detail="RUNWAY_API_KEY not configured in .env")

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers={
                "Authorization": f"Bearer {RUNWAY_KEY}",
                "Content-Type": "application/json",
                "X-Runway-Version": "2024-11-06",
            },
            json={
                "model": "gen3a_turbo",
                "promptImage": req.image_url,
                "promptText": RUNWAY_VIDEO_PROMPT,
                "ratio": "768:1280",
                "duration": 5,
            },
        )
    if not res.is_success:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    return {"task_id": res.json()["id"]}


@app.get("/api/video-status/{task_id}")
async def video_status(task_id: str):
    if not RUNWAY_KEY:
        raise HTTPException(status_code=400, detail="RUNWAY_API_KEY not configured in .env")

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
            headers={"Authorization": f"Bearer {RUNWAY_KEY}", "X-Runway-Version": "2024-11-06"},
        )
    if not res.is_success:
        raise HTTPException(status_code=res.status_code, detail=res.text)
    return res.json()


# ════════════════════════════════════════════════════════
#  PUBLISH
# ════════════════════════════════════════════════════════
@app.post("/api/publish/facebook")
async def publish_facebook(req: PublishRequest):
    if not FB_TOKEN or not FB_PAGE_ID:
        raise HTTPException(status_code=400,
                            detail="Facebook not configured. Set FB_PAGE_ACCESS_TOKEN and FB_PAGE_ID in .env")
    async with httpx.AsyncClient(timeout=30) as client:
        if req.image_url and not req.image_url.startswith("data:"):
            res = await client.post(
                f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
                data={"url": req.image_url, "caption": req.text,
                      "access_token": FB_TOKEN, "published": "true"},
            )
        else:
            res = await client.post(
                f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed",
                data={"message": req.text, "access_token": FB_TOKEN},
            )
    data = res.json()
    if "error" in data:
        raise HTTPException(status_code=400, detail=data["error"]["message"])
    return data


@app.post("/api/publish/instagram")
async def publish_instagram(req: PublishRequest):
    if not FB_TOKEN or not IG_USER_ID:
        raise HTTPException(status_code=400,
                            detail="Instagram not configured. Set FB_PAGE_ACCESS_TOKEN and IG_USER_ID in .env")
    if not req.image_url or req.image_url.startswith("data:"):
        raise HTTPException(status_code=400,
                            detail="Instagram requires a publicly hosted image URL.")
    async with httpx.AsyncClient(timeout=30) as client:
        create = await client.post(
            f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
            data={"image_url": req.image_url, "caption": req.text, "access_token": FB_TOKEN},
        )
        create_data = create.json()
        if "error" in create_data:
            raise HTTPException(status_code=400, detail=create_data["error"]["message"])

        pub = await client.post(
            f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
            data={"creation_id": create_data["id"], "access_token": FB_TOKEN},
        )
        pub_data = pub.json()
        if "error" in pub_data:
            raise HTTPException(status_code=400, detail=pub_data["error"]["message"])
    return pub_data


@app.post("/api/publish/tiktok")
async def publish_tiktok(req: PublishRequest):
    if not TIKTOK_TOKEN:
        raise HTTPException(status_code=400,
                            detail="TikTok not configured. Set TIKTOK_ACCESS_TOKEN in .env")
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://open.tiktokapis.com/v2/post/publish/content/init/",
            headers={
                "Authorization": f"Bearer {TIKTOK_TOKEN}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={
                "post_info": {
                    "title": req.text[:150],
                    "privacy_level": "SELF_ONLY",  # change to PUBLIC_TO_EVERYONE after app audit
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_images": [req.image_url],
                    "photo_cover_index": 0,
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            },
        )
    data = res.json()
    if data.get("error", {}).get("code") not in (None, "ok"):
        raise HTTPException(status_code=400,
                            detail=data["error"].get("message", "TikTok API error"))
    return data


# ════════════════════════════════════════════════════════
#  MEDIA LIBRARY
# ════════════════════════════════════════════════════════
@app.get("/api/media")
def list_media():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM media ORDER BY uploaded_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/api/media/upload")
async def upload_media(
    file: UploadFile = File(...),
    tags: str = Form("[]"),
):
    content = await file.read()
    media_type = "video" if (file.content_type or "").startswith("video/") else "image"
    item_id = "m_" + uuid.uuid4().hex
    ext = Path(file.filename).suffix or (".mp4" if media_type == "video" else ".jpg")
    file_path = MEDIA_DIR / f"{item_id}{ext}"
    file_path.write_bytes(content)

    # Thumbnail — JPEG for images, placeholder for video
    thumbnail_b64 = ""
    if media_type == "image":
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(content))
            img.thumbnail((160, 160))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            thumbnail_b64 = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            pass  # Pillow not installed — no thumbnail generated

    tags_list = json.loads(tags) if tags else []
    item = {
        "id": item_id,
        "name": file.filename,
        "type": media_type,
        "mime_type": file.content_type or "",
        "file_path": str(file_path),
        "thumbnail_b64": thumbnail_b64,
        "tags": json.dumps(tags_list),
        "used": 0,
        "uploaded_at": datetime.utcnow().isoformat(),
    }
    with get_db() as conn:
        conn.execute(
            "INSERT INTO media VALUES "
            "(:id,:name,:type,:mime_type,:file_path,:thumbnail_b64,:tags,:used,:uploaded_at)",
            item,
        )
        conn.commit()
    return {**item, "tags": tags_list, "used": False}


@app.get("/api/media/{item_id}/file")
def serve_media_file(item_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(row["file_path"], media_type=row["mime_type"])


@app.patch("/api/media/{item_id}")
def update_media(item_id: str, req: MediaUpdateRequest):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media item not found")
        updates = {}
        if req.tags is not None:
            updates["tags"] = json.dumps(req.tags)
        if req.used is not None:
            updates["used"] = int(req.used)
        if not updates:
            return row_to_dict(row)
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE media SET {set_clause} WHERE id=?", (*updates.values(), item_id))
        conn.commit()
        row = conn.execute("SELECT * FROM media WHERE id=?", (item_id,)).fetchone()
    return row_to_dict(row)


@app.delete("/api/media/{item_id}")
def delete_media(item_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Media item not found")
        Path(row["file_path"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM media WHERE id=?", (item_id,))
        conn.commit()
    return {"deleted": item_id}


@app.post("/api/media/match")
def match_media(req: FindMediaRequest):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM media").fetchall()
    items = [row_to_dict(r) for r in rows]
    return find_matching_media(items, req.platform, req.content_type, req.description, req.tone)


# ════════════════════════════════════════════════════════
#  CONFIG / STATUS
# ════════════════════════════════════════════════════════
@app.get("/api/content-types")
def get_content_types():
    return CONTENT_TYPES

@app.get("/api/config/status")
def config_status():
    return {
        "anthropic": bool(ANTHROPIC_KEY),
        "openai":    bool(OPENAI_KEY),
        "runway":    bool(RUNWAY_KEY),
        "facebook":  bool(FB_TOKEN and FB_PAGE_ID),
        "instagram": bool(FB_TOKEN and IG_USER_ID),
        "tiktok":    bool(TIKTOK_TOKEN),
    }
