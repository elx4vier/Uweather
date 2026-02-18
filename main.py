import json
import urllib.request
import urllib.parse
import time
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

# =========================
# ⚡ CONFIG
# =========================
CACHE = {}
CACHE_TTL = 600
DEBOUNCE_DELAY = 0.4
LAST_QUERY_TIME = 0
LAST_ACTION = None  # Armazena a última ação para referência (não usado mais no debounce)

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
# 🏳 COUNTRY FLAG
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
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except:
        return None

# =========================
# 📍 GEOLOCATION
# =========================
def geocode_city(city):
    cache_key = f"geo-{city.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        result = (
            r["latitude"],
            r["longitude"],
            r["name"],
            r.get("country_code", "")
        )
        set_cache(cache_key, result)
        return result
    return None, None, None, None

def get_ip_location():
    cached = get_cache("ip-location")
    if cached:
        return cached
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        result = (
            data["lat"],
            data["lon"],
            data["city"],
            data["countryCode"]
        )
        set_cache("ip-location", result)
        return result
    return None, None, None, None

# =========================
# 🌤 WEATHER (OPEN-METEO)
# =========================
WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Snow",
    95: "Thunderstorm"
}

def get_weather(lat, lon, unit):
    cache_key = f"weather-{lat}-{lon}-{unit}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    temp_unit = "celsius" if unit == "metric" else "fahrenheit"
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current_weather=true"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit={temp_unit}"
        f"&timezone=auto"
    )
    data = get_json(url)
    if not data:
        return None
    current = data.get("current_weather")
    daily = data.get("daily")
    if not current or not daily:
        return None
    result = {
        "current_temp": current.get("temperature"),
        "current_desc": WMO.get(current.get("weathercode")),
        "forecast": []
    }
    try:
        for i in range(1, 4):
            result["forecast"].append(
                f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}"
            )
    except:
        pass
    set_cache(cache_key, result)
    return result

# =========================
# 🚀 EXTENSION
# =========================
class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())

class WeatherHandler(EventListener):
    def on_event(self, event, extension):
        global LAST_QUERY_TIME, LAST_ACTION
        now = time.time()

        # ✅ DEBOUNCE: sempre mostra "Buscando..." enquanto digita
        if now - LAST_QUERY_TIME < DEBOUNCE_DELAY:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Buscando...",
                    description="Aguarde enquanto processamos sua consulta",
                    on_enter=DoNothingAction()
                )
            ])

        LAST_QUERY_TIME = now
        unit = extension.preferences.get("unit", "metric")
        query = event.get_argument()

        # =========================
        # 📍 LOCALIZAÇÃO
        # =========================
        if query:
            lat, lon, city, country = geocode_city(query)
            if not lat:
                action = RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Cidade não encontrada",
                        description="Digite uma cidade válida",
                        on_enter=DoNothingAction()
                    )
                ])
                LAST_ACTION = action
                return action
        else:
            lat, lon, city, country = get_ip_location()
            if not lat:
                action = RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Não foi possível encontrar sua localização",
                        description="Verifique sua conexão com a internet",
                        on_enter=DoNothingAction()
                    )
                ])
                LAST_ACTION = action
                return action

        # =========================
        # 🌤 WEATHER
        # =========================
        weather = get_weather(lat, lon, unit)
        if not weather:
            action = RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro ao buscar clima",
                    description="Tente novamente em instantes",
                    on_enter=DoNothingAction()
                )
            ])
            LAST_ACTION = action
            return action

        symbol = "°C" if unit == "metric" else "°F"
        flag = country_flag(country)

        if weather["current_desc"]:
            first_line = f"{weather['current_temp']}{symbol} - {weather['current_desc']}"
        else:
            first_line = f"{weather['current_temp']}{symbol}"

        desc = (
            f"{first_line}\n"
            f"Próximos dias: {' | '.join(weather['forecast'])}"
        )

        action = RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{flag} {city}, {country}",
                description=desc,
                on_enter=DoNothingAction()
            )
        ])
        LAST_ACTION = action
        return action

if __name__ == "__main__":
    UWeatherExtension().run()
