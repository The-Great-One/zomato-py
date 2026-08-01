"""Zomato web API client.

Reverse-engineered from Zomato's web frontend. Handles CSRF token
acquisition, session cookies, and the locus location cookie that
Zomato uses to determine the user's city.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from . import endpoints as ep
from .exceptions import (
    ZomatoAPIError,
    ZomatoAuthError,
    ZomatoNotFoundError,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Indian cities with known Zomato city IDs (common ones)
CITY_IDS: dict[str, int] = {
    "gurugram": 12939,
    "delhi": 1,
    "mumbai": 3,
    "bangalore": 4,
    "pune": 5,
    "hyderabad": 6,
    "chennai": 7,
    "kolkata": 8,
    "ahmedabad": 9,
    "goa": 13,
    "chandigarh": 14,
    "jaipur": 10,
    "lucknow": 11,
    "kochi": 12,
    "indore": 15,
    "noida": 12939,  # same metro area as Gurugram
    "faridabad": 12940,
}

# Common food keywords for dish extraction from review text
FOOD_KEYWORDS: list[str] = [
    "pizza", "burger", "pasta", "coffee", "momos", "biryani", "thali",
    "dosa", "paneer", "chicken", "sandwich", "shake", "dessert", "cake",
    "soup", "salad", "noodles", "tandoori", "kebab", "curry", "naan",
    "roti", "idli", "samosa", "chaat", "paratha", "butter chicken",
    "masala", "tikka", "ramen", "sushi", "tacos", "wraps", "pav bhaji",
    "chole", "rajma", "dal", "pulao", "fried rice", "manchurian",
    "spring rolls", "dim sum", "waffle", "pancake", "brownie", "ice cream",
    "kulfi", "falooda", "mojito", "latte", "cappuccino", "tea", "chai",
    "lassi", "juice", "smoothie", "cocktail", "mocktail", "beer", "wine",
    "bowl", "fries", "nachos", "wings", "nuggets", "butter", "cheese",
    "chocolate", "cookie", "pastry", "donut", "bagel", "muffin",
    "risotto", "gnocchi", "ravioli", "tiramisu", "gelato", "espresso",
    "mughlai", "shawarma", "falafel", "hummus", "pita", "biryani pot",
    "hyderabadi", "lucknowi", "kacchi", "handi", "kadhai", "bhuna",
    "rogan josh", "saag", "baingan", "bhindi", "aloo", "gobi",
    "mediterranean", "continental", "italian", "chinese", "thai",
    "mexican", "lebanese", "korean", "japanese", "american",
    "south indian", "north indian", "mughlai", "bengali", "rajasthani",
    "gujarati", "punjabi", "maharashtrian", "andhra", "chettinad",
    "kerala", "goan", "kashmiri", "awadhi",
]


@dataclass
class Location:
    """User location for Zomato API requests."""

    lat: float = 28.4595
    lng: float = 77.0266
    city_id: int = 12939
    city_name: str = "Gurugram"
    entity_type: str = "city"
    dsz_id: int = 333

    def to_cookie(self) -> str:
        """Serialize to the locus cookie format used by Zomato."""
        locus = {
            "addressId": 0,
            "lat": self.lat,
            "lng": self.lng,
            "cityId": self.city_id,
            "ltv": self.city_id,
            "lty": self.entity_type,
            "fetchFromGoogle": False,
            "dszId": self.dsz_id,
            "fen": self.city_name,
        }
        return urllib.parse.quote(json.dumps(locus))


class ZomatoClient:
    """Client for the Zomato web API.

    No API key required. The client automatically manages CSRF tokens
    and session cookies, replicating the behavior of the Zomato web app.

    Session persistence: CSRF tokens and cookies are saved to a JSON file
    in ``cache_dir`` (default ``~/.zomato-py``) so they can be reused across
    runs without re-fetching the CSRF token every time.

    Example:
        >>> client = ZomatoClient()
        >>> restaurants = client.search_restaurants(city="gurugram")
        >>> for r in restaurants:
        ...     print(r["name"], r["rating"])
    """

    def __init__(
        self,
        location: Location | None = None,
        session: requests.Session | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.location = location or Location()
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{ep.ZOMATO_BASE}/",
        })
        self._csrf: str = ""
        self._csrf_time: float = 0
        self._csrf_max_age: int = 1800  # 30 minutes

        # ── Persistent session ────────────────────────────────────
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".zomato-py"
        self._cache_file = self._cache_dir / "session.json"
        self._load_session()

    # ── Session persistence ──────────────────────────────────────

    def _load_session(self) -> None:
        """Load CSRF token and cookies from the cache file if available."""
        try:
            if self._cache_file.exists():
                data = json.loads(self._cache_file.read_text())
                csrf = data.get("csrf", "")
                csrf_time = data.get("csrf_time", 0)
                # Only restore if not expired
                if csrf and (time.time() - csrf_time < self._csrf_max_age):
                    self._csrf = csrf
                    self._csrf_time = csrf_time
                # Restore cookies
                cookies = data.get("cookies", {})
                for name, value in cookies.items():
                    self._session.cookies.set(name, value, domain=".zomato.com", path="/")
        except (json.JSONDecodeError, OSError, KeyError):
            # Corrupt or missing cache — silently start fresh
            pass

    def _save_session(self) -> None:
        """Save CSRF token and cookies to the cache file."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cookies: dict[str, str] = {}
            for c in self._session.cookies:
                if c.name not in cookies:
                    cookies[c.name] = c.value
            data = {
                "csrf": self._csrf,
                "csrf_time": self._csrf_time,
                "cookies": cookies,
            }
            self._cache_file.write_text(json.dumps(data))
        except OSError:
            # Can't write cache — non-fatal, session just won't persist
            pass

    # ── Internal helpers ──────────────────────────────────────────

    def _ensure_csrf(self) -> str:
        """Get or refresh the CSRF token."""
        if self._csrf and (time.time() - self._csrf_time < self._csrf_max_age):
            return self._csrf
        resp = self._session.get(
            f"{ep.ZOMATO_BASE}{ep.CSRF}",
            headers={"Referer": f"{ep.ZOMATO_BASE}/"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._csrf = data.get("csrf", "")
        self._csrf_time = time.time()
        if not self._csrf:
            raise ZomatoAuthError("Failed to acquire CSRF token")
        self._save_session()
        return self._csrf

    def _cookies(self) -> dict[str, str]:
        """Build the cookie dict including the locus location cookie."""
        cookies: dict[str, str] = {}
        for c in self._session.cookies:
            # Only keep the first occurrence of each cookie name
            if c.name not in cookies:
                cookies[c.name] = c.value
        cookies["locus"] = self.location.to_cookie()
        cookies["lty"] = str(self.location.city_id)
        cookies["ltv"] = str(self.location.city_id)
        cookies["zl"] = "en"
        return cookies

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        need_csrf: bool = False,
    ) -> dict | list:
        """Make a GET request to a Zomato webroute."""
        url = f"{ep.ZOMATO_BASE}{path}"
        headers: dict[str, str] = {}
        if need_csrf:
            headers["x-zomato-csrft"] = self._ensure_csrf()

        resp = self._session.get(
            url,
            params=params,
            headers=headers,
            cookies=self._cookies(),
        )
        return self._handle_response(resp, path)

    def _post(
        self,
        path: str,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict | list:
        """Make a POST request to a Zomato webroute (always needs CSRF)."""
        url = f"{ep.ZOMATO_BASE}{path}"
        headers = {
            "x-zomato-csrft": self._ensure_csrf(),
            "Content-Type": "application/json",
        }
        resp = self._session.post(
            url,
            json=json_body or {},
            params=params,
            headers=headers,
            cookies=self._cookies(),
        )
        return self._handle_response(resp, path)

    def _handle_response(self, resp: requests.Response, path: str) -> dict | list:
        """Parse API response and raise appropriate errors."""
        if resp.status_code == 401:
            # CSRF might have expired — clear and retry once
            self._csrf = ""
            raise ZomatoAuthError(
                f"Unauthorized request to {path} — CSRF token may have expired",
                status_code=401,
            )
        if resp.status_code == 404:
            raise ZomatoNotFoundError(
                f"Resource not found at {path}", status_code=404
            )
        if resp.status_code >= 500:
            raise ZomatoAPIError(
                f"Server error {resp.status_code} at {path}",
                status_code=resp.status_code,
            )
        try:
            data = resp.json()
        except requests.JSONDecodeError:
            raise ZomatoAPIError(
                f"Non-JSON response from {path}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        if isinstance(data, dict) and data.get("status") == "failed":
            raise ZomatoAPIError(
                data.get("message", "Unknown API error"),
                status_code=resp.status_code,
            )
        return data

    # ── Public API: Location ──────────────────────────────────────

    def search_location(self, query: str) -> list[dict]:
        """Search for Zomato location entities (cities, subzones).

        Returns list of dicts with keys: name, entity_id, entity_type,
        latitude, longitude, display_title, display_subtitle.
        """
        data = self._get(ep.LOCATION_SEARCH, params={
            "q": query,
            "lat": self.location.lat,
            "lng": self.location.lng,
        })
        suggestions = data.get("locationSuggestions", [])
        return [
            {
                "name": s.get("entity_title") or s.get("entity_name", ""),
                "entity_id": s.get("entity_id", 0),
                "entity_type": s.get("entity_type", ""),
                "latitude": s.get("entity_latitude", 0),
                "longitude": s.get("entity_longitude", 0),
                "display_title": s.get("display_title", ""),
                "display_subtitle": s.get("display_subtitle", ""),
            }
            for s in suggestions
        ]

    def get_location(self, lat: float, lng: float) -> dict:
        """Get location details for given coordinates."""
        data = self._get(ep.LOCATION_GET, params={"lat": lat, "lng": lng})
        return data.get("locationDetails", {})

    # ── Public API: Search ───────────────────────────────────────

    def search_restaurants(
        self,
        city: str = "gurugram",
        context: str = "delivery",
        lat: float | None = None,
        lng: float | None = None,
        cuisine: str | None = None,
    ) -> list[dict]:
        """Search for restaurants in a city.

        Uses the server-rendered ``__PRELOADED_STATE__`` from Zomato's
        curated listing pages, which are **not** IP-scoped unlike the
        ``getPage`` webroute.  When *cuisine* is provided, fetches the
        cuisine-specific listing page (e.g. ``/ncr/restaurants/burger``)
        and the "best <city> <cuisine>" page, deduplicates, and returns
        up to ~30 unique results.

        Args:
            city: City name slug (e.g. 'gurugram', 'delhi', 'mumbai')
            context: 'delivery', 'dineout', or 'nightlife'
            lat/lng: Override location coordinates (unused by SSR fetch
                but accepted for API compatibility)
            cuisine: Optional cuisine filter (e.g. 'burger', 'pizza')

        Returns list of restaurant dicts with keys:
            resId, name, cuisine, rating, rating_text, cost_for_two,
            image_url, url, locality, is_promoted
        """
        city_lower = city.lower().replace(" ", "")
        if city_lower in CITY_IDS:
            self.location.city_id = CITY_IDS[city_lower]
            self.location.city_name = city.title()

        # Build candidate URLs — SSR pages embed results in __PRELOADED_STATE__
        ncr_cities = {"gurugram", "noida", "faridabad", "delhi"}
        base = "/ncr" if city_lower in ncr_cities else f"/{city}"
        city_display = "gurgaon" if city_lower == "gurugram" else city_lower

        urls: list[str] = []
        if cuisine:
            slug = cuisine.lower().replace(" ", "-")
            # Best <city> <cuisine> restaurants (curated, highest-rated)
            urls.append(f"https://www.zomato.com{base}/best-{city_display}-{slug}-restaurants")
            # Generic cuisine listing
            urls.append(f"https://www.zomato.com{base}/restaurants/{slug}")
            if context == "delivery":
                urls.append(
                    f"https://www.zomato.com{base}/restaurants/{slug}?order-online=1"
                )
        else:
            if context == "delivery":
                urls.append(f"https://www.zomato.com{base}/restaurants?order-online=1")
            elif context == "dineout":
                urls.append(f"https://www.zomato.com{base}/dine-out")
            elif context == "nightlife":
                urls.append(f"https://www.zomato.com{base}/nightlife")
            else:
                urls.append(f"https://www.zomato.com{base}/restaurants")

        seen: dict[int | str, dict] = {}
        for url in urls:
            for res in self._fetch_ssr_search(url):
                rid = res.get("resId") or res.get("res_id") or res.get("name", "")
                if rid and rid not in seen:
                    seen[rid] = res

        return list(seen.values())

    def _fetch_ssr_search(self, page_url: str) -> list[dict]:
        """Fetch a Zomato listing page and extract restaurants from
        the server-rendered ``__PRELOADED_STATE__`` JSON blob.

        This bypasses the IP-scoped ``getPage`` webroute by reading
        results that are embedded directly in the HTML.
        """
        import json as _json
        import re as _re

        resp = self._session.get(
            page_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            cookies=self._cookies(),
            timeout=30,
            allow_redirects=True,
        )
        if resp.status_code != 200 or len(resp.text) < 50_000:
            return []

        match = _re.search(
            r'window\.__PRELOADED_STATE__\s*=\s*JSON\.parse\("(.*?)"\)',
            resp.text,
            _re.DOTALL,
        )
        if not match:
            return []

        try:
            raw = match.group(1)
            unescaped = raw.encode().decode("unicode_escape")
            data = _json.loads(unescaped)
        except (ValueError, UnicodeDecodeError):
            return []

        results: list[dict] = []
        search_pages = data.get("pages", {}).get("search", {})
        for page_data in search_pages.values():
            if not isinstance(page_data, dict):
                continue
            sections = page_data.get("sections", {})
            for raw in sections.get("SECTION_SEARCH_RESULT", []):
                if isinstance(raw, dict):
                    results.append(self._parse_restaurant(raw))
        return results

    def _parse_restaurant(self, raw: dict) -> dict:
        """Parse a raw restaurant entity from the search results."""
        info = raw.get("info", {})
        rating = info.get("rating", {})
        rating_new = info.get("ratingNew", {}).get("ratings", {})
        delivery_rating = rating_new.get("DELIVERY", {})
        dining_rating = rating_new.get("DINING", {})

        # Parse cuisine — can be a list of dicts or a string
        cuisine_raw = info.get("cuisine", "")
        if isinstance(cuisine_raw, list):
            cuisine = ", ".join(c.get("name", "") for c in cuisine_raw if isinstance(c, dict))
        elif isinstance(cuisine_raw, str):
            cuisine = cuisine_raw
        else:
            cuisine = info.get("cuisine_string", "")

        # Parse locality
        locality = info.get("locality", {})
        locality_name = ""
        if isinstance(locality, dict):
            locality_name = locality.get("name", "") or locality.get("localityName", "")

        # Parse cost for two
        cft = info.get("cft", {})
        cost_text = cft.get("text", "") if isinstance(cft, dict) else ""

        # Parse timing
        timing = info.get("timing", {})
        timing_text = timing.get("text", "") if isinstance(timing, dict) else ""

        return {
            "resId": info.get("resId"),
            "name": info.get("name", ""),
            "cuisine": cuisine,
            "rating": rating.get("aggregate_rating", "0"),
            "rating_text": rating.get("rating_subtitle", ""),
            "votes": rating.get("votes", "0"),
            "cost_for_two": cost_text,
            "cost_for_one": info.get("cfo", {}).get("text", "") if isinstance(info.get("cfo"), dict) else "",
            "image_url": info.get("image", {}).get("url", ""),
            "url": info.get("resUrl", ""),
            "locality": locality_name,
            "timing": timing_text,
            "is_promoted": raw.get("isPromoted", False),
            "delivery_rating": delivery_rating.get("rating", "0"),
            "delivery_reviews": delivery_rating.get("reviewCount", "0"),
            "dining_rating": dining_rating.get("rating", "0"),
            "dining_reviews": dining_rating.get("reviewCount", "0"),
        }

    def auto_suggest(
        self,
        query: str,
        entity_id: int | None = None,
        entity_type: str = "city",
    ) -> dict:
        """Get search auto-suggestions.

        Returns dict with 'results' key containing suggestions.
        """
        if entity_id is None:
            entity_id = self.location.city_id
        return self._get(ep.SEARCH_AUTOSUGGEST, params={
            "q": query,
            "entity_id": entity_id,
            "entity_type": entity_type,
        })

    # ── Public API: Restaurant ────────────────────────────────────

    def get_restaurant(self, res_id: int) -> dict:
        """Get detailed information about a restaurant.

        Returns dict with keys: name, cuisine, rating, cost_for_two,
        address, locality, city, timings, phone, photos, menu_url, etc.
        """
        data = self._get(ep.RESTAURANT_INFO, params={"res_id": res_id})
        sections = data.get("page_data", {}).get("sections", {})

        basic = sections.get("SECTION_BASIC_INFO", {})
        if not isinstance(basic, dict):
            basic = {}

        # Contact info (address, phone, city, coordinates)
        contact = sections.get("SECTION_RES_CONTACT", {})
        if not isinstance(contact, dict):
            contact = {}

        # Header details (locality)
        header = sections.get("SECTION_RES_HEADER_DETAILS", {})
        if not isinstance(header, dict):
            header = {}

        # Cost for two, cuisines, menu
        details = sections.get("SECTION_RES_DETAILS", {})
        if not isinstance(details, dict):
            details = {}

        # Extract cost for two
        cft_details = details.get("CFT_DETAILS", {})
        cfts = cft_details.get("cfts", [])
        cost_for_two = cfts[0].get("title", "") if cfts else ""

        # Extract locality from header
        locality_info = header.get("LOCALITY", {})
        if not isinstance(locality_info, dict):
            locality_info = {}

        # Extract timings
        timing_obj = basic.get("timing", {})
        if isinstance(timing_obj, dict):
            timings = timing_obj.get("timing_desc", "")
            if not timings:
                # Try customised timings
                custom = timing_obj.get("customised_timings", {})
                if isinstance(custom, dict):
                    hours = custom.get("opening_hours", [])
                    if hours and isinstance(hours, list):
                        first = hours[0] if hours else {}
                        if isinstance(first, dict):
                            timings = f"{first.get('timing', '')} ({first.get('days', '')})"
        else:
            timings = str(timing_obj)

        # Extract phone
        phone_details = contact.get("phoneDetails", {})
        phone = phone_details.get("phoneStr", "") if isinstance(phone_details, dict) else ""

        return {
            "res_id": res_id,
            "name": basic.get("name", ""),
            "cuisine": basic.get("cuisine_string", ""),
            "rating": basic.get("rating", {}).get("aggregate_rating", "0"),
            "rating_text": basic.get("rating", {}).get("rating_subtitle", ""),
            "votes": basic.get("rating", {}).get("votes", "0"),
            "cost_for_two": cost_for_two,
            "address": contact.get("address", ""),
            "locality": locality_info.get("text", ""),
            "city": contact.get("city_name", ""),
            "timings": timings,
            "phone": phone,
            "latitude": contact.get("latitude", ""),
            "longitude": contact.get("longitude", ""),
            "res_url": basic.get("resUrl", ""),
            "status": basic.get("res_status_text", ""),
            "is_perm_closed": basic.get("is_perm_closed", False),
            "photos": self._extract_photos(sections),
            "menu_pages": self._extract_menu_pages(details),
            "rating_new": basic.get("ratingNew", {}),
            "raw_sections": list(sections.keys()),
        }

    def _extract_photos(self, sections: dict) -> list[str]:
        """Extract photo URLs from the restaurant page sections."""
        photos = []
        carousel = sections.get("SECTION_IMAGE_CAROUSEL", {})
        if isinstance(carousel, dict):
            for entity in carousel.get("entities", []):
                if isinstance(entity, dict):
                    for eid in entity.get("entity_ids", []):
                        photos.append(eid)
        return photos

    def _extract_menu_pages(self, details: dict) -> list[dict]:
        """Extract menu page info from SECTION_RES_DETAILS."""
        image_menus = details.get("IMAGE_MENUS", {})
        if not isinstance(image_menus, dict):
            return []
        menus = image_menus.get("menus", [])
        return [
            {
                "label": m.get("label", ""),
                "subtitle": m.get("subtitle", ""),
                "thumb": m.get("thumb", ""),
            }
            for m in menus
            if isinstance(m, dict)
        ]

    # ── Public API: Restaurant Offers & Hygiene ───────────────────

    def get_restaurant_offers(self, res_id: int) -> list[dict]:
        """Get available offers for a restaurant.

        Calls the order/resOffer webroute and returns a list of offer dicts.
        Some restaurants may return an empty list.

        Args:
            res_id: Zomato restaurant ID

        Returns:
            List of offer dicts. Each offer typically has fields like
            title, description, code, type, etc.
        """
        data = self._get(ep.ORDER_RES_OFFER, params={"res_id": res_id})
        offers = data.get("restaurantOffers", [])
        if not isinstance(offers, list):
            return []
        return offers

    def get_hygiene_details(self, res_id: int) -> dict:
        """Get hygiene/audit details for a restaurant.

        Calls the restaurant/getHygieneDetails webroute and returns a dict
        with valid_until, audit_on, and sections data.

        Args:
            res_id: Zomato restaurant ID

        Returns:
            Dict with keys: valid_until, audit_on, sections
        """
        data = self._get(ep.RESTAURANT_HYGIENE, params={"res_id": res_id})
        page_data = data.get("page_data", data)
        return {
            "valid_until": page_data.get("valid_until", ""),
            "audit_on": page_data.get("audit_on", ""),
            "sections": page_data.get("sections", page_data.get("content", {}).get("sections", {})),
        }

    # ── Public API: Reviews ───────────────────────────────────────

    def get_reviews(
        self,
        res_id: int,
        offset: int = 0,
        limit: int = 10,
        sort: str = "",
    ) -> list[dict]:
        """Get restaurant reviews.

        The Zomato reviews endpoint returns data in two possible structures:
        - New format: ``entities.REVIEWS`` (dict keyed by review ID) with
          ``page_data.sections.SECTION_REVIEWS`` containing entity_ids.
        - Legacy format: ``page_data.sections.SECTION_REVIEW`` (dict or list
          of review objects directly).

        This method handles both formats transparently.

        Returns list of review dicts with keys: review_id, rating,
        rating_text, text, user_name, user_id, timestamp, likes,
        comments_count, experience, review_tags, review_photos, review_url.
        """
        params: dict[str, Any] = {
            "res_id": res_id,
            "offset": offset,
            "limit": limit,
        }
        if sort:
            params["sort"] = sort

        data = self._get(ep.REVIEWS_LOAD_MORE, params=params)

        # ── New format: entities.REVIEWS (dict keyed by review ID) ──
        entities = data.get("entities", {})
        reviews_data = entities.get("REVIEWS", {})

        # ── Fallback: legacy format — page_data.sections.SECTION_REVIEW ──
        if not reviews_data:
            sections = data.get("page_data", {}).get("sections", {})
            # Try SECTION_REVIEW (singular, legacy) and SECTION_REVIEWS (plural)
            reviews_data = sections.get("SECTION_REVIEW", sections.get("SECTION_REVIEWS", {}))

        reviews = []
        if isinstance(reviews_data, dict):
            for key, review in reviews_data.items():
                if not isinstance(review, dict):
                    continue
                reviews.append(self._parse_review(review))
        elif isinstance(reviews_data, list):
            for review in reviews_data:
                if isinstance(review, dict):
                    reviews.append(self._parse_review(review))
        return reviews

    def _parse_review(self, raw: dict) -> dict:
        """Parse a raw review entity.

        Handles both the new API field names (reviewId, ratingV2,
        likeCount, commentCount, reviewUserId, reviewTags, etc.) and
        legacy field names (id, rating, likesCount, commentsCount,
        userId, ratingText) for backward compatibility.
        """
        return {
            "review_id": raw.get("reviewId", raw.get("id", "")),
            "rating": raw.get("ratingV2", raw.get("rating", "0")),
            "rating_text": raw.get("ratingV2Text", raw.get("ratingText", "")),
            "text": raw.get("reviewText", ""),
            "user_name": raw.get("userName", ""),
            "user_id": raw.get("reviewUserId", raw.get("userId", "")),
            "timestamp": raw.get("timestamp", ""),
            "likes": raw.get("likeCount", raw.get("likesCount", 0)),
            "comments_count": raw.get("commentCount", raw.get("commentsCount", 0)),
            "experience": raw.get("experience", ""),
            "review_tags": raw.get("reviewTags", []),
            "review_photos": raw.get("reviewPhotos", []),
            "review_url": raw.get("reviewUrl", ""),
        }

    # ── Public API: Rating Trends ─────────────────────────────────

    def get_rating_trends(self, res_id: int, months: int = 6) -> list[dict]:
        """Analyze rating trends over time for a restaurant.

        Fetches reviews in batches (up to 200) and groups them by month,
        calculating the average rating per month. The trend for each month
        is determined by comparing to the previous month's average.

        Args:
            res_id: Zomato restaurant ID
            months: Maximum number of recent months to return (default 6)

        Returns:
            List of dicts sorted by month (most recent first), each with:
            - month: "YYYY-MM" string
            - avg_rating: float, average rating for that month
            - count: int, number of reviews in that month
            - trend: "up", "down", or "stable" (compared to previous month)
        """
        # Fetch reviews in batches
        all_reviews: list[dict] = []
        batch_size = 10
        max_reviews = 200

        for offset in range(0, max_reviews, batch_size):
            batch = self.get_reviews(res_id, offset=offset, limit=batch_size)
            if not batch:
                break
            all_reviews.extend(batch)
            if len(batch) < batch_size:
                break

        # Group reviews by month
        monthly: dict[str, list[float]] = defaultdict(list)
        for review in all_reviews:
            timestamp = review.get("timestamp", "")
            rating_str = str(review.get("rating", "0"))
            if not timestamp or rating_str == "0":
                continue

            month_key = self._parse_timestamp_to_month(timestamp)
            if month_key:
                try:
                    rating_val = float(rating_str)
                    monthly[month_key].append(rating_val)
                except (ValueError, TypeError):
                    pass

        # Build sorted list of months (most recent first)
        sorted_months = sorted(monthly.keys(), reverse=True)[:months]

        results: list[dict] = []
        prev_avg: float | None = None

        for month_key in sorted_months:
            ratings = monthly[month_key]
            avg = sum(ratings) / len(ratings) if ratings else 0

            if prev_avg is not None:
                diff = avg - prev_avg
                if diff > 0.1:
                    trend = "up"
                elif diff < -0.1:
                    trend = "down"
                else:
                    trend = "stable"
            else:
                trend = "stable"

            results.append({
                "month": month_key,
                "avg_rating": round(avg, 2),
                "count": len(ratings),
                "trend": trend,
            })
            prev_avg = avg

        return results

    def _parse_timestamp_to_month(self, timestamp: str) -> str | None:
        """Parse a review timestamp string to a 'YYYY-MM' key.

        Handles formats like:
        - "Jun 23, 2019"
        - "2024-01-15"
        - "January 15, 2024"
        """
        timestamp = timestamp.strip()
        if not timestamp:
            return None

        # Try common formats
        formats = [
            "%b %d, %Y",      # Jun 23, 2019
            "%B %d, %Y",      # January 23, 2019
            "%Y-%m-%d",       # 2019-06-23
            "%d %b %Y",       # 23 Jun 2019
            "%d %B %Y",       # 23 January 2019
            "%b %Y",          # Jun 2019
            "%B %Y",          # January 2019
            "%Y-%m",          # 2019-06
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(timestamp, fmt)
                return dt.strftime("%Y-%m")
            except ValueError:
                continue

        # Try regex extraction for partial dates like "Jun 2019" or "2019"
        m = re.match(r"(\w{3,9})\s+(\d{4})", timestamp)
        if m:
            month_str, year = m.group(1), m.group(2)
            for fmt in ["%b %Y", "%B %Y"]:
                try:
                    dt = datetime.strptime(f"{month_str} {year}", fmt)
                    return dt.strftime("%Y-%m")
                except ValueError:
                    continue

        # Just a year
        m = re.match(r"^(\d{4})$", timestamp)
        if m:
            return f"{m.group(1)}-00"

        return None

    # ── Public API: Popular Dishes ────────────────────────────────

    def get_popular_dishes(self, res_id: int, limit: int = 10) -> list[dict]:
        """Extract popular dishes mentioned in reviews.

        Fetches up to 100 reviews and scans review text and review tags
        for food keyword mentions. Returns dishes sorted by mention count,
        with average rating of reviews mentioning each dish.

        Args:
            res_id: Zomato restaurant ID
            limit: Maximum number of dishes to return (default 10)

        Returns:
            List of dicts sorted by mentions (descending), each with:
            - dish: dish name (capitalized)
            - mentions: number of reviews mentioning this dish
            - avg_rating: average rating from reviews mentioning this dish
        """
        # Fetch up to 100 reviews
        all_reviews: list[dict] = []
        batch_size = 10
        max_reviews = 100

        for offset in range(0, max_reviews, batch_size):
            batch = self.get_reviews(res_id, offset=offset, limit=batch_size)
            if not batch:
                break
            all_reviews.extend(batch)
            if len(batch) < batch_size:
                break

        # Track dish mentions and ratings
        dish_mentions: dict[str, int] = defaultdict(int)
        dish_ratings: dict[str, list[float]] = defaultdict(list)

        for review in all_reviews:
            text = (review.get("text", "") or "").lower()
            try:
                rating = float(review.get("rating", "0"))
            except (ValueError, TypeError):
                rating = 0

            mentioned_dishes: set[str] = set()

            # Check review text against food keywords
            for keyword in FOOD_KEYWORDS:
                if keyword in text:
                    mentioned_dishes.add(keyword)

            # Check review tags (list of dicts with "name" field)
            review_tags = review.get("review_tags", [])
            if isinstance(review_tags, list):
                for tag in review_tags:
                    if isinstance(tag, dict):
                        tag_name = (tag.get("name", "") or "").lower().strip()
                        if tag_name and tag_name not in mentioned_dishes:
                            # Check if tag name contains a known food keyword
                            for keyword in FOOD_KEYWORDS:
                                if keyword in tag_name:
                                    mentioned_dishes.add(keyword)
                                    break
                            else:
                                # No keyword match — use the tag name itself
                                # if it's short and looks like a dish
                                if 2 < len(tag_name) < 40 and " " not in tag_name:
                                    mentioned_dishes.add(tag_name)

            for dish in mentioned_dishes:
                dish_mentions[dish] += 1
                dish_ratings[dish].append(rating)

        # Build result list
        dishes: list[dict] = []
        for dish, mentions in dish_mentions.items():
            ratings = dish_ratings[dish]
            avg_rating = sum(ratings) / len(ratings) if ratings else 0
            dishes.append({
                "dish": dish.title(),
                "mentions": mentions,
                "avg_rating": round(avg_rating, 2),
            })

        # Sort by mention count (descending), then by avg_rating
        dishes.sort(key=lambda d: (d["mentions"], d["avg_rating"]), reverse=True)

        return dishes[:limit]

    # ── Public API: Value for Money ───────────────────────────────

    def get_value_for_money(self, res_id: int) -> dict:
        """Calculate value-for-money metrics for a restaurant.

        Fetches restaurant details and computes cost_per_rating =
        cost_for_two / rating. A lower cost_per_rating indicates better
        value for money.

        Args:
            res_id: Zomato restaurant ID

        Returns:
            Dict with keys: name, rating, cost_for_two, cost_per_rating,
            verdict. Verdict thresholds:
            - "great value": cost_per_rating < 100
            - "good": cost_per_rating 100–200
            - "pricey": cost_per_rating > 200
        """
        info = self.get_restaurant(res_id)
        name = info.get("name", "")
        rating_str = str(info.get("rating", "0"))
        cost_str = info.get("cost_for_two", "")

        # Parse numeric rating
        try:
            rating = float(rating_str)
        except (ValueError, TypeError):
            rating = 0

        # Parse cost for two — extract digits from strings like "₹600 for two people"
        cost_digits = re.findall(r"[\d,]+", cost_str.replace("₹", "").replace("Rs.", "").replace("Rs", ""))
        cost_for_two = 0
        if cost_digits:
            try:
                cost_for_two = int(cost_digits[0].replace(",", ""))
            except (ValueError, IndexError):
                cost_for_two = 0

        # Calculate cost per rating
        if rating > 0:
            cost_per_rating = cost_for_two / rating
        else:
            cost_per_rating = 0

        # Determine verdict
        if cost_per_rating == 0:
            verdict = "unknown"
        elif cost_per_rating < 100:
            verdict = "great value"
        elif cost_per_rating <= 200:
            verdict = "good"
        else:
            verdict = "pricey"

        return {
            "name": name,
            "rating": rating,
            "cost_for_two": cost_for_two,
            "cost_per_rating": round(cost_per_rating, 2),
            "verdict": verdict,
        }

    # ── Public API: Collections ──────────────────────────────────

    def get_collections(self, city: str = "gurugram") -> list[dict]:
        """Get curated restaurant collections for a city.

        Returns list of dicts with: title, url, image_url, description.
        """
        data = self._get(ep.GET_PAGE, params={
            "url": f"/{city}",
            "lat": self.location.lat,
            "lng": self.location.lng,
        })
        sections = data.get("page_data", {}).get("sections", {})
        coll_section = sections.get("SECTION_COLLECTIONS", {})
        collections = coll_section.get("collections", [])
        return [
            {
                "title": c.get("title", ""),
                "url": c.get("url", ""),
                "image_url": c.get("image", ""),
                "description": c.get("description", ""),
            }
            for c in collections
            if isinstance(c, dict)
        ]

    # ── Public API: Home / Quick Links ────────────────────────────

    def get_quick_links(self, city_id: int | None = None) -> dict:
        """Get quick links for the home page (categories like Delivery, Dine-out)."""
        if city_id is None:
            city_id = self.location.city_id
        return self._get(ep.HOME_QUICK_LINKS, params={"city_id": city_id})

    # ── Public API: Kitchen / Blog ────────────────────────────────

    def get_kitchen_cities(self) -> list[dict]:
        """Get available cities for Zomato Kitchen."""
        data = self._get(ep.KITCHEN_CITY)
        return data.get("cities", [])

    def get_blog_posts(self) -> dict:
        """Get latest Zomato blog posts."""
        return self._get(ep.BLOG_POSTS)

    # ── Public API: Menu ──────────────────────────────────────────

    def get_menu(self, res_id: int) -> dict:
        """Get restaurant menu."""
        return self._get(ep.MENU_VIEW, params={"res_id": res_id, "api_key": ""})

    # ── Public API: Events (District) ─────────────────────────────

    def get_events(
        self,
        city: str = "gurugram",
        category: str = "",
        when: str = "",
    ) -> list[dict]:
        """Get events from District by Zomato.

        Scrapes the District events page (Next.js RSC) and extracts
        event data including titles, venues, cities, dates, and descriptions.

        Args:
            city: Filter by city name (empty = all cities)
            category: Filter by category/genre
            when: Filter by date — 'today', 'tomorrow', 'weekend', or 'YYYY-MM-DD'

        Returns list of event dicts with keys: title, venue, city, date,
        description, start_epoch, end_epoch.
        """
        html = self._get_district_events_html()

        events = self._parse_district_events(html)

        # Filter by date if specified
        if when:
            events = self._filter_events_by_when(events, when)

        # Filter by city if specified
        if city:
            city_lower = city.lower()
            events = [
                e for e in events
                if city_lower in (e.get("city", "")).lower()
                or city_lower in (e.get("venue", "")).lower()
            ]

        # Filter by category if specified
        if category:
            cat_lower = category.lower()
            events = [
                e for e in events
                if cat_lower in (e.get("category", "")).lower()
            ]

        return events

    def get_movies(self, city: str = "gurugram") -> list[dict]:
        """Get movies from District by Zomato.

        Returns list of movie dicts with keys: title, venue, city,
        image_url, url.
        """
        url = f"{ep.DISTRICT_BASE}{ep.DISTRICT_MOVIES_PAGE}"
        resp = self._session.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        html = resp.text
        return self._parse_district_events(html)

    def _parse_district_events(self, html: str) -> list[dict]:
        """Parse events from District RSC (React Server Component) HTML.

        District uses Next.js RSC which streams data via self.__next_f.push().
        We extract ItemDetails blocks from the RSC payload, each containing
        a complete event with name, venue, city, date, and description.
        """
        # Extract all __next_f pushes by finding script boundaries
        push_starts = [
            m.start() for m in re.finditer(r'self\.__next_f\.push\(\[1,"', html)
        ]
        if not push_starts:
            return []

        combined = ""
        for start in push_starts:
            content_start = html.find('[1,"', start) + 4
            if content_start < 4:
                continue
            script_end = html.find("</script>", content_start)
            if script_end < 0:
                continue
            push_end = html.rfind('"])', content_start, script_end)
            if push_end < 0:
                push_end = html.rfind('")', content_start, script_end)
            chunk = html[content_start:push_end]
            unescaped = (
                chunk.replace('\\"', '"')
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )
            combined += unescaped

        # Find all ItemDetails blocks — each contains a complete event/venue/artist
        item_blocks: list[str] = []
        idx = 0
        while True:
            pos = combined.find('"ItemDetails":{', idx)
            if pos < 0:
                break
            # Find matching closing brace
            brace_count = 0
            start = pos + len('"ItemDetails":')
            end = start
            for j in range(start, min(start + 10000, len(combined))):
                if combined[j] == '{':
                    brace_count += 1
                elif combined[j] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = j + 1
                        break
            item_blocks.append(combined[start:end])
            idx = end

        # Skip patterns for non-event names
        skip_patterns = (
            "Next.", "Metadata", "$L", "$S", "I[", "HC[",
            "twitter:", "og:", "viewport", "robots", "googlebot",
            "Events Home", "Messi Banner", "Search",
            "Music Event", "Nightlife Event", "Comedy Event",
            "Sports Event", "Performances Event",
        )

        ui_labels = {
            "events", "featured events", "movies", "all events",
            "all movies", "today", "tomorrow", "this weekend",
        }

        events: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for block in item_blocks:
            # ── Type 1: VenueData — venue with next_event_details ──
            if '"VenueData":{' in block:
                # Extract venue name — it's the first "name" field right after VenueData
                venue_name_m = re.search(
                    r'"VenueData"\s*:\s*\{[^{]*?"name"\s*:\s*"([^"]+)"', block
                )
                if not venue_name_m:
                    continue
                venue_name = venue_name_m.group(1)

                # Extract next_event_details
                next_name_m = re.search(
                    r'"next_event_details"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', block
                )
                if not next_name_m:
                    continue  # Venue with no upcoming event
                event_name = next_name_m.group(1)

                next_date_m = re.search(
                    r'"next_event_details"\s*:\s*\{[^}]*"date_string"\s*:\s*"([^"]+)"', block
                )
                date_str = next_date_m.group(1).replace("\\u0026", "&") if next_date_m else ""

                addr_m = re.search(r'"address"\s*:\s*"([^"]+)"', block)
                desc_m = re.search(r'"description"\s*:\s*"([^"]+)"', block)

                # Guess city from address
                addr = addr_m.group(1) if addr_m else ""
                city = ""
                for c in ["Gurugram", "Gurgaon", "Noida", "Delhi", "Faridabad", "Ghaziabad"]:
                    if c.lower() in addr.lower():
                        city = "Gurugram" if c == "Gurgaon" else c
                        if city == "Delhi":
                            city = "Delhi/NCR"
                        break

                # Dedup by event_name+venue
                dedup_key = f"{event_name}|{venue_name}"
                if dedup_key in seen_names:
                    continue
                seen_names.add(dedup_key)

                events.append({
                    "title": event_name,
                    "venue": venue_name,
                    "city": city,
                    "locality": "",
                    "date": date_str,
                    "description": desc_m.group(1) if desc_m else "",
                    "tag_line": "",
                    "category": "",
                    "price": "",
                    "min_price": 0,
                    "rating": "",
                    "review_count": 0,
                    "image_url": "",
                    "image_gallery": [],
                    "video_url": "",
                    "url": "",
                    "start_epoch": 0,
                    "end_epoch": 0,
                    "is_activity": False,
                    "address": addr,
                    "offer_string": "",
                    "popularity_score": 0,
                    "number_attended": 0,
                    "distance": "",
                    "lat": "",
                    "long": "",
                    "date_string_v2": "",
                })
                continue

            # ── Type 2: EventData — full event with venue_name ──
            if '"EventData":{' not in block:
                continue  # Skip ArtistData, EditorialData, etc.

            # Extract name
            name_m = re.search(r'"name"\s*:\s*"([^"]{3,200})"', block)
            if not name_m:
                continue
            name = name_m.group(1)
            if name in seen_names:
                continue
            if name.lower() in ui_labels:
                continue
            if any(p in name for p in skip_patterns):
                continue
            seen_names.add(name)

            # Extract venue_name
            venue_m = re.search(r'"venue_name"\s*:\s*"([^"]+)"', block)
            venue = venue_m.group(1) if venue_m else ""

            # Extract city
            city_m = re.search(r'"city"\s*:\s*"([^"]+)"', block)
            city = city_m.group(1) if city_m else ""

            # Extract date — prefer next_event_date_string, fallback to date_string
            next_date_m = re.search(r'"next_event_date_string"\s*:\s*"([^"]+)"', block)
            date_m = re.search(r'"date_string"\s*:\s*"([^"]+)"', block)
            date_str = ""
            if next_date_m and next_date_m.group(1):
                date_str = next_date_m.group(1)
            elif date_m and date_m.group(1):
                date_str = date_m.group(1)

            # Extract date_string_v2 (alternate date format)
            date_v2_m = re.search(r'"date_string_v2"\s*:\s*"([^"]+)"', block)
            date_string_v2 = date_v2_m.group(1) if date_v2_m else ""

            # Extract description (lowercase = real description)
            desc_m = re.search(r'"description"\s*:\s*"([^"]{20,500})"', block)
            desc = desc_m.group(1) if desc_m else ""

            # Extract tag_line
            tag_m = re.search(r'"tag_line"\s*:\s*"([^"]+)"', block)
            tag_line = tag_m.group(1) if tag_m else ""

            # Extract event slug for URL
            slug_m = re.search(r'"event_slug"\s*:\s*"([^"]+)"', block)
            slug = slug_m.group(1) if slug_m else ""

            # Extract start_time_epoch for sorting
            epoch_m = re.search(r'"start_time_epoch"\s*:\s*"?(\\d+)"?', block)
            epoch = int(epoch_m.group(1)) if epoch_m else 0

            # Extract end_time_epoch for date filtering
            end_epoch_m = re.search(r'"end_time_epoch"\s*:\s*"?(\\d+)"?', block)
            end_epoch = int(end_epoch_m.group(1)) if end_epoch_m else 0

            # Extract locality
            locality_m = re.search(r'"locality"\s*:\s*"([^"]+)"', block)
            locality = locality_m.group(1) if locality_m else ""

            # Extract price
            price_m = re.search(r'"price_string"\s*:\s*"([^"]*)"', block)
            price = price_m.group(1) if price_m else ""
            min_price_m = re.search(r'"min_price"\s*:\s*"?(\d+)"?', block)
            min_price = int(min_price_m.group(1)) if min_price_m else 0

            # Extract rating
            rating_m = re.search(r'"rating"\s*:\s*"?([\d.]+)"?', block)
            rating = rating_m.group(1) if rating_m else ""
            review_m = re.search(r'"review_count"\s*:\s*"?(\d+)"?', block)
            review_count = int(review_m.group(1)) if review_m else 0

            # Extract image
            img_m = re.search(r'"(https://cdn\.district\.in/assets/events/[^"]+)"', block)
            if not img_m:
                img_m = re.search(r'"(https://media\.insider\.in/image/[^"]+)"', block)
            image_url = img_m.group(1) if img_m else ""

            # Extract image gallery (multiple image URLs)
            image_gallery: list[str] = []
            for g_m in re.finditer(r'"(https://cdn\.district\.in/assets/events/[^"]+)"', block):
                url = g_m.group(1)
                if url not in image_gallery:
                    image_gallery.append(url)
            for g_m in re.finditer(r'"(https://media\.insider\.in/image/[^"]+)"', block):
                url = g_m.group(1)
                if url not in image_gallery:
                    image_gallery.append(url)
            # If we only found one image, keep it as the gallery
            if not image_gallery and image_url:
                image_gallery = [image_url]

            # Extract video URL
            video_m = re.search(r'"(https://[^"]*(?:video|youtube|youtu\.be|vimeo)[^"]*)"', block, re.IGNORECASE)
            video_url = video_m.group(1) if video_m else ""

            # Extract is_activity flag (water parks, go-karting, arcades)
            is_activity_m = re.search(r'"is_activity"\s*:\s*(true|false)', block)
            is_activity = is_activity_m.group(1) == "true" if is_activity_m else False

            # Extract additional EventData fields
            offer_m = re.search(r'"offer_string"\s*:\s*"([^"]*)"', block)
            offer_string = offer_m.group(1) if offer_m else ""

            popularity_m = re.search(r'"popularity_score"\s*:\s*"?([\d.]+)"?', block)
            popularity_score = float(popularity_m.group(1)) if popularity_m else 0

            attended_m = re.search(r'"number_attended"\s*:\s*"?(\d+)"?', block)
            number_attended = int(attended_m.group(1)) if attended_m else 0

            distance_m = re.search(r'"distance"\s*:\s*"([^"]*)"', block)
            distance = distance_m.group(1) if distance_m else ""

            lat_m = re.search(r'"lat"\s*:\s*"?(-?[\d.]+)"?', block)
            lat = lat_m.group(1) if lat_m else ""

            long_m = re.search(r'"long"\s*:\s*"?(-?[\d.]+)"?', block)
            lng = long_m.group(1) if long_m else ""

            events.append({
                "title": name,
                "venue": venue,
                "city": city,
                "locality": locality,
                "date": date_str,
                "description": desc,
                "tag_line": tag_line,
                "category": "",
                "price": price,
                "min_price": min_price,
                "rating": rating,
                "review_count": review_count,
                "image_url": image_url,
                "image_gallery": image_gallery,
                "video_url": video_url,
                "url": f"{ep.DISTRICT_BASE}/events/{slug}-buy-tickets" if slug else "",
                "start_epoch": epoch,
                "end_epoch": end_epoch,
                "is_activity": is_activity,
                "address": "",
                "offer_string": offer_string,
                "popularity_score": popularity_score,
                "number_attended": number_attended,
                "distance": distance,
                "lat": lat,
                "long": lng,
                "date_string_v2": date_string_v2,
            })

        # Classify events
        for e in events:
            e["category"] = self._classify_event(e)

        # Sort by start_epoch (earliest first, 0 = unknown goes last)
        events.sort(key=lambda e: (e["start_epoch"] == 0, e["start_epoch"]))

        return events

    # ── Event classification ───────────────────────────────────────

    _CATEGORY_KEYWORDS: dict[str, list[str]] = {
        "Comedy": [
            "comedy", "standup", "stand up", "stand-up", "comics",
            "laugh", "joke", "punchline", "hideout", "foyer",
        ],
        "Live Music": [
            "live", "music", "band", "concert", "tour", "acoustic",
            "guitar", "vocal", "qawwal", "classical", "rap", "hip-hop",
            "hip hop", "singer", "artist", "krishna das", "zafrir",
            "afro", "supper club",
        ],
        "Party / Nightlife": [
            "party", "club", "dj", "night", "social", "block party",
            "ctrl", "apes", "room xo", "d-dion", "martini",
        ],
        "Food & Drink": [
            "brunch", "supper club", "culinary", "festival", "tasting",
            "aperitivo", "shaam", "anatolia", "turkish", "food",
            "indian shaam", "marièta", "cosy",
        ],
        "Theatre / Performance": [
            "theatrical", "theatre", "theater", "performance",
            "auditorium", "krishn",
        ],
        "Watch Party": [
            "watch party", "screening", "got latent",
        ],
    }

    def _classify_event(self, event: dict) -> str:
        """Classify an event into a category based on its text fields."""
        if event.get("is_activity", False):
            return "Activity / Adventure"

        text = " ".join([
            event.get("title", ""),
            event.get("venue", ""),
            event.get("tag_line", ""),
            event.get("description", ""),
        ]).lower()

        scores: dict[str, int] = {}
        for cat, keywords in self._CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scores[cat] = score

        if scores:
            return max(scores, key=scores.get)

        return "Other"

    def _filter_events_by_when(self, events: list[dict], when: str) -> list[dict]:
        """Filter events by date keyword or ISO date.

        Supports: 'today', 'tomorrow', 'weekend' (Sat-Sun),
        or a specific date like '2026-08-01'.
        """
        from datetime import datetime, timedelta, timezone

        # Use Indian timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)

        when_lower = when.lower().strip()

        if when_lower == "today":
            target_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            target_end = target_start + timedelta(days=1)
        elif when_lower == "tomorrow":
            target_start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            target_end = target_start + timedelta(days=1)
        elif when_lower == "weekend":
            # Find upcoming Saturday
            days_until_sat = (5 - now.weekday()) % 7
            if days_until_sat == 0 and now.weekday() == 5:
                # It's Saturday already
                days_until_sat = 0
            target_start = (now + timedelta(days=days_until_sat)).replace(hour=0, minute=0, second=0, microsecond=0)
            target_end = target_start + timedelta(days=2)  # Sat + Sun
        else:
            # Try parsing as YYYY-MM-DD
            try:
                target_start = datetime.strptime(when, "%Y-%m-%d").replace(tzinfo=ist)
                target_end = target_start + timedelta(days=1)
            except ValueError:
                return events  # Invalid date format — return unfiltered

        target_start_ts = target_start.timestamp()
        target_end_ts = target_end.timestamp()

        filtered = []
        for e in events:
            start = self._to_float(e.get("start_epoch"))
            end = self._to_float(e.get("end_epoch"))
            if start == 0:
                date_str = str(e.get("date", "")).lower().strip()

                # Venue rails commonly use human strings such as
                # "10 Jan 2026 • 9:00 PM" rather than epochs.
                date_part = re.split(r"\s*[•·|]\s*", date_str, maxsplit=1)[0].strip()
                parsed_date = None
                for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"):
                    try:
                        parsed_date = datetime.strptime(date_part.title(), fmt).replace(tzinfo=ist)
                        break
                    except ValueError:
                        continue
                if parsed_date is not None:
                    event_end = parsed_date + timedelta(days=1)
                    if parsed_date < target_end and event_end > target_start:
                        filtered.append(e)
                    continue

                # Recurring venue events ("Every Sat" / "Every Sunday")
                # apply when the requested target range contains that weekday.
                recurring_weekdays = set()
                if "sat" in date_str:
                    recurring_weekdays.add(5)
                if "sun" in date_str:
                    recurring_weekdays.add(6)
                if recurring_weekdays:
                    cursor = target_start
                    while cursor < target_end:
                        if cursor.weekday() in recurring_weekdays:
                            filtered.append(e)
                            break
                        cursor += timedelta(days=1)
                    continue

                if when_lower == "today" and "today" in date_str:
                    filtered.append(e)
                elif when_lower == "tomorrow" and "tomorrow" in date_str:
                    filtered.append(e)
                elif when_lower == "weekend" and "weekend" in date_str:
                    filtered.append(e)
                continue
            if end == 0:
                end = start + 86400  # Assume 24h if no end
            # Event overlaps with target date range
            if start < target_end_ts and end > target_start_ts:
                filtered.append(e)

        return filtered

    def get_restaurant_events(
        self,
        city: str = "gurugram",
        when: str = "today",
        query: str = "",
        nightlife_only: bool = False,
        category: str = "",
    ) -> list[dict]:
        """Get restaurants that have events on a given day.

        Groups District events by venue and returns a list of restaurants
        with their upcoming events.

        Args:
            city: Filter by city (empty = all cities)
            when: 'today', 'tomorrow', 'weekend', or 'YYYY-MM-DD'
            query: Optional keyword filter (e.g. 'sufi', 'live', 'comedy')
            nightlife_only: Exclude activities (water parks, go-karting, arcades)
            category: Filter by classified category (comedy, live music, party, etc.)

        Returns list of dicts with keys: restaurant, locality, city, events (list).
        """
        events = self.get_events(city=city, when=when)
        if nightlife_only:
            events = [e for e in events if not e.get("is_activity", False)]
        if category:
            cat_lower = category.lower()
            events = [e for e in events if cat_lower in e.get("category", "").lower()]
        if query:
            q = query.lower()
            events = [
                e for e in events
                if q in e.get("title", "").lower()
                or q in e.get("venue", "").lower()
                or q in e.get("description", "").lower()
                or q in e.get("tag_line", "").lower()
            ]

        # Group by venue
        by_venue: dict[str, dict] = {}
        for e in events:
            venue = e.get("venue", "") or "Unknown"
            if venue not in by_venue:
                by_venue[venue] = {
                    "restaurant": venue,
                    "locality": e.get("locality", ""),
                    "city": e.get("city", ""),
                    "address": e.get("address", ""),
                    "events": [],
                }
            by_venue[venue]["events"].append({
                "title": e.get("title", ""),
                "date": e.get("date", ""),
                "price": e.get("price", ""),
                "tag_line": e.get("tag_line", ""),
                "category": e.get("category", ""),
                "url": e.get("url", ""),
            })

        return list(by_venue.values())

    def get_dining_slots(self, res_id: int, date: str = "") -> dict:
        """Get available dining time slots for a restaurant."""
        return self._get(ep.DINING_SLOTS, params={
            "res_id": res_id,
            "date": date,
        })

    # ── Restaurant search by name ─────────────────────────────────

    def find_restaurant_by_url(self, url_slug: str) -> dict | None:
        """Find a restaurant by its Zomato URL slug.

        Args:
            url_slug: e.g. 'ncr/avatar-sector-58-gurgaon' or full URL

        Returns:
            Restaurant dict (from get_restaurant) or None if not found.
        """
        slug = url_slug.lstrip("/")
        if slug.startswith("https://"):
            # Full URL — extract the path
            from urllib.parse import urlparse
            parsed = urlparse(url_slug)
            slug = parsed.path.lstrip("/")

        # Fetch the HTML page to extract resId
        resp = self._session.get(
            f"{ep.ZOMATO_BASE}/{slug}",
            headers={"Accept": "text/html, */*"},
            cookies=self._cookies(),
        )
        if resp.status_code != 200:
            return None
        html = resp.text
        # Extract resId from the page
        match = re.search(r'"resId"\s*:\s*(\d{5,})', html)
        if not match:
            match = re.search(r'resId["\s:=]+(\d{5,})', html)
        if not match:
            return None
        res_id = int(match.group(1))
        return self.get_restaurant(res_id)

    def search_restaurant_by_name(self, name: str, city: str = "gurugram") -> list[dict]:
        """Search for restaurants by name on Zomato.

        Uses the getPage endpoint to search for restaurants matching the name.
        Returns list of restaurant dicts with resId, name, rating, etc.

        Args:
            name: Restaurant name (e.g. 'Avatar')
            city: City slug for search context

        Returns:
            List of matching restaurants with basic info.
        """
        # Try the getPage endpoint with the search query
        data = self._get(ep.GET_PAGE, params={
            "url": f"/{city}/restaurants?q={urllib.parse.quote(name)}",
            "lat": self.location.lat,
            "lng": self.location.lng,
        })
        sections = data.get("page_data", {}).get("sections", {})
        results = sections.get("SECTION_SEARCH_RESULT", [])
        restaurants = []
        for r in results:
            if isinstance(r, dict):
                parsed = self._parse_restaurant(r)
                if name.lower() in parsed.get("name", "").lower():
                    restaurants.append(parsed)
        return restaurants

    def get_dining_offers(self, res_id: int) -> list[dict]:
        """Get dining offers for a restaurant from its Zomato page.

        This is different from get_restaurant_offers() which uses the order/resOffer
        endpoint. This method extracts dining offers (time-limited discounts)
        from the restaurant/info endpoint's SECTION_DINING_OFFERS.

        Args:
            res_id: Zomato restaurant ID

        Returns:
            List of offer dicts with title, subtitle, start_time, end_time,
            offer_value, offer_type.
        """
        data = self._get(ep.RESTAURANT_INFO, params={"res_id": res_id})
        sections = data.get("page_data", {}).get("sections", {})

        offers: list[dict] = []
        # SECTION_DINING_OFFERS is a list
        raw_offers = sections.get("SECTION_DINING_OFFERS", [])
        if isinstance(raw_offers, list):
            for o in raw_offers:
                if not isinstance(o, dict):
                    continue
                offers.append({
                    "title": o.get("title", "").replace("\n", " "),
                    "subtitle": o.get("subtitle", "").replace("\n", " "),
                    "start_time": o.get("start_time", ""),
                    "end_time": o.get("end_time", ""),
                    "offer_value": o.get("offer_value", 0),
                    "offer_type": o.get("offerType", ""),
                })

        # Also check V2 offers
        v2 = sections.get("SECTION_DINING_OFFERS_V2", {})
        if isinstance(v2, dict):
            v2_offers = v2.get("offers", [])
            if isinstance(v2_offers, list):
                for o in v2_offers:
                    if not isinstance(o, dict):
                        continue
                    heading = o.get("heading", "")
                    offers.append({
                        "title": o.get("title", "").replace("\n", " "),
                        "subtitle": o.get("subtitle", "").replace("\n", " "),
                        "start_time": o.get("start_time", ""),
                        "end_time": o.get("end_time", ""),
                        "offer_value": o.get("offer_value", 0),
                        "offer_type": o.get("offerType", ""),
                        "heading": heading,
                    })

        return offers

    def find_party_places(
        self,
        lat: float | None = None,
        lng: float | None = None,
        radius_km: float = 15,
        when: str = "weekend",
        include_offers: bool = True,
        crawl_details: bool = True,
    ) -> list[dict]:
        """Find party places near a location.

        Combines District events with Zomato restaurant data and dining offers.
        Sorts by distance from the user's location.

        Args:
            lat/lng: User location (defaults to client location)
            radius_km: Max distance in km (default 15)
            when: Date filter for events
            include_offers: Include dining offers from Zomato
            crawl_details: Crawl individual District venue/event pages and
                enrich results with descriptions, organizers, and ticket offers

        Returns:
            List of dicts with: name, rating, address, distance_km,
            events (list), offers (list), source ('district' or 'zomato')
        """
        if lat is None:
            lat = self.location.lat
        if lng is None:
            lng = self.location.lng

        results: list[dict] = []

        # 1. Get District events (nightlife only)
        events = self.get_events(city="", when=when)
        nightlife = [e for e in events if not e.get("is_activity", False)]

        # Crawl individual venue/event pages and use their schema.org data to
        # enrich the cards returned by the main listing page.
        detail_candidates_by_name: dict[str, list[dict]] = defaultdict(list)
        detail_by_url: dict[str, dict] = {}
        detail_by_identity: dict[tuple[str, str], dict] = {}
        venue_detail_by_name: dict[str, dict] = {}
        if crawl_details:
            try:
                crawl = self.crawl_individual_pages(
                    include_events=True,
                    include_venues=True,
                    include_zomato_details=False,
                    max_pages=50,
                    city=self.location.city_name.lower(),
                )
                for page in crawl.get("events", []):
                    schema = page.get("schema_event")
                    if isinstance(schema, dict):
                        normalized_name = page.get("name", "").strip().lower()
                        if normalized_name:
                            detail_candidates_by_name[normalized_name].append(schema)
                        page_url = page.get("url", "").rstrip("/")
                        if page_url:
                            detail_by_url[page_url] = schema
                        location = schema.get("location", {})
                        location_name = location.get("name", "") if isinstance(location, dict) else ""
                        if normalized_name and location_name:
                            detail_by_identity[(normalized_name, location_name.strip().lower())] = schema

                # Venue pages expose additional event rails that are missing
                # from the main discovery listing. Convert them into the same
                # event structure and merge them before date filtering.
                venue_events: list[dict] = []
                for page in crawl.get("venues", []):
                    venue_data = page.get("venue_data")
                    if not isinstance(venue_data, dict) or not venue_data:
                        continue
                    venue_name = venue_data.get("name", page.get("name", ""))
                    venue_detail_by_name[venue_name.strip().lower()] = venue_data
                    rails = venue_data.get("venue_page_rails") or venue_data.get("venue_events_by_categories") or []
                    for rail in rails if isinstance(rails, list) else []:
                        for item in rail.get("items", []) if isinstance(rail, dict) else []:
                            if not isinstance(item, dict):
                                continue
                            title = item.get("label", "")
                            if not title:
                                continue
                            event = {
                                "title": title,
                                "venue": venue_name,
                                "city": self.location.city_name,
                                "locality": "",
                                "date": item.get("date_time", ""),
                                "description": venue_data.get("description", ""),
                                "tag_line": venue_data.get("tagline", ""),
                                "price": item.get("price", ""),
                                "category": item.get("category", ""),
                                "url": f"{ep.DISTRICT_BASE}/events/{item.get('slug')}-buy-tickets" if item.get("slug") else "",
                                "start_epoch": 0,
                                "end_epoch": 0,
                                "is_activity": False,
                                "address": venue_data.get("address", ""),
                                "lat": venue_data.get("latitude", 0),
                                "long": venue_data.get("longitude", 0),
                            }
                            if not event["category"]:
                                event["category"] = self._classify_event(event)
                            venue_events.append(event)

                if when:
                    venue_events = self._filter_events_by_when(venue_events, when)
                seen = {
                    (e.get("title", "").strip().lower(), e.get("venue", "").strip().lower())
                    for e in nightlife
                }
                for event in venue_events:
                    key = (event.get("title", "").strip().lower(), event.get("venue", "").strip().lower())
                    if key not in seen:
                        nightlife.append(event)
                        seen.add(key)
            except Exception:
                # Keep any enrichment collected before a malformed or failed
                # page; main-feed discovery remains usable.
                pass

        # Group by venue and add distance
        by_venue: dict[str, dict] = {}
        for e in nightlife:
            venue = e.get("venue", "") or "Unknown"
            venue_detail = venue_detail_by_name.get(venue.strip().lower(), {})
            e_lat = self._to_float(e.get("lat") or venue_detail.get("latitude"))
            e_lng = self._to_float(e.get("long") or venue_detail.get("longitude"))
            dist = 0
            if e_lat and e_lng:
                dist = self._haversine(lat, lng, e_lat, e_lng)
            if dist > radius_km:
                continue
            if venue not in by_venue:
                by_venue[venue] = {
                    "name": venue,
                    "address": e.get("address", "") or venue_detail.get("address", ""),
                    "city": e.get("city", ""),
                    "locality": e.get("locality", ""),
                    "lat": e_lat,
                    "lng": e_lng,
                    "distance_km": round(dist, 1),
                    "events": [],
                    "offers": [],
                    "venue_details": venue_detail,
                    "source": "district",
                }
            normalized_title = e.get("title", "").strip().lower()
            normalized_venue = venue.strip().lower()
            name_candidates = detail_candidates_by_name.get(normalized_title, [])
            name_detail = name_candidates[0] if len(name_candidates) == 1 else {}
            detail = (
                detail_by_url.get(e.get("url", "").rstrip("/"))
                or detail_by_identity.get((normalized_title, normalized_venue))
                or name_detail
            )
            organizer = detail.get("organizer", {}) if isinstance(detail, dict) else {}
            location_detail = detail.get("location", {}) if isinstance(detail, dict) else {}
            ticket_offer = detail.get("offers", {}) if isinstance(detail, dict) else {}
            by_venue[venue]["events"].append({
                "title": e.get("title", ""),
                "date": e.get("date", ""),
                "price": e.get("price", ""),
                "category": e.get("category", ""),
                "url": e.get("url", ""),
                "description": detail.get("description", e.get("description", "")) if isinstance(detail, dict) else e.get("description", ""),
                "organizer": organizer.get("name", "") if isinstance(organizer, dict) else "",
                "start_date": detail.get("startDate", "") if isinstance(detail, dict) else "",
                "end_date": detail.get("endDate", "") if isinstance(detail, dict) else "",
                "ticket_offer": ticket_offer if isinstance(ticket_offer, (dict, list)) else {},
                "detail_location": location_detail if isinstance(location_detail, dict) else {},
                "detail_crawled": bool(detail),
            })

        results.extend(by_venue.values())

        # 2. Search Zomato nightlife restaurants in the area
        # This catches bars/clubs not listed on District.in
        try:
            restaurants = self.search_restaurants(
                city=self.location.city_name.lower() if hasattr(self.location, 'city_name') else "gurugram",
                context="nightlife",
            )
            for r in restaurants:
                name = r.get("name", "")
                if not name:
                    continue
                # Check if already found via District
                if any(name.lower() in v.get("name", "").lower() for v in results):
                    continue
                results.append({
                    "name": name,
                    "address": "",
                    "city": self.location.city_name,
                    "locality": r.get("locality", ""),
                    "lat": 0,
                    "lng": 0,
                    "distance_km": 0,
                    "rating": r.get("rating", ""),
                    "events": [],
                    "offers": [],
                    "source": "zomato",
                    "res_id": r.get("resId"),
                })
        except Exception:
            pass

        # 3. Get dining offers for Zomato restaurants
        if include_offers:
            for r in results:
                res_id = r.get("res_id")
                if res_id and not r.get("offers"):
                    try:
                        r["offers"] = self.get_dining_offers(res_id)
                    except Exception:
                        pass

        # Sort by distance (0 = unknown, goes last)
        results.sort(key=lambda x: (x["distance_km"] == 0, x["distance_km"]))

        return results

    @staticmethod
    def _district_http_get(
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        timeout: int = 15,
        retries: int = 2,
    ) -> requests.Response:
        """Thread-safe District GET with bounded retry/backoff for 429/5xx."""
        response: requests.Response | None = None
        for attempt in range(retries + 1):
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            if response.status_code != 429 and response.status_code < 500:
                return response
            if attempt < retries:
                time.sleep(0.5 * (2 ** attempt))
        assert response is not None
        return response

    def _get_district_events_html(self, cache_seconds: int = 60) -> str:
        """Fetch the discovery page once and briefly reuse it across crawl phases."""
        cached_at = getattr(self, "_district_events_cached_at", 0.0)
        cached_html = getattr(self, "_district_events_cached_html", "")
        if cached_html and time.time() - cached_at < cache_seconds:
            return cached_html
        url = f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}"
        response = self._district_http_get(
            url,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        self._district_events_cached_html = response.text
        self._district_events_cached_at = time.time()
        return response.text

    def get_district_venue_by_slug(self, slug: str) -> dict:
        """Fetch a District venue page through its client-side venue API.

        District's venue-guide HTML sets ``shouldFetchOnClient=true``. The
        browser then calls this endpoint with a guest token and standard web
        client headers. It returns venue details, event rails, opening hours,
        coordinates, policies, facilities, gallery and linked dining menus.
        """
        url = f"{ep.DISTRICT_BASE}{ep.DISTRICT_VENUE_PAGE}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "x-app-type": ep.DISTRICT_WEB_APP_TYPE,
            "x-client-id": ep.DISTRICT_WEB_CLIENT_ID,
            "x-app-version": ep.DISTRICT_WEB_APP_VERSION,
            "Referer": f"{ep.DISTRICT_BASE}/events/{slug}/venue-guide",
        }
        access_token = os.getenv("DISTRICT_ACCESS_TOKEN", "")
        refresh_token = os.getenv("DISTRICT_REFRESH_TOKEN", "")
        if access_token:
            headers["x-access-token"] = access_token
            if refresh_token:
                headers["x-refresh-token"] = refresh_token
        else:
            headers["x-guest-token"] = os.getenv(
                "DISTRICT_GUEST_TOKEN", ep.DISTRICT_GUEST_TOKEN
            )
        response = self._district_http_get(
            url,
            params={"venue_slug": slug},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("status") == "STATUS_FAILURE":
            raise ZomatoAPIError(data.get("message", "District venue API failed"))
        return data if isinstance(data, dict) else {}

    def crawl_individual_pages(
        self,
        include_events: bool = True,
        include_venues: bool = True,
        include_zomato_details: bool = True,
        max_pages: int = 50,
        city: str = "gurugram",
    ) -> dict:
        """Crawl individual District venue/event pages and cross-reference Zomato.

        Starts from District.in's main events page, extracts all venue and event
        slugs, then visits every individual page. District's individual pages
        currently load their detail data client-side, so the crawler records
        whether useful RSC data was found. Venue names are cross-referenced with
        Zomato to fetch ratings, offers, reviews, and other restaurant details.

        Args:
            include_events: Crawl individual event pages
            include_venues: Crawl individual venue pages
            include_zomato_details: Cross-reference venue names on Zomato
            max_pages: Maximum total pages to crawl
            city: Zomato city context for restaurant search

        Returns:
            Dict with keys: venues, events, stats
        """
        import concurrent.futures

        # Reuse the discovery HTML already fetched by get_events() when this
        # crawl is part of find_party_places().
        html = self._get_district_events_html()

        # Extract combined RSC data using the same logic as _parse_district_events
        combined = self._extract_district_rsc(html)

        # Extract ItemDetails blocks
        item_blocks: list[str] = []
        idx = 0
        while True:
            pos = combined.find('"ItemDetails":{', idx)
            if pos < 0:
                break
            brace_count = 0
            start = pos + len('"ItemDetails":')
            end = start
            for j in range(start, min(start + 20000, len(combined))):
                if combined[j] == '{':
                    brace_count += 1
                elif combined[j] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = j + 1
                        break
            item_blocks.append(combined[start:end])
            idx = end

        # Extract unique venue and event slugs
        venue_map: dict[str, str] = {}
        event_map: dict[str, str] = {}
        for block in item_blocks:
            if '"VenueData":{' in block:
                slug_m = re.search(r'"slug"\s*:\s*"([^"]+)"', block)
                name_m = re.search(
                    r'"VenueData"\s*:\s*\{[^{]*?"name"\s*:\s*"([^"]+)"', block
                )
                if slug_m:
                    venue_map[slug_m.group(1)] = name_m.group(1) if name_m else ""
            if '"EventData":{' in block:
                slug_m = re.search(r'"event_slug"\s*:\s*"([^"]+)"', block)
                name_m = re.search(r'"name"\s*:\s*"([^"]{3,200})"', block)
                if slug_m:
                    event_map[slug_m.group(1)] = name_m.group(1) if name_m else ""

        # Reserve crawl budget across venue guides and event detail pages.
        max_pages = max(0, int(max_pages))
        venue_items = list(venue_map.items()) if include_venues else []
        event_items = list(event_map.items()) if include_events else []
        if max_pages == 0:
            venue_budget = 0
        elif include_events and venue_items:
            venue_budget = min(len(venue_items), max(1, max_pages // 3))
        else:
            venue_budget = min(len(venue_items), max_pages)
        venue_items = venue_items[:venue_budget]

        def crawl_page(item: tuple[str, str], page_type: str) -> dict:
            slug, name = item
            if page_type == "event":
                url = f"{ep.DISTRICT_BASE}/events/{slug}-buy-tickets"
            else:
                url = f"{ep.DISTRICT_BASE}/events/{slug}/venue-guide"
            try:
                r = self._district_http_get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                )
                if r.status_code >= 400:
                    return {
                        "slug": slug,
                        "name": name,
                        "url": url,
                        "status": "not_found" if r.status_code == 404 else "error",
                        "http_status": r.status_code,
                        "error": "" if r.status_code == 404 else f"HTTP {r.status_code}",
                        "events": [],
                    }
                page_html = r.text
                rsc = self._extract_district_rsc(page_html)
                parsed_events = self._parse_district_events(page_html)
                venue_data: dict = {}
                if page_type == "venue" and r.status_code < 400:
                    try:
                        venue_data = self.get_district_venue_by_slug(slug)
                    except Exception:
                        venue_data = {}

                # Event detail pages expose rich schema.org JSON-LD even when
                # ItemDetails is absent. Parse it as the canonical detail source.
                json_ld_items: list[dict] = []
                for match in re.finditer(
                    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                    page_html,
                    re.DOTALL | re.IGNORECASE,
                ):
                    try:
                        value = json.loads(match.group(1))
                        if isinstance(value, dict):
                            json_ld_items.append(value)
                        elif isinstance(value, list):
                            json_ld_items.extend(x for x in value if isinstance(x, dict))
                    except (json.JSONDecodeError, TypeError):
                        continue

                event_schema = next(
                    (
                        item for item in json_ld_items
                        if item.get("@type") == "Event"
                        or (
                            isinstance(item.get("@type"), list)
                            and "Event" in item.get("@type", [])
                        )
                    ),
                    None,
                )
                has_detail_data = bool(
                    venue_data or parsed_events or event_schema
                    or "EventData" in rsc or "ItemDetails" in rsc
                )
                return {
                    "slug": slug,
                    "name": name,
                    "url": url,
                    "status": "ok",
                    "http_status": r.status_code,
                    "page_size": len(page_html),
                    "rsc_size": len(rsc),
                    "has_event_data": has_detail_data,
                    "events": parsed_events,
                    "venue_data": venue_data,
                    "schema_event": event_schema,
                    "json_ld": json_ld_items,
                    "client_side_only": not has_detail_data,
                }
            except Exception as exc:
                return {
                    "slug": slug,
                    "name": name,
                    "url": url,
                    "status": "error",
                    "error": str(exc),
                    "events": [],
                }

        # Phase 1: crawl a bounded share of venue pages. Their client API may
        # reveal event slugs absent from the main discovery page.
        venue_results: list[dict] = []
        event_results: list[dict] = []
        if venue_items:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                venue_results = list(
                    executor.map(lambda item: crawl_page(item, "venue"), venue_items)
                )

        venue_event_map: dict[str, str] = {}
        if include_events:
            for venue in venue_results:
                venue_data = venue.get("venue_data", {})
                if not isinstance(venue_data, dict):
                    continue
                rails = venue_data.get("venue_page_rails") or venue_data.get("venue_events_by_categories") or []
                for rail in rails if isinstance(rails, list) else []:
                    for item in rail.get("items", []) if isinstance(rail, dict) else []:
                        if isinstance(item, dict) and item.get("slug"):
                            venue_event_map[item["slug"]] = item.get("label", "")

        # Phase 2: prioritize venue-only discoveries, then fill the remaining
        # budget with event slugs already present on the main page.
        combined_event_map = dict(venue_event_map)
        combined_event_map.update(
            {slug: name for slug, name in event_items if slug not in combined_event_map}
        )
        remaining_budget = max(0, max_pages - len(venue_results))
        selected_events = (
            list(combined_event_map.items())[:remaining_budget]
            if include_events
            else []
        )
        if selected_events:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                event_results = list(
                    executor.map(lambda item: crawl_page(item, "event"), selected_events)
                )

        # Cross-reference venue names on Zomato
        if include_zomato_details:
            for venue in venue_results:
                name = venue.get("name", "")
                if not name:
                    continue
                try:
                    matches = self.search_restaurant_by_name(name, city=city)
                    venue["zomato_matches"] = matches
                    if matches:
                        best = matches[0]
                        res_id = best.get("resId")
                        if res_id:
                            venue["zomato_details"] = self.get_restaurant(int(res_id))
                            venue["dining_offers"] = self.get_dining_offers(int(res_id))
                    else:
                        venue["zomato_details"] = None
                        venue["dining_offers"] = []
                except Exception as exc:
                    venue["zomato_error"] = str(exc)
                    venue["zomato_matches"] = []

        # Sort for deterministic output
        venue_results.sort(key=lambda x: x.get("name", ""))
        event_results.sort(key=lambda x: x.get("name", ""))

        return {
            "venues": venue_results,
            "events": event_results,
            "stats": {
                "venue_slugs_found": len(venue_map),
                "event_slugs_found": len(set(event_map) | set(venue_event_map)),
                "main_page_event_slugs_found": len(event_map),
                "venue_page_event_slugs_found": len(venue_event_map),
                "venue_pages_crawled": len(venue_results),
                "event_pages_crawled": len(event_results),
                "pages_with_embedded_data": sum(
                    1 for x in venue_results + event_results
                    if x.get("has_event_data")
                ),
                "client_side_only_pages": sum(
                    1 for x in venue_results + event_results
                    if x.get("client_side_only")
                ),
            },
        }

    def _extract_district_rsc(self, html: str) -> str:
        """Extract and unescape all Next.js RSC push payloads from HTML."""
        push_starts = [
            m.start() for m in re.finditer(r'self\.__next_f\.push\(\[1,"', html)
        ]
        combined = ""
        for start in push_starts:
            content_start = html.find('[1,"', start) + 4
            if content_start < 4:
                continue
            script_end = html.find("</script>", content_start)
            if script_end < 0:
                continue
            push_end = html.rfind('"])', content_start, script_end)
            if push_end < 0:
                push_end = html.rfind('")', content_start, script_end)
            if push_end < 0:
                continue
            chunk = html[content_start:push_end]
            unescaped = (
                chunk.replace('\\\\"', '"')
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )
            combined += unescaped
        return combined

    @staticmethod
    def _to_float(value: Any) -> float:
        """Convert API coordinate values safely; malformed values become zero."""
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """Calculate distance between two lat/lng points in km."""
        import math
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    # ── Utility ──────────────────────────────────────────────────

    def set_location(self, city: str | None = None, lat: float | None = None, lng: float | None = None):
        """Update the client's location for subsequent API calls."""
        if city:
            city_lower = city.lower().replace(" ", "")
            if city_lower in CITY_IDS:
                self.location.city_id = CITY_IDS[city_lower]
                self.location.city_name = city.title()
        if lat is not None:
            self.location.lat = lat
        if lng is not None:
            self.location.lng = lng