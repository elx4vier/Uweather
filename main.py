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
# ⚡ CACHE
# =========================

CACHE = {}
CACHE_TTL = 600


def get_cache(key):
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
    return None


def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}


# =========================
# 🌤 WMO DESCRIPTIONS
# =========================

WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Heavy rain showers",
    95: "Thunderstorm"
}


# =========================
# 🌐 REQUEST
# =========================

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as response:
            return json.loads(response.read().decode())
    except:
        return None


# =========================
# 📍 GEOLOCATION
# =========================

def geocode_city(city):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)

    if data and data.get("results"):
        r = data["results"][0]
        return r["latitude"], r["longitude"], r["name"], r.get("country_code", "")

    return None, None, None, None


def get_ip_location():
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        return data["lat"], data["lon"], data["city"], data["countryCode"]
    return None, None, None, None


# =========================
# ☁ OPENWEATHER
# =========================

def get_openweather(lat, lon, unit, api_key, lang):

    units = "metric" if unit == "metric" else "imperial"

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast?"
        f"lat={lat}&lon={lon}&units={units}&appid={api_key}&lang={lang}"
    )

    data = get_json(url)
    if not data or "list" not in data:
        return None

    current = data["list"][0]
    forecasts = data["list"][8:32:8]

    result = {
        "current_temp": current["main"]["temp"],
        "current_desc": current["weather"][0]["description"],
        "forecast": []
    }

    for f in forecasts[:3]:
        result["forecast"].append({
            "temp": f["main"]["temp"]
        })

    return result


# =========================
# 🌤 OPEN-METEO
# =========================

def get_open_meteo(lat, lon, unit):

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

    current = data["current_weather"]
    daily = data["daily"]

    desc = WMO.get(current["weathercode"], "Weather")

    result = {
        "current_temp": current["temperature"],
        "current_desc": desc,
        "forecast": []
    }

    for i in range(1, 4):
        result["forecast"].append({
            "temp": f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}"
        })

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

        prefs = extension.preferences
        provider = prefs.get("provider", "open-meteo")
        unit = prefs.get("unit", "metric")
        api_key = prefs.get("api_key", "")
        lang = prefs.get("language", "en")

        query = event.get_argument()

        # =========================
        # 📍 DEFINE LOCALIZAÇÃO
        # =========================

        if query:
            lat, lon, city, country = geocode_city(query)
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Cidade não encontrada",
                        description="Digite uma cidade válida para continuar",
                        on_enter=DoNothingAction()
                    )
                ])
        else:
            lat, lon, city, country = get_ip_location()
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Falha na localização",
                        description="Não foi possível detectar sua localização",
                        on_enter=DoNothingAction()
                    )
                ])

        location_name = f"{city}, {country}" if country else city

        # =========================
        # ☁ BUSCAR CLIMA
        # =========================

        cache_key = f"{provider}-{lat}-{lon}-{unit}"
        weather = get_cache(cache_key)

        if not weather:

            if provider == "openweather":
                if not api_key:
                    return RenderResultListAction([
                        SmallResultItem(
                            icon='images/icon.png',
                            name="Missing OpenWeather API key",
                            description="Add your API key in settings",
                            on_enter=DoNothingAction()
                        )
                    ])
                weather = get_openweather(lat, lon, unit, api_key, lang)
            else:
                weather = get_open_meteo(lat, lon, unit)

            if weather:
                set_cache(cache_key, weather)

        if not weather:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro ao buscar clima",
                    description="Tente novamente",
                    on_enter=DoNothingAction()
                )
            ])

        symbol = "°C" if unit == "metric" else "°F"

        forecast = " | ".join(f"{f['temp']}" for f in weather["forecast"])

        desc = (
            f"{weather['current_temp']}{symbol} - {weather['current_desc']}\n"
            f"Próximos dias: {forecast}"
        )

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"📍 {location_name}",
                description=desc,
                on_enter=DoNothingAction()
            )
        ])


if __name__ == "__main__":
    UWeatherExtension().run()
