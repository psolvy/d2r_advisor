import json
import re
from enum import Enum
from typing import Any, Dict, Final, List

from rapidfuzz import fuzz, process

from d2rlootreader.cfg import REPOSITORY_DIR


class Q(Enum):
    UNKNOWN = "Unknown"
    BASE = "Base"
    MAGIC = "Magic"
    RARE = "Rare"
    CRAFTED = "Crafted"
    SET = "Set"
    UNIQUE = "Unique"
    RUNEWORD = "Runeword"


class ItemParser:
    _none_match: Final = (None, 0, None)
    _scorers: Final = [fuzz.ratio, fuzz.token_set_ratio]
    _num_like: Final = r"(?i)\b(?:\d|[OIlZSBgq])+\b"
    _digit_translation: Final = str.maketrans(
        {
            # 0
            "O": "0",
            "o": "0",
            "Ο": "0",
            "О": "0",
            "〇": "0",
            # 1
            "I": "1",
            "l": "1",
            "|": "1",
            "!": "1",
            # 2
            "Z": "2",
            "z": "2",
            # 3
            "E": "3",
            "e": "3",
            # 4
            "A": "4",
            "a": "4",
            # 5
            "S": "5",
            "s": "5",
            "$": "5",
            # 6
            "G": "6",
            # 7
            "T": "7",
            "t": "7",
            # 8
            "B": "8",
            "b": "8",
            # 9
            "g": "9",
            "q": "9",
        }
    )

    # only the files the parser actually reads — ranges.json (676 KB) and
    # gamble*.json used to be parsed too, on EVERY instantiation
    _REPO_FILES = ("affixes", "bases", "classes", "magic", "rares",
                   "requirements", "runewords", "set", "skills", "stats",
                   "uniques")
    _REPO_CACHE: Dict[str, Any] = None

    def __init__(self, lines: List[str], quality_hint: str = None):
        self.R = self.repository_data = self.load_repository_data()
        self.lines = lines
        # Quality detected from the tooltip title color (screenshot), if any.
        # It restricts name matching to that quality and wins over the fuzzy
        # matcher when the name is not in the repository (new/renamed items).
        self.quality_hint = quality_hint

    @classmethod
    def load_repository_data(cls) -> Dict[str, Any]:
        # parse_best builds up to ~9 parsers per scan; re-reading ~1 MB of
        # JSON each time cost ~100 ms of pure churn per scan
        if cls._REPO_CACHE is None:
            data = {}
            for stem in cls._REPO_FILES:
                fname = REPOSITORY_DIR / f"{stem}.json"
                if fname.exists():
                    with open(fname, encoding="utf-8") as f:
                        data[stem] = json.load(f)
            # MOD OVERLAY: repository/overlay/<same name>.json merges over
            # the vanilla tables — renamed/new mod uniques, changed bases
            # etc. live there and survive updates (the dir is user data).
            overlay_dir = REPOSITORY_DIR / "overlay"
            if overlay_dir.is_dir():
                for fname in sorted(overlay_dir.glob("*.json")):
                    try:
                        with open(fname, encoding="utf-8") as f:
                            extra = json.load(f)
                    except (OSError, ValueError):
                        continue
                    base = data.get(fname.stem)
                    if isinstance(base, dict) and isinstance(extra, dict):
                        base.update(extra)
                    elif isinstance(base, list) and isinstance(extra, list):
                        base.extend(x for x in extra if x not in base)
                    else:
                        data[fname.stem] = extra
            cls._REPO_CACHE = data
        return cls._REPO_CACHE

    def parse_item_lines_to_json(self) -> Dict[str, Any]:
        result = {
            "quality": None,
            "name": None,
            "base": None,
            "slot": None,
            "tier": None,
            "requirements": {},
            "stats": {},
            "affixes": {},
            "tooltip": self.lines,
        }
        if not self.lines:
            return result

        lines = self.lines[:]

        result["quality"], result["name"], lines = self._parse_item_quality_name(lines)
        result["base"], result["slot"], result["tier"], lines = self._parse_item_base_slot_tier(lines)
        if result["quality"] == Q.BASE.value:
            result["name"] = result["base"]

        result["requirements"], result["stats"], result["affixes"], lines = self._parse_requirements_stats_affixes(
            lines
        )

        return result

    def _normalize_skill(self, line: str) -> str:
        skill, _, _ = process.extractOne(
            line, self.R.get("skills", {}), scorer=fuzz.token_set_ratio, processor=str.lower, score_cutoff=90
        ) or (None, 0, None)
        if skill:
            align = fuzz.partial_ratio_alignment(line, skill, processor=str.lower)
            start, end = align.src_start, align.src_end
            line = line[:start] + "[Skill]" + line[end:]

        return line, skill

    def _normalize_numbers(self, line: str) -> str:
        numbers = re.findall(self._num_like, line)
        line = re.sub(self._num_like, "#", line)
        return line, [self._text_to_int(n) for n in numbers]

    def _text_to_int(self, s: str) -> int:
        """
        Convert a string containing OCR/leet-like confusables into an integer.
        - Transliterates a conservative set of visually confusable characters into ASCII digits.
        - Keeps any Unicode decimal digits as-is (Python int() accepts them).
        - Ignores non-digits after transliteration.
        """
        normalized = s.translate(self._digit_translation)
        digits = [ch for ch in normalized if ch.isdigit()]
        if not digits:
            return 0
        return int("".join(digits))

    def _join_params(self, line, numbers, skill):
        params = []
        num_idx = 0
        for match in re.finditer(r"#|\[Skill\]", line):
            token = match.group(0)
            if token == "#" and num_idx < len(numbers):
                params.append(numbers[num_idx])
                num_idx += 1
            elif token == "[Skill]" and skill:
                params.append(skill)
        return params

    def _match_class(self, query):
        class_, _, _ = process.extractOne(
            query, self.R.get("classes", {}), scorer=fuzz.partial_token_set_ratio, score_cutoff=100
        ) or (None, 0, None)
        if class_:
            align = fuzz.partial_ratio_alignment(query, class_, processor=str.lower)
            return query[align.src_start : align.src_end]

    def _parse_item_quality_name(self, lines):
        name_line = lines[0].strip()
        hint = self.quality_hint

        if hint == Q.BASE.value:
            return Q.BASE.value, None, lines

        # Gold title = Unique or Runeword; only the name tells them apart.
        if hint in (None, Q.UNIQUE.value, Q.RUNEWORD.value):
            match, _, _ = process.extractOne(
                name_line, self.R.get("runewords", {}).keys(), scorer=fuzz.ratio, processor=str.lower, score_cutoff=85
            ) or (None, 0, None)
            if match:
                return Q.RUNEWORD.value, match, lines[1:]

            for scorer in self._scorers:
                match, _, _ = process.extractOne(
                    name_line, self.R.get("uniques", {}).keys(), scorer=scorer, processor=str.lower, score_cutoff=85
                ) or (None, 0, None)
                if match:
                    return Q.UNIQUE.value, match, lines[1:]

            if hint:
                return Q.UNIQUE.value, name_line, lines[1:]

        if hint in (None, Q.SET.value):
            for scorer in self._scorers:
                match, _, _ = process.extractOne(
                    name_line, self.R.get("set", {}).keys(), scorer=scorer, processor=str.lower, score_cutoff=85
                ) or (None, 0, None)
                if match:
                    return Q.SET.value, match, lines[1:]

            if hint:
                return Q.SET.value, name_line, lines[1:]

        if hint in (None, Q.RARE.value, Q.CRAFTED.value):
            rares = self.R.get("rares", {})
            prefix, _, _ = (
                process.extractOne(
                    name_line, rares["prefixes"], scorer=fuzz.partial_ratio, processor=str.lower, score_cutoff=90
                )
                or self._none_match
            )
            suffix, _, _ = (
                process.extractOne(
                    name_line, rares["suffixes"], scorer=fuzz.partial_ratio, processor=str.lower, score_cutoff=90
                )
                or self._none_match
            )
            name = f"{prefix} {suffix}".strip()
            if name.lower() == name_line.lower():
                return (hint or Q.RARE.value), name, lines[1:]
            if hint:
                return hint, name_line, lines[1:]

        if hint in (None, Q.MAGIC.value):
            magic = self.R.get("magic", {})
            prefix, _, _ = (
                process.extractOne(
                    name_line, magic["prefixes"], scorer=fuzz.token_set_ratio, processor=str.lower, score_cutoff=85
                )
                or self._none_match
            )
            suffix, _, _ = (
                process.extractOne(
                    name_line, magic["suffixes"], scorer=fuzz.token_set_ratio, processor=str.lower, score_cutoff=85
                )
                or self._none_match
            )
            name = ((f"{prefix} " if prefix else "") + (suffix or "")).strip()
            if prefix or suffix:
                return Q.MAGIC.value, name, lines
            if hint:
                # Magic names embed the base; keep the line for base parsing.
                return Q.MAGIC.value, name_line, lines

        return Q.BASE.value, None, lines

    def _parse_item_base_slot_tier(self, lines):
        if not lines:
            return None, None, None, lines
        base_line = lines[0].strip()
        bases = self.R.get("bases", {})

        for scorer in self._scorers:
            matches = process.extract(base_line, bases.keys(), scorer=scorer, score_cutoff=85)
            if matches:
                longest_match = max(matches, key=lambda m: len(m[0]))
                return longest_match[0], bases[longest_match[0]]["slot"], bases[longest_match[0]]["tier"], lines[1:]

        return None, None, None, lines

    def _match_stat_line(self, line, requirements, stats, affixes):
        """Try to classify one line as requirement/stat/affix. True if consumed."""
        normal_line, numbers = self._normalize_numbers(line)

        requirement, _, _ = process.extractOne(
            normal_line,
            self.R.get("requirements", {}).keys(),
            scorer=fuzz.ratio,
            processor=str.lower,
            score_cutoff=85,
        ) or (None, 0, None)
        if requirement:
            requirements[self.R.get("requirements", {})[requirement]] = (
                numbers[0] if numbers else self._match_class(requirement)
            )
            return True

        stat, _, _ = process.extractOne(
            normal_line, self.R.get("stats", {}).keys(), scorer=fuzz.ratio, processor=str.lower, score_cutoff=85
        ) or (None, 0, None)
        if stat:
            stats[self.R.get("stats", {})[stat]] = numbers
            return True

        affix, _, _ = process.extractOne(
            normal_line, self.R.get("affixes", {}), scorer=fuzz.ratio, processor=str.lower, score_cutoff=85
        ) or (None, 0, None)
        if affix:
            affixes.append((affix, numbers))
            return True

        normal_line, skill = self._normalize_skill(normal_line)
        skill_affix, _, _ = process.extractOne(
            normal_line, self.R.get("affixes", {}), scorer=fuzz.ratio, processor=str.lower, score_cutoff=85
        ) or (None, 0, None)
        if skill_affix:
            affixes.append((skill_affix, self._join_params(normal_line, numbers, skill)))
            return True

        return False

    def _parse_requirements_stats_affixes(self, lines):
        requirements = {}
        stats = {}
        affixes = []
        remaining_lines = []

        for line in lines:
            if self._match_stat_line(line, requirements, stats, affixes):
                continue
            # D2R joins some affixes on one line, e.g.
            # "Ethereal (Cannot be Repaired), Socketed (3)" — split and retry.
            # OCR can read the comma as ';' or '.'; unmatched parts roll back.
            parts = [p.strip() for p in re.split(r"[,;.]", line) if p.strip()]
            if len(parts) > 1:
                matched_any = False
                for part in parts:
                    if self._match_stat_line(part, requirements, stats, affixes):
                        matched_any = True
                    else:
                        remaining_lines.append(part)
                if matched_any:
                    continue
                # roll back the unmatched parts we just queued; keep the line whole
                del remaining_lines[-len(parts):]
            remaining_lines.append(line)

        return requirements, stats, affixes, remaining_lines
