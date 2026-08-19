"""Game knowledge for the verdict popup: rune/gem advice and item value tiers.

- Runes: cube-upgrade recipe + which runewords use this rune.
- Gems: upgrade path and what each grade is good for.
- Value tiers: curated S/A/B/C rating for well-known uniques/sets
  (repository/value_tiers.json).
"""
import json
import re

from advisor.links import item_url, recipe_url
from d2rlootreader.cfg import REPOSITORY_DIR

RUNE_ORDER = [
    "El", "Eld", "Tir", "Nef", "Eth", "Ith", "Tal", "Ral", "Ort", "Thul", "Amn",
    "Sol", "Shael", "Dol", "Hel", "Io", "Lum", "Ko", "Fal", "Lem", "Pul", "Um",
    "Mal", "Ist", "Gul", "Vex", "Ohm", "Lo", "Sur", "Ber", "Jah", "Cham", "Zod",
]
_RUNE_INDEX = {r: i for i, r in enumerate(RUNE_ORDER)}

# Cube upgrade: (count of this rune, extra gem) -> next rune.
# El..Ort need 3 runes and no gem; Thul..Lem need 3 runes + a gem;
# Pul..Cham need 2 runes + a gem.
_UP_GEMS = {
    "Thul": "chipped topaz", "Amn": "chipped amethyst", "Sol": "chipped sapphire",
    "Dol": "chipped ruby", "Hel": "chipped emerald", "Io": "chipped diamond",
    "Lum": "flawed topaz", "Ko": "flawed amethyst", "Fal": "flawed sapphire",
    "Lem": "flawed ruby", "Pul": "flawed emerald", "Um": "flawed diamond",
    "Mal": "topaz", "Ist": "amethyst", "Gul": "sapphire", "Vex": "ruby",
    "Ohm": "emerald", "Lo": "diamond", "Sur": "flawless topaz",
    "Ber": "flawless amethyst", "Jah": "flawless sapphire", "Cham": "flawless ruby",
}

_RUNE_LINE = re.compile(r"^([A-Za-z]+)\s+Rune$", re.I)

GEM_TYPES = ("Amethyst", "Diamond", "Emerald", "Ruby", "Sapphire", "Topaz", "Skull")
GEM_GRADES = ("Chipped", "Flawed", "", "Flawless", "Perfect")  # "" = plain

_runewords = None
_tiers = None


def _load_runewords():
    global _runewords
    if _runewords is None:
        try:
            with open(REPOSITORY_DIR / "runewords_full.json", encoding="utf-8") as f:
                _runewords = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _runewords = {}
    return _runewords


def _load_tiers():
    global _tiers
    if _tiers is None:
        try:
            with open(REPOSITORY_DIR / "value_tiers.json", encoding="utf-8") as f:
                _tiers = {k.lower(): v for k, v in json.load(f).items()}
        except (FileNotFoundError, json.JSONDecodeError):
            _tiers = {}
    return _tiers


def _find_rune(item):
    for line in (item or {}).get("tooltip") or []:
        m = _RUNE_LINE.match(line.strip())
        if m:
            rune = m.group(1).capitalize()
            if rune in _RUNE_INDEX:
                return rune
    return None


def rune_advice(item):
    """Popup lines for a rune item, or None."""
    rune = _find_rune(item)
    if rune is None:
        return None
    lines = []
    accent, dim = "#ffd94d", "#9a9a9a"

    i = _RUNE_INDEX[rune]
    if i + 1 < len(RUNE_ORDER):
        nxt = RUNE_ORDER[i + 1]
        count = 2 if rune in ("Pul", "Um", "Mal", "Ist", "Gul", "Vex", "Ohm",
                              "Lo", "Sur", "Ber", "Jah", "Cham") else 3
        gem = _UP_GEMS.get(rune)
        recipe = f"{count}× {rune}" + (f" + {gem}" if gem else "") + f" → {nxt}"
        lines.append((f"Cube up: {recipe}", "#e8e8e8", recipe_url("rune upgrade cube recipes")))

    used_in = sorted(name for name, rw in _load_runewords().items()
                     if rune in rw.get("runes", []))
    if used_in:
        shown = ", ".join(used_in[:8]) + ("…" if len(used_in) > 8 else "")
        lines.append((f"Used in: {shown}", dim, recipe_url(f"runewords with {rune} rune")))

    # season goals: show live progress (counts are managed ONLY in the
    # Season Goals window — a scan must not touch the counter)
    try:
        from advisor import goals
        for text, ready in goals.rune_popup_lines(rune):
            lines.append((text, "#4dff64" if ready else accent))
    except Exception:
        pass
    return lines or None


def gem_advice(item):
    """Popup lines for a gem item, or None."""
    first = ""
    for line in (item or {}).get("tooltip") or []:
        first = line.strip()
        break
    m = re.match(r"^(Chipped|Flawed|Flawless|Perfect)?\s*(Amethyst|Diamond|Emerald|Ruby|Sapphire|Topaz|Skull)$",
                 first, re.I)
    if not m:
        return None
    grade = (m.group(1) or "").capitalize()
    gem = m.group(2).capitalize()
    dim = "#9a9a9a"

    lines = []
    idx = GEM_GRADES.index(grade if grade else "")
    if idx + 1 < len(GEM_GRADES):
        nxt = GEM_GRADES[idx + 1] or "regular"
        lines.append((f"Cube up: 3× → {nxt.lower()} {gem.lower()}", "#e8e8e8",
                      recipe_url("gem upgrade cube recipe")))
    if grade == "Perfect":
        lines.append(("Perfect: reroll Grand Charms (3 p-gems + GC), crafting recipes", dim,
                      recipe_url("perfect gem uses crafting")))
    elif grade in ("Chipped", "Flawed"):
        lines.append(("Low gems: rune cube-up recipes, early sockets", dim))
    return lines or None


def get_value_tier(item):
    """(tier, note) for a recognized Unique/Set item, or None."""
    if (item or {}).get("quality") not in ("Unique", "Set"):
        return None
    name = (item.get("name") or "").lower()
    entry = _load_tiers().get(name)
    if not entry:
        return None
    return entry.get("tier"), entry.get("note", "")


# ---------------------------------------------------------------------------
# Cube: crafts, tier upgrades, set context

_cube = None
_ranges_raw = None

# Upgrade recipes: (kind, quality) -> runes+gem. kind: weapon/armor.
_UPGRADE_RECIPES = {
    ("weapon", "Unique", "Normal"): "Ral + Sol + P.Emerald",
    ("armor", "Unique", "Normal"): "Tal + Shael + P.Diamond",
    ("weapon", "Unique", "Exceptional"): "Lum + Pul + P.Emerald",
    ("armor", "Unique", "Exceptional"): "Ko + Lem + P.Diamond",
    ("weapon", "Rare", "Normal"): "Ort + Amn + P.Sapphire",
    ("armor", "Rare", "Normal"): "Ral + Thul + P.Amethyst",
    ("weapon", "Rare", "Exceptional"): "Fal + Um + P.Sapphire",
    ("armor", "Rare", "Exceptional"): "Ko + Pul + P.Amethyst",
}
_ARMOR_SLOTS = {"Body", "Helm", "Shield", "Boots", "Gloves", "Belt"}
_WEAPON_SLOTS = {"Sword", "Axe", "Polearm", "Spear", "Staff", "Wand", "Scepter", "Mace",
                 "Club", "Hammer", "Dagger", "Bow", "Crossbow", "Javelin", "Katar", "Orb",
                 "Grimoire", "Throwing"}


def _load_cube():
    global _cube
    if _cube is None:
        try:
            with open(REPOSITORY_DIR / "cube.json", encoding="utf-8") as f:
                _cube = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _cube = {"crafts": [], "tier_up": {}}
    return _cube


def _load_ranges_raw():
    global _ranges_raw
    if _ranges_raw is None:
        try:
            with open(REPOSITORY_DIR / "ranges.json", encoding="utf-8") as f:
                _ranges_raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _ranges_raw = {}
    return _ranges_raw


def craft_advice(item):
    """Craft recipe lines when hovering a magic item of a craftable base."""
    if (item or {}).get("quality") != "Magic":
        return None
    base = (item.get("base") or "").lower()
    if not base:
        return None
    lines = []
    for craft in _load_cube().get("crafts", []):
        if any(base == b.lower() for b in craft["bases"]):
            lines.append((f"Craftable → {craft['result']}: this + Jewel + "
                          f"{craft['rune']} + {craft['gem']}", "#ffa800",
                          recipe_url(f"{craft['result']} craft recipe")))
    return lines or None


def upgrade_advice(item):
    """Tier-upgrade recipe for Unique/Rare items on non-elite bases."""
    quality = (item or {}).get("quality")
    if quality not in ("Unique", "Rare"):
        return None
    base, tier, slot = item.get("base"), item.get("tier"), item.get("slot")
    if not base or tier not in ("Normal", "Exceptional"):
        return None
    nxt = _load_cube().get("tier_up", {}).get(base)
    if not nxt:
        return None
    kind = "armor" if slot in _ARMOR_SLOTS else "weapon" if slot in _WEAPON_SLOTS else None
    if kind is None:
        return None
    recipe = _UPGRADE_RECIPES.get((kind, quality, tier))
    if not recipe:
        return None
    return [(f"Upgrade base: {recipe} + this → {nxt} (keeps mods, higher def/dmg)",
             "#9ecfff", recipe_url(f"{quality.lower()} {kind} upgrade cube recipe"))]


# Quest items: name (lowercase) -> what to do with it. Matched against the
# item name, base and the first tooltip lines; verdict is forced to keep.
QUEST_ITEMS = {
    "wirt's leg": "Act 1 — cube with a Tome of Town Portal = Secret Cow Level portal",
    "horadric malus": "Act 1 quest — return to Charsi for an imbue (save it for a good base)",
    "scroll of inifuss": "Act 1 quest — bring to Akara",
    "staff of kings": "Act 2 — cube with the Amulet of the Viper → Horadric Staff",
    "amulet of the viper": "Act 2 — cube with the Staff of Kings → Horadric Staff",
    "horadric staff": "Act 2 — place in the orifice in Tal Rasha's Tomb. Don't sell!",
    "horadric cube": "Keep forever — it's the crafting engine",
    "book of skill": "Act 2 reward — right-click: +1 skill point",
    "khalim's eye": "Act 3 — cube Eye + Brain + Heart + Flail → Khalim's Will",
    "khalim's brain": "Act 3 — cube Eye + Brain + Heart + Flail → Khalim's Will",
    "khalim's heart": "Act 3 — cube Eye + Brain + Heart + Flail → Khalim's Will",
    "khalim's flail": "Act 3 — cube with Eye + Brain + Heart → Khalim's Will",
    "khalim's will": "Act 3 — smash the Compelling Orb in Travincal with it",
    "the gidbinn": "Act 3 — give to Ormus for a rare ring",
    "lam esen's tome": "Act 3 quest — reward: +5 stat points",
    "the golden bird": "Act 3 — trades up to a Potion of Life (+20 life)",
    "jade figurine": "Act 3 — trade chain ends in Potion of Life (+20 life)",
    "potion of life": "Drink it: permanent +20 life",
    "hellforge hammer": "Act 4 — smash Mephisto's Soulstone on the Hellforge (runes + gems)",
    "hell forge hammer": "Act 4 — smash Mephisto's Soulstone on the Hellforge (runes + gems)",
    "mephisto's soulstone": "Act 4 — smash it on the Hellforge with the hammer",
    "malah's potion": "Act 5 quest item — use per quest",
    "scroll of resistance": "Act 5 — read it: permanent +10 all resistances",
}


def quest_advice(item):
    """[(line, color)] for a quest item, or None. Verdict should become keep."""
    candidates = []
    for field in ("name", "base"):
        v = (item or {}).get(field)
        if v:
            candidates.append(v.lower())
    for line in ((item or {}).get("tooltip") or [])[:3]:
        candidates.append(line.strip().lower())
    for key, note in QUEST_ITEMS.items():
        if any(key in c for c in candidates):
            return [(f"Quest item — {note}", "#ffd700")]
    return None


# Endgame special items: essences, uber keys/organs, tokens, trophies.
SPECIAL_ITEMS = {
    "twisted essence of suffering": ("keep", "Cube all 4 essences → Token of Absolution (respec)"),
    "charged essence of hatred": ("keep", "Cube all 4 essences → Token of Absolution (respec)"),
    "burning essence of terror": ("keep", "Cube all 4 essences → Token of Absolution (respec)"),
    "festering essence of destruction": ("keep", "Cube all 4 essences → Token of Absolution (respec)"),
    "token of absolution": ("keep", "Right-click to respec stats & skills"),
    "key of terror": ("keep", "Uber key — cube Terror+Hate+Destruction → Pandemonium portal; sells well"),
    "key of hate": ("keep", "Uber key — cube Terror+Hate+Destruction → Pandemonium portal; sells well"),
    "key of destruction": ("keep", "Uber key — cube Terror+Hate+Destruction → Pandemonium portal; sells well"),
    "diablo's horn": ("keep", "Uber organ — cube Horn+Eye+Brain → Uber Tristram portal"),
    "baal's eye": ("keep", "Uber organ — cube Horn+Eye+Brain → Uber Tristram portal"),
    "mephisto's brain": ("keep", "Uber organ — cube Horn+Eye+Brain → Uber Tristram portal"),
    "standard of heroes": ("keep", "Uber Tristram trophy"),
}


def special_advice(item):
    """{verdict, note, name} for endgame special items and PvP ears, or None."""
    lines = (item or {}).get("tooltip") or []
    if not lines:
        return None
    first = lines[0].strip()
    low = first.lower()
    for key, (verdict, note) in SPECIAL_ITEMS.items():
        if key in low:
            return {"verdict": verdict, "note": note, "name": first}
    if low.endswith(" ear"):
        return {"verdict": "check", "note": "PvP trophy — someone's ear", "name": first}
    return None


# Consumables: name (lowercase) -> (verdict, note). Matched against the first
# tooltip line; short keys ("key") match only as the whole line.
CONSUMABLES = {
    "full rejuvenation potion": ("keep", "Instant full heal — always carry purples"),
    "rejuvenation potion": ("keep", "45% heal; 3 in the cube → full rejuv"),
    "super healing potion": ("check", "Top belt refill (vendors don't sell these)"),
    "super mana potion": ("check", "Top belt refill (vendors don't sell these)"),
    "greater healing potion": ("trash", "Belt filler at best — supers are better"),
    "greater mana potion": ("trash", "Belt filler at best — supers are better"),
    "healing potion": ("trash", "Vendor-refillable consumable"),
    "mana potion": ("trash", "Vendor-refillable consumable"),
    "antidote potion": ("trash", "Drink vs poison; costs 1 gold at any vendor"),
    "thawing potion": ("trash", "Drink vs cold; vendor-refillable"),
    "stamina potion": ("trash", "Get FRW instead"),
    "scroll of town portal": ("check", "Fill your TP tome"),
    "scroll of identify": ("check", "Fill the tome — or just use Cain"),
    "tome of town portal": ("keep", "Always carry one (also: cube with Wirt's Leg = cows)"),
    "tome of identify": ("keep", "Carry one, refill at vendors"),
    "key": ("check", "Opens locked chests; stacks to 12"),
    "arrows": ("trash", "Ammo — vendors sell it"),
    "bolts": ("trash", "Ammo — vendors sell it"),
    "fulminating potion": ("trash", "Throwing potion — vendor food"),
    "exploding potion": ("trash", "Throwing potion — vendor food"),
    "oil potion": ("trash", "Throwing potion — vendor food"),
    "gas potion": ("trash", "Throwing potion — vendor food"),
}


def consumable_advice(item):
    """{verdict, note, name} for potions/scrolls/tomes/keys/ammo, or None."""
    lines = (item or {}).get("tooltip") or []
    if not lines:
        return None
    first = lines[0].strip().lower()
    for key, (verdict, note) in CONSUMABLES.items():
        if first == key or (len(key) > 6 and key in first):
            return {"verdict": verdict, "note": note, "name": lines[0].strip()}
    return None


_GAMBLE_BY_SLOT = {
    "Amulet": ("Good gamble — can hit +2 class skills", "#4dff64"),
    "Ring": ("Decent gamble — FCR/dual-leech rolls possible", "#9ecfff"),
    "Gloves": ("Weak gamble — better crafted than gambled", "#9a9a9a"),
    "Boots": ("Weak gamble — better found than gambled", "#9a9a9a"),
    "Belt": ("Weak gamble — better crafted than gambled", "#9a9a9a"),
}
_GAMBLE_CIRCLETS = ("circlet", "coronet", "tiara", "diadem")


_gamble_db = None
_CLASS_RE = re.compile(r"Amazon|Assassin|Barbarian|Druid|Necromancer|Paladin|Sorceress")
DBM_URL = "https://gambling.diablo.deadlybossmods.com/"


def _load_gamble():
    global _gamble_db
    if _gamble_db is None:
        try:
            with open(REPOSITORY_DIR / "gamble.json", encoding="utf-8") as f:
                _gamble_db = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _gamble_db = {}
    return _gamble_db


# Gamble-screen slots worth buying (jewelry + circlets; the rest is gold drain).
GAMBLE_BUY = {"Amulet", "Ring", "Circlet", "Coronet", "Jewel"}


def match_gamble_offer(lines):
    """Map OCR lines of the gamble screen to base names, preserving order."""
    from rapidfuzz import fuzz, process
    names = list(_load_gamble().keys())
    if not names:
        return []
    offer = []
    for ln in lines or []:
        m = process.extractOne(ln, names, scorer=fuzz.ratio,
                               processor=str.lower, score_cutoff=82)
        if m:
            offer.append(m[0])
    return offer


def gamble_offer_summary(offer):
    """Popup lines for a scanned gamble offer list."""
    marks = [("★ " + n if n in GAMBLE_BUY else n) for n in offer]
    return [
        (f"Gamble offer ({len(offer)}): " + " · ".join(marks), "#e8e8e8"),
        ("★ = worth the gold (jewelry / circlets); the rest drains it", "#9a9a9a"),
        ("Press Shift+F10 — the Seed Finder opens pre-filled with this offer", "#ffd94d"),
        ("Built-in seed finder = the DBM simulator, running locally", "#9ecfff", DBM_URL),
    ]


def gamble_advice(item, char_level=0):
    """Gamble-target lines for a gamble-screen base: reachable uniques and
    chase affixes with the character level they need (ilvl = clvl-5..clvl+4,
    circlets add their hidden magic level for affixes)."""
    base = ((item or {}).get("base") or (item or {}).get("name") or "").strip()
    db = _load_gamble()
    entry = db.get(base)
    if entry is None:
        low = base.lower()
        entry = next((v for k, v in db.items() if k.lower() == low), None)

    if entry is None:
        link = recipe_url("gambling guide")
        b = base.lower()
        if any(c in b for c in _GAMBLE_CIRCLETS):
            return [("Best gamble in the game — +2 skills / 20 FCR circlet rolls", "#ffd94d", link)]
        slot_line = _GAMBLE_BY_SLOT.get((item or {}).get("slot") or "")
        if slot_line:
            return [(slot_line[0], slot_line[1], link)]
        return [("Weapons/armor are poor gambles — save gold for circlets/amulets", "#9a9a9a", link)]

    maglvl = entry.get("maglvl", 0)

    def clvl_for(alvl, magic=False):
        return max(1, alvl - 4 - (maglvl if magic else 0))

    def mark(clvl):
        if not char_level:
            return f"clvl {clvl}+"
        return f"clvl {clvl}+ ✓" if char_level >= clvl else f"clvl {clvl}+ (you: {char_level})"

    lines = [("Gamble odds — rare 1:10, set 1:1000, unique 1:2000; base can tier-upgrade",
              "#9a9a9a", DBM_URL)]
    if entry.get("uniques"):
        parts = [f"{u['name']} ({mark(clvl_for(u['alvl']))})" for u in entry["uniques"][:4]]
        lines.append(("Uniques here: " + " · ".join(parts), "#c7b377", DBM_URL))
    if entry.get("affixes"):
        seen, parts = set(), []
        for a in entry["affixes"]:
            norm = _CLASS_RE.sub("class", a["label"])
            norm = re.sub(r"^[\d-]+% ", "", norm)
            if norm in seen:
                continue
            seen.add(norm)
            parts.append(f"{a['label']} ({mark(clvl_for(a['alvl'], magic=True))})")
            if len(parts) == 3:
                break
        if parts:
            lines.append(("Chase mods: " + " · ".join(parts), "#ffd94d", DBM_URL))
    if maglvl:
        lines.append((f"{base}: hidden +{maglvl} magic level — affixes unlock earlier", "#9a9a9a"))
    lines.append(("Seed simulator (plan exact buys): gambling.diablo.deadlybossmods.com",
                  "#9ecfff", DBM_URL))
    return lines


def set_advice(item):
    """Other pieces of the set for a recognized Set item."""
    if (item or {}).get("quality") != "Set" or not item.get("name"):
        return None
    entry = _load_ranges_raw().get("set", {}).get(item["name"])
    if not entry:
        low = item["name"].lower()
        entry = next((v for k, v in _load_ranges_raw().get("set", {}).items()
                      if k.lower() == low), None)
    if not entry:
        return None
    lines = []
    if entry.get("set"):
        pieces = ", ".join(entry.get("pieces", [])) or "—"
        lines.append((f"{entry['set']} — other pieces: {pieces}", "#9a9a9a",
                      item_url(f"{entry['set']} set")))
    return lines or None
