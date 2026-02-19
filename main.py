import logging
import requests
import time
import os
import threading
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

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

# ==============================
# OPEN-METEO CÓDIGOS
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

# ==============================
# WEATHER SERVICE
# ==============================
class WeatherService:

    @staticmethod
    def fetch_location(session):
        """Obter localização com fallback em múltiplas APIs"""
        apis = [
            ("https://ip-api.com/json/", "ip-api.com", 2),
            ("https://freeipapi.com/api/json", "freeipapi.com", 2),
            ("https://ipapi.co/json/", "ipapi.co", 2),
            ("https://ipinfo.io/json", "ipinfo.io", 3)
        ]
        for url, name, timeout in apis:
            try:
                r = session.get(url, timeout=timeout)
                if r.status_code != 200:
                    continue
                data = r.json()
                if data.get("status") == "fail" or "error" in data:
                    continue
                geo = {
                    "ip": data.get("query") or data.get("ip") or data.get("ipAddress"),
                    "city": data.get("city") or data.get("cityName") or "Desconhecida",
                    "region": data.get("regionName") or data.get("region") or "",
                    "country": (data.get("countryCode") or data.get("country_code") or "BR")[:2],
                    "provider": name
                }
                geo["latitude"] = data.get("lat") or data.get("latitude")
                geo["longitude"] = data.get("lon") or data.get("longitude")
                return geo
            except Exception:
                continue
        return {"city": "Nenhuma API respondeu", "region": "", "ip": "N/A", "country": "??", "provider": "Nenhuma API respondeu"}

    @staticmethod
    def fetch_weather_openmeteo(session, lat, lon):
        """Buscar clima no Open-Meteo"""
        try:
            r = session.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&daily=temperature_2m_max,temperature_2m_min,weathercode"
                "&current_weather=true&timezone=auto",
                timeout=5
            )
            data = r.json()
            daily = data.get("daily", {})
            forecast = []
            for i in range(min(2, len(daily.get("temperature_2m_max", [])))):
                forecast.append({
                    "max": int(daily["temperature_2m_max"][i]),
                    "min": int(daily["temperature_2m_min"][i]),
                    "code": daily["weathercode"][i],
                    "desc": OPEN_METEO_WEATHER_CODES.get(daily["weathercode"][i], "desconhecido")
                })
            current = data.get("current_weather", {})
            return {
                "current": {
                    "temp": int(current.get("temperature", 0)),
                    "code": current.get("weathercode", 0),
                    "desc": OPEN_METEO_WEATHER_CODES.get(current.get("weathercode", 0), "desconhecido")
                },
                "forecast": forecast
            }
        except Exception as e:
            logger.error(f"Erro ao obter clima: {e}")
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
        self.icon_default = os.path.join(self.base_path, "images", "icon.png")
        self.cache = load_cache(self.base_path)
        self.last_preferences = {}
        threading.Thread(target=self.preload_weather, daemon=True).start()

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else self.icon_default

    def preload_weather(self):
        """Pré-carregamento do clima para localização automática"""
        try:
            geo = WeatherService.fetch_location(self.session)
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if lat is None or lon is None:
                return
            weather = WeatherService.fetch_weather_openmeteo(self.session, lat, lon)
            if weather:
                self.cache["auto"] = {"geo": geo, "data": weather, "ts": time.time()}
                save_cache(self.base_path, self.cache)
        except Exception as e:
            logger.error(f"Preload falhou: {e}")

# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):
    def on_event(self, event, extension):
        try:
            # =========================
            # Reset cache se mudar preferências (exceto interface)
            # =========================
            prefs_to_check = ["provider", "api_key", "unit", "location_mode", "static_location"]
            prefs = {k: extension.preferences.get(k) for k in prefs_to_check}
            if prefs != extension.last_preferences:
                extension.cache = {}
                save_cache(extension.base_path, extension.cache)
                extension.last_preferences = prefs.copy()

            provider = (extension.preferences.get("provider") or "openweather").lower()
            unit = (extension.preferences.get("unit") or "c").lower()
            location_mode = (extension.preferences.get("location_mode") or "auto").lower()
            interface_mode = (extension.preferences.get("interface_mode") or "complete").lower()

            query = (event.get_argument() or "").strip()
            geo = None
            key = None

            # =========================
            # Localização automática
            # =========================
            if not query and location_mode == "auto":
                key = "auto"
                now = time.time()
                if key in extension.cache and now - extension.cache[key]["ts"] < CACHE_TTL:
                    geo = extension.cache[key]["geo"]
                    weather = extension.cache[key]["data"]
                    return self.render({**geo, **weather}, extension, interface_mode)

                geo = WeatherService.fetch_location(extension.session)
                lat = geo.get("latitude")
                lon = geo.get("longitude")
                if lat is None or lon is None:
                    return RenderResultListAction([
                        ExtensionResultItem(icon=extension.icon("icon.png"), name="Cidade não encontrada", on_enter=None)
                    ])
                weather = WeatherService.fetch_weather_openmeteo(extension.session, lat, lon)
                if weather:
                    extension.cache[key] = {"geo": geo, "data": weather, "ts": now}
                    save_cache(extension.base_path, extension.cache)
                else:
                    return RenderResultListAction([
                        ExtensionResultItem(icon=extension.icon("error.png"), name="Erro ao obter clima", on_enter=None)
                    ])

            # =========================
            # Localização manual ou pesquisa por cidade
            # =========================
            elif query or location_mode == "manual":
                key = query.lower() if query else "manual"
                city = query if query else extension.preferences.get("static_location") or ""
                if key in extension.cache and time.time() - extension.cache[key]["ts"] < CACHE_TTL:
                    geo = extension.cache[key]["geo"]
                    weather = extension.cache[key]["data"]
                    return self.render({**geo, **weather}, extension, interface_mode)

                # Usar geocoding Open-Meteo
                r = extension.session.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1", timeout=5)
                results = r.json().get("results")
                if not results:
                    return RenderResultListAction([
                        ExtensionResultItem(icon=extension.icon("icon.png"), name="Cidade não encontrada", on_enter=None)
                    ])
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                geo = {
                    "city": results[0]["name"],
                    "region": results[0].get("admin1", ""),
                    "country": results[0].get("country_code", "BR"),
                    "latitude": lat,
                    "longitude": lon,
                    "provider": "Open-Meteo"
                }
                weather = WeatherService.fetch_weather_openmeteo(extension.session, lat, lon)
                extension.cache[key] = {"geo": geo, "data": weather, "ts": time.time()}
                save_cache(extension.base_path, extension.cache)

            return self.render({**geo, **weather}, extension, interface_mode)

        except Exception as e:
            logger.error(f"Erro listener: {e}")
            return RenderResultListAction([
                ExtensionResultItem(icon=extension.icon("error.png"), name="Erro ao obter clima", on_enter=None)
            ])

    # =========================
    # Renderização permanece inalterada
    # =========================
    def render(self, data, extension, interface_mode):
        city_name = data.get("city") or data.get("city_name") or "Desconhecida"
        country = data.get("country") or "BR"
        flag = country_flag(country)
        temp = data["current"]["temp"]
        desc = data["current"].get("desc", "desconhecido")
        forecast = data.get("forecast", [])

        items = []

        if interface_mode == "complete":
            line1 = f"{city_name}, {country} {flag}"
            line2 = f"{temp}º, {desc}"
            line3 = ""
            if forecast:
                parts = []
                if len(forecast) >= 1:
                    parts.append(f"Amanhã: {forecast[0]['min']}º / {forecast[0]['max']}º")
                if len(forecast) >= 2:
                    parts.append(f"Depois: {forecast[1]['min']}º / {forecast[1]['max']}º")
                line3 = " | ".join(parts)
            items.append(
                ExtensionResultItem(icon=extension.icon("icon.png"), name=f"{line1}\n{line2}", description=line3 if line3 else None, on_enter=None)
            )

        elif interface_mode == "essential":
            line1 = f"{temp}º, {desc}"
            line2 = f"{city_name}, {country} {flag}"
            items.append(
                ExtensionResultItem(icon=extension.icon("icon.png"), name=line1, description=line2, on_enter=None)
            )

        elif interface_mode == "minimal":
            minimal_text = f"{temp}º – {city_name} {flag}"
            items.append(
                ExtensionSmallResultItem(icon=extension.icon("icon.png"), name=minimal_text)
            )

        return RenderResultListAction(items)


if __name__ == "__main__":
    UWeather().run()
