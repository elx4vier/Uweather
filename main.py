import logging
import requests
import time
import os
import threading
import json
import locale
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction

logger = logging.getLogger(__name__)
CACHE_TTL = 600  # 10 minutos
CACHE_FILE = "cache_weather.json"

# ==============================
# SESSION
# ==============================
def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ==============================
# UTILITÁRIOS
# ==============================
def get_system_language():
    try:
        lang = locale.getdefaultlocale()[0]
        if lang:
            return lang.replace('_', '-')
    except:
        pass
    return "en-US"

def country_flag(country_code):
    if not country_code or len(country_code) != 2:
        return ""
    offset = 127397
    return chr(ord(country_code[0].upper()) + offset) + chr(ord(country_code[1].upper()) + offset)

def load_cache(base_path):
    path = os.path.join(base_path, CACHE_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(base_path, cache_data):
    path = os.path.join(base_path, CACHE_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
    except Exception as e:
        logger.error(f"Erro ao salvar cache: {e}")

def convert_temperature(temp, unit):
    if unit == "f":
        return int(temp * 9 / 5 + 32)
    return int(temp)

# ==============================
# MAPEAMENTO DE CÓDIGOS
# ==============================
OPEN_METEO_WEATHER_CODES = {
    0: "céu limpo", 1: "parcialmente nublado", 2: "nublado", 3: "nublado",
    45: "neblina", 48: "neblina com gelo", 51: "chuva fraca", 53: "chuva moderada",
    55: "chuva forte", 56: "chuva congelante fraca", 57: "chuva congelante forte",
    61: "chuva", 63: "chuva forte", 65: "chuva intensa", 66: "chuva congelante leve",
    67: "chuva congelante intensa", 71: "neve fraca", 73: "neve moderada",
    75: "neve intensa", 77: "granizo", 80: "chuva forte", 81: "chuva intensa",
    82: "chuva intensa", 85: "neve leve", 86: "neve intensa", 95: "trovoada",
    96: "trovoada com granizo", 99: "trovoada com granizo intenso"
}

def get_owm_description(code):
    if 200 <= code <= 232: return "tempestade"
    if 300 <= code <= 321: return "garoa"
    if 500 <= code <= 531: return "chuva"
    if 600 <= code <= 622: return "neve"
    if 701 <= code <= 781: return "neblina"
    if code == 800: return "céu limpo"
    if code == 801: return "poucas nuvens"
    if 802 <= code <= 804: return "nublado"
    return "desconhecido"

# ==============================
# WEATHER SERVICE
# ==============================
class WeatherService:
    @staticmethod
    def fetch_location(session):
        apis = [
            ("https://ip-api.com/json/", 2),
            ("https://freeipapi.com/api/json", 2),
            ("https://ipapi.co/json/", 2)
        ]
        for url, timeout in apis:
            try:
                r = session.get(url, timeout=timeout)
                if r.status_code != 200: continue
                data = r.json()
                return {
                    "city": data.get("city") or data.get("cityName") or "Desconhecida",
                    "country": (data.get("countryCode") or data.get("country_code") or "BR")[:2],
                    "latitude": data.get("lat") or data.get("latitude"),
                    "longitude": data.get("lon") or data.get("longitude")
                }
            except: continue
        return None

    @staticmethod
    def fetch_weather_openmeteo(session, lat, lon, unit="c"):
        try:
            r = session.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&daily=temperature_2m_max,temperature_2m_min,weathercode"
                "&current_weather=true&timezone=auto", timeout=5
            )
            data = r.json()
            daily = data.get("daily", {})
            forecast = []
            for i in range(min(2, len(daily.get("temperature_2m_max", [])))):
                forecast.append({
                    "max": convert_temperature(daily["temperature_2m_max"][i], unit),
                    "min": convert_temperature(daily["temperature_2m_min"][i], unit),
                    "desc": OPEN_METEO_WEATHER_CODES.get(daily["weathercode"][i], "desconhecido")
                })
            current = data.get("current_weather", {})
            return {
                "current": {
                    "temp": convert_temperature(current.get("temperature", 0), unit),
                    "desc": OPEN_METEO_WEATHER_CODES.get(current.get("weathercode", 0), "desconhecido")
                },
                "forecast": forecast
            }
        except Exception as e:
            logger.error(f"Erro Open-Meteo: {e}")
            return None

    @staticmethod
    def fetch_weather_openweather(session, lat, lon, api_key, unit="c"):
        try:
            u = "metric" if unit == "c" else "imperial"
            r_curr = session.get(f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units={u}", timeout=5)
            data_curr = r_curr.json()
            
            if r_curr.status_code != 200:
                logger.error(f"OWM Error: {data_curr.get('message')}")
                return None

            r_fore = session.get(f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units={u}", timeout=5)
            data_fore = r_fore.json()
            
            forecast = []
            if r_fore.status_code == 200 and "list" in data_fore:
                f_day = data_fore["list"][8] if len(data_fore["list"]) > 8 else data_fore["list"][0]
                forecast.append({
                    "max": int(f_day["main"]["temp_max"]),
                    "min": int(f_day["main"]["temp_min"]),
                    "desc": get_owm_description(f_day["weather"][0]["id"])
                })

            return {
                "current": {
                    "temp": int(data_curr["main"]["temp"]),
                    "desc": get_owm_description(data_curr["weather"][0]["id"])
                },
                "forecast": forecast
            }
        except Exception as e:
            logger.error(f"Erro OpenWeather: {e}")
            return None

# ==============================
# EXTENSION
# ==============================
class UWeather(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.session = create_session()
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.cache = load_cache(self.base_path)
        threading.Thread(target=self.preload_weather, daemon=True).start()

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else os.path.join(self.base_path, "images", "icon.png")

    def get_weather_data(self, lat, lon, unit):
        provider = (self.preferences.get("provider") or "open-meteo").lower()
        if provider == "openweather":
            api_key = self.preferences.get("api_key")
            if not api_key:
                return {"error": "API Key ausente"}
            return WeatherService.fetch_weather_openweather(self.session, lat, lon, api_key, unit)
        return WeatherService.fetch_weather_openmeteo(self.session, lat, lon, unit)

    def preload_weather(self):
        geo = WeatherService.fetch_location(self.session)
        if geo:
            unit = (self.preferences.get("unit") or "c").lower()
            weather = self.get_weather_data(geo["latitude"], geo["longitude"], unit)
            if weather and "error" not in weather:
                provider = (self.preferences.get("provider") or "open-meteo").lower()
                self.cache[f"auto_{provider}_{unit}"] = {"geo": geo, "data": weather, "ts": time.time()}
                save_cache(self.base_path, self.cache)

# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):
    def on_event(self, event, extension):
        unit = (extension.preferences.get("unit") or "c").lower()
        mode = (extension.preferences.get("location_mode") or "auto").lower()
        interface = (extension.preferences.get("interface_mode") or "complete").lower()
        provider = (extension.preferences.get("provider") or "open-meteo").lower()
        query = (event.get_argument() or "").strip()
        
        geo = None
        key = None
        
        if not query and mode == "auto":
            key = f"auto_{provider}_{unit}"
            if key in extension.cache and time.time() - extension.cache[key]["ts"] < CACHE_TTL:
                return self.render(extension.cache[key], extension, interface)
            geo = WeatherService.fetch_location(extension.session)
        elif query or mode == "manual":
            city_name = query if query else extension.preferences.get("static_location") or ""
            key = f"{city_name.lower()}_{provider}_{unit}"
            if key in extension.cache and time.time() - extension.cache[key]["ts"] < CACHE_TTL:
                return self.render(extension.cache[key], extension, interface)
            
            try:
                r = extension.session.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city_name}&count=1")
                res = r.json().get("results")
                if res:
                    geo = {"city": res[0]["name"], "country": res[0].get("country_code", "BR"),
                           "latitude": res[0]["latitude"], "longitude": res[0]["longitude"]}
            except: pass

        if geo:
            weather = extension.get_weather_data(geo["latitude"], geo["longitude"], unit)
            
            if weather:
                if isinstance(weather, dict) and "error" in weather:
                    return RenderResultListAction([
                        ExtensionResultItem(icon=extension.icon("icon.png"),
                                            name=weather["error"],
                                            description="Verifique as configurações da extensão",
                                            on_enter=None)
                    ])
                
                data = {"geo": geo, "data": weather, "ts": time.time()}
                extension.cache[key] = data
                save_cache(extension.base_path, extension.cache)
                return self.render(data, extension, interface)

        return RenderResultListAction([
            ExtensionResultItem(icon=extension.icon("icon.png"),
                                name="Localização ou dados não disponíveis",
                                description=f"Provedor atual: {provider}",
                                on_enter=None)
        ])

    def render(self, cached_item, extension, interface_mode):
        geo = cached_item["geo"]
        weather = cached_item["data"]
        lang = get_system_language()
        url = f"https://weather.com/{lang}/weather/today/l/{geo['latitude']},{geo['longitude']}"

        temp = weather["current"]["temp"]
        desc = weather["current"]["desc"]
        flag = country_flag(geo['country'])
        title = f"{geo['city']}, {geo['country']} {flag} — {temp}º, {desc}"

        if interface_mode == "complete":
            f = weather.get("forecast", [])
            desc_text = f"Amanhã: {f[0]['min']}º/{f[0]['max']}º" if f else "Clique para ver detalhes"
            item = ExtensionResultItem(icon=extension.icon("icon.png"), name=title, description=desc_text, on_enter=OpenUrlAction(url))
        elif interface_mode == "essential":
            item = ExtensionResultItem(icon=extension.icon("icon.png"), name=f"{temp}º, {desc}", description=f"{geo['city']} {flag}", on_enter=OpenUrlAction(url))
        else:
            item = ExtensionSmallResultItem(icon=extension.icon("icon.png"), name=f"{temp}º – {geo['city']} {flag}", on_enter=OpenUrlAction(url))

        return RenderResultListAction([item])

if __name__ == "__main__":
    UWeather().run()
