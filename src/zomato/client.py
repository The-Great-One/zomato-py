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
        url = f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}"
        resp = self._session.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        html = resp.text

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
                chunk.replace('\\\\"', '"')
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
            epoch_m = re.search(r'"start_time_epoch"\s*:\s*"?(\d+)"?', block)
            epoch = int(epoch_m.group(1)) if epoch_m else 0

            # Extract end_time_epoch for date filtering
            end_epoch_m = re.search(r'"end_time_epoch"\s*:\s*"?(\d+)"?', block)
            end_epoch = int(end_epoch_m.group(1)) if end_epoch_m else 0

            # Extract image
            img_m = re.search(r'"(https://cdn\.district\.in/assets/events/[^"]+)"', block)
            if not img_m:
                img_m = re.search(r'"(https://media\.insider\.in/image/[^"]+)"', block)
            image_url = img_m.group(1) if img_m else ""

            events.append({
                "title": name,
                "venue": venue,
                "city": city,
                "date": date_str,
                "description": desc,
                "tag_line": tag_line,
                "category": "",
                "image_url": image_url,
                "url": f"{ep.DISTRICT_BASE}/events/{slug}" if slug else "",
                "start_epoch": epoch,
                "end_epoch": end_epoch,
            })

        # Sort by start_epoch (earliest first, 0 = unknown goes last)
        events.sort(key=lambda e: (e["start_epoch"] == 0, e["start_epoch"]))

        return events

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
            start = e.get("start_epoch", 0)
            end = e.get("end_epoch", 0)
            if start == 0:
                # No epoch — check date_string for keywords
                date_str = e.get("date", "").lower()
                if when_lower == "today" and "today" in date_str:
                    filtered.append(e)
                elif when_lower == "tomorrow" and "tomorrow" in date_str:
                    filtered.append(e)
                elif when_lower == "weekend" and ("sat" in date_str or "sun" in date_str or "weekend" in date_str):
                    filtered.append(e)
                continue
            if end == 0:
                end = start + 86400  # Assume 24h if no end
            # Event overlaps with target date range
            if start < target_end_ts and end > target_start_ts:
                filtered.append(e)

        return filtered

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