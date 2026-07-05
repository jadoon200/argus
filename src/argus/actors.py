"""Threat-actor -> nation attribution registry — the cross-graph join between the cyber and
open-source pictures.

SENTINEL's cyber campaigns and OSINT reporting both name threat groups (APT28, Lazarus,
Sandworm, …); this curated registry resolves those names — and their many vendor aliases —
to a widely-reported **nation-state attribution**, so an analyst can join a cyber campaign to
the geopolitical actor a brief is about ("this Sandworm campaign ⇄ Russia ⇄ the narrative
you're reading"). Parallel to `sources.py` (which rates publishers): reference data, curated,
conservative.

**Responsible-use / honesty:** attribution is *contested and probabilistic*. These nations are
the **consensus of open reporting**, not a definitive finding, and are surfaced as human-review
decision support — never an automated verdict of state responsibility. The canonical/alias
names follow common industry usage (MITRE ATT&CK groups, vendor naming).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ThreatActor:
    name: str  # canonical name
    nation: str  # widely-reported nation-state attribution (open-reporting consensus)
    aliases: tuple[str, ...]  # vendor/industry aliases
    note: str  # short descriptor

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


# Curated set of well-known, widely-attributed nation-state groups. Not exhaustive; extend as
# needed. Attribution reflects the consensus of open reporting, not a definitive claim.
THREAT_ACTORS: list[ThreatActor] = [
    ThreatActor(
        "APT28",
        "Russia",
        ("Fancy Bear", "Sofacy", "Sednit", "STRONTIUM", "Forest Blizzard"),
        "Russian military intelligence (GRU) cyber-espionage group.",
    ),
    ThreatActor(
        "APT29",
        "Russia",
        ("Cozy Bear", "The Dukes", "Midnight Blizzard", "NOBELIUM"),
        "Russian foreign-intelligence (SVR) cyber-espionage group.",
    ),
    ThreatActor(
        "Sandworm",
        "Russia",
        ("Voodoo Bear", "Seashell Blizzard", "Iridium"),
        "Russian GRU group linked to destructive/ICS attacks.",
    ),
    ThreatActor(
        "Turla",
        "Russia",
        ("Snake", "Venomous Bear", "Waterbug"),
        "Russian FSB-linked long-running espionage group.",
    ),
    ThreatActor(
        "Lazarus Group",
        "North Korea",
        ("Lazarus", "Hidden Cobra", "Diamond Sleet", "ZINC"),
        "North Korean state group (espionage + financial theft).",
    ),
    ThreatActor(
        "Kimsuky",
        "North Korea",
        ("Velvet Chollima", "Emerald Sleet", "THALLIUM"),
        "North Korean espionage group targeting policy/academia.",
    ),
    ThreatActor(
        "APT38",
        "North Korea",
        ("BlueNoroff", "Stardust Chollima"),
        "North Korean financially-motivated group (bank heists).",
    ),
    ThreatActor(
        "APT1",
        "China",
        ("Comment Crew", "PLA Unit 61398", "Comment Panda"),
        "Chinese PLA cyber-espionage unit.",
    ),
    ThreatActor(
        "APT41",
        "China",
        ("Double Dragon", "Wicked Panda", "BARIUM", "Brass Typhoon"),
        "Chinese group blending espionage and financial crime.",
    ),
    ThreatActor(
        "APT10",
        "China",
        ("Stone Panda", "MenuPass", "Cicada"),
        "Chinese espionage group targeting managed service providers.",
    ),
    ThreatActor(
        "Mustang Panda",
        "China",
        ("Bronze President", "Twill Typhoon", "RedDelta"),
        "Chinese espionage group targeting governments/NGOs.",
    ),
    ThreatActor(
        "Volt Typhoon",
        "China",
        ("Vanguard Panda", "BRONZE SILHOUETTE"),
        "Chinese group pre-positioning in critical infrastructure.",
    ),
    ThreatActor(
        "APT33",
        "Iran",
        ("Elfin", "Refined Kitten", "Peach Sandstorm"),
        "Iranian espionage group targeting aviation/energy.",
    ),
    ThreatActor(
        "APT34",
        "Iran",
        ("OilRig", "Helix Kitten", "Hazel Sandstorm"),
        "Iranian espionage group targeting the Middle East.",
    ),
    ThreatActor(
        "APT35",
        "Iran",
        ("Charming Kitten", "Phosphorus", "Mint Sandstorm"),
        "Iranian group targeting dissidents, academics, officials.",
    ),
    ThreatActor(
        "MuddyWater",
        "Iran",
        ("Mango Sandstorm", "Static Kitten", "Seedworm"),
        "Iranian intelligence (MOIS) espionage group.",
    ),
]

_BY_NAME: dict[str, ThreatActor] = {n.lower(): a for a in THREAT_ACTORS for n in a.names}

# Free-text scanning is where false attribution happens, so aliases that are ordinary English
# words are handled specially:
# - Titlecase dictionary words (a snake in the datacenter, cicada season) are EXCLUDED from
#   scanning in any casing — still resolvable by exact lookup via resolve_actor().
# - The Microsoft element names are distinctive only in their all-caps vendor form, so they are
#   matched case-SENSITIVELY ("ZINC targets researchers" hits; "Zinc mining output" does not).
_SCAN_EXCLUDED = {"snake", "cicada", "phosphorus", "iridium", "elfin"}
_CASE_SENSITIVE = {"ZINC", "STRONTIUM", "BARIUM", "THALLIUM", "NOBELIUM"}


def _alternation(names: list[str]) -> str:
    # Longest-first so multi-word aliases match before any shorter substring; word boundaries
    # so "APT1" never matches inside "APT10".
    return r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b"


_ci_names = [
    n
    for a in THREAT_ACTORS
    for n in a.names
    if n.lower() not in _SCAN_EXCLUDED and n not in _CASE_SENSITIVE
]
_cs_names = [n for a in THREAT_ACTORS for n in a.names if n in _CASE_SENSITIVE]
_SCAN_CI = re.compile(_alternation(_ci_names), re.IGNORECASE)
_SCAN_CS = re.compile(_alternation(_cs_names))


def resolve_actor(name: str) -> ThreatActor | None:
    """The threat actor whose canonical name or alias equals `name` (case-insensitive)."""
    return _BY_NAME.get(name.strip().lower())


def attributions_in_text(text: str) -> list[ThreatActor]:
    """Every distinct threat actor named in `text` (by canonical name or alias), deduped.

    Generic-word aliases are excluded or case-gated (see above) so ordinary prose about
    snakes, cicadas or zinc mining is never attributed to a state."""
    seen: dict[str, ThreatActor] = {}
    for match in _SCAN_CI.findall(text or "") + _SCAN_CS.findall(text or ""):
        actor = _BY_NAME[match.lower()]
        seen.setdefault(actor.name, actor)
    return list(seen.values())


def actors_for_nation(nation: str) -> list[ThreatActor]:
    """Known threat groups attributed (in open reporting) to `nation` (case-insensitive)."""
    return [a for a in THREAT_ACTORS if a.nation.lower() == nation.strip().lower()]
