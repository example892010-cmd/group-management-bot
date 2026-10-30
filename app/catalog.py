"""Anime title catalog, matching and plain-text import/export helpers."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Literal

from rapidfuzz import fuzz, process

AnimeStatus = Literal["available", "unavailable"]
_VALID_STATUSES = {"available", "unavailable"}


def normalize_title(value: str) -> str:
    """Normalize titles consistently while preserving Tamil/Unicode letters."""
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    # Tamil and other Indic scripts use combining marks (Unicode categories M).
    # Keep letters, digits, underscore and combining marks; separate other symbols.
    value = "".join(
        char if (char not in {"\uFE0E", "\uFE0F", "\u200D"} and (char.isalnum() or char == "_" or unicodedata.category(char).startswith("M"))) else " "
        for char in value
    )
    return re.sub(r"\s+", " ", value).strip()


def parse_title_lines(text: str) -> list[str]:
    """Parse one-title-per-line TXT content, dropping blanks/comments/duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        title = raw_line.strip().lstrip("\ufeff")
        if not title or title.startswith("#"):
            continue
        key = normalize_title(title)
        if key and key not in seen:
            seen.add(key)
            result.append(title)
    return result


@dataclass
class Catalog:
    available: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.available = parse_title_lines("\n".join(self.available))
        self.unavailable = parse_title_lines("\n".join(self.unavailable))
        available_keys = {normalize_title(title) for title in self.available}
        self.unavailable = [
            title for title in self.unavailable
            if normalize_title(title) not in available_keys
        ]

    def titles(self, status: AnimeStatus) -> list[str]:
        self._validate_status(status)
        return list(getattr(self, status))

    def add(self, status: AnimeStatus, incoming: Iterable[str]) -> dict[str, list[str]]:
        self._validate_status(status)
        target: list[str] = getattr(self, status)
        other_status: AnimeStatus = "unavailable" if status == "available" else "available"
        other_keys = {normalize_title(title) for title in getattr(self, other_status)}
        target_keys = {normalize_title(title) for title in target}
        report = {"added": [], "duplicates": [], "conflicts": [], "invalid": []}
        for raw in incoming:
            title = raw.strip()
            key = normalize_title(title)
            if not key:
                report["invalid"].append(raw)
            elif key in target_keys:
                report["duplicates"].append(title)
            elif key in other_keys:
                report["conflicts"].append(title)
            else:
                target.append(title)
                target_keys.add(key)
                report["added"].append(title)
        return report

    def remove(self, status: AnimeStatus, incoming: Iterable[str]) -> dict[str, list[str]]:
        self._validate_status(status)
        target: list[str] = getattr(self, status)
        by_key = {normalize_title(title): title for title in target}
        report = {"removed": [], "not_found": []}
        remove_keys: set[str] = set()
        for raw in incoming:
            title = raw.strip()
            key = normalize_title(title)
            if not key or key not in by_key:
                report["not_found"].append(title or raw)
            elif key not in remove_keys:
                remove_keys.add(key)
                report["removed"].append(by_key[key])
        setattr(self, status, [title for title in target if normalize_title(title) not in remove_keys])
        return report

    def replace(self, status: AnimeStatus, incoming: Iterable[str]) -> dict[str, list[str]]:
        """Replace one list; titles already assigned to the other list are skipped."""
        self._validate_status(status)
        other_status: AnimeStatus = "unavailable" if status == "available" else "available"
        other_keys = {normalize_title(title) for title in getattr(self, other_status)}
        clean = parse_title_lines("\n".join(incoming))
        accepted: list[str] = []
        conflicts: list[str] = []
        for title in clean:
            if normalize_title(title) in other_keys:
                conflicts.append(title)
            else:
                accepted.append(title)
        setattr(self, status, accepted)
        return {"replaced": accepted, "conflicts": conflicts}

    def find_mentioned(self, message: str) -> tuple[str, AnimeStatus] | None:
        """Find the longest exact title mentioned in a message."""
        normalized_message = normalize_title(message)
        if not normalized_message:
            return None
        candidates = [
            (title, status)
            for status in ("available", "unavailable")
            for title in getattr(self, status)
        ]
        candidates.sort(key=lambda item: len(normalize_title(item[0])), reverse=True)
        for title, status in candidates:
            normalized = normalize_title(title)
            # normalize_title has already converted punctuation to spaces, so padded
            # containment gives word-boundary matching for Latin and Indic scripts.
            if f" {normalized} " in f" {normalized_message} ":
                return title, status  # type: ignore[return-value]
        return None

    def suggest_correction(self, message: str, threshold: int = 86) -> str | None:
        """Suggest a close title only for short title-like messages, not full sentences."""
        query = normalize_title(message)
        tokens = query.split()
        # Common casual address words should not block a spelling suggestion.
        while tokens and tokens[-1] in {"bro", "macha", "machi", "nanba", "da", "dei"}:
            tokens.pop()
        while tokens and tokens[0] in {"bro", "macha", "machi", "nanba", "da", "dei"}:
            tokens.pop(0)
        query = " ".join(tokens)
        if not query or len(query) < 4 or len(query) > 48 or len(query.split()) > 5:
            return None
        all_titles = self.available + self.unavailable
        if not all_titles:
            return None
        choices = {normalize_title(title): title for title in all_titles}
        if query in choices:
            return None
        match = process.extractOne(query, list(choices), scorer=fuzz.ratio)
        if not match:
            return None
        matched_key, score, _ = match
        if score < threshold:
            return None
        if abs(len(query) - len(matched_key)) > max(2, int(len(matched_key) * 0.22)):
            return None
        return choices[matched_key]

    def export_text(self, status: AnimeStatus) -> str:
        self._validate_status(status)
        titles = getattr(self, status)
        return "" if not titles else "\n".join(titles) + "\n"

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid anime status: {status}")
