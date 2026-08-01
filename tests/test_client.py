"""Unit tests for the Zomato client.

All tests mock HTTP responses — no live network calls.
Run with: python -m pytest tests/ -q
"""

import json
import pytest
import responses
from unittest.mock import patch, MagicMock

from zomato import ZomatoClient, Location
from zomato.client import USER_AGENT
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