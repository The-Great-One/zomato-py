"""Zomato web API client.

Reverse-engineered from Zomato's web frontend. Handles CSRF token
acquisition, session cookies, and the locus location cookie that
Zomato uses to determine the user's city.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

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
        return self._csrf

    def _cookies(self) -> dict[str, str]:
        """Build the cookie dict including the locus location cookie."""
        cookies = dict(self._session.cookies)
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
    ) -> list[dict]:
        """Search for restaurants in a city.

        Args:
            city: City name slug (e.g. 'gurugram', 'delhi', 'mumbai')
            context: 'delivery', 'dineout', or 'nightlife'
            lat/lng: Override location coordinates

        Returns list of restaurant dicts with keys:
            resId, name, cuisine, rating, rating_text, cost_for_two,
            image_url, url, locality, is_promoted
        """
        # Update location to match the city being searched
        city_lower = city.lower().replace(" ", "")
        if city_lower in CITY_IDS:
            self.location.city_id = CITY_IDS[city_lower]
            self.location.city_name = city.title()

        if lat is None:
            lat = self.location.lat
        if lng is None:
            lng = self.location.lng

        url_path = f"/{city}/restaurants"
        if context == "delivery":
            url_path = f"/{city}/restaurants?order-online=1"
        elif context == "dineout":
            url_path = f"/{city}/dine-out"
        elif context == "nightlife":
            url_path = f"/{city}/nightlife"

        data = self._get(ep.GET_PAGE, params={
            "url": url_path,
            "lat": lat,
            "lng": lng,
        })

        sections = data.get("page_data", {}).get("sections", {})
        results = sections.get("SECTION_SEARCH_RESULT", [])
        return [self._parse_restaurant(r) for r in results if isinstance(r, dict)]

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

    # ── Public API: Reviews ───────────────────────────────────────

    def get_reviews(
        self,
        res_id: int,
        offset: int = 0,
        limit: int = 10,
        sort: str = "",
    ) -> list[dict]:
        """Get restaurant reviews.

        Returns list of review dicts with keys: rating, text, user_name,
        user_id, timestamp, likes, comments_count.
        """
        params: dict[str, Any] = {
            "res_id": res_id,
            "offset": offset,
            "limit": limit,
        }
        if sort:
            params["sort"] = sort

        data = self._get(ep.REVIEWS_LOAD_MORE, params=params)
        sections = data.get("page_data", {}).get("sections", {})
        entities = sections.get("SECTION_REVIEW", {})

        reviews = []
        if isinstance(entities, dict):
            for key, review in entities.items():
                if not isinstance(review, dict):
                    continue
                reviews.append(self._parse_review(review))
        elif isinstance(entities, list):
            for review in entities:
                if isinstance(review, dict):
                    reviews.append(self._parse_review(review))
        return reviews

    def _parse_review(self, raw: dict) -> dict:
        """Parse a raw review entity."""
        return {
            "review_id": raw.get("id", ""),
            "rating": raw.get("rating", "0"),
            "rating_text": raw.get("ratingText", ""),
            "text": raw.get("reviewText", ""),
            "user_name": raw.get("userName", ""),
            "user_id": raw.get("userId", ""),
            "timestamp": raw.get("timestamp", ""),
            "likes": raw.get("likesCount", 0),
            "comments_count": raw.get("commentsCount", 0),
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
    ) -> list[dict]:
        """Get events from District by Zomato.

        Scrapes the District events page (Next.js RSC) and extracts
        event data including titles, venues, cities, and categories.

        Returns list of event dicts with keys: title, venue, city,
        category, image_url, url.
        """
        url = f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}"
        resp = self._session.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        html = resp.text

        events = self._parse_district_events(html)

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
        We extract the RSC payload, unescape it, and parse event data.
        """
        # Extract all __next_f pushes by finding script boundaries
        # The regex (.*?) fails on escaped quotes inside pushes, so we
        # extract by finding each push and its closing </script> tag.
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
                chunk.replace('\\\\"', '"')
                .replace('\\"', '"')
                .replace("\\n", "\n")
                .replace("\\\\", "\\")
            )
            combined += unescaped

        # Extract event data from the RSC payload
        # District uses "name" for event/restaurant names and "title" for UI section headers
        events = []

        # Find all event names — these are in "name" fields within ItemDetails/EditorialData
        # Pattern: "name":"Event Name" where the name is not a UI label
        name_pattern = re.findall(
            r'"name"\s*:\s*"([^"]{3,200})"', combined
        )

        # Find venue names
        venue_pattern = re.findall(
            r'"venue_name"\s*:\s*"([^"]+)"', combined
        )

        # Find cities — District uses "city" field (not "city_name")
        city_pattern = re.findall(
            r'"city"\s*:\s*"([^"]+)"', combined
        )

        # Find category/genre info
        genre_pattern = re.findall(
            r'"genre"\s*:\s*"([^"]+)"', combined
        )

        # Find image URLs
        image_pattern = re.findall(
            r'"(https://cdn\.district\.in/assets/events/[^"]+)"',
            combined,
        )

        # Find event URLs
        url_pattern = re.findall(
            r'"(/event/[^"]+)"', combined
        )

        # UI label titles to exclude (these are section headers, not event names)
        ui_labels = {
            "featured events", "explore events",
            "happening at venues near you",
            "offers for you", "today", "tomorrow",
            "this weekend", "happening around you",
            "artists in your district", "all events",
            "events", "movies", "all movies",
            "city tours", "historical tours", "tours",
            "food & drink", "comedy shows", "music shows",
            "workshops", "kids", "amusement parks",
            "district offer logged out after 3 new designs",
        }

        # Patterns that indicate a non-event name (Next.js components, metadata, SEO tags)
        skip_patterns = (
            "Next.", "Metadata", "$L", "$S", "I[", "HC[",
            "default", "props", "children",
            "twitter:", "og:", "description", "image", "url",
            "schema", "ItemList", "AggregateRating",
            "application/ld+json", "dangerouslySetInnerHTML",
            "District by Zomato", "Get Upcoming Events",
            "googlebot", "robots", "viewport", "referrer",
            "content-type", "X-UA-Compatible", "charset",
            "width=device-width", "application/json",
            "stylesheet", "preconnect", "prefetch",
            "noopener", "noreferrer", "dns-prefetch",
            "EditURI", "wlwmanifest", "canonical",
            "shortlink", "pingback",
        )

        # Combine all data points
        max_len = max(
            len(name_pattern),
            len(venue_pattern),
            len(city_pattern),
            1,
        )

        seen_names = set()
        for i in range(max_len):
            name = name_pattern[i] if i < len(name_pattern) else ""
            if not name or name in seen_names:
                continue
            # Skip UI labels and non-event names
            if name.lower() in ui_labels:
                continue
            # Skip Next.js component/metadata names
            if any(p in name for p in skip_patterns):
                continue
            seen_names.add(name)

            event: dict[str, Any] = {
                "title": name,
                "venue": venue_pattern[i] if i < len(venue_pattern) else "",
                "city": city_pattern[i] if i < len(city_pattern) else "",
                "category": genre_pattern[i] if i < len(genre_pattern) else "",
                "image_url": image_pattern[i] if i < len(image_pattern) else "",
                "url": f"{ep.DISTRICT_BASE}{url_pattern[i]}" if i < len(url_pattern) else "",
            }
            events.append(event)

        return events

    # ── Public API: Dining ────────────────────────────────────────

    def get_dining_slots(self, res_id: int, date: str = "") -> dict:
        """Get available dining time slots for a restaurant."""
        return self._get(ep.DINING_SLOTS, params={
            "res_id": res_id,
            "date": date,
        })

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