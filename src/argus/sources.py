"""Curated source registry.

Maps a provenance label (an RSS feed key, or a GDELT article domain) to publisher
metadata and a **NATO Admiralty source-reliability grade**:

    A  completely reliable      D  not usually reliable
    B  usually reliable         E  unreliable
    C  fairly reliable          F  cannot be judged

Grades are deliberately conservative and transparent: no open-source outlet is graded
A (that rank is reserved for "completely reliable"); established wire services and
public broadcasters earn B, regional/other outlets C, state-affiliated outlets D (a
provenance caution, not a quality verdict), and anything unrecognised defaults to F
until corroboration raises an event's per-document credibility (see nlp/reliability.py).
"""

from dataclasses import dataclass

DEFAULT_RELIABILITY = "F"


@dataclass(frozen=True)
class SourceInfo:
    name: str
    kind: str  # wire | broadcaster | igo | ngo | state | aggregator | other
    reliability: str  # A..F


# Keyed by the provenance label stored on a Document.source. RSS feeds use their
# config.rss_feeds key; GDELT articles use their (lowercased) domain.
REGISTRY: dict[str, SourceInfo] = {
    # --- curated RSS feeds (config.rss_feeds keys) ---
    "bbc-world": SourceInfo("BBC World", "broadcaster", "B"),
    "guardian-world": SourceInfo("The Guardian (World)", "broadcaster", "B"),
    "aljazeera": SourceInfo("Al Jazeera English", "broadcaster", "B"),
    "npr-world": SourceInfo("NPR (World)", "broadcaster", "B"),
    "dw-world": SourceInfo("Deutsche Welle", "broadcaster", "B"),
    "france24": SourceInfo("France 24", "broadcaster", "B"),
    "channelnewsasia": SourceInfo("Channel NewsAsia", "broadcaster", "B"),
    "un-news": SourceInfo("UN News", "igo", "B"),
    "reliefweb": SourceInfo("ReliefWeb (UN OCHA)", "igo", "B"),
    # --- common GDELT article domains ---
    "reuters.com": SourceInfo("Reuters", "wire", "B"),
    "apnews.com": SourceInfo("Associated Press", "wire", "B"),
    "afp.com": SourceInfo("Agence France-Presse", "wire", "B"),
    "bloomberg.com": SourceInfo("Bloomberg", "wire", "B"),
    "bbc.com": SourceInfo("BBC", "broadcaster", "B"),
    "bbc.co.uk": SourceInfo("BBC", "broadcaster", "B"),
    "theguardian.com": SourceInfo("The Guardian", "broadcaster", "B"),
    "aljazeera.com": SourceInfo("Al Jazeera", "broadcaster", "B"),
    "dw.com": SourceInfo("Deutsche Welle", "broadcaster", "B"),
    "france24.com": SourceInfo("France 24", "broadcaster", "B"),
    "npr.org": SourceInfo("NPR", "broadcaster", "B"),
    "channelnewsasia.com": SourceInfo("Channel NewsAsia", "broadcaster", "B"),
    "straitstimes.com": SourceInfo("The Straits Times", "broadcaster", "B"),
    "nytimes.com": SourceInfo("The New York Times", "broadcaster", "B"),
    "washingtonpost.com": SourceInfo("The Washington Post", "broadcaster", "B"),
    "ft.com": SourceInfo("Financial Times", "broadcaster", "B"),
    "cnn.com": SourceInfo("CNN", "broadcaster", "C"),
    "scmp.com": SourceInfo("South China Morning Post", "broadcaster", "C"),
    "un.org": SourceInfo("United Nations", "igo", "B"),
    "reliefweb.int": SourceInfo("ReliefWeb (UN OCHA)", "igo", "B"),
    # state-affiliated outlets: provenance caution (D), not a quality judgement
    "rt.com": SourceInfo("RT (state-affiliated, RU)", "state", "D"),
    "sputniknews.com": SourceInfo("Sputnik (state-affiliated, RU)", "state", "D"),
    "tass.com": SourceInfo("TASS (state, RU)", "state", "D"),
    "xinhuanet.com": SourceInfo("Xinhua (state, CN)", "state", "D"),
    "globaltimes.cn": SourceInfo("Global Times (state-affiliated, CN)", "state", "D"),
    "presstv.ir": SourceInfo("Press TV (state, IR)", "state", "D"),
}


def info_for(label: str) -> SourceInfo | None:
    return REGISTRY.get(label.lower())


def grade_for(label: str) -> str:
    """Admiralty source-reliability grade for a provenance label (F if unknown)."""
    info = REGISTRY.get(label.lower())
    return info.reliability if info else DEFAULT_RELIABILITY
