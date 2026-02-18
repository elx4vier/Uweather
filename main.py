import json
import urllib.request
import urllib.parse
import time
import math

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.ActionThread import ActionThread
from ulauncher.api.shared.event import KeywordQueryEvent

from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction


CACHE = {}
CACHE_TTL = 600
EARTH_RADIUS_KM = 6371


# =========================
# CACHE
# =========================

def get_cache(key):
    entry = CACHE.get(key)
    if entry and time.time() - entry["time"] < CACHE_TTL:
        return entry["data"]
    return None


def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}


# =========================
# HAVERSINE
# =========================

def haversine(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (
            math.sin(dlat / 2) ** 2 +
            math.cos(lat1) *
            math.cos(lat2) *
            math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))
        return EARTH_RADIUS_KM * c
    except Exception:
        return 999999


# =========================
# FLAG
# =========================

def country_flag(code):
    if not code:
        return ""
    return "".join(chr(127397 + ord(c)) for c in code.upper())


# =========================
# HTTP REQUEST
# =========================

def get_json(url):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


# =========================
# IP LOCATION
# =========================

def get_ip_location():
    cached = get_cache("ip")
    if cached:
        return cached

    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        result = (data.get("lat"), data.get("lon"), data.get("city"))
        set_cache("ip", result)
        return result

    return None, None, None


# =========================
# GEOCODE
# =========================

def geocode_city(query):
    key = f"geo-{query.lower()}"
    cached = get_cache(key)
    if cached:
        return cached

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=5"
    )

    data = get_json(url)
    results = data.get("results") if data else None

    if not results:
        return []

    set_cache(key, results)
    return results


# =========================
# WEATHER (Open-Meteo)
# =========================

def get_weather(lat, lon, unit):

    key = f"weather-{lat}-{lon}-{unit}"
    cached = get_cache(key)
    if cached:
        return cached

    temp_unit = "celsius" if unit == "metric" else "fahrenheit"

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current_weather=true"
        f"&temperature_unit={temp_unit}"
        "&timezone=auto"
    )

    data = get_json(url)
    if not data:
        return None

    current = data.get("current_weather")
    if not current:
        return None

    temp = current.get("temperature")

    if temp is not None:
        set_cache(key, temp)

    return temp


# =========================
# EXTENSION
# =========================

class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())


class WeatherHandler(EventListener):

    def on_event(self, event, extension):

        query = (event.get_argument() or "").strip()
        unit = extension.preferences.get("unit", "metric")
        symbol = "°C" if unit == "metric" else "°F"

        if not query:
            extension.run_thread(
                ActionThread(self.show_nearby, extension, unit, symbol)
            )

            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Detectando sua cidade...",
                    description="Aguarde...",
                    on_enter=DoNothingAction()
                )
            ])

        extension.run_thread(
            ActionThread(
                self.search_and_render,
                extension,
                query,
                unit,
                symbol
            )
        )

        return RenderResultListAction([
            SmallResultItem(
                icon='images/icon.png',
                name=f"Buscando: {query}",
                description="Refinando resultados...",
                on_enter=DoNothingAction()
            )
        ])

    # =========================

    def show_nearby(self, extension, unit, symbol):
        try:
            lat, lon, city_name = get_ip_location()

            if lat is None:
                extension.set_results([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Erro de localização",
                        description="Não foi possível detectar sua cidade",
                        on_enter=DoNothingAction()
                    )
                ])
                return

            cities = geocode_city(city_name)
            items = []

            for city in cities[:3]:

                temp = get_weather(
                    city["latitude"],
                    city["longitude"],
                    unit
                )

                if temp is None:
                    continue

                flag = country_flag(city.get("country_code"))

                items.append(
                    ExtensionResultItem(
                        icon='images/icon.png',
                        name=f"{flag} {city['name']} ({city['country_code']})",
                        description=f"{temp}{symbol}",
                        on_enter=DoNothingAction()
                    )
                )

            extension.set_results(items or [
                SmallResultItem(
                    icon='images/icon.png',
                    name="Sem dados disponíveis",
                    description="Não foi possível obter previsão",
                    on_enter=DoNothingAction()
                )
            ])

        except Exception as e:
            extension.set_results([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro interno",
                    description=str(e),
                    on_enter=DoNothingAction()
                )
            ])

    # =========================

    def search_and_render(self, extension, query, unit, symbol):
        try:
            user_lat, user_lon, _ = get_ip_location()
            cities = geocode_city(query)

            if not cities:
                extension.set_results([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Cidade não encontrada",
                        description="Verifique a grafia",
                        on_enter=DoNothingAction()
                    )
                ])
                return

            if user_lat is not None:
                cities.sort(
                    key=lambda c: haversine(
                        user_lat,
                        user_lon,
                        c["latitude"],
                        c["longitude"]
                    )
                )

            items = []

            for city in cities:

                temp = get_weather(
                    city["latitude"],
                    city["longitude"],
                    unit
                )

                if temp is None:
                    continue

                flag = country_flag(city.get("country_code"))
                admin = city.get("admin1")

                label = (
                    f"{city['name']} ({admin}) ({city['country_code']})"
                    if admin else
                    f"{city['name']} ({city['country_code']})"
                )

                items.append(
                    ExtensionResultItem(
                        icon='images/icon.png',
                        name=f"{flag} {label}",
                        description=f"{temp}{symbol}",
                        on_enter=DoNothingAction()
                    )
                )

            extension.set_results(items)

        except Exception as e:
            extension.set_results([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro interno",
                    description=str(e),
                    on_enter=DoNothingAction()
                )
            ])


if __name__ == "__main__":
    UWeatherExtension().run()
