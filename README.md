<div align="center">

<img src="https://via.placeholder.com/120x120.png?text=Zomato" alt="zomato-py logo" width="120" height="120" />

# zomato-py

**Unofficial Python client for Zomato's web API. No API key required.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/The-Great-One/zomato-py)](https://github.com/The-Great-One/zomato-py/issues)
[![GitHub pull requests](https://img.shields.io/github/issues-pr/The-Great-One/zomato-py)](https://github.com/The-Great-One/zomato-py/pulls)
[![GitHub stars](https://img.shields.io/github/stars/The-Great-One/zomato-py?style=social)](https://github.com/The-Great-One/zomato-py/stargazers)

[Report Bug](https://github.com/The-Great-One/zomato-py/issues/new?template=bug_report.md) · [Request Feature](https://github.com/The-Great-One/zomato-py/issues/new?template=feature_request.md)

</div>

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)
- [Acknowledgments](#acknowledgments)

---

## About

`zomato-py` is an unofficial Python client for Zomato's web API. No API key
required — reverse-engineered from Zomato's web frontend. Discover restaurants,
read reviews, browse collections, find events, track rating trends, extract
popular dishes, and more.

## Features

- ✅ Discover restaurants, read reviews, browse collections
- ✅ Find events (District by Zomato), track rating trends
- ✅ Extract popular dishes, value-for-money analysis
- ✅ Hygiene details, dining slots, menus, offers
- ✅ Persistent session (CSRF + cookies, auto-refresh)
- ✅ Location detection via browser (loopback callback)
- ✅ `--json` output on all commands
- ✅ No authentication required (guest-first)

## Getting Started

### Prerequisites

- Python 3.10+

### Installation

```bash
git clone https://github.com/The-Great-One/zomato-py.git
cd zomato-py
pip install -e .
```

The CLI is symlinked to `/usr/local/bin/zomato` after install.

## Usage

### Quick start

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

### CLI usage

```
zomato --help
```

#### Restaurants

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

#### Events

```bash
# All upcoming events
zomato events --city gurugram

# Events today
zomato events --city gurugram --when today

# Filter by keyword
zomato events --query comedy

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

#### Party and nightlife discovery

`zomato party` combines District's main feed with a recursive crawl of every
linked venue guide.

```bash
# Weekend nightlife near explicit coordinates
zomato party --when weekend --lat <LAT> --lng <LNG>

# Increase the distance radius
zomato party --when weekend --lat <LAT> --lng <LNG> --radius 25

# Skip the recursive page crawl
zomato party --when weekend --no-crawl

# Require an explicit or previously saved location
zomato party --no-location-detect
```

#### Rating trends

```bash
# Show rating trends for last 6 months
zomato trends --id 3116 --months 6

# Extended analysis
zomato trends --id 3116 --months 24
```

#### Popular dishes

```bash
# Most mentioned dishes
zomato dishes --id 308020 --limit 10
```

#### Value for money

```bash
zomato value --id 308020
```

#### Offers

```bash
zomato offers --id 308020
```

#### Hygiene details

```bash
zomato hygiene --id 308020
```

#### Search & approved local location

```bash
# Auto-suggest search
zomato search pizza --city gurugram

# Ask the default browser for location permission
zomato location detect

# Inspect the saved record
zomato location show

# Save validated coordinates
zomato location set --lat <LAT> --lng <LNG>

# Remove the saved record
zomato location clear

# Search Zomato's location entities
zomato location search Gurugram
```

#### JSON output

All commands support `--json` for machine-readable output:

```bash
zomato reviews --id 308020 --json | jq .
zomato trends --id 3116 --json | jq .
```

### API reference

#### `ZomatoClient`

```python
from zomato import Location, ZomatoClient

client = ZomatoClient(location=Location(lat=28.45, lng=77.02, city_id=12939))
```

##### Location

```python
from zomato import BrowserLocationDetector, LocationRecord, LocationStore

store = LocationStore()  # ~/.zomato-py/location.json
saved = store.load()
if saved is None:
    saved = BrowserLocationDetector(store=store).detect(timeout=60)
```

##### Restaurants

| Method | Description |
|--------|-------------|
| `search_restaurants(city, context)` | Search restaurants (delivery, dineout, nightlife) |
| `get_restaurant(res_id)` | Get full restaurant details |
| `get_collections(city)` | Get curated collections for a city |
| `auto_suggest(query)` | Get search auto-suggestions |

##### Reviews

| Method | Description |
|--------|-------------|
| `get_reviews(res_id, limit)` | Get paginated reviews with rating, text, tags |
| `get_rating_trends(res_id, months)` | Monthly avg rating with trend direction |
| `get_popular_dishes(res_id, limit)` | Most mentioned dishes from reviews |

##### Events (District by Zomato)

| Method | Description |
|--------|-------------|
| `get_events(city, when, category)` | Get events with filtering |
| `get_restaurant_events(city, when, query)` | Group events by restaurant/venue |
| `get_movies(city)` | Get movies from District |

##### Extra features

| Method | Description |
|--------|-------------|
| `get_restaurant_offers(res_id)` | Active offers/discounts |
| `get_hygiene_details(res_id)` | Food hygiene audit data |
| `get_value_for_money(res_id)` | Cost-per-rating value analysis |
| `get_dining_slots(res_id, date)` | Available table time slots |
| `get_menu(res_id)` | Full restaurant menu |

##### Utility

| Method | Description |
|--------|-------------|
| `set_location(city, lat, lng)` | Update client location |

### Event classification

Events are automatically classified into categories: Comedy, Live Music,
Party / Nightlife, Food & Drink, Theatre / Performance, Watch Party,
Activity / Adventure.

### Persistent session

The client saves CSRF tokens and cookies to `~/.zomato-py/session.json`
automatically. Subsequent runs reuse the cached session. The session expires
after 30 minutes and is refreshed automatically.

### How it works

1. **CSRF**: Acquires a token from `/webroutes/auth/csrf`.
2. **Location**: The `locus` cookie determines the user's city.
3. **Restaurant search**: `/webroutes/getPage` returns `SECTION_SEARCH_RESULT`.
4. **Reviews**: `/webroutes/reviews/loadMore` returns reviews in
   `entities.REVIEWS`.
5. **Events**: District.in uses Next.js RSC; data streams via
   `self.__next_f.push()` payloads.

### Limitations

- Restaurant search results are IP-geolocated.
- No authentication — user-specific endpoints are not supported.
- Event data depends on District.in's RSC payload format.

### Testing

```bash
# Unit tests (mocked, no network)
python -m pytest tests/test_client.py -q

# Live smoke tests (real API calls)
ZOMATO_LIVE=1 python -m pytest tests/test_smoke.py -q
```

## Roadmap

- [x] v0.1 – Restaurant search, details, reviews
- [x] v0.1 – Events, rating trends, popular dishes
- [ ] v0.2 – Packaged release
- [ ] v1.0 – Stable API

See the open issues for the full list of proposed features and known bugs.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and
follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

## Contact

Sahil Goel – [@The-Great-One](https://github.com/The-Great-One) –
sahilgoel187@gmail.com

Project link: [https://github.com/The-Great-One/zomato-py](https://github.com/The-Great-One/zomato-py)

## Acknowledgments

- [Img Shields](https://shields.io)
- [Contributor Covenant](https://www.contributor-covenant.org)
