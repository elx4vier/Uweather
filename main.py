import logging
import requests
import time
import os
import json
import locale
from concurrent.futures import ThreadPoolExecutor
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

def country_flag(code):
    if not code or len(code) != 2: return ""
    offset = 127397
    return chr(ord(code[0].upper()) + offset) + chr(ord(code[1].upper()) + offset)

# ==============================
# WEATHER CODES & SERVICE
# ==============================
OPEN_METEO_CODES = {
    0: "céu limpo", 1: "parcialmente nublado", 2: "nublado", 3: "nublado",
    45: "neblina", 48: "neblina com gelo", 51: "chuva fraca", 53: "chuva moderada",
    55: "chuva forte", 56: "chuva congelante fraca", 57: "chuva congelante forte",
    61: "chuva", 63: "chuva forte", 65: "chuva intensa", 66: "chuva congelante leve",
    67: "chuva congelante intensa", 71: "neve fraca", 73: "neve moderada",
    75: "neve intensa", 77: "granizo", 80: "chuva forte", 81: "chuva intensa",
    82: "chuva intensa", 85: "neve leve", 86: "neve intensa", 95: "trovoada",
    96: "trovoada com granizo", 99: "trovoada com granizo intenso"
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
                        "city": data.get("city") or data.get("cityName") or "Desconhecida",
                        "state": data.get("region") or "",
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
                    "max": int(daily["temperature_2m_max"][i]) if unit.lower() == "c" else int(daily["temperature_2m_max"][i] * 9/5 + 32),
                    "min": int(daily["temperature_2m_min"][i]) if unit.lower() == "c" else int(daily["temperature_2m_min"][i] * 9/5 + 32),
                    "desc": OPEN_METEO_CODES.get(daily["weathercode"][i], "desconhecido")
                }
                for i in range(min(2, len(daily.get("temperature_2m_max", []))))
            ]
            current = data.get("current_weather", {})
            temp = int(current.get("temperature", 0)) if unit.lower() == "c" else int(current.get("temperature", 0) * 9/5 + 32)
            
            return {
                "current": {
                    "temp": temp,
                    "desc": OPEN_METEO_CODES.get(current.get("weathercode", 0), "desconhecido")
                },
                "forecast": forecast
            }
        except Exception: return None

# ==============================
# EXTENSION CORE
# ==============================
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
        except Exception as e: logger.error(f"Erro cache: {e}")

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else os.path.join(self.base_path, "images", "icon.png")

    def update_location(self):
        mode = (self.preferences.get("location_mode") or "auto").lower()
        unit = (self.preferences.get("unit") or "c").lower()
        
        geo = None
        if mode == "auto":
            geo = WeatherService.fetch_location(self.session)
        else:
            city = (self.preferences.get("static_location") or "").strip()
            if city:
                try:
                    r = self.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                        params={"name": city, "count": 1}, timeout=5)
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
                self.cache[f"{mode}_{unit}"] = {"geo": geo, "data": weather, "ts": time.time()}
                self.save_cache()

class PreferencesUpdateListener(EventListener):
    def on_event(self, event, extension):
        extension.cache = {}
        extension.save_cache()
        ThreadPoolExecutor(max_workers=1).submit(extension.update_location)

class WeatherListener(EventListener):
    def on_event(self, event, extension):
        unit = (extension.preferences.get("unit") or "c").lower()
        mode = (extension.preferences.get("location_mode") or "auto").lower()
        interface = (extension.preferences.get("interface_mode") or "complete").lower()
        query = (event.get_argument() or "").strip()

        key = f"{mode}_{unit}"

        if not query:
            if key not in extension.cache or (time.time() - extension.cache[key]["ts"] > CACHE_TTL):
                extension.update_location()
            
            if key in extension.cache:
                return self.render(extension.cache[key], extension, interface)
        else:
            return self.search_city_weather(query, extension, unit, interface)

        return RenderResultListAction([
            ExtensionResultItem(icon=extension.icon("icon.png"),
                                 name="Carregando clima...",
                                 description="Buscando informações meteorológicas...",
                                 on_enter=None)
        ])

    def search_city_weather(self, query, extension, unit, interface):
        try:
            r = extension.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                     params={"name": query, "count": 3}, timeout=5)
            results = r.json().get("results", [])
            if not results:
                return RenderResultListAction([ExtensionResultItem(icon=extension.icon("icon.png"), name="Cidade não encontrada", on_enter=None)])

            items = []
            for res in results:
                weather = WeatherService.fetch_weather(extension.session, res["latitude"], res["longitude"], unit)
                if weather:
                    geo = {"city": res.get("name"), "state": res.get("admin1", ""), "country": res.get("country_code", "BR"),
                           "latitude": res.get("latitude"), "longitude": res.get("longitude")}
                    items.append(self.render({"geo": geo, "data": weather}, extension, interface, return_item=True))
            return RenderResultListAction(items)
        except:
            return RenderResultListAction([ExtensionResultItem(name="Erro na busca", on_enter=None)])

    def render(self, item_data, extension, interface_mode, return_item=False):
        geo, weather = item_data["geo"], item_data["data"]
        lang = get_system_language()
        url = f"https://weather.com/{lang}/weather/today/l/{geo['latitude']},{geo['longitude']}"
        temp, desc = weather["current"]["temp"], weather["current"]["desc"]
        flag = country_flag(geo["country"])
        loc_text = f"{geo['city']} {flag}"

        if interface_mode == "complete":
            forecast = weather.get("forecast", [])
            desc_text = f"Agora: {desc.capitalize()} | Amanhã: {forecast[0]['min']}º/{forecast[0]['max']}º" if forecast else desc
            item = ExtensionResultItem(icon=extension.icon("icon.png"), name=f"{loc_text} — {temp}º", description=desc_text, on_enter=OpenUrlAction(url))
        elif interface_mode == "essential":
            item = ExtensionResultItem(icon=extension.icon("icon.png"), name=f"{temp}º, {desc.capitalize()}", description=loc_text, on_enter=OpenUrlAction(url))
        else:
            item = ExtensionSmallResultItem(icon=extension.icon("icon.png"), name=f"{temp}º – {loc_text} ({desc})", on_enter=OpenUrlAction(url))
        
        return item if return_item else RenderResultListAction([item])

if __name__ == "__main__":
    UWeather().run()
