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


# =========================
# ⚡ CACHE
# =========================

def get_cache(key):
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
    return None


def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}


# =========================
# 📏 DISTÂNCIA (para priorizar cidades próximas)
# =========================

def distance(lat1, lon1, lat2, lon2):
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


# =========================
# 🏳 BANDEIRA
# =========================

def country_flag(code):
    if not code:
        return ""
    return "".join(chr(127397 + ord(c)) for c in code.upper())


# =========================
# 🌐 REQUEST
# =========================

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.loads(response.read().decode())
    except:
        return None


# =========================
# 📍 LOCALIZAÇÃO DO USUÁRIO
# =========================

def get_ip_location():
    cached = get_cache("ip")
    if cached:
        return cached

    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        result = (data["lat"], data["lon"])
        set_cache("ip", result)
        return result

    return None, None


# =========================
# 🌍 BUSCAR MÚLTIPLAS CIDADES
# =========================

def geocode_city_multiple(city):

    cache_key = f"geo-{city.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=5"
    data = get_json(url)

    if not data or not data.get("results"):
        return []

    results = data["results"]
    set_cache(cache_key, results)
    return results


# =========================
# 🌤 WEATHER
# =========================

def get_weather(lat, lon, unit):

    temp_unit = "celsius" if unit == "metric" else "fahrenheit"

    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current_weather=true"
        f"&temperature_unit={temp_unit}"
        f"&timezone=auto"
    )

    data = get_json(url)
    if not data:
        return None

    return data["current_weather"]["temperature"]


# =========================
# 🚀 EXTENSION
# =========================

class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())


class WeatherHandler(EventListener):

    def on_event(self, event, extension):

        query = event.get_argument()
        unit = extension.preferences.get("unit", "metric")

        if not query:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Digite uma cidade...",
                    description="Ex: Viana",
                    on_enter=DoNothingAction()
                )
            ])

        # 🔥 Mostra instantâneo
        extension.run_thread(
            ActionThread(self.search_and_render, query, unit)
        )

        return RenderResultListAction([
            SmallResultItem(
                icon='images/icon.png',
                name="Buscando...",
                description="Carregando resultados...",
                on_enter=DoNothingAction()
            )
        ])

    # =========================
    # 🔥 THREAD REAL
    # =========================

    def search_and_render(self, query, unit):

        user_lat, user_lon = get_ip_location()
        cities = geocode_city_multiple(query)

        if not cities:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Cidade não encontrada",
                    description="Tente outro nome",
                    on_enter=DoNothingAction()
                )
            ])

        # 📍 ordenar por proximidade
        if user_lat:
            cities.sort(key=lambda c:
                distance(user_lat, user_lon, c["latitude"], c["longitude"])
            )

        items = []

        for city in cities[:5]:

            temp = get_weather(city["latitude"], city["longitude"], unit)
            if temp is None:
                continue

            symbol = "°C" if unit == "metric" else "°F"
            flag = country_flag(city.get("country_code"))

            items.append(
                ExtensionResultItem(
                    icon='images/icon.png',
                    name=f"{flag} {city['name']} ({city['country_code']})",
                    description=f"{temp}{symbol}",
                    on_enter=DoNothingAction()
                )
            )

        return RenderResultListAction(items)


if __name__ == "__main__":
    UWeatherExtension().run()
