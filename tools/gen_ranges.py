"""Generate repository/ranges.json — stat roll ranges for uniques & set items.

Source: game data JSON dumps from https://github.com/blizzhackers/d2data
(uniqueitems.json, setitems.json, skills.json). Files are downloaded into
tools/_cache on first run; delete that folder to force a re-download.

Usage:  python tools/gen_ranges.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(__file__).resolve().parent / "_cache"
REPO = ROOT / "d2rlootreader" / "repository"
OUT = REPO / "ranges.json"

D2DATA_RAW = "https://raw.githubusercontent.com/blizzhackers/d2data/master/json/"
SOURCES = ["uniqueitems.json", "setitems.json", "skills.json"]

# ---------------------------------------------------------------------------

SKILL_TABS = {
    0: ("Bow and Crossbow Skills (Amazon only)", "+# to Bow and Crossbow Skills (Amazon only)"),
    1: ("Passive and Magic Skills (Amazon only)", "+# to Passive and Magic Skills (Amazon only)"),
    2: ("Javelin and Spear Skills (Amazon only)", "+# to Javelin and Spear Skills (Amazon only)"),
    3: ("Fire Skills (Sorceress only)", "+# to Fire Skills (Sorceress only)"),
    4: ("Lightning Skills (Sorceress only)", "+# to Lightning Skills (Sorceress only)"),
    5: ("Cold Skills (Sorceress only)", "+# to Cold Skills (Sorceress only)"),
    6: ("Curses (Necromancer only)", "+# to Curses (Necromancer only)"),
    7: ("Poison and Bone Skills (Necromancer only)", "+# to Poison and Bone Skills (Necromancer only)"),
    8: ("Summoning Skills (Necromancer only)", "+# to Summoning Skills (Necromancer only)"),
    9: ("Combat Skills (Paladin only)", "+# to Combat Skills (Paladin only)"),
    10: ("Offensive Auras (Paladin only)", "+# to Offensive Auras (Paladin only)"),
    11: ("Defensive Auras (Paladin only)", "+# to Defensive Auras (Paladin only)"),
    12: ("Combat Skills (Barbarian only)", "+# to Combat Skills (Barbarian only)"),
    13: ("Combat Masteries (Barbarian only)", "+# to Combat Masteries (Barbarian only)"),
    14: ("Warcries (Barbarian only)", "+# to Warcries (Barbarian only)"),
    15: ("Summoning Skills (Druid only)", "+# to Summoning Skills (Druid only)"),
    16: ("Shapeshifting Skills (Druid only)", "+# to Shapeshifting Skills (Druid only)"),
    17: ("Elemental Skills (Druid only)", "+# to Elemental Skills (Druid only)"),
    18: ("Traps (Assassin only)", "+# to Traps (Assassin only)"),
    19: ("Martial Arts (Assassin only)", "+# to Martial Arts (Assassin only)"),
    20: ("Shadow Disciplines (Assassin only)", "+# to Shadow Disciplines (Assassin only)"),
}

# code -> ("label with {r} placeholder", "affix template for roll matching" | None)
SIMPLE = {
    "dmg%": ("+{r}% Enhanced Damage", "+#% Enhanced Damage"),
    "ac%": ("+{r}% Enhanced Defense", "+#% Enhanced Defense"),
    "ac": ("+{r} Defense", "+# Defense"),
    "ac-miss": ("+{r} Defense vs. Missile", "+# Defense vs. Missile"),
    "ac-hth": ("+{r} Defense vs. Melee", "+# Defense vs. Melee"),
    "reduce-ac": ("-{r}% Target Defense", "-#% Target Defense"),
    "dmg-ac": ("-{r} to Monster Defense Per Hit", "-# to Monster Defense Per Hit"),
    "str": ("+{r} to Strength", "+# to Strength"),
    "dex": ("+{r} to Dexterity", "+# to Dexterity"),
    "vit": ("+{r} to Vitality", "+# to Vitality"),
    "enr": ("+{r} to Energy", "+# to Energy"),
    "all-stats": ("+{r} to all Attributes", "+# to all Attributes"),
    "hp": ("+{r} to Life", "+# to Life"),
    "hp%": ("Increase Maximum Life {r}%", "Increase Maximum Life #%"),
    "mana": ("+{r} to Mana", "+# to Mana"),
    "mana%": ("Increase Maximum Mana {r}%", "Increase Maximum Mana #%"),
    "regen": ("Replenish Life +{r}", "Replenish Life +#"),
    "regen-mana": ("Regenerate Mana {r}%", "Regenerate Mana #%"),
    "regen-stam": ("Heal Stamina Plus {r}%", "Heal Stamina Plus #%"),
    "stam": ("+{r} Maximum Stamina", "+# Maximum Stamina"),
    "stamdrain": ("{r}% Slower Stamina Drain", "#% Slower Stamina Drain"),
    "att": ("+{r} to Attack Rating", "+# to Attack Rating"),
    "att%": ("{r}% Bonus to Attack Rating", "#% Bonus to Attack Rating"),
    "att-undead": ("+{r} to Attack Rating against Undead", "+# to Attack Rating against Undead"),
    "att-demon": ("+{r} to Attack Rating against Demons", "+# to Attack Rating against Demons"),
    "dmg-undead": ("+{r}% Damage to Undead", "+#% Damage to Undead"),
    "dmg-demon": ("+{r}% Damage to Demons", "+#% Damage to Demons"),
    "swing1": ("+{r}% Increased Attack Speed", "+#% Increased Attack Speed"),
    "swing2": ("+{r}% Increased Attack Speed", "+#% Increased Attack Speed"),
    "swing3": ("+{r}% Increased Attack Speed", "+#% Increased Attack Speed"),
    "cast1": ("+{r}% Faster Cast Rate", "+#% Faster Cast Rate"),
    "cast2": ("+{r}% Faster Cast Rate", "+#% Faster Cast Rate"),
    "cast3": ("+{r}% Faster Cast Rate", "+#% Faster Cast Rate"),
    "balance1": ("+{r}% Faster Hit Recovery", "+#% Faster Hit Recovery"),
    "balance2": ("+{r}% Faster Hit Recovery", "+#% Faster Hit Recovery"),
    "balance3": ("+{r}% Faster Hit Recovery", "+#% Faster Hit Recovery"),
    "move1": ("+{r}% Faster Run/Walk", "+#% Faster Run/Walk"),
    "move2": ("+{r}% Faster Run/Walk", "+#% Faster Run/Walk"),
    "move3": ("+{r}% Faster Run/Walk", "+#% Faster Run/Walk"),
    "block": ("{r}% Increased Chance of Blocking", "#% Increased Chance of Blocking"),
    "block1": ("+{r}% Faster Block Rate", "+#% Faster Block Rate"),
    "block2": ("+{r}% Faster Block Rate", "+#% Faster Block Rate"),
    "block3": ("+{r}% Faster Block Rate", "+#% Faster Block Rate"),
    "lifesteal": ("{r}% Life stolen per hit", "#% Life stolen per hit"),
    "manasteal": ("{r}% Mana stolen per hit", "#% Mana stolen per hit"),
    "mag%": ("{r}% Better Chance of Getting Magic Items", "#% Better Chance of Getting Magic Items"),
    "gold%": ("{r}% Extra Gold from Monsters", "#% Extra Gold from Monsters"),
    "res-all": ("All Resistances +{r}", "All Resistances +#"),
    "res-fire": ("Fire Resist +{r}%", "Fire Resist +#%"),
    "res-cold": ("Cold Resist +{r}%", "Cold Resist +#%"),
    "res-ltng": ("Lightning Resist +{r}%", "Lightning Resist +#%"),
    "res-pois": ("Poison Resist +{r}%", "Poison Resist +#%"),
    "res-mag": ("Magic Resist +{r}%", "Magic Resist +#%"),
    "res-fire-max": ("+{r}% to Maximum Fire Resist", "+#% to Maximum Fire Resist"),
    "res-cold-max": ("+{r}% to Maximum Cold Resist", "+#% to Maximum Cold Resist"),
    "res-ltng-max": ("+{r}% to Maximum Lightning Resist", "+#% to Maximum Lightning Resist"),
    "res-pois-max": ("+{r}% to Maximum Poison Resist", "+#% to Maximum Poison Resist"),
    "res-all-max": ("+{r}% to All Maximum Resistances", None),
    "res-pois-len": ("Poison Length Reduced by {r}%", "Poison Length Reduced by #%"),
    "red-dmg": ("Damage Reduced by {r}", "Damage Reduced by #"),
    "red-dmg%": ("Damage Reduced by {r}%", "Damage Reduced by #%"),
    "red-mag": ("Magic Damage Reduced by {r}", "Magic Damage Reduced by #"),
    "abs-fire": ("+{r} Fire Absorb", "+# Fire Absorb"),
    "abs-cold": ("+{r} Cold Absorb", "+# Cold Absorb"),
    "abs-ltng": ("+{r} Lightning Absorb", "+# Lightning Absorb"),
    "abs-mag": ("+{r} Magic Absorb", "+# Magic Absorb"),
    "abs-fire%": ("Fire Absorb {r}%", "Fire Absorb #%"),
    "abs-cold%": ("Cold Absorb {r}%", "Cold Absorb #%"),
    "abs-ltng%": ("Lightning Absorb {r}%", "Lightning Absorb #%"),
    "abs-mag%": ("Magic Absorb {r}%", "Magic Absorb #%"),
    "thorns": ("Attacker Takes Damage of {r}", "Attacker Takes Damage of #"),
    "light-thorns": ("Attacker Takes Lightning Damage of {r}", "Attacker Takes Lightning Damage of #"),
    "light": ("+{r} to Light Radius", "+# to Light Radius"),
    "ease": ("Requirements -{r}%", "Requirements -#%"),
    "dur": ("Increase Maximum Durability {r}%", "Increase Maximum Durability #%"),
    "crush": ("{r}% Chance of Crushing Blow", "+#% Chance of Crushing Blow"),
    "deadly": ("{r}% Deadly Strike", "+#% Deadly Strike"),
    "openwounds": ("{r}% Chance of Open Wounds", "#% Chance of Open Wounds"),
    "slow": ("Slows Target by {r}%", "Slows Target by #%"),
    "freeze": ("Freezes Target +{r}", "Freezes Target +#"),
    "howl": ("Hit Causes Monster to Flee {r}%", "Hit Causes Monster to Flee #%"),
    "stupidity": ("Hit Blinds Target +{r}", "Hit Blinds Target +#"),
    "demon-heal": ("+{r} Life after each Demon Kill", "+# Life after each Demon Kill"),
    "heal-kill": ("+{r} Life after each Kill", "+# Life after each Kill"),
    "mana-kill": ("+{r} to Mana after each Kill", "+# to Mana after each Kill"),
    "dmg-to-mana": ("{r}% Damage Taken Goes To Mana", "+#% Damage Taken Goes To Mana"),
    "addxp": ("+{r}% to Experience Gained", "+#% to Experience Gained"),
    "cheap": ("Reduces all Vendor Prices {r}%", "Reduces all Vendor Prices #%"),
    "dmg": ("Damage +{r}", "Damage +#"),
    "dmg-min": ("+{r} to Minimum Damage", "+# to Minimum Damage"),
    "dmg-max": ("+{r} to Maximum Damage", "+# to Maximum Damage"),
    "fire-min": ("+{r} to Minimum Fire Damage", "+# to Minimum Fire Damage"),
    "fire-max": ("+{r} to Maximum Fire Damage", "+# to Maximum Fire Damage"),
    "ltng-min": ("+{r} to Minimum Lightning Damage", "+# to Minimum Lightning Damage"),
    "ltng-max": ("+{r} to Maximum Lightning Damage", "+# to Maximum Lightning Damage"),
    "cold-min": ("+{r} to Minimum Cold Damage", "+# to Minimum Cold Damage"),
    "cold-max": ("+{r} to Maximum Cold Damage", "+# to Maximum Cold Damage"),
    "pois-min": ("+{r} to Minimum Poison Damage", "+# to Minimum Poison Damage"),
    "pois-max": ("+{r} to Maximum Poison Damage", "+# to Maximum Poison Damage"),
    "extra-fire": ("+{r}% to Fire Skill Damage", "+#% to Fire Skill Damage"),
    "extra-cold": ("+{r}% to Cold Skill Damage", "+#% to Cold Skill Damage"),
    "extra-ltng": ("+{r}% to Lightning Skill Damage", "+#% to Lightning Skill Damage"),
    "extra-pois": ("+{r}% to Poison Skill Damage", "+#% to Poison Skill Damage"),
    "extra-mag": ("+{r}% to Magic Skill Damage", None),
    "pierce-fire": ("-{r}% to Enemy Fire Resistance", "-#% to Enemy Fire Resistance"),
    "pierce-cold": ("-{r}% to Enemy Cold Resistance", "-#% to Enemy Cold Resistance"),
    "pierce-ltng": ("-{r}% to Enemy Lightning Resistance", "-#% to Enemy Lightning Resistance"),
    "pierce-pois": ("-{r}% to Enemy Poison Resistance", "-#% to Enemy Poison Resistance"),
    "pierce-mag": ("-{r}% to Enemy Magic Resistance", None),
    "pierce": ("Piercing Attack ({r}%)", None),
    "fireskill": ("+{r} to Fire Skills", "+# to Fire Skills"),
    "allskills": ("+{r} to All Skills", "+# to All Skills"),
    "ama": ("+{r} to Amazon Skill Levels", "+# to Amazon Skill Levels"),
    "sor": ("+{r} to Sorceress Skill Levels", "+# to Sorceress Skill Levels"),
    "nec": ("+{r} to Necromancer Skill Levels", "+# to Necromancer Skill Levels"),
    "pal": ("+{r} to Paladin Skill Levels", "+# to Paladin Skill Levels"),
    "bar": ("+{r} to Barbarian Skill Levels", "+#  to Barbarian Skill Levels"),
    "dru": ("+{r} to Druid Skill Levels", "+# to Druid Skill Levels"),
    "ass": ("+{r} to Assassin Skill Levels", "+# to Assassin Skill Levels"),
    "war": ("+{r} to Warcries (Barbarian only)", "+# to Warcries (Barbarian only)"),
    "skilltab-war": ("+{r} to Warcries (Barbarian only)", "+# to Warcries (Barbarian only)"),
    "reanimate": ("Reanimate As: Returned ({r}%)", None),
    "charge-noconsume": ("+{r}% Chance to not Consume Charges", None),
}

FLAGS = {
    "indestruct": "Indestructible",
    "ethereal": "Ethereal (Cannot Be Repaired)",
    "knock": "Knockback",
    "ignore-ac": "Ignore Target's Defense",
    "nofreeze": "Cannot Be Frozen",
    "half-freeze": "Half Freeze Duration",
    "noheal": "Prevent Monster Heal",
    "magicarrow": "Fires Magic Arrows",
    "explosivearrow": "Fires Explosive Arrows or Bolts",
    "rep-quant": "Replenishes quantity",
    "stack": "Increased Stack Size",
    "rip": "Slain Monsters Rest in Peace",
    "pierce-immunity-fire": "Monster Fire Immunity is Sundered",
    "pierce-immunity-cold": "Monster Cold Immunity is Sundered",
    "pierce-immunity-light": "Monster Lightning Immunity is Sundered",
    "pierce-immunity-poison": "Monster Poison Immunity is Sundered",
    "pierce-immunity-damage": "Monster Physical Immunity is Sundered",
    "pierce-immunity-magic": "Monster Magic Immunity is Sundered",
}

PER_LEVEL = {  # value shown is par/8 per character level
    "hp/lvl": "Life", "mana/lvl": "Mana", "ac/lvl": "Defense", "dmg/lvl": "Maximum Damage",
    "att/lvl": "Attack Rating", "att%/lvl": "Bonus to Attack Rating %", "str/lvl": "Strength",
    "dex/lvl": "Dexterity", "vit/lvl": "Vitality", "stam/lvl": "Maximum Stamina",
    "thorns/lvl": "Attacker Takes Damage", "abs-cold/lvl": "Cold Absorb", "abs-fire/lvl": "Fire Absorb",
    "mag%/lvl": "Magic Find %", "gold%/lvl": "Extra Gold %", "deadly/lvl": "Deadly Strike %",
    "att-und/lvl": "Attack Rating against Undead", "dmg-und/lvl": "Damage to Undead %",
    "att-dem/lvl": "Attack Rating against Demons", "dmg-dem/lvl": "Damage to Demons %",
    "dmg%/lvl": "Enhanced Damage %", "res-ltng/lvl": "Lightning Resist %",
    "regen-stam/lvl": "Heal Stamina %",
}

SKIP = {"bloody", "*hp", "*enr", "*charged", "cold-len", "pois-len", "dmg-elem", "magdam-rand", "pierce-dmg"}

# ---------------------------------------------------------------------------


def fetch(name):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / name
    if not path.exists():
        print(f"downloading {name} ...")
        urllib.request.urlretrieve(D2DATA_RAW + name, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# repository name -> d2data internal index
ALIASES = {"bartuc's cut-throat": "cutthroat1"}


def rng(lo, hi):
    lo, hi = int(lo or 0), int(hi or 0)
    if lo == hi:
        return str(lo), False
    if lo < 0 or hi < 0:
        return f"({lo} to {hi})", True
    return f"{lo}-{hi}", True


def build_skill_lookup(skills):
    by_id = {}
    for it in skills.values():
        sid, name = it.get("*Id"), it.get("skill")
        if sid is not None and name:
            by_id[int(sid)] = name
    return by_id


def skill_name(par, skills_by_id):
    if par is None or par == "":
        return "?"
    try:
        return skills_by_id.get(int(par), f"Skill {par}")
    except (ValueError, TypeError):
        return str(par)


def convert_prop(code, par, lo, hi, skills_by_id, unmapped):
    """Return a prop dict {label, tmpl, min, max, var} or None to skip."""
    lo = int(lo) if lo not in (None, "") else 0
    hi = int(hi) if hi not in (None, "") else 0
    orig = code
    code = code.lower() if code.endswith("skill") and code[0].isupper() else code

    if code in SKIP or code.endswith(("-Affix1", "-Affix2", "-Affix3", "-Affix4", "-Affix5", "-Affix6")):
        return None
    if code in FLAGS:
        return {"label": FLAGS[code], "tmpl": None, "min": lo, "max": hi, "var": False}
    if code in SIMPLE:
        label_t, tmpl = SIMPLE[code]
        r, var = rng(lo, hi)
        label = label_t.format(r=r).replace("+-", "-").replace("+(", "(")
        return {"label": label, "tmpl": tmpl, "min": lo, "max": hi, "var": var}
    if code in PER_LEVEL:
        per = (int(par) if par not in (None, "") else 0) / 8.0
        return {"label": f"+{per:g} {PER_LEVEL[code]} per Character Level", "tmpl": None,
                "min": 0, "max": 0, "var": False}

    # For these, min/max hold a skill-ID pool — the level lives in par.
    if code == "skill-rand":
        lvl = int(par) if par not in (None, "") else 0
        return {"label": f"+{lvl} to a Random Skill", "tmpl": None, "min": lvl, "max": lvl, "var": False}
    if code == "randclassskill":
        lvl = int(par) if par not in (None, "") else 3
        return {"label": f"+{lvl} to a Random Class's Skill Levels", "tmpl": None,
                "min": lvl, "max": lvl, "var": False}

    if code in ("skill", "oskill"):
        r, var = rng(lo, hi)
        return {"label": f"+{r} to {skill_name(par, skills_by_id)}", "tmpl": None,
                "min": lo, "max": hi, "var": var}
    if code == "skilltab":
        try:
            tab, tmpl = SKILL_TABS[int(par)]
        except (KeyError, ValueError, TypeError):
            tab, tmpl = f"Skill Tab {par}", None
        r, var = rng(lo, hi)
        return {"label": f"+{r} to {tab}", "tmpl": tmpl, "min": lo, "max": hi, "var": var}
    if code in ("hit-skill", "att-skill", "gethit-skill", "death-skill", "kill-skill", "levelup-skill"):
        trigger = {
            "hit-skill": "on striking", "att-skill": "on attack", "gethit-skill": "when struck",
            "death-skill": "when you Die", "kill-skill": "when you Kill an Enemy",
            "levelup-skill": "when you Level-Up",
        }[code]
        return {"label": f"{lo}% Chance to cast level {hi} {skill_name(par, skills_by_id)} {trigger}",
                "tmpl": None, "min": lo, "max": hi, "var": False}
    if code == "charged":
        return {"label": f"Level {hi} {skill_name(par, skills_by_id)} ({lo} Charges)",
                "tmpl": None, "min": lo, "max": hi, "var": False}
    if code == "aura":
        r, var = rng(lo, hi)
        return {"label": f"Level {r} {skill_name(par, skills_by_id)} Aura When Equipped",
                "tmpl": None, "min": lo, "max": hi, "var": var}
    if code == "sock":
        n = par if par not in (None, "") else (f"{lo}-{hi}" if lo != hi else lo)
        return {"label": f"Socketed ({n})", "tmpl": "Socketed (#)", "min": lo, "max": hi,
                "var": bool(lo != hi)}
    if code in ("dmg-norm", "dmg-fire", "dmg-ltng", "dmg-mag"):
        kind = {"dmg-norm": "", "dmg-fire": " Fire", "dmg-ltng": " Lightning", "dmg-mag": " Magic"}[code]
        return {"label": f"Adds {lo}-{hi}{kind} Damage", "tmpl": None, "min": lo, "max": hi, "var": False}
    if code == "dmg-cold":
        return {"label": f"Adds {lo}-{hi} Cold Damage", "tmpl": None, "min": lo, "max": hi, "var": False}
    if code == "dmg-pois":
        frames = int(par) if par not in (None, "") else 0
        total = round(lo * frames / 256)
        secs = round(frames / 25)
        return {"label": f"+{total} Poison Damage over {secs} Seconds", "tmpl": None,
                "min": lo, "max": hi, "var": False}
    if code == "rep-dur":
        return {"label": "Repairs durability over time", "tmpl": None, "min": lo, "max": hi, "var": False}

    unmapped[orig] = unmapped.get(orig, 0) + 1
    r, var = rng(lo, hi)
    return {"label": f"{orig} {r}", "tmpl": None, "min": lo, "max": hi, "var": var}


def item_props(it, skills_by_id, unmapped):
    props = []
    for i in range(1, 13):
        code = it.get(f"prop{i}")
        if not code:
            continue
        p = convert_prop(code, it.get(f"par{i}"), it.get(f"min{i}"), it.get(f"max{i}"),
                         skills_by_id, unmapped)
        if p:
            props.append(p)
    return props


def set_bonus_props(it, skills_by_id, unmapped):
    """Per-item green set bonuses (aprop1a..aprop5b).

    Index i = the bonus unlocks with (i + 1) set items worn; the a/b suffix
    is just two bonus slots per step.
    """
    props = []
    for i in range(1, 6):
        for suffix in ("a", "b"):
            code = it.get(f"aprop{i}{suffix}")
            if not code:
                continue
            p = convert_prop(code, it.get(f"apar{i}{suffix}"), it.get(f"amin{i}{suffix}"),
                             it.get(f"amax{i}{suffix}"), skills_by_id, unmapped)
            if p:
                p["label"] += f"  ({i + 1} set items)"
                p["tmpl"] = None  # never match rolls against set bonuses
                p["set_bonus"] = True
                props.append(p)
    return props


def main():
    from display_names import display_name
    uniques_src = fetch("uniqueitems.json")
    for it in uniques_src.values():  # txt index -> what the game SHOWS
        it["index"] = display_name(it["index"])
    sets_src = fetch("setitems.json")
    skills_by_id = build_skill_lookup(fetch("skills.json"))

    with open(REPO / "uniques.json", encoding="utf-8") as f:
        repo_uniques = json.load(f)
    with open(REPO / "set.json", encoding="utf-8") as f:
        repo_sets = json.load(f)

    unmapped = {}
    out = {"unique": {}, "set": {}}

    src_uniques = {}
    for it in uniques_src.values():
        key = it["index"].lower()
        # Prefer spawnable entries, but keep non-spawnable ones as fallback
        # (D2R sunder charms have no spawnable flag in this dump).
        if it.get("spawnable") or key not in src_uniques:
            src_uniques[key] = it
    missing_u = []
    for name, base in repo_uniques.items():
        it = src_uniques.get(ALIASES.get(name.lower(), name.lower()))
        if not it:
            missing_u.append(name)
            continue
        out["unique"][name] = {"base": base, "props": item_props(it, skills_by_id, unmapped)}

    src_sets = {it["index"].lower(): it for it in sets_src.values()}
    set_groups = {}
    for it in sets_src.values():
        set_groups.setdefault(it.get("set", ""), []).append(it["index"])
    missing_s = []
    for name, base in repo_sets.items():
        it = src_sets.get(name.lower())
        if not it:
            missing_s.append(name)
            continue
        set_name = it.get("set", "")
        pieces = sorted(p for p in set_groups.get(set_name, []) if p != it["index"])
        out["set"][name] = {"base": base, "set": set_name, "pieces": pieces,
                            "props": item_props(it, skills_by_id, unmapped)
                            + set_bonus_props(it, skills_by_id, unmapped)}

    # ---- runewords: their own mods (T1Code/Min/Max), same prop mapping -----
    out["runeword"] = {}
    for entry in fetch("runes.json").values():
        if not entry.get("complete"):
            continue
        name = entry.get("*Rune Name") or entry.get("Name")
        if not name:
            continue
        props = []
        for i in range(1, 8):
            code = entry.get(f"T1Code{i}")
            if not code:
                continue
            p = convert_prop(code, entry.get(f"T1Param{i}"), entry.get(f"T1Min{i}"),
                             entry.get(f"T1Max{i}"), skills_by_id, unmapped)
            if p:
                props.append(p)
        out["runeword"][name] = {"props": props}

    # ---- magic affix tiers: template -> [{name, min, max}] ------------------
    # For blue/yellow items: which prefix/suffix tier a rolled value belongs
    # to, and the overall cap for that stat.
    tiers = {}
    for src in ("magicprefix.json", "magicsuffix.json"):
        for row in fetch(src).values():
            if not row.get("spawnable") or not row.get("Name"):
                continue
            for i in (1, 2, 3):
                code = row.get(f"mod{i}code")
                if not code:
                    continue
                entry = SIMPLE.get(code)
                if not entry or not entry[1] or entry[1].count("#") != 1:
                    continue
                lo = abs(int(row.get(f"mod{i}min") or 0))
                hi = abs(int(row.get(f"mod{i}max") or 0))
                lo, hi = min(lo, hi), max(lo, hi)
                if hi == 0:
                    continue
                tiers.setdefault(entry[1], set()).add((row["Name"], lo, hi))
    out["affix_tiers"] = {
        tmpl: [{"name": n, "min": lo, "max": hi}
               for n, lo, hi in sorted(vals, key=lambda t: (t[1], t[2]))]
        for tmpl, vals in tiers.items()
    }
    # Superior (white) items roll these outside the magic affix system.
    for tmpl, lo, hi in (("+#% Enhanced Damage", 5, 15),
                         ("+#% Enhanced Defense", 5, 15),
                         ("Increase Maximum Durability #%", 10, 15)):
        out["affix_tiers"].setdefault(tmpl, []).insert(
            0, {"name": "Superior", "min": lo, "max": hi})

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"written {OUT}")
    print(f"uniques: {len(out['unique'])}/{len(repo_uniques)}  sets: {len(out['set'])}/{len(repo_sets)}"
          f"  runewords: {len(out['runeword'])}")
    if missing_u:
        print("uniques without data:", ", ".join(missing_u))
    if missing_s:
        print("sets without data:", ", ".join(missing_s))
    if unmapped:
        print("unmapped prop codes (raw fallback):", unmapped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
