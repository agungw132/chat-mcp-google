import pytest

from chat_google.mcp_servers import maps_server


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(ValueError):
        maps_server._get_api_key()


@pytest.mark.asyncio
async def test_search_places_text(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/place/textsearch/json"
        assert params["query"] == "Tatsu Mall of The Netherlands"
        return (
            {
                "results": [
                    {
                        "name": "Tatsu",
                        "formatted_address": "Mall of The Netherlands, Leidschendam",
                        "rating": 4.5,
                        "user_ratings_total": 123,
                        "place_id": "place-1",
                        "types": ["restaurant", "food", "point_of_interest"],
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.search_places_text("Tatsu Mall of The Netherlands", limit=1)
    assert "Places for 'Tatsu Mall of The Netherlands' (showing 1):" in result
    assert "Tatsu" in result
    assert "place-1" in result


@pytest.mark.asyncio
async def test_search_places_text_no_results(monkeypatch):
    async def fake_request_json(path, params=None):
        return {"results": []}, None

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.search_places_text("unknown place")
    assert result == "No places found for 'unknown place'"


@pytest.mark.asyncio
async def test_geocode_address(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/geocode/json"
        assert params["address"] == "Damrak 1 Amsterdam"
        return (
            {
                "results": [
                    {
                        "formatted_address": "Damrak 1, 1012 LG Amsterdam, Netherlands",
                        "place_id": "geo-1",
                        "types": ["street_address"],
                        "geometry": {"location": {"lat": 52.377, "lng": 4.898}},
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.geocode_address("Damrak 1 Amsterdam", limit=1)
    assert "Geocode results for 'Damrak 1 Amsterdam' (showing 1):" in result
    assert "LatLng: 52.377, 4.898" in result
    assert "geo-1" in result


@pytest.mark.asyncio
async def test_reverse_geocode(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/geocode/json"
        assert params["latlng"] == "52.377,4.898"
        return (
            {
                "results": [
                    {
                        "formatted_address": "Amsterdam, Netherlands",
                        "place_id": "rev-1",
                        "types": ["locality", "political"],
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.reverse_geocode(52.377, 4.898, limit=1)
    assert "Reverse geocode results for '52.377,4.898' (showing 1):" in result
    assert "Amsterdam, Netherlands" in result
    assert "rev-1" in result


@pytest.mark.asyncio
async def test_get_place_details(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/place/details/json"
        assert params["place_id"] == "place-1"
        return (
            {
                "result": {
                    "name": "Tatsu",
                    "place_id": "place-1",
                    "formatted_address": "Leidschendam, NL",
                    "formatted_phone_number": "+31 70 000 0000",
                    "international_phone_number": "+31 70 000 0000",
                    "website": "https://example.com",
                    "rating": 4.6,
                    "user_ratings_total": 99,
                    "opening_hours": {"open_now": True, "weekday_text": ["Mon: 10:00-22:00"]},
                    "geometry": {"location": {"lat": 52.1, "lng": 4.4}},
                    "url": "https://maps.google.com/?cid=123",
                    "types": ["restaurant", "food"],
                }
            },
            None,
        )

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.get_place_details("place-1")
    assert "Place Details:" in result
    assert "Name: Tatsu" in result
    assert "LatLng: 52.1, 4.4" in result
    assert "Open Now: True" in result


@pytest.mark.asyncio
async def test_get_directions(monkeypatch):
    async def fake_request_json(path, params=None):
        assert path == "/directions/json"
        assert params["origin"] == "Leiden"
        assert params["destination"] == "Rotterdam"
        return (
            {
                "routes": [
                    {
                        "summary": "A4",
                        "legs": [
                            {
                                "start_address": "Leiden, Netherlands",
                                "end_address": "Rotterdam, Netherlands",
                                "distance": {"value": 36000},
                                "duration": {"value": 2100},
                                "duration_in_traffic": {"value": 2700},
                            }
                        ],
                    }
                ]
            },
            None,
        )

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.get_directions(
        origin="Leiden",
        destination="Rotterdam",
        mode="driving",
        units="metric",
        departure_time="now",
    )
    assert "Directions from 'Leiden' to 'Rotterdam'" in result
    assert "A4" in result
    assert "Distance: 36.0 km" in result
    assert "Duration: 35m" in result
    assert "Map Link: https://www.google.com/maps/dir/?api=1" in result


@pytest.mark.asyncio
async def test_get_directions_validation_error():
    result = await maps_server.get_directions("A", "B", mode="flying")
    assert result.startswith("Error getting directions:")
    assert "Input should be" in result


@pytest.mark.asyncio
async def test_maps_tool_propagates_api_error(monkeypatch):
    async def fake_request_json(path, params=None):
        return None, "Error: Google Maps API status REQUEST_DENIED - API key invalid"

    monkeypatch.setattr(maps_server, "_request_json", fake_request_json)
    result = await maps_server.search_places_text("Tatsu")
    assert result == "Error: Google Maps API status REQUEST_DENIED - API key invalid"
