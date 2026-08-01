"""Zomato CLI — command-line interface for restaurant & event discovery."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from .client import ZomatoClient
from .location import (
    BrowserLocationDetector,
    LocationDetectionError,
    LocationRecord,
    LocationStore,
)


def _print_restaurants(restaurants: list[dict]) -> None:
    if not restaurants:
        print("No restaurants found.")
        return
    print(f"\nFound {len(restaurants)} restaurants:\n")
    for i, r in enumerate(restaurants, 1):
        rating = r.get("rating", "N/A")
        name = r.get("name", "Unknown")
        cuisine = r.get("cuisine", "")
        cost = r.get("cost_for_two", "")
        locality = r.get("locality", "")
        print(f"  {i:2d}. {name} — {rating}★ — {cuisine} — {cost} — {locality}")


def _print_restaurant(info: dict) -> None:
    print(f"\n  Name:        {info.get('name', 'N/A')}")
    print(f"  Rating:      {info.get('rating', 'N/A')} ({info.get('rating_text', '')})")
    print(f"  Cuisine:     {info.get('cuisine', 'N/A')}")
    print(f"  Cost (two):  {info.get('cost_for_two', 'N/A')}")
    print(f"  Address:     {info.get('address', 'N/A')}")
    print(f"  Locality:    {info.get('locality', 'N/A')}")
    print(f"  City:        {info.get('city', 'N/A')}")
    print(f"  Timings:     {info.get('timings', 'N/A')}")
    print(f"  Phone:       {info.get('phone', 'N/A')}")


def _print_reviews(reviews: list[dict]) -> None:
    if not reviews:
        print("No reviews found.")
        return
    print(f"\nFound {len(reviews)} reviews:\n")
    for i, rev in enumerate(reviews, 1):
        rating = rev.get("rating", "N/A")
        user = rev.get("user_name", "Anonymous")
        text = rev.get("text", "")[:200]
        likes = rev.get("likes", 0)
        experience = rev.get("experience", "")
        tags = rev.get("tags", [])
        print(f"  {i}. {rating}★ by {user} (👍 {likes})" +
              (f" [{experience}]" if experience else ""))
        if tags:
            print(f"     Tags: {', '.join(tags[:5])}")
        print(f"     {text}\n")


def _print_events(events: list[dict]) -> None:
    if not events:
        print("No events found.")
        return
    print(f"\nFound {len(events)} events:\n")
    for i, e in enumerate(events, 1):
        title = e.get("title", "Unknown")
        venue = e.get("venue", "")
        city = e.get("city", "")
        locality = e.get("locality", "")
        date = e.get("date", "")
        desc = e.get("description", "")
        tag_line = e.get("tag_line", "")
        price = e.get("price", "")
        rating = e.get("rating", "")
        category = e.get("category", "")
        print(f"  {i:2d}. {title}")
        if category:
            print(f"      🎭 {category}")
        if date:
            print(f"      📅 {date}")
        if venue:
            print(f"      📍 {venue}" + (f", {locality}" if locality else ""))
        if city:
            print(f"      🏙️  {city}")
        if price:
            print(f"      💰 {price}")
        if rating:
            print(f"      ⭐ {rating}")
        if tag_line:
            print(f"      📝 {tag_line}")
        elif desc:
            print(f"      📝 {desc[:150]}")


def _print_locations(locations: list[dict]) -> None:
    if not locations:
        print("No locations found.")
        return
    print(f"\nFound {len(locations)} locations:\n")
    for i, loc in enumerate(locations, 1):
        print(f"  {i}. {loc['name']} (ID: {loc['entity_id']}, Type: {loc['entity_type']})")
        if loc.get("display_subtitle"):
            print(f"     {loc['display_subtitle']}")


def cmd_restaurants(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    if args.lat and args.lng:
        client.set_location(lat=args.lat, lng=args.lng)
    results = client.search_restaurants(
        city=args.city,
        context=args.context,
    )
    if args.limit:
        results = results[:args.limit]
    _print_restaurants(results)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_restaurant(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    info = client.get_restaurant(res_id=args.id)
    _print_restaurant(info)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))


def cmd_reviews(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    reviews = client.get_reviews(
        res_id=args.id,
        limit=args.limit,
    )
    _print_reviews(reviews)
    if args.json:
        print(json.dumps(reviews, indent=2, ensure_ascii=False))


def cmd_events(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    events = client.get_events(
        city=args.city,
        category=args.category,
        when=args.when,
    )
    # Filter by keyword query (searches title, venue, description)
    if args.query:
        q = args.query.lower()
        events = [
            e for e in events
            if q in e.get("title", "").lower()
            or q in e.get("venue", "").lower()
            or q in e.get("description", "").lower()
            or q in e.get("category", "").lower()
        ]
    if args.limit:
        events = events[:args.limit]
    _print_events(events)
    if args.json:
        print(json.dumps(events, indent=2, ensure_ascii=False))


def cmd_restaurant_events(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    restaurants = client.get_restaurant_events(
        city=args.city,
        when=args.when,
        query=args.query,
        nightlife_only=not args.include_activities,
        category=args.category,
    )
    # Filter by category
    if args.category:
        cat = args.category.lower()
        restaurants = [
            r for r in restaurants
            if any(cat in ev.get("category", "").lower() for ev in r.get("events", []))
        ]
    if args.limit and args.limit > 0:
        restaurants = restaurants[:args.limit]
    if not restaurants:
        print("No restaurants with events found.")
        return
    when_label = args.when or "all upcoming"
    print(f"\n{len(restaurants)} restaurants with events ({when_label}):\n")
    for i, r in enumerate(restaurants, 1):
        print(f"  {i}. {r['restaurant']}")
        if r.get("locality"):
            print(f"     📍 {r['locality']}, {r.get('city', '')}")
        elif r.get("address"):
            print(f"     📍 {r['address']}")
        for ev in r.get("events", []):
            line = f"     → {ev['title']}"
            if ev.get("category"):
                line += f" [{ev['category']}]"
            if ev.get("date"):
                line += f" — {ev['date']}"
            if ev.get("price"):
                line += f" — {ev['price']}"
            print(line)
    if args.json:
        print(json.dumps(restaurants, indent=2, ensure_ascii=False))


def cmd_movies(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    movies = client.get_movies(city=args.city)
    if args.limit:
        movies = movies[:args.limit]
    _print_events(movies)
    if args.json:
        print(json.dumps(movies, indent=2, ensure_ascii=False))


def cmd_search(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    results = client.auto_suggest(query=args.query)
    print(json.dumps(results, indent=2, ensure_ascii=False))


def cmd_location_search(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    locations = client.search_location(query=args.query)
    _print_locations(locations)
    if args.json:
        print(json.dumps(locations, indent=2, ensure_ascii=False))


def _print_location_record(location: LocationRecord, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(location.to_dict(), indent=2, ensure_ascii=False))
        return
    accuracy = "unknown" if location.accuracy is None else f"{location.accuracy:g} m"
    print(f"Latitude: {location.latitude}")
    print(f"Longitude: {location.longitude}")
    print(f"Accuracy: {accuracy}")
    print(f"Source: {location.source}")
    print(f"Approved at: {location.approved_at}")


def cmd_location_detect(args: argparse.Namespace) -> None:
    """Request browser geolocation approval and persist the result."""
    store = LocationStore()
    location = BrowserLocationDetector(store=store).detect(timeout=args.timeout)
    _print_location_record(location, as_json=args.json)


def cmd_location_show(args: argparse.Namespace) -> None:
    """Show the currently persisted approved location."""
    location = LocationStore().load()
    if location is None:
        raise ValueError(
            "No approved location is saved; use zomato location set or zomato location detect."
        )
    _print_location_record(location, as_json=args.json)


def cmd_location_set(args: argparse.Namespace) -> None:
    """Validate and persist manually supplied coordinates."""
    location = LocationRecord(
        latitude=args.lat,
        longitude=args.lng,
        accuracy=args.accuracy,
        source="manual",
        approved_at=datetime.now(timezone.utc).isoformat(),
    )
    LocationStore().save(location)
    _print_location_record(location, as_json=args.json)


def cmd_location_clear(args: argparse.Namespace) -> None:
    """Clear any persisted approved location."""
    cleared = LocationStore().clear()
    if args.json:
        print(json.dumps({"cleared": cleared}))
    else:
        print("Saved location cleared." if cleared else "No saved location to clear.")


def cmd_collections(args: argparse.Namespace) -> None:
    client = ZomatoClient()
    if args.city:
        client.set_location(city=args.city)
    collections = client.get_collections(city=args.city)
    if not collections:
        print("No collections found.")
        return
    print(f"\nFound {len(collections)} collections:\n")
    for i, c in enumerate(collections, 1):
        print(f"  {i}. {c.get('title', 'Unknown')}")
        if c.get("description"):
            print(f"     {c['description']}")
        if c.get("url"):
            print(f"     {c['url']}")


def cmd_trends(args: argparse.Namespace) -> None:
    """Show rating trend analysis for a restaurant."""
    client = ZomatoClient()
    trends = client.get_rating_trends(res_id=args.id, months=args.months)
    if not trends:
        print("No review data found for trend analysis.")
        return
    info = client.get_restaurant(res_id=args.id)
    print(f"\n  {info.get('name', 'Unknown')} — Current: {info.get('rating', '?')}★")
    print(f"  Rating trend (last {args.months} months):\n")
    for t in trends:
        bar_len = int(float(t["avg_rating"]) * 10) if t["avg_rating"] else 0
        bar = "█" * (bar_len // 4) + "░" * (25 - bar_len // 4)
        trend_icon = {"up": "📈", "down": "📉", "stable": "➡️"}.get(t["trend"], "")
        print(f"  {t['month']}  {bar} {t['avg_rating']:.1f}  ({t['count']} reviews) {trend_icon}")
    if args.json:
        print(json.dumps(trends, indent=2, ensure_ascii=False))


def cmd_dishes(args: argparse.Namespace) -> None:
    """Show most mentioned dishes from reviews."""
    client = ZomatoClient()
    dishes = client.get_popular_dishes(res_id=args.id, limit=args.limit)
    if not dishes:
        print("No dish mentions found in reviews.")
        return
    info = client.get_restaurant(res_id=args.id)
    print(f"\n  Most mentioned dishes at {info.get('name', 'Unknown')}:\n")
    for i, d in enumerate(dishes, 1):
        mentions = d["mentions"]
        avg_rating = d.get("avg_rating", 0)
        bar = "▓" * min(mentions, 30)
        rating_str = f" {avg_rating:.1f}★" if avg_rating else ""
        print(f"  {i:2d}. {d['dish']:<20} {bar} {mentions} mentions{rating_str}")
    if args.json:
        print(json.dumps(dishes, indent=2, ensure_ascii=False))


def cmd_offers(args: argparse.Namespace) -> None:
    """Show active offers at a restaurant."""
    client = ZomatoClient()
    offers = client.get_restaurant_offers(res_id=args.id)
    if not offers:
        print("No active offers found.")
        return
    info = client.get_restaurant(res_id=args.id)
    print(f"\n  Active offers at {info.get('name', 'Unknown')}:\n")
    for i, o in enumerate(offers, 1):
        print(f"  {i}. {o.get('title', o.get('label', ''))}")
        if o.get('description'):
            print(f"     {o['description']}")
        if o.get('code'):
            print(f"     Code: {o['code']}")
    if args.json:
        print(json.dumps(offers, indent=2, ensure_ascii=False))


def cmd_hygiene(args: argparse.Namespace) -> None:
    """Show hygiene/safety details for a restaurant."""
    client = ZomatoClient()
    hygiene = client.get_hygiene_details(res_id=args.id)
    if not hygiene:
        print("No hygiene data available.")
        return
    info = client.get_restaurant(res_id=args.id)
    print(f"\n  Hygiene details for {info.get('name', 'Unknown')}:\n")
    if hygiene.get("valid_until"):
        print(f"  Valid until:   {hygiene['valid_until']}")
    if hygiene.get("audit_on"):
        print(f"  Last audit:    {hygiene['audit_on']}")
    sections = hygiene.get("sections", {})
    if isinstance(sections, dict):
        for sid, section in sections.items():
            if not isinstance(section, dict):
                continue
            title = section.get("title", "")
            subtitle = section.get("subtitle", "")
            print(f"  {title}")
            if subtitle:
                print(f"     {subtitle}")
    elif isinstance(sections, list):
        for section in sections:
            title = section.get("title", "") if isinstance(section, dict) else ""
            subtitle = section.get("subtitle", "") if isinstance(section, dict) else ""
            print(f"  {title}")
            if subtitle:
                print(f"     {subtitle}")
    if args.json:
        print(json.dumps(hygiene, indent=2, ensure_ascii=False))


def cmd_value(args: argparse.Namespace) -> None:
    """Show value-for-money analysis for a restaurant."""
    client = ZomatoClient()
    value = client.get_value_for_money(res_id=args.id)
    if not value:
        print("Could not compute value analysis.")
        return
    print(f"\n  {value.get('name', 'Unknown')}")
    print(f"  Rating:        {value.get('rating', '?')}★")
    print(f"  Cost for two:  {value.get('cost_for_two', '?')}")
    print(f"  Cost per ★:   {value.get('cost_per_rating', '?')}")
    verdict = value.get("verdict", "")
    icons = {"great value": "💚", "good": "💛", "pricey": "❤️", "unknown": "❓"}
    icon = icons.get(verdict, "")
    print(f"  Verdict:       {icon} {verdict}")
    if args.json:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def _location_guidance() -> str:
    return "use --lat/--lng or zomato location set/detect"


def _resolve_party_coordinates(
    args: argparse.Namespace,
    *,
    store: LocationStore | None = None,
    detector: BrowserLocationDetector | None = None,
) -> tuple[float, float]:
    """Resolve coordinates by explicit, persisted, then browser precedence."""
    has_latitude = args.lat is not None
    has_longitude = args.lng is not None
    if has_latitude != has_longitude:
        raise ValueError("--lat and --lng must be supplied together")
    if has_latitude:
        explicit = LocationRecord(
            latitude=args.lat,
            longitude=args.lng,
            accuracy=None,
            source="explicit",
            approved_at=datetime.now(timezone.utc).isoformat(),
        )
        return explicit.latitude, explicit.longitude

    store = store or LocationStore()
    persisted = store.load()
    if persisted is not None:
        return persisted.latitude, persisted.longitude

    if args.no_location_detect:
        raise ValueError(
            "No approved location is saved and browser detection is disabled; "
            "use --lat/--lng, zomato location set, or zomato location detect."
        )

    detector = detector or BrowserLocationDetector(store=store)
    try:
        detected = detector.detect(timeout=args.location_timeout)
    except LocationDetectionError as exc:
        raise ValueError(f"Location detection failed: {exc}; {_location_guidance()}.") from exc
    return detected.latitude, detected.longitude


def cmd_party(args: argparse.Namespace) -> None:
    """Find party places near you."""
    client = ZomatoClient()
    store = LocationStore()
    detector = BrowserLocationDetector(store=store)
    latitude, longitude = _resolve_party_coordinates(
        args, store=store, detector=detector
    )
    client.set_location(lat=latitude, lng=longitude)
    if args.city:
        client.set_location(city=args.city)
    places = client.find_party_places(
        lat=latitude,
        lng=longitude,
        radius_km=args.radius,
        when=args.when,
        include_offers=not args.no_offers,
        crawl_details=not args.no_crawl,
    )
    if not places:
        print("No party places found near you.")
        return
    print(f"\n{len(places)} party places near you ({args.when or 'all upcoming'}):\n")
    for i, p in enumerate(places, 1):
        name = p.get("name", "Unknown")
        dist = p.get("distance_km", 0)
        rating = p.get("rating", "")
        source = p.get("source", "")
        source_icon = "🎭" if source == "district" else "🍽️"
        dist_str = f"{dist}km" if dist else "?"
        rating_str = f"{rating}★" if rating else ""
        print(f"  {i:2d}. {source_icon} {name} — {dist_str} {rating_str}")
        if p.get("locality"):
            print(f"      📍 {p['locality']}, {p.get('city', '')}")
        if p.get("address"):
            print(f"      📍 {p['address']}")
        for ev in p.get("events", []):
            line = f"      → {ev['title']}"
            if ev.get("category"):
                line += f" [{ev['category']}]"
            if ev.get("date"):
                line += f" — {ev['date']}"
            if ev.get("price"):
                line += f" — {ev['price']}"
            print(line)
        for off in p.get("offers", []):
            if off.get("title"):
                line = f"      💰 {off['title']}"
                if off.get("subtitle"):
                    line += f" ({off['subtitle']})"
                print(line)
    if args.json:
        print(json.dumps(places, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zomato",
        description="Discover restaurants, reviews, events, and more on Zomato",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # restaurants
    p = sub.add_parser("restaurants", help="Search restaurants in a city")
    p.add_argument("--city", default="gurugram", help="City slug (e.g. gurugram, delhi)")
    p.add_argument("--context", default="delivery", choices=["delivery", "dineout", "nightlife"])
    p.add_argument("--lat", type=float, default=None)
    p.add_argument("--lng", type=float, default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_restaurants)

    # restaurant
    p = sub.add_parser("restaurant", help="Get details for a specific restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_restaurant)

    # reviews
    p = sub.add_parser("reviews", help="Get reviews for a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_reviews)

    # events
    p = sub.add_parser("events", help="Discover events near you")
    p.add_argument("--city", default="gurugram")
    p.add_argument("--category", default="")
    p.add_argument("--query", default="", help="Keyword search (e.g. 'sufi', 'comedy', 'live music')")
    p.add_argument("--when", default="", help="Date filter: 'today', 'tomorrow', 'weekend', or 'YYYY-MM-DD'")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_events)

    # restaurant-events
    p = sub.add_parser("restaurant-events", help="List restaurants having events on a given day")
    p.add_argument("--city", default="gurugram")
    p.add_argument("--when", default="", help="'today', 'tomorrow', 'weekend', 'YYYY-MM-DD', or empty for all upcoming")
    p.add_argument("--query", default="", help="Keyword filter (e.g. 'sufi', 'live', 'comedy')")
    p.add_argument("--category", default="", help="Filter by category: comedy, live music, party, food, theatre, watch party")
    p.add_argument("-n", "--limit", type=int, default=0, help="Max number of restaurants to show (0 = all)")
    p.add_argument("--include-activities", action="store_true", help="Include water parks, go-karting, arcades (excluded by default)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_restaurant_events)

    # movies
    p = sub.add_parser("movies", help="Discover movies near you")
    p.add_argument("--city", default="gurugram")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_movies)

    # search (auto-suggest)
    p = sub.add_parser("search", help="Search suggestions for a query")
    p.add_argument("query", help="Search query (e.g. 'pizza')")
    p.add_argument("--city", default="gurugram")
    p.set_defaults(func=cmd_search)

    # location
    p = sub.add_parser("location", help="Manage an approved local location")
    location_sub = p.add_subparsers(dest="location_command", required=True)

    location_detect = location_sub.add_parser(
        "detect", help="Approve location access in your web browser"
    )
    location_detect.add_argument("--timeout", type=float, default=60.0)
    location_detect.add_argument("--json", action="store_true")
    location_detect.set_defaults(func=cmd_location_detect)

    location_show = location_sub.add_parser("show", help="Show the saved location")
    location_show.add_argument("--json", action="store_true")
    location_show.set_defaults(func=cmd_location_show)

    location_set = location_sub.add_parser("set", help="Save explicit coordinates")
    location_set.add_argument("--lat", type=float, required=True)
    location_set.add_argument("--lng", type=float, required=True)
    location_set.add_argument("--accuracy", type=float, default=None)
    location_set.add_argument("--json", action="store_true")
    location_set.set_defaults(func=cmd_location_set)

    location_clear = location_sub.add_parser("clear", help="Clear the saved location")
    location_clear.add_argument("--json", action="store_true")
    location_clear.set_defaults(func=cmd_location_clear)

    location_search = location_sub.add_parser(
        "search", help="Search Zomato location entities"
    )
    location_search.add_argument("query", help="Location name (e.g. 'Gurugram')")
    location_search.add_argument("--json", action="store_true")
    location_search.set_defaults(func=cmd_location_search)

    # collections
    p = sub.add_parser("collections", help="Get curated collections for a city")
    p.add_argument("--city", default="gurugram")
    p.set_defaults(func=cmd_collections)

    # trends (NEW)
    p = sub.add_parser("trends", help="Rating trend analysis for a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--months", type=int, default=6, help="Number of months to analyze (default: 6)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_trends)

    # dishes (NEW)
    p = sub.add_parser("dishes", help="Most mentioned dishes from reviews")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--limit", type=int, default=10, help="Max dishes to show")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_dishes)

    # offers (NEW)
    p = sub.add_parser("offers", help="Active offers at a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_offers)

    # hygiene (NEW)
    p = sub.add_parser("hygiene", help="Hygiene/safety details for a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_hygiene)

    # value (NEW)
    p = sub.add_parser("value", help="Value-for-money analysis for a restaurant")
    p.add_argument("--id", type=int, required=True, help="Restaurant ID")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_value)

    # party (NEW)
    p = sub.add_parser("party", help="Find party places near you")
    p.add_argument("--city", default="gurugram", help="City name")
    p.add_argument("--lat", type=float, default=None, help="Your latitude")
    p.add_argument("--lng", type=float, default=None, help="Your longitude")
    p.add_argument(
        "--no-location-detect",
        action="store_true",
        help="Do not open a browser when no approved location is saved",
    )
    p.add_argument(
        "--location-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for browser location approval (default: 60)",
    )
    p.add_argument("--radius", type=float, default=15, help="Max distance in km (default: 15)")
    p.add_argument("--when", default="weekend", help="'today', 'tomorrow', 'weekend', 'YYYY-MM-DD', or empty for all")
    p.add_argument("--no-offers", action="store_true", help="Skip fetching dining offers")
    p.add_argument("--no-crawl", action="store_true", help="Skip crawling individual event and venue pages")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_party)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()