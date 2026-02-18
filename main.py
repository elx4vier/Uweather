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


# =========================
# ⚡ CACHE SYSTEM
# =========================

CACHE = {}
CACHE_TTL = 600  # 10 minutes


def get_cache(key):
    if key in CACHE:
        if time.time() - CACHE[key]["time"] < CACHE_TTL:
            return CACHE[key]["data"]
    return None


def set_cache(key, data):
    CACHE[key] = {
        "time": time.time(),
        "data": data
    }


# =========================
# 🌍 INTERFACE TEXTS
# =========================

TEXTS = {
    "en": {"current": "Current weather", "forecast": "Forecast"},
    "pt": {"current": "Clima atual", "forecast": "Previsão"},
    "es": {"current": "Clima actual", "forecast": "Pronóstico"},
    "fr": {"current": "Météo actuelle", "forecast": "Prévision"},
    "ru": {"current": "Текущая погода", "forecast": "Прогноз"}
}


# =========================
# 🌤 WMO TRANSLATIONS
# =========================

WMO_TRANSLATIONS = {
    0: {
        "en": "Clear sky",
        "pt": "Céu limpo",
        "es": "Cielo despejado",
        "fr": "Ciel dégagé",
        "ru": "Ясно"
    },
    1: {
        "en": "Mainly clear",
        "pt": "Principalmente limpo",
        "es": "Mayormente despejado",
        "fr": "Principalement clair",
        "ru": "Преимущественно ясно"
    },
    2: {
        "en": "Partly cloudy",
        "pt": "Parcialmente nublado",
        "es": "Parcialmente nublado",
        "fr": "Partiellement nuageux",
        "ru": "Переменная облачность"
    },
    3: {
        "en": "Overcast",
        "pt": "Encoberto",
        "es": "Cubierto",
        "fr": "Couvert",
        "ru": "Пасмурно"
    }
}


# =========================
# 🌐 SAFE REQUEST
# =========================

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as response:
            return json.loads(response.read().decode())
    except:
        return None


# =========================
# 📍 LOCATION
# =========================

def get_ip_location():
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        return data["lat"], data["lon"], data["city"]
    return None, None, None


def geocode_city(city):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        return r["latitude"], r["longitude"], r["name"]
    return None, None, None


# =========================
# ☁ OPENWEATHER (WITH LANG)
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
            "temp": f["main"]["temp"],
            "desc": f["weather"][0]["description"]
        })

    return result


# =========================
# 🌤 OPEN-METEO (WITH WMO)
# =========================

def get_open_meteo(lat, lon, unit, lang):

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

    wmo_code = current["weathercode"]
    description = WMO_TRANSLATIONS.get(wmo_code, {}).get(lang, "Weather")

    result = {
        "current_temp": current["temperature"],
        "current_desc": description,
        "forecast": []
    }

    for i in range(1, 4):
        result["forecast"].append({
            "temp": f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}",
            "desc": ""
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

        provider = prefs.get("provider", "openweather")
        unit = prefs.get("unit", "metric")
        location_mode = prefs.get("location_mode", "auto")
        static_city = prefs.get("static_city", "")
        api_key = prefs.get("api_key", "")
        lang = prefs.get("language", "en")
        view_mode = int(prefs.get("view_mode", 5))

        T = TEXTS.get(lang, TEXTS["en"])

        if location_mode == "manual" and static_city:
            lat, lon, city = geocode_city(static_city)
        else:
            lat, lon, city = get_ip_location()

        if not lat:
            return SmallResultItem(
                icon='images/icon.png',
                name="Location failed",
                description="",
                on_enter=DoNothingAction()
            )

        cache_key = f"{provider}-{lat}-{lon}-{unit}-{lang}"
        cached = get_cache(cache_key)
        if cached:
            weather = cached
        else:
            if provider == "openweather":
                weather = get_openweather(lat, lon, unit, api_key, lang)
            else:
                weather = get_open_meteo(lat, lon, unit, lang)

            if weather:
                set_cache(cache_key, weather)

        if not weather:
            return SmallResultItem(
                icon='images/icon.png',
                name="Weather error",
                description="",
                on_enter=DoNothingAction()
            )

        symbol = "°C" if unit == "metric" else "°F"

        if view_mode == 1:
            desc = f"{weather['current_temp']}{symbol}"

        elif view_mode == 2:
            desc = f"{weather['current_temp']}{symbol} - {weather['current_desc']}"

        elif view_mode == 3:
            desc = f"{T['current']}: {weather['current_temp']}{symbol}"

        elif view_mode == 4:
            forecast = " | ".join(f"{f['temp']}{symbol}" for f in weather["forecast"])
            desc = f"{weather['current_temp']}{symbol} → {forecast}"

        else:
            forecast = " | ".join(f"{f['temp']}{symbol}" for f in weather["forecast"])
            desc = f"{T['current']}: {weather['current_temp']}{symbol} - {weather['current_desc']}\n{T['forecast']}: {forecast}"

        return ExtensionResultItem(
            icon='images/icon.png',
            name=f"📍 {city}",
            description=desc,
            on_enter=DoNothingAction()
        )


if __name__ == "__main__":
    UWeatherExtension().run()
