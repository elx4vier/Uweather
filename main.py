import json
import urllib.request
import urllib.parse
import time
import math

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.ActionThread import ActionThread
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item import ExtensionResultItem, SmallResultItem
from ulauncher.api.shared.action import RenderResultListAction, DoNothingAction


CACHE = {}
CACHE_TTL = 600


# =========================
# CACHE
# =========================

def get_cache(key):
    data = CACHE.get(key)
    if data and time.time() - data["time"] < CACHE_TTL:
        return data["data"]
    return None


def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}


# =========================
# DISTÂNCIA
# =========================

def distance(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


# =========================
# BANDEIRA
# =========================

def country_flag(code):
    if not code:
        return ""
    return "".join(chr(127397 + ord(c)) for c in code.upper())


# =========================
# REQUEST
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
# LOCALIZAÇÃO DO USUÁRIO
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

    cache_key = f"geo-{query.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=7"
    )

    data = get_json(url)

    if not data or not data.get("results"):
        return []

    results = data["results"]
    set_cache(cache_key, results)
    return results


# =========================
# WEATHER
# =========================

def get_weather(lat, lon, unit):

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

    return current.get("temperature")


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

        if not query:
            extension.run_thread(
                ActionThread(self.show_nearby, extension, unit)
            )

            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Detectando cidades próximas...",
                    description="Aguarde...",
                    on_enter=DoNothingAction()
                )
            ])

        extension.run_thread(
            ActionThread(self.search_and_render, extension, query, unit)
        )

        return RenderResultListAction([
            SmallResultItem(
                icon='images/icon.png',
                name=f"Buscando: {query}",
                description="Digite mais para refinar a busca",
                on_enter=DoNothingAction()
            )
        ])

    # =========================
    # MOSTRAR PRÓXIMAS
    # =========================

    def show_nearby(self, extension, unit):

        lat, lon, city_name = get_ip_location()

        if lat is None:
            extension.set_results([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro de localização",
                    description="Não foi possível detectar sua cidade atual",
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
            symbol = "°C" if unit == "metric" else "°F"

            items.append(
                ExtensionResultItem(
                    icon='images/icon.png',
                    name=f"{flag} {city['name']} ({city['country_code']})",
                    description=f"{temp}{symbol}",
                    on_enter=DoNothingAction()
                )
            )

        if not items:
            items.append(
                SmallResultItem(
                    icon='images/icon.png',
                    name="Sem dados disponíveis",
                    description="Não foi possível obter a previsão",
                    on_enter=DoNothingAction()
                )
            )

        extension.set_results(items)

    # =========================
    # BUSCA INTELIGENTE
    # =========================

    def search_and_render(self, extension, query, unit):

        user_lat, user_lon, _ = get_ip_location()
        cities = geocode_city(query)

        if not cities:
            extension.set_results([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Cidade não encontrada",
                    description="Verifique a grafia e tente novamente",
                    on_enter=DoNothingAction()
                )
            ])
            return

        if user_lat is not None:
            cities.sort(
                key=lambda c: distance(
                    user_lat,
                    user_lon,
                    c["latitude"],
                    c["longitude"]
                )
            )

        items = []

        for city in cities[:5]:

            temp = get_weather(
                city["latitude"],
                city["longitude"],
                unit
            )

            if temp is None:
                continue

            flag = country_flag(city.get("country_code"))
            symbol = "°C" if unit == "metric" else "°F"

            admin = city.get("admin1")
            location_label = (
                f"{city['name']} ({admin}) ({city['country_code']})"
                if admin else
                f"{city['name']} ({city['country_code']})"
            )

            items.append(
                ExtensionResultItem(
                    icon='images/icon.png',
                    name=f"{flag} {location_label}",
                    description=f"{temp}{symbol}",
                    on_enter=DoNothingAction()
                )
            )

        if not items:
            items.append(
                SmallResultItem(
                    icon='images/icon.png',
                    name="Sem dados disponíveis",
                    description="Não foi possível obter a previsão",
                    on_enter=DoNothingAction()
                )
            )

        extension.set_results(items)


if __name__ == "__main__":
    UWeatherExtension().run()
    
