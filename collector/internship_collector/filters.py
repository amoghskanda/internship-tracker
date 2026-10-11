"""Season, title, and location filters."""

from __future__ import annotations

import re

SUMMER_2027_RE = re.compile(r"\b(?:summer[\s,\-]*2027|2027[\s,\-]*summer)\b", re.IGNORECASE)
INTERNSHIP_RE = re.compile(r"\bintern(?:ship)?\b", re.IGNORECASE)

_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
}
_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia"
}
_US_CITY_MARKERS = {
    "austin", "boston", "chicago", "dallas", "denver", "detroit", "houston", "indianapolis", "los angeles", "miami", "nyc", "new york city", "philadelphia", "phoenix", "pittsburgh", "portland", "raleigh", "san diego", "san francisco", "san jose", "seattle", "sf", "washington, d.c.", "washington dc", "washington, dc"
}
_FOREIGN_MARKERS = {
    "australia", "brazil", "canada", "china", "france", "germany", "india", "ireland", "italy", "japan", "mexico", "singapore", "spain", "united kingdom", "uk", "england"
}


def has_summer_2027(value: str) -> bool:
    return bool(SUMMER_2027_RE.search(value or ""))


def is_internship_title(title: str) -> bool:
    return bool(INTERNSHIP_RE.search(title or ""))


def matches_role_keywords(role: str, keywords: tuple[str, ...] | list[str] | None) -> bool:
    if not keywords:
        return True
    lowered = (role or "").casefold()
    return any(keyword.casefold() in lowered for keyword in keywords)


def is_us_location(location: str, *, include_remote_unknown: bool = False) -> bool:
    """Return true only when the location text identifies the United States."""

    raw = (location or "").strip()
    if not raw:
        return False
    lower = re.sub(r"\s+", " ", raw.casefold())
    if re.search(r"\b(?:u\.?s\.?a?\.?|united states(?: of america)?|america)\b", lower):
        return True
    if any(re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", lower) for name in _STATE_NAMES):
        return True
    # Match city labels as tokens. A plain substring would classify locations
    # such as "Milan" because they contain "la".
    if any(re.search(r"(?<![a-z])" + re.escape(city) + r"(?![a-z])", lower) for city in _US_CITY_MARKERS):
        return True
    if any(re.search(r"(?<![a-z])" + re.escape(country) + r"(?![a-z])", lower) for country in _FOREIGN_MARKERS):
        return False
    # IN is also the common country abbreviation for India, so require an
    # explicit Indiana city/name instead of treating it as a state code.
    state_codes = _STATE_CODES - {"IN"}
    if re.search(r"(?:^|[\s,;/()])(?:" + "|".join(sorted(state_codes)) + r")(?:$|[,;/()])", raw.upper()):
        return True
    if include_remote_unknown and re.search(r"\bremote\b", lower):
        return True
    return False


def location_allowed(location: str, country_filter: str | None, *, include_remote_unknown: bool = False) -> bool:
    if not country_filter:
        return True
    if country_filter.casefold() in {"us", "usa", "u.s.", "united states"}:
        return is_us_location(location, include_remote_unknown=include_remote_unknown)
    # Keep the default extensible without claiming that arbitrary abbreviations
    # are countries. Callers can pass None for an unfiltered global collection.
    return country_filter.casefold() in (location or "").casefold()
