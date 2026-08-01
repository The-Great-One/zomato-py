"""Unit tests for the Zomato client.

All tests mock HTTP responses — no live network calls.
Run with: python -m pytest tests/ -q
"""

import json
import pytest
import responses
from unittest.mock import patch

from zomato import ZomatoClient, Location
from zomato import endpoints as ep
from zomato.exceptions import ZomatoAPIError, ZomatoAuthError, ZomatoNotFoundError


# ── Fixtures ────────────────────────────────────────────────────

CSRF_TOKEN = "test_csrf_token_12345"


@pytest.fixture
def client(tmp_path):
    """ZomatoClient with mocked session and isolated cache dir."""
    c = ZomatoClient(
        location=Location(lat=28.4595, lng=77.0266, city_id=12939, city_name="Gurugram"),
        cache_dir=str(tmp_path / ".zomato-py"),
    )
    return c


@pytest.fixture
def csrf_response():
    """Mock CSRF endpoint response."""
    return {
        "csrf": CSRF_TOKEN,
        "csrf_set_time": 1700000000,
    }


# ── Location tests ──────────────────────────────────────────────

class TestLocation:
    def test_to_cookie(self):
        loc = Location(lat=28.45, lng=77.02, city_id=12939, city_name="Gurugram")
        cookie = loc.to_cookie()
        assert "Gurugram" in cookie
        assert "12939" in cookie
        assert "28.45" in cookie

    def test_defaults(self):
        loc = Location()
        assert loc.city_id == 12939
        assert loc.city_name == "Gurugram"


# ── CSRF tests ──────────────────────────────────────────────────

class TestCSRF:
    @responses.activate
    def test_ensure_csrf_success(self, client, csrf_response):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.CSRF}",
            json=csrf_response,
            status=200,
        )
        token = client._ensure_csrf()
        assert token == CSRF_TOKEN

    @responses.activate
    def test_ensure_csrf_caches(self, client, csrf_response):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.CSRF}",
            json=csrf_response,
            status=200,
        )
        # Call twice — should only make one HTTP request
        t1 = client._ensure_csrf()
        t2 = client._ensure_csrf()
        assert t1 == t2 == CSRF_TOKEN
        assert len(responses.calls) == 1

    @responses.activate
    def test_ensure_csrf_failure(self, client):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.CSRF}",
            json={"csrf": ""},
            status=200,
        )
        with pytest.raises(ZomatoAuthError, match="Failed to acquire CSRF"):
            client._ensure_csrf()


# ── Search restaurants tests ────────────────────────────────────

class TestSearchRestaurants:
    @responses.activate
    def test_search_restaurants(self, client):
        mock_data = {
            "page_data": {
                "sections": {
                    "SECTION_SEARCH_RESULT": [
                        {
                            "type": "restaurant",
                            "info": {
                                "resId": 12345,
                                "name": "Test Restaurant",
                                "cuisine": [
                                    {"name": "North Indian"},
                                    {"name": "Chinese"},
                                ],
                                "rating": {"aggregate_rating": "4.2", "rating_subtitle": "Very Good", "votes": "100"},
                                "cft": {"text": "₹500 for two"},
                                "cfo": {"text": "₹250 for one"},
                                "image": {"url": "https://b.zmtcdn.com/test.jpg"},
                                "resUrl": "/gurugram/test-restaurant",
                                "locality": {"name": "DLF Phase 1"},
                                "timing": {"text": "Open now"},
                                "ratingNew": {
                                    "ratings": {
                                        "DELIVERY": {"rating": "4.2", "reviewCount": "50"},
                                        "DINING": {"rating": "4.5", "reviewCount": "30"},
                                    }
                                },
                            },
                            "isPromoted": False,
                        }
                    ]
                }
            }
        }
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.GET_PAGE}",
            json=mock_data,
            status=200,
        )
        results = client.search_restaurants(city="gurugram")
        assert len(results) == 1
        r = results[0]
        assert r["name"] == "Test Restaurant"
        assert r["resId"] == 12345
        assert r["cuisine"] == "North Indian, Chinese"
        assert r["rating"] == "4.2"
        assert r["cost_for_two"] == "₹500 for two"
        assert r["locality"] == "DLF Phase 1"
        assert r["delivery_rating"] == "4.2"
        assert r["dining_rating"] == "4.5"

    @responses.activate
    def test_search_restaurants_empty(self, client):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.GET_PAGE}",
            json={"page_data": {"sections": {"SECTION_SEARCH_RESULT": []}}},
            status=200,
        )
        results = client.search_restaurants(city="gurugram")
        assert results == []


# ── Restaurant info tests ──────────────────────────────────────

class TestRestaurantInfo:
    @responses.activate
    def test_get_restaurant(self, client):
        mock_data = {
            "page_data": {
                "sections": {
                    "SECTION_BASIC_INFO": {
                        "res_id": "1827",
                        "name": "The Singh's",
                        "cuisine_string": "North Indian, Mughlai",
                        "rating": {"aggregate_rating": "3.8", "rating_subtitle": "Good", "votes": "50"},
                        "timing": {"timing_desc": "11 AM – 11 PM", "customised_timings": {}},
                        "res_status_text": "Open",
                        "resUrl": "/ncr/the-singhs",
                    },
                    "SECTION_RES_CONTACT": {
                        "address": "5-G/41, Market 5, NIT, Faridabad",
                        "city_name": "Faridabad",
                        "latitude": "28.39",
                        "longitude": "77.30",
                        "phoneDetails": {"phoneStr": "+919876543210"},
                    },
                    "SECTION_RES_HEADER_DETAILS": {
                        "LOCALITY": {"text": "NIT, Faridabad", "url": "https://www.zomato.com/ncr/nit-faridabad-restaurants"},
                    },
                    "SECTION_RES_DETAILS": {
                        "CFT_DETAILS": {
                            "cfts": [{"title": "₹600 for two people (approx.)"}],
                        },
                        "IMAGE_MENUS": {
                            "menus": [{"label": "Food", "subtitle": "3 pages", "thumb": "https://b.zmtcdn.com/menu.jpg"}],
                        },
                    },
                    "SECTION_IMAGE_CAROUSEL": {
                        "entities": [
                            {"entity_type": "IMAGES", "entity_ids": ["r_123", "r_456"]}
                        ]
                    },
                }
            }
        }
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.RESTAURANT_INFO}",
            json=mock_data,
            status=200,
        )
        info = client.get_restaurant(res_id=1827)
        assert info["name"] == "The Singh's"
        assert info["cuisine"] == "North Indian, Mughlai"
        assert info["rating"] == "3.8"
        assert info["cost_for_two"] == "₹600 for two people (approx.)"
        assert info["address"] == "5-G/41, Market 5, NIT, Faridabad"
        assert info["locality"] == "NIT, Faridabad"
        assert info["city"] == "Faridabad"
        assert info["timings"] == "11 AM – 11 PM"
        assert info["phone"] == "+919876543210"
        assert len(info["photos"]) == 2
        assert len(info["menu_pages"]) == 1
        assert info["menu_pages"][0]["label"] == "Food"


# ── Reviews tests ──────────────────────────────────────────────

class TestReviews:
    @responses.activate
    def test_get_reviews(self, client):
        mock_data = {
            "page_data": {
                "sections": {
                    "SECTION_REVIEW": {
                        "rev1": {
                            "id": "rev1",
                            "rating": "5",
                            "ratingText": "Excellent",
                            "reviewText": "Best food ever!",
                            "userName": "John Doe",
                            "userId": "u123",
                            "timestamp": "2024-01-15",
                            "likesCount": 10,
                            "commentsCount": 2,
                        }
                    }
                }
            }
        }
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.REVIEWS_LOAD_MORE}",
            json=mock_data,
            status=200,
        )
        reviews = client.get_reviews(res_id=1827, limit=5)
        assert len(reviews) == 1
        r = reviews[0]
        assert r["rating"] == "5"
        assert r["text"] == "Best food ever!"
        assert r["user_name"] == "John Doe"
        assert r["likes"] == 10


# ── Location search tests ─────────────────────────────────────

class TestLocationSearch:
    @responses.activate
    def test_search_location(self, client):
        mock_data = {
            "locationSuggestions": [
                {
                    "entity_title": "Gurugram",
                    "entity_id": 12939,
                    "entity_type": "city",
                    "entity_latitude": 28.4595,
                    "entity_longitude": 77.0266,
                    "display_title": "Gurugram",
                    "display_subtitle": "Haryana, India",
                }
            ]
        }
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.LOCATION_SEARCH}",
            json=mock_data,
            status=200,
        )
        locations = client.search_location("Gurugram")
        assert len(locations) == 1
        loc = locations[0]
        assert loc["name"] == "Gurugram"
        assert loc["entity_id"] == 12939


# ── Error handling tests ───────────────────────────────────────

class TestErrorHandling:
    @responses.activate
    def test_401_error(self, client):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.RESTAURANT_INFO}",
            json={"message": "Unauthorized request! Please refresh the page."},
            status=401,
        )
        with pytest.raises(ZomatoAuthError):
            client.get_restaurant(res_id=1827)

    @responses.activate
    def test_404_error(self, client):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.RESTAURANT_INFO}",
            json={"message": "Not found"},
            status=404,
        )
        with pytest.raises(ZomatoNotFoundError):
            client.get_restaurant(res_id=99999)

    @responses.activate
    def test_api_failure(self, client):
        responses.add(
            responses.GET,
            f"{ep.ZOMATO_BASE}{ep.GET_PAGE}",
            json={"status": "failed", "message": "Missing/Invalid parameters"},
            status=400,
        )
        # _get only raises for 401, 404, 5xx — 400 with "status":"failed" should raise
        with pytest.raises(ZomatoAPIError):
            client.search_restaurants(city="gurugram")


# ── District events tests ─────────────────────────────────────

class TestDistrictEvents:
    @responses.activate
    def test_get_events(self, client):
        # Mock the District events page HTML with an ItemDetails block
        html = '''<html><body>
        <script>self.__next_f.push([1,"4:dummy"])</script>
        <script>self.__next_f.push([1,"some_data_with_\\"ItemDetails\\":{\\"EventData\\":{\\"name\\":\\"Test Concert\\",\\"venue_name\\":\\"Saket Social\\",\\"city\\":\\"Delhi/NCR\\",\\"date_string\\":\\"1 Aug, 7PM\\",\\"description\\":\\"A live music concert\\",\\"event_slug\\":\\"test-concert-2026\\"}}"])</script>
        </body></html>'''
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}",
            body=html,
            status=200,
        )
        events = client.get_events(city="")
        # Should find at least one event
        assert any(e.get("title") == "Test Concert" for e in events)
        if events:
            e = events[0]
            assert e["venue"] == "Saket Social"
            assert e["city"] == "Delhi/NCR"
            assert e["date"] == "1 Aug, 7PM"

    @responses.activate
    def test_get_events_empty(self, client):
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}",
            body="<html><body>No data</body></html>",
            status=200,
        )
        events = client.get_events(city="")
        assert events == []


# ── District individual-page crawling tests ────────────────────


def _district_rsc_html(payload: dict) -> str:
    """Wrap a payload in the Next.js RSC script format District serves."""
    return (
        "<html><body><script>self.__next_f.push([1,"
        f"{json.dumps(json.dumps(payload, separators=(',', ':')))}"
        "])</script></body></html>"
    )


def _event_json_ld(name: str, description: str) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": name,
        "description": description,
        "startDate": "2026-08-01T20:00:00+05:30",
        "endDate": "2026-08-02T01:00:00+05:30",
        "organizer": {"@type": "Organization", "name": "District Nights"},
        "location": {"@type": "Place", "name": "Rail Venue"},
        "offers": {"@type": "Offer", "price": "999", "priceCurrency": "INR"},
    }
    return (
        '<html><body><script type="application/ld+json">'
        f"{json.dumps(schema)}"
        "</script></body></html>"
    )


class TestDistrictIndividualPages:
    @responses.activate
    def test_get_district_venue_by_slug_sends_guest_headers_and_returns_rails(self, client):
        venue_api = f"{ep.DISTRICT_BASE}/gw/consumer/event/venue-page-web"
        payload = {
            "name": "Rail Venue",
            "venue_page_rails": [
                {"title": "Upcoming", "items": [{"label": "Hidden Party", "slug": "hidden-party"}]}
            ],
        }
        responses.add(responses.GET, venue_api, json=payload, status=200)

        venue = client.get_district_venue_by_slug("rail-venue")

        assert venue["venue_page_rails"][0]["items"][0]["slug"] == "hidden-party"
        request = responses.calls[0].request
        assert request.params == {"venue_slug": "rail-venue"}
        assert request.headers["x-guest-token"] == "1212"
        assert request.headers["x-app-type"] == "WEB"
        assert request.headers["x-client-id"] == "district-web"
        assert request.headers["x-app-version"] == "11.11.1"
        assert request.headers["Referer"] == (
            f"{ep.DISTRICT_BASE}/events/rail-venue/venue-guide"
        )

    @responses.activate
    def test_crawl_uses_canonical_routes_parses_json_ld_and_recurses_into_venue_rails(self, client):
        main_payload = {
            "ItemDetails": {
                "VenueData": {"name": "Rail Venue", "slug": "rail-venue"}
            },
            "second": {
                "ItemDetails": {
                    "EventData": {"name": "Listed Party", "event_slug": "listed-party"}
                }
            },
        }
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}{ep.DISTRICT_EVENTS_PAGE}",
            body=_district_rsc_html(main_payload),
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}/events/rail-venue/venue-guide",
            body="<html><body>client rendered venue</body></html>",
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}/gw/consumer/event/venue-page-web",
            json={
                "name": "Rail Venue",
                "venue_page_rails": [
                    {
                        "title": "More events",
                        "items": [{"label": "Hidden Party", "slug": "hidden-party"}],
                    }
                ],
            },
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}/events/listed-party-buy-tickets",
            body=_event_json_ld("Listed Party", "Listed detail from JSON-LD"),
            status=200,
        )
        responses.add(
            responses.GET,
            f"{ep.DISTRICT_BASE}/events/hidden-party-buy-tickets",
            body=_event_json_ld("Hidden Party", "Rail-only detail from JSON-LD"),
            status=200,
        )

        crawl = client.crawl_individual_pages(
            include_zomato_details=False,
            max_pages=10,
        )

        assert crawl["stats"] == {
            "venue_slugs_found": 1,
            "event_slugs_found": 2,
            "main_page_event_slugs_found": 1,
            "venue_page_event_slugs_found": 1,
            "venue_pages_crawled": 1,
            "event_pages_crawled": 2,
            "pages_with_embedded_data": 3,
            "client_side_only_pages": 0,
        }
        pages = {page["slug"]: page for page in crawl["events"]}
        assert set(pages) == {"listed-party", "hidden-party"}
        assert pages["listed-party"]["url"].endswith("/events/listed-party-buy-tickets")
        assert pages["hidden-party"]["url"].endswith("/events/hidden-party-buy-tickets")
        assert pages["hidden-party"]["schema_event"]["description"] == (
            "Rail-only detail from JSON-LD"
        )
        requested_urls = {call.request.url.split("?")[0] for call in responses.calls}
        assert f"{ep.DISTRICT_BASE}/events/rail-venue/venue-guide" in requested_urls
        assert f"{ep.DISTRICT_BASE}/events/listed-party-buy-tickets" in requested_urls
        assert f"{ep.DISTRICT_BASE}/events/hidden-party-buy-tickets" in requested_urls

    def test_find_party_places_merges_weekend_rail_event_with_distance_and_json_ld_detail(self, client):
        venue_data = {
            "name": "Rail Venue",
            "address": "Sector 29, Gurugram",
            "latitude": 28.4695,
            "longitude": 77.0266,
            "venue_page_rails": [
                {
                    "title": "Upcoming",
                    "items": [
                        {
                            "label": "Hidden Saturday Party",
                            "slug": "hidden-saturday-party",
                            "date_time": "Sat, 8 PM",
                            "price": "₹999 onwards",
                        },
                        {
                            "label": "Hidden Wednesday Party",
                            "slug": "hidden-wednesday-party",
                            "date_time": "Wed, 8 PM",
                        },
                    ],
                }
            ],
        }
        hidden_schema = {
            "@type": "Event",
            "name": "Hidden Saturday Party",
            "description": "Detail parsed from the event JSON-LD",
            "startDate": "2026-08-01T20:00:00+05:30",
            "endDate": "2026-08-02T01:00:00+05:30",
            "organizer": {"name": "District Nights"},
            "location": {"name": "Rail Venue", "address": "Sector 29"},
            "offers": {"price": "999", "priceCurrency": "INR"},
        }
        crawl = {
            "venues": [{"name": "Rail Venue", "venue_data": venue_data}],
            "events": [
                {
                    "name": "Hidden Saturday Party",
                    "schema_event": hidden_schema,
                    "json_ld": [hidden_schema],
                }
            ],
            "stats": {},
        }

        with (
            patch.object(client, "get_events", return_value=[]),
            patch.object(client, "crawl_individual_pages", return_value=crawl) as crawl_mock,
            patch.object(client, "search_restaurants", return_value=[]),
        ):
            places = client.find_party_places(
                lat=28.4595,
                lng=77.0266,
                radius_km=5,
                when="weekend",
                include_offers=False,
            )

        crawl_mock.assert_called_once_with(
            include_events=True,
            include_venues=True,
            include_zomato_details=False,
            max_pages=50,
            city="gurugram",
        )
        assert len(places) == 1
        place = places[0]
        assert place["name"] == "Rail Venue"
        assert place["address"] == "Sector 29, Gurugram"
        assert place["distance_km"] == pytest.approx(1.1, abs=0.1)
        assert [event["title"] for event in place["events"]] == ["Hidden Saturday Party"]
        event = place["events"][0]
        assert event["detail_crawled"] is True
        assert event["description"] == "Detail parsed from the event JSON-LD"
        assert event["organizer"] == "District Nights"
        assert event["start_date"] == "2026-08-01T20:00:00+05:30"
        assert event["ticket_offer"] == {"price": "999", "priceCurrency": "INR"}
        assert event["url"] == (
            f"{ep.DISTRICT_BASE}/events/hidden-saturday-party-buy-tickets"
        )

    def test_find_party_places_computes_distance_from_string_coordinates(self, client):
        event = {
            "title": "String Coordinate Party",
            "venue": "String Coordinate Venue",
            "city": "Gurugram",
            "date": "Every Sat",
            "start_epoch": 0,
            "end_epoch": 0,
            "is_activity": False,
            "lat": "28.4695",
            "long": "77.0266",
        }

        with (
            patch.object(client, "get_events", return_value=[event]),
            patch.object(client, "search_restaurants", return_value=[]),
        ):
            places = client.find_party_places(
                lat=28.4595,
                lng=77.0266,
                radius_km=5,
                include_offers=False,
                crawl_details=False,
            )

        assert len(places) == 1
        assert places[0]["lat"] == 28.4695
        assert places[0]["lng"] == 77.0266
        assert places[0]["distance_km"] == pytest.approx(1.1, abs=0.1)

    def test_filter_venue_rail_human_date_by_exact_iso_date(self, client):
        events = [
            {"title": "Matching Party", "date": "10 Jan 2026 • 9:00 PM"},
            {"title": "Other Party", "date": "11 Jan 2026 • 9:00 PM"},
        ]

        filtered = client._filter_events_by_when(events, "2026-01-10")

        assert [event["title"] for event in filtered] == ["Matching Party"]

    def test_filter_recurring_venue_rail_event_by_requested_weekday(self, client):
        events = [
            {"title": "Saturday Party", "date": "Every Sat"},
            {"title": "Sunday Party", "date": "Every Sunday"},
        ]

        filtered = client._filter_events_by_when(events, "2026-01-10")

        assert [event["title"] for event in filtered] == ["Saturday Party"]


# ── City IDs tests ─────────────────────────────────────────────

class TestCityIDs:
    def test_known_cities(self):
        from zomato.client import CITY_IDS
        assert CITY_IDS["gurugram"] == 12939
        assert CITY_IDS["delhi"] == 1
        assert CITY_IDS["mumbai"] == 3

    def test_set_location(self, client):
        client.set_location(city="mumbai")
        assert client.location.city_id == 3
        assert client.location.city_name == "Mumbai"