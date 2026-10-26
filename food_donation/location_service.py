"""Verifies pickup locations with the free Open-Meteo Geocoding API
(https://geocoding-api.open-meteo.com, no API key needed).

The coordinates are stored with each donation so the final app can show
donations on a map or sort them by distance from a volunteer.
"""
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from .exceptions import (
    APIUnavailableError,
    InvalidAPIResponseError,
    LocationNotFoundError,
    LocationServiceError,
    NetworkError,
)


class LocationService:
    BASE_URL = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(self, timeout=5):
        self.timeout = timeout

    def verify(self, location):
        """Return {'name', 'state', 'country', 'latitude', 'longitude'} for a place.
        'Anna Nagar, Chennai' is tried as given, then as 'Chennai'."""
        candidates = [location]
        if "," in location:
            candidates.append(location.rsplit(",", 1)[1].strip())
        for place in candidates:
            if len(place) < 2:
                continue
            try:
                return self._lookup(place)
            except LocationNotFoundError:
                continue
        raise LocationNotFoundError(f"'{location}' was not found on the map.")

    def _lookup(self, place):
        query = urllib.parse.urlencode({"name": place, "count": 1, "language": "en", "format": "json"})
        data = self._get_json(f"{self.BASE_URL}?{query}")
        if not isinstance(data, dict):
            raise InvalidAPIResponseError("Unexpected response from the location service.")
        if data.get("error"):
            raise APIUnavailableError(f"Location service error: {data.get('reason', 'unknown')}")
        results = data.get("results")
        if not results:
            raise LocationNotFoundError(f"'{place}' was not found.")
        if not isinstance(results, list) or not isinstance(results[0], dict):
            raise InvalidAPIResponseError("Unexpected response from the location service.")
        best = results[0]
        try:
            return {
                "name": str(best["name"]),
                "state": best.get("admin1") or "",
                "country": best.get("country") or "",
                "latitude": round(float(best["latitude"]), 4),
                "longitude": round(float(best["longitude"]), 4),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidAPIResponseError("Location data was incomplete.") from error

    def _get_json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "FoodDonationPrototype/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 429 or error.code >= 500:
                raise APIUnavailableError(f"Location service unavailable (HTTP {error.code}).") from error
            raise LocationServiceError(f"Location service rejected the request (HTTP {error.code}).") from error
        except (socket.timeout, TimeoutError) as error:
            raise NetworkError("Location service timed out.") from error
        except urllib.error.URLError as error:
            raise NetworkError(f"Could not reach the location service ({error.reason}).") from error
        except OSError as error:
            raise NetworkError(f"Network error: {error}") from error
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidAPIResponseError("Location service sent invalid JSON.") from error


class OfflineLocationService:
    """Stand-in used for tests or when running without internet."""

    def verify(self, location):
        raise NetworkError("Location check is turned off.")
