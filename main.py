import logging
import requests
import time
import os
import json
import locale
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction

logger = logging.getLogger(__name__)

CACHE_TTL = 600
CACHE_FILE = "cache_weather.json"

def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def get_system_language():
    try:
        lang = locale.getdefaultlocale()[0]
        return lang.replace("_", "-") if lang else "en-US"
    except Exception:
        return "en-US"

def load_translations(base_path, lang):
    lang = (lang or "en").lower()
    path = os.path.join(base_path, "translations", f"{lang}.json")
    if not os.path.exists(path):
        path = os.path.join(base_path, "translations", "en.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def country_flag(code):
    if not code or len(code) != 2: return ""
    offset = 127397
    return chr(ord(code[0].upper()) + offset) + chr(ord(code[1].upper()) + offset)

OPEN_METEO_CODES = {
    0: "clear sky", 1: "partly cloudy", 2: "cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle",
    55: "dense drizzle", 56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain", 66: "light freezing rain",
    67: "heavy freezing rain", 71: "light snow", 73: "moderate snow",
    75: "heavy snow", 77: "snow grains", 80: "light rain showers", 81: "moderate rain showers",
    82: "violent rain showers", 85: "light snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail"
}

class WeatherService:
    @staticmethod
    def fetch_location(session):
        apis = [("https://ip-api.com/json/", 2), ("https://freeipapi.com/api/json", 2)]
        for url, timeout in apis:
            try:
                r = session.get(url, timeout=timeout)
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "city": data.get("city") or data.get("cityName") or "Unknown",
                        "state": data.get("regionName") or data.get("region") or "",
                        "country": (data.get("countryCode") or data.get("country_code") or "BR")[:2],
                        "latitude": data.get("lat") or data.get("latitude"),
                        "longitude": data.get("lon") or data.get("longitude")
                    }
            except: continue
        return None

    @staticmethod
    def fetch_weather(session, lat, lon, unit="c"):
        try:
            r = session.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&daily=temperature_2m_max,temperature_2m_min,weathercode&current_weather=true&timezone=auto",
                timeout=5
            )
            data = r.json()
            daily = data.get("daily", {})
            forecast = [
                {
                    "max": int(daily["temperature_2m_max"][i]),
                    "min": int(daily["temperature_2m_min"][i]),
                } for i in range(min(3, len(daily.get("temperature_2m_max", []))))
            ]
            
            if unit.lower() == "f":
                for f in forecast:
                    f["max"] = int(f["max"] * 9/5 + 32)
                    f["min"] = int(f["min"] * 9/5 + 32)

            current = data.get("current_weather", {})
            temp = int(current.get("temperature", 0))
            if unit.lower() == "f": temp = int(temp * 9/5 + 32)
            
            return {
                "current": {
                    "temp": temp,
                    "weathercode": current.get("weathercode", 0)
                },
                "forecast": forecast
            }
        except Exception: return None

class UWeather(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesUpdateListener())
        self.session = create_session()
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.cache = self.load_cache()
        
    def load_cache(self):
        path = os.path.join(self.base_path, CACHE_FILE)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f: return json.load(f)
            except: return {}
        return {}

    def save_cache(self):
        path = os.path.join(self.base_path, CACHE_FILE)
        try:
            with open(path, "w", encoding="utf-8") as f: json.dump(self.cache, f)
        except: pass

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else os.path.join(self.base_path, "images", "icon.png")

    # ===== NEW: icon function based on weather and time of day =====
    def weather_icon(self, weather_code, is_night=False):
        code_map = {
            0: "weather-clear",
            1: "weather-few-clouds-wind",
            2: "weather-many-clouds",
            3: "weather-many-clouds",
            45: "weather-mist",
            48: "weather-mist",
            51: "weather-showers",
            53: "weather-showers",
            55: "weather-showers",
            56: "weather-showers",
            57: "weather-showers",
            61: "weather-showers",
            63: "weather-showers",
            65: "weather-showers",
            66: "weather-showers",
            67: "weather-showers",
            71: "weather-snow-scattered",
            73: "weather-snow-scattered",
            75: "weather-snow-scattered",
            77: "weather-snow",
            80: "weather-showers",
            81: "weather-showers",
            82: "weather-showers",
            85: "weather-snow",
            86: "weather-snow",
            95: "weather-storm",
            96: "weather-storm",
            99: "weather-storm",
        }
        base_name = code_map.get(weather_code, "weather-mist")
        suffix = "night" if is_night else "day"
        filename = f"{base_name}-{suffix}.svg"

        path = os.path.join(self.base_path, "images", filename)
        if os.path.exists(path):
            return filename
        neutral_file = f"{base_name}.svg"
        return neutral_file if os.path.exists(os.path.join(self.base_path, "images", neutral_file)) else "icon.png"
    # ===============================================================

    def update_location(self):
        mode = (self.preferences.get("location_mode") or "auto").lower()
        unit = (self.preferences.get("unit") or "c").lower()
        static_city = (self.preferences.get("static_location") or "").strip()
        geo = None

        if mode == "auto":
            geo = WeatherService.fetch_location(self.session)
        else:
            if not static_city: return False
            try:
                r = self.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                    params={"name": static_city, "count": 1}, timeout=5)
                res = r.json().get("results", [])
                if res:
                    geo = {
                        "city": res[0].get("name"), "state": res[0].get("admin1", ""),
                        "country": res[0].get("country_code", "BR"),
                        "latitude": res[0].get("latitude"), "longitude": res[0].get("longitude")
                    }
            except: pass

        if geo:
            weather = WeatherService.fetch_weather(self.session, geo["latitude"], geo["longitude"], unit)
            if weather:
                self.cache = {
                    "params": {"mode": mode, "unit": unit, "city": static_city},
                    "data": {"geo": geo, "weather": weather, "ts": time.time()}
                }
                self.save_cache()
                return True
        return False

class PreferencesUpdateListener(EventListener):
    def on_event(self, event, extension):
        extension.cache = {}
        path = os.path.join(extension.base_path, CACHE_FILE)
        if os.path.exists(path):
            try: os.remove(path)
            except: pass
        extension.update_location()

class WeatherListener(EventListener):
    def on_event(self, event, extension):
        unit = (extension.preferences.get("unit") or "c").lower()
        mode = (extension.preferences.get("location_mode") or "auto").lower()
        interface = (extension.preferences.get("interface_mode") or "complete").lower()
        static_city = (extension.preferences.get("static_location") or "").strip()
        query = (event.get_argument() or "").strip()
        t = load_translations(extension.base_path, extension.preferences.get("language"))

        if mode == "manual" and not static_city:
            return RenderResultListAction([ExtensionResultItem(icon=extension.icon("error.png"), name=t.get("location_not_found", "Location not found"), on_enter=None)])

        if not query:
            cache_valid = False
            if "params" in extension.cache:
                p = extension.cache["params"]
                if p.get("mode") == mode and p.get("unit") == unit and p.get("city") == static_city:
                    cache_valid = True

            if not cache_valid or (time.time() - extension.cache["data"]["ts"] > CACHE_TTL):
                success = extension.update_location()
                if not success:
                    return RenderResultListAction([ExtensionResultItem(icon=extension.icon("icon.png"), name=t.get("searching_weather", "Fetching weather information..."), on_enter=None)])

            return self.render(extension.cache["data"], extension, interface, t)

        return self.search_city_weather(query, extension, unit, interface, t)

    def search_city_weather(self, query, extension, unit, interface, t):
        try:
            r = extension.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                     params={"name": query, "count": 3}, timeout=5)
            results = r.json().get("results", [])
            if not results:
                return RenderResultListAction([ExtensionResultItem(icon=extension.icon("icon.png"), name=t.get("city_not_found", "City not found"), on_enter=None)])

            items = []
            for res in results:
                weather = WeatherService.fetch_weather(extension.session, res["latitude"], res["longitude"], unit)
                if weather:
                    geo = {"city": res.get("name"), "state": res.get("admin1", ""), "country": res.get("country_code", "BR"),
                           "latitude": res.get("latitude"), "longitude": res.get("longitude")}
                    item_data = {"geo": geo, "weather": weather}
                    items.append(self.render(item_data, extension, interface, t, return_item=True))
            return RenderResultListAction(items)
        except:
            return RenderResultListAction([ExtensionResultItem(icon=extension.icon("error.png"), name=t.get("search_error", "Search error"), on_enter=None)])

    def render(self, item_data, extension, interface_mode, t, return_item=False):
        geo, weather = item_data["geo"], item_data["weather"]
        lang = get_system_language()
        url = f"https://weather.com/{lang}/weather/today/l/{geo['latitude']},{geo['longitude']}"
        temp = weather["current"]["temp"]
        weather_code = weather["current"].get("weathercode", 0)
        desc = t.get(f"weather_code.{weather_code}", OPEN_METEO_CODES.get(weather_code, "unknown")).lower()
        flag = country_flag(geo["country"])

        now_hour = datetime.now().hour
        is_night = now_hour < 6 or now_hour >= 18
        icon_file = extension.weather_icon(weather_code, is_night)

        state_info = f", {geo['state']}" if geo['state'] else ""
        loc_line = f"{geo['city']}{state_info} {flag}"

        if interface_mode == "complete":
            f = weather.get("forecast", [])
            tomorrow_label = t.get("tomorrow", "Tomorrow")
            day_after_label = t.get("day_after", "Later")
            line3 = f"{tomorrow_label}: {f[1]['min']}º / {f[1]['max']}º | {day_after_label}: {f[2]['min']}º / {f[2]['max']}º" if len(f) >= 3 else ""
            item = ExtensionResultItem(
                icon=extension.icon(icon_file),
                name=loc_line,
                description=f"{temp}º, {desc}\n{line3}",
                on_enter=OpenUrlAction(url)
            )
        elif interface_mode == "essential":
            item = ExtensionResultItem(
                icon=extension.icon(icon_file),
                name=f"{temp}º, {desc}",
                description=loc_line,
                on_enter=OpenUrlAction(url)
            )
        else:
            item = ExtensionSmallResultItem(
                icon=extension.icon(icon_file),
                name=f"{temp}º – {loc_line} ({desc})",
                on_enter=OpenUrlAction(url)
            )

        return item if return_item else RenderResultListAction([item])

if __name__ == "__main__":
    UWeather().run()
