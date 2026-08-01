"""CLI tests for local location management and party coordinate resolution."""

from __future__ import annotations

import argparse
import json
from unittest.mock import Mock, patch

import pytest

from zomato.cli import (
    _resolve_party_coordinates,
    build_parser,
    cmd_location_clear,
    cmd_location_detect,
    cmd_location_set,
    cmd_location_show,
    cmd_party,
)
from zomato.location import LocationDetectionError, LocationRecord


SAFE_LATITUDE = 12.25
SAFE_LONGITUDE = 34.5
APPROVED_AT = "2026-08-01T12:00:00+00:00"


def approved(source="manual"):
    return LocationRecord(
        latitude=SAFE_LATITUDE,
        longitude=SAFE_LONGITUDE,
        accuracy=20,
        source=source,
        approved_at=APPROVED_AT,
    )


def party_args(**changes):
    values = {
        "lat": None,
        "lng": None,
        "no_location_detect": False,
        "location_timeout": 60.0,
        "city": "gurugram",
        "radius": 15,
        "when": "weekend",
        "no_offers": False,
        "no_crawl": False,
        "json": False,
    }
    values.update(changes)
    return argparse.Namespace(**values)


def test_party_explicit_complete_pair_takes_precedence():
    store = Mock()
    detector = Mock()

    coordinates = _resolve_party_coordinates(
        party_args(lat=1.25, lng=2.5), store=store, detector=detector
    )

    assert coordinates == (1.25, 2.5)
    store.load.assert_not_called()
    detector.detect.assert_not_called()


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(SAFE_LATITUDE, None), (None, SAFE_LONGITUDE)],
)
def test_party_partial_explicit_pair_is_an_error(lat, lng):
    with pytest.raises(ValueError, match="together"):
        _resolve_party_coordinates(party_args(lat=lat, lng=lng), store=Mock(), detector=Mock())


def test_party_persisted_location_prevents_browser_launch():
    store = Mock()
    store.load.return_value = approved()
    detector = Mock()

    coordinates = _resolve_party_coordinates(party_args(), store=store, detector=detector)

    assert coordinates == (SAFE_LATITUDE, SAFE_LONGITUDE)
    detector.detect.assert_not_called()


def test_party_missing_location_triggers_browser_detector():
    store = Mock()
    store.load.return_value = None
    detector = Mock()
    detector.detect.return_value = approved(source="browser")

    coordinates = _resolve_party_coordinates(party_args(), store=store, detector=detector)

    assert coordinates == (SAFE_LATITUDE, SAFE_LONGITUDE)
    detector.detect.assert_called_once_with(timeout=60.0)


def test_party_no_detect_failure_explains_all_location_options():
    store = Mock()
    store.load.return_value = None

    with pytest.raises(ValueError) as exc:
        _resolve_party_coordinates(
            party_args(no_location_detect=True), store=store, detector=Mock()
        )

    message = str(exc.value)
    assert "--lat/--lng" in message
    assert "zomato location set" in message
    assert "zomato location detect" in message


def test_party_detection_failure_explains_manual_fallbacks():
    store = Mock()
    store.load.return_value = None
    detector = Mock()
    detector.detect.side_effect = LocationDetectionError("permission denied")

    with pytest.raises(ValueError) as exc:
        _resolve_party_coordinates(party_args(), store=store, detector=detector)

    message = str(exc.value)
    assert "permission denied" in message
    assert "--lat/--lng" in message
    assert "zomato location set/detect" in message


def test_party_forwards_resolved_coordinates_to_find_party_places():
    client = Mock()
    client.find_party_places.return_value = []
    persisted = approved()

    with (
        patch("zomato.cli.ZomatoClient", return_value=client),
        patch("zomato.cli.LocationStore") as store_class,
        patch("zomato.cli.BrowserLocationDetector") as detector_class,
    ):
        store_class.return_value.load.return_value = persisted
        cmd_party(party_args())

    detector_class.return_value.detect.assert_not_called()
    client.set_location.assert_any_call(lat=SAFE_LATITUDE, lng=SAFE_LONGITUDE)
    assert client.find_party_places.call_args.kwargs["lat"] == SAFE_LATITUDE
    assert client.find_party_places.call_args.kwargs["lng"] == SAFE_LONGITUDE


def test_parser_exposes_location_commands_and_party_detection_controls():
    parser = build_parser()

    detect = parser.parse_args(["location", "detect", "--timeout", "4", "--json"])
    assert detect.func is cmd_location_detect
    assert detect.timeout == 4
    assert detect.json is True

    show = parser.parse_args(["location", "show", "--json"])
    assert show.func is cmd_location_show

    set_args = parser.parse_args(
        ["location", "set", "--lat", "1", "--lng", "2", "--accuracy", "3", "--json"]
    )
    assert set_args.func is cmd_location_set

    clear = parser.parse_args(["location", "clear", "--json"])
    assert clear.func is cmd_location_clear

    party = parser.parse_args(["party", "--no-location-detect", "--location-timeout", "5"])
    assert party.no_location_detect is True
    assert party.location_timeout == 5


def test_location_set_show_detect_and_clear_emit_json(capsys):
    store = Mock()
    detector = Mock()
    detector.detect.return_value = approved(source="browser")

    with (
        patch("zomato.cli.LocationStore", return_value=store),
        patch("zomato.cli.BrowserLocationDetector", return_value=detector),
    ):
        cmd_location_set(
            argparse.Namespace(
                lat=SAFE_LATITUDE, lng=SAFE_LONGITUDE, accuracy=10, json=True
            )
        )
        set_output = json.loads(capsys.readouterr().out)
        saved = store.save.call_args.args[0]
        assert saved.source == "manual"
        assert set_output["source"] == "manual"

        store.load.return_value = saved
        cmd_location_show(argparse.Namespace(json=True))
        assert json.loads(capsys.readouterr().out) == saved.to_dict()

        cmd_location_detect(argparse.Namespace(timeout=3, json=True))
        assert json.loads(capsys.readouterr().out)["source"] == "browser"
        detector.detect.assert_called_once_with(timeout=3)

        store.clear.return_value = True
        cmd_location_clear(argparse.Namespace(json=True))
        assert json.loads(capsys.readouterr().out) == {"cleared": True}


def test_location_show_missing_is_clear_error():
    with patch("zomato.cli.LocationStore") as store_class:
        store_class.return_value.load.return_value = None
        with pytest.raises(ValueError, match="No approved location"):
            cmd_location_show(argparse.Namespace(json=True))
