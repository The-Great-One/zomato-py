# zomato-py

Unofficial Python client for Zomato's web API. No API key required —
reverse-engineered from Zomato's web frontend. Discover restaurants, read
reviews, browse collections, find events, track rating trends, extract
popular dishes, and more.

## Install

```bash
git clone https://github.com/The-Great-One/zomato-py.git
cd zomato-py
pip install -e .
```

The CLI is symlinked to `/usr/local/bin/zomato` after install.

## Quick start

```python
from zomato import ZomatoClient

client = ZomatoClient()

# Search restaurants
restaurants = client.search_restaurants(city="gurugram")
for r in restaurants:
    print(r["name"], r["rating"], r["cuisine"])

# Get restaurant details
info = client.get_restaurant(res_id=308020)
print(info["name"], info["rating"], info["cost_for_two"])

# Get reviews
reviews = client.get_reviews(res_id=308020, limit=10)
for rev in reviews:
    print(rev["rating"], rev["user_name"], rev["text"][:100])

# Find events
events = client.get_events(city="gurugram", when="today")
for e in events:
    print(e["title"], e["venue"], e["date"], e["category"])
```

## CLI usage

```
zomato --help
```

### Restaurants

```bash
# Search restaurants in a city
zomato restaurants --city gurugram

# Search with context (delivery, dineout, nightlife)
zomato restaurants --city delhi --context nightlife

# Get details for a specific restaurant
zomato restaurant --id 308020

# Get reviews
zomato reviews --id 308020 --limit 10

# Get curated collections
zomato collections --city gurugram
```

### Events

```bash
# All upcoming events
zomato events --city gurugram

# Events today
zomato events --city gurugram --when today

# Filter by keyword
zomato events --query comedy
zomato events --query "live music"

# Filter by category
zomato events --category comedy

# Filter by date
zomato events --when 2026-08-15
zomato events --when weekend

# List restaurants with events
zomato restaurant-events --city gurugram
zomato restaurant-events --when today --query sufi
zomato restaurant-events --category "live music" -n 5

# Include activities (water parks, go-karting — excluded by default)
zomato restaurant-events --include-activities

# Movies
zomato movies --city gurugram
```

### Party and nightlife discovery

`zomato party` combines District's main feed with a recursive crawl of every
linked venue guide. Venue pages are loaded through District's client-side API,
and event links found only inside venue rails are then crawled individually.
This finds listings that the curated `/events` page omits and enriches results
with descriptions, organizers, ticket offers, exact coordinates, venue hours,
facilities, policies, and menus.

```bash
# Weekend nightlife near explicit coordinates (highest precedence)
zomato party --when weekend --lat <LAT> --lng <LNG>

# Increase the distance radius
zomato party --when weekend --lat <LAT> --lng <LNG> --radius 25

# Skip the recursive page crawl when a faster, main-feed-only result is enough
zomato party --when weekend --no-crawl

# Require an explicit or previously saved location; never launch a browser
zomato party --no-location-detect
```

Party coordinates resolve in this order: a complete `--lat`/`--lng` pair,
the approved location saved by `zomato location set/detect`, then a browser
location prompt. Supplying only one explicit coordinate is an error. Use
`--no-location-detect` to disable the browser fallback.

Activities such as water parks and go-karting remain excluded. Individual-page
crawling is enabled by default. District access/refresh tokens may optionally
be supplied via `DISTRICT_ACCESS_TOKEN` and `DISTRICT_REFRESH_TOKEN`; otherwise
the unauthenticated guest web flow is used.

### Rating trends

Track how a restaurant's rating changes over time. Fetches historical
reviews, groups by month, and shows whether the trend is up, down, or
stable.

```bash
# Show rating trends for last 6 months
zomato trends --id 3116 --months 6

# Extended analysis
zomato trends --id 3116 --months 24
```

Output:
```
Cafe Festa — Current: 0★
  Rating trend (last 24 months):

  2019-06  ████████████░░░░░░░░░░░░░ 5.0  (20 reviews) ➡️
  2018-12  ███████░░░░░░░░░░░░░░░░░░ 3.0  (20 reviews) 📉
  2018-09  ██████░░░░░░░░░░░░░░░░░░░ 2.5  (40 reviews) 📉
  2018-07  ██████████░░░░░░░░░░░░░░░ 4.0  (20 reviews) 📈
```

### Popular dishes

Extracts dish mentions from review text and review tags.

```bash
# Most mentioned dishes
zomato dishes --id 308020 --limit 10
```

Output:
```
Most mentioned dishes at Krispy Kreme - Doughnuts & Coffee:

   1. Donut                ▓▓▓▓▓▓▓▓▓▓ 10 mentions 1.0★
   2. Chocolate            ▓▓▓▓▓▓▓▓▓▓ 10 mentions 1.0★
```

### Value for money

Calculates cost-per-rating to identify whether a restaurant is good value.

```bash
zomato value --id 308020
```

Output:
```
Krispy Kreme - Doughnuts & Coffee
  Rating:        3.8★
  Cost for two:  300
  Cost per ★:   78.95
  Verdict:       💚 great value
```

Verdicts:
- 💚 great value — cost per rating < 100
- 💛 good — cost per rating 100-200
- ❤️ pricey — cost per rating > 200

### Offers

```bash
zomato offers --id 308020
```

### Hygiene details

Shows Zomato's food hygiene audit sections for a restaurant.

```bash
zomato hygiene --id 308020
```

Output:
```
Hygiene details for Krispy Kreme - Doughnuts & Coffee:

  Valid until:   1st Jan'70
  Last audit:    1st Jan'70
  Premises and pest control
     Restaurant's license compliance status...
  Equipment and packaging
     Quality and upkeep of equipment...
  Raw material handling
     Procurement and storage of raw materials...
  Food processing
     Safety practices followed through cooking...
  Personal hygiene
     Standards of personal hygiene maintained...
  Water supply and disposal
     Quality of sourcing, supply utilities...
```

### Search & approved local location

```bash
# Auto-suggest search
zomato search pizza --city gurugram

# Ask the default browser for location permission and save the approved result
zomato location detect

# Inspect the saved record (also supports --json)
zomato location show

# Save validated coordinates without opening a browser
zomato location set --lat <LAT> --lng <LNG>

# Remove the saved record
zomato location clear

# Search Zomato's location entities
zomato location search Gurugram
```

Approved locations are stored at `~/.zomato-py/location.json`. Writes use an
atomic replacement and private file permissions where the operating system
supports them. Browser detection is platform-independent: it opens a minimal
page served temporarily on IPv4 loopback (`127.0.0.1`) and accepts one
state-protected callback. Coordinates are persisted only after a successful
browser permission callback. Permission denial, unavailable location services,
timeouts, and browser-launch failures leave the saved location unchanged.

### JSON output

All commands support `--json` for machine-readable output:

```bash
zomato reviews --id 308020 --json | jq .
zomato trends --id 3116 --json | jq .
```

## API reference

### `ZomatoClient`

```python
from zomato import Location, ZomatoClient

client = ZomatoClient(location=Location(lat=28.45, lng=77.02, city_id=12939))
```

#### Location

The approved-location persistence and browser-detection APIs are also exported
from the package root:

```python
from zomato import BrowserLocationDetector, LocationRecord, LocationStore

store = LocationStore()  # ~/.zomato-py/location.json
saved = store.load()
if saved is None:
    saved = BrowserLocationDetector(store=store).detect(timeout=60)
```

`LocationError`, `LocationStorageError`, and `LocationDetectionError` are public
for callers that need to handle persistence and browser-approval failures.

| Method | Description |
|--------|-------------|
| `search_location(query)` | Search for Zomato location entities |
| `get_location(lat, lng)` | Get location details for coordinates |

#### Restaurants

| Method | Description |
|--------|-------------|
| `search_restaurants(city, context)` | Search restaurants (delivery, dineout, nightlife) |
| `get_restaurant(res_id)` | Get full restaurant details |
| `get_collections(city)` | Get curated collections for a city |
| `auto_suggest(query)` | Get search auto-suggestions |

#### Reviews

| Method | Description |
|--------|-------------|
| `get_reviews(res_id, limit)` | Get paginated reviews with rating, text, tags |
| `get_rating_trends(res_id, months)` | Monthly avg rating with trend direction |
| `get_popular_dishes(res_id, limit)` | Most mentioned dishes from reviews |

#### Events (District by Zomato)

| Method | Description |
|--------|-------------|
| `get_events(city, when, category)` | Get events with filtering |
| `get_restaurant_events(city, when, query)` | Group events by restaurant/venue |
| `get_movies(city)` | Get movies from District |

#### Extra features

| Method | Description |
|--------|-------------|
| `get_restaurant_offers(res_id)` | Active offers/discounts |
| `get_hygiene_details(res_id)` | Food hygiene audit data |
| `get_value_for_money(res_id)` | Cost-per-rating value analysis |
| `get_dining_slots(res_id, date)` | Available table time slots |
| `get_menu(res_id)` | Full restaurant menu |

#### Utility

| Method | Description |
|--------|-------------|
| `set_location(city, lat, lng)` | Update client location |

### Event classification

Events are automatically classified into categories:
- Comedy — standup, comedy, laugh
- Live Music — live, concert, acoustic, band, qawwal
- Party / Nightlife — party, club, DJ, night
- Food & Drink — brunch, culinary, festival, tasting
- Theatre / Performance — theatre, play, performance
- Watch Party — screening, watch party
- Activity / Adventure — water park, go-karting, arcade

### Event fields

Each event dict contains: title, venue, city, locality, date, description,
tag_line, category, price, min_price, rating, review_count, image_url, url,
start_epoch, end_epoch, is_activity, address, offer_string,
popularity_score, number_attended, distance, lat, long, date_string_v2.

## Persistent session

The client saves CSRF tokens and cookies to `~/.zomato-py/session.json`
automatically. Subsequent runs reuse the cached session, avoiding
unnecessary CSRF token fetches. The session expires after 30 minutes and
is refreshed automatically.

## How it works

1. **CSRF**: Acquires a token from `/webroutes/auth/csrf`, sends it as
   header `x-zomato-csrft` on requests that need it.
2. **Location**: The `locus` cookie (JSON with cityId, lat, lng) determines
   the user's city. Server-side IP geolocation may override this for
   restaurant search results.
3. **Restaurant search**: `/webroutes/getPage?url=/{city}/restaurants`
   returns `SECTION_SEARCH_RESULT` with restaurant cards.
4. **Reviews**: `/webroutes/reviews/loadMore` returns reviews in
   `entities.REVIEWS` keyed by review ID. Each review has `ratingV2`,
   `reviewText`, `timestamp`, `reviewTags`, and `experience` type.
5. **Events**: District.in uses Next.js RSC (React Server Components).
   Data streams via `self.__next_f.push()` payloads. Event data is
   extracted from `ItemDetails` blocks (EventData, VenueData, ArtistData).

## Limitations

- Restaurant search results are IP-geolocated — the server assigns a
  delivery subzone (dszId) based on IP, not the `locus` cookie. Search may
  return restaurants from a nearby subzone rather than the exact city
  center. Restaurant details, reviews, and events are not affected.
- No authentication — user-specific endpoints (orders, bookmarks,
  profile) require login and are not supported.
- Event data depends on District.in's RSC payload format, which may
  change without notice.

## Testing

```bash
# Unit tests (mocked, no network)
python -m pytest tests/test_client.py -q

# Live smoke tests (real API calls)
ZOMATO_LIVE=1 python -m pytest tests/test_smoke.py -q
```

## License

MIT