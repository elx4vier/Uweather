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


# ==============================
# CACHE EM ARQUIVO
# ==============================
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
# WEATHER SERVICE
# ==============================
OPEN_METEO_WEATHER_CODES = {
    0: "céu limpo",
    1: "parcialmente nublado",
    2: "nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina com gelo",
    51: "chuva fraca",
    53: "chuva moderada",
    55: "chuva forte",
    56: "chuva congelante fraca",
    57: "chuva congelante forte",
    61: "chuva",
    63: "chuva forte",
    65: "chuva intensa",
    66: "chuva congelante leve",
    67: "chuva congelante intensa",
    71: "neve fraca",
    73: "neve moderada",
    75: "neve intensa",
    77: "granizo",
    80: "chuva forte",
    81: "chuva intensa",
    82: "chuva intensa",
    85: "neve leve",
    86: "neve intensa",
    95: "trovoada",
    96: "trovoada com granizo",
    99: "trovoada com granizo intenso"
}


class WeatherService:

    @staticmethod
    def fetch_location(session):
        try:
            r = session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if "latitude" in geo:
                return geo
        except Exception:
            pass
        try:
            r = session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {
                "latitude": geo["lat"],
                "longitude": geo["lon"],
                "city": geo.get("city", "Desconhecida"),
                "country": geo.get("countryCode", "BR")
            }
        except Exception:
            pass
        raise Exception("Não foi possível obter sua localização atual")

    @staticmethod
    def fetch_weather_openweather(session, api_key, city=None, lat=None, lon=None, unit="c"):
        if city:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units={'metric' if unit == 'c' else 'imperial'}&lang=pt_br"
        else:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units={'metric' if unit == 'c' else 'imperial'}&lang=pt_br"

        r = session.get(url, timeout=5)
        data = r.json()
        if r.status_code == 401:
            raise Exception("api key inválida")
        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("cidade não encontrada")
        return WeatherService.parse_weather(data)

    @staticmethod
    def fetch_weather_openmeteo(session, city=None, lat=None, lon=None, unit="c"):
        if city and not lat and not lon:
            r = session.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1", timeout=5)
            geo = r.json().get("results")
            if not geo:
                raise Exception("cidade não encontrada")
            lat = geo[0]["latitude"]
            lon = geo[0]["longitude"]
            city_name = geo[0]["name"]
            country = geo[0]["country_code"]
        else:
            city_name = city or "Desconhecida"
            country = "BR"

        r = session.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&daily=temperature_2m_max,temperature_2m_min,weathercode"
            "&current_weather=true&timezone=auto",
            timeout=5
        )
        data = r.json()
        forecast_list = []

        daily = data.get("daily", {})
        if "temperature_2m_max" in daily and "temperature_2m_min" in daily and "weathercode" in daily:
            for i in range(min(2, len(daily["temperature_2m_max"]))):
                forecast_list.append({
                    "max": int(daily["temperature_2m_max"][i]),
                    "min": int(daily["temperature_2m_min"][i]),
                    "code": daily["weathercode"][i],
                    "desc": OPEN_METEO_WEATHER_CODES.get(daily["weathercode"][i], "desconhecido")
                })

        current = data.get("current_weather", {})
        code = current.get("weathercode", 0)
        desc = OPEN_METEO_WEATHER_CODES.get(code, "desconhecido")

        return {
            "city": f"{city_name}, {country}",
            "city_name": city_name,
            "country": country,
            "current": {
                "temp": int(current.get("temperature", 0)),
                "code": code,
                "desc": desc
            },
            "forecast": forecast_list
        }

    @staticmethod
    def parse_weather(data):
        current = data["list"][0]
        daily = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            temp_max = item["main"]["temp_max"]
            temp_min = item["main"]["temp_min"]
            code = item["weather"][0]["id"]
            desc = item["weather"][0]["description"].lower()
            if date not in daily:
                daily[date] = {"max": temp_max, "min": temp_min, "code": code, "desc": desc}
            else:
                daily[date]["max"] = max(daily[date]["max"], temp_max)
                daily[date]["min"] = min(daily[date]["min"], temp_min)
        sorted_dates = sorted(daily.keys())
        forecast = []
        for date in sorted_dates[1:3]:
            forecast.append({
                "max": int(daily[date]["max"]),
                "min": int(daily[date]["min"]),
                "code": daily[date]["code"]
            })
        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "city_name": data['city']['name'],
            "country": data['city']['country'],
            "current": {
                "temp": int(current["main"]["temp"]),
                "code": data["list"][0]["weather"][0]["id"],
                "desc": data["list"][0]["weather"][0]["description"].lower()
            },
            "forecast": forecast
        }


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
        threading.Thread(target=self.preload_weather, daemon=True).start()

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else self.icon_default

    def preload_weather(self):
        try:
            api_key = (self.preferences.get("api_key") or "").lower()
            if not api_key:
                return
            geo = WeatherService.fetch_location(self.session)
            data = WeatherService.fetch_weather_openweather(
                self.session,
                api_key,
                lat=geo["latitude"],
                lon=geo["longitude"]
            )
            self.cache["auto"] = {"data": data, "ts": time.time()}
            save_cache(self.base_path, self.cache)
        except Exception as e:
            logger.error(f"Preload falhou: {e}")


# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):
    def on_event(self, event, extension):
        try:
            provider = (extension.preferences.get("provider") or "openweather").lower()
            api_key = (extension.preferences.get("api_key") or "").lower()
            unit = (extension.preferences.get("unit") or "c").lower()
            location_mode = (extension.preferences.get("location_mode") or "auto").lower()
            static_location = (extension.preferences.get("static_location") or "").lower()
            interface_mode = (extension.preferences.get("interface_mode") or "complete").lower()

            query = (event.get_argument() or "").strip().lower()
            geo = None
            key = None

            # Limpar cache se unidade mudou
            unit_cached = extension.cache.get("_unit", "c")
            if unit != unit_cached:
                extension.cache = {}
                extension.cache["_unit"] = unit
                save_cache(extension.base_path, extension.cache)

            # Determinar chave e localização
            if not query and location_mode == "auto":
                key = "auto"
                if key in extension.cache:
                    entry = extension.cache[key]
                    data, ts = entry["data"], entry["ts"]
                    if time.time() - ts < CACHE_TTL:
                        return self.render(data, extension, interface_mode)
                try:
                    geo = WeatherService.fetch_location(extension.session)
                except Exception:
                    # Sem internet e sem cache
                    if "auto" in extension.cache:
                        data = extension.cache["auto"]["data"]
                        return self.render(data, extension, interface_mode)
                    return RenderResultListAction([
                        ExtensionResultItem(
                            icon=extension.icon("error.png"),
                            name="Erro ao obter clima",
                            on_enter=None
                        )
                    ])

            elif not query and location_mode == "manual" and static_location:
                query = static_location
                key = query.lower()
            else:
                key = query.lower()

            # Cache
            if key in extension.cache:
                entry = extension.cache[key]
                data, ts = entry["data"], entry["ts"]
                if time.time() - ts < CACHE_TTL:
                    return self.render(data, extension, interface_mode)

            # Buscar clima
            try:
                if provider == "openweather":
                    if query:
                        data = WeatherService.fetch_weather_openweather(
                            extension.session, api_key, city=query, unit=unit)
                    else:
                        data = WeatherService.fetch_weather_openweather(
                            extension.session, api_key, lat=geo["latitude"], lon=geo["longitude"], unit=unit)
                else:
                    data = WeatherService.fetch_weather_openmeteo(
                        extension.session,
                        city=query,
                        lat=geo["latitude"] if geo else None,
                        lon=geo["longitude"] if geo else None,
                        unit=unit
                    )
            except Exception as e:
                msg = str(e).lower()
                # API key inválida sempre independente
                if "api key" in msg or "invalid api key" in msg:
                    return RenderResultListAction([
                        ExtensionResultItem(
                            icon=extension.icon("error.png"),
                            name="API key inválida",
                            on_enter=None
                        )
                    ])
                # Cidade não encontrada
                if "cidade não encontrada" in msg or "city not found" in msg:
                    return RenderResultListAction([
                        ExtensionResultItem(
                            icon=extension.icon("icon.png"),
                            name="Cidade não encontrada",
                            on_enter=None
                        )
                    ])
                # Qualquer outro erro
                return RenderResultListAction([
                    ExtensionResultItem(
                        icon=extension.icon("error.png"),
                        name="Erro ao obter clima",
                        on_enter=None
                    )
                ])

            # Atualizar cache
            extension.cache[key] = {"data": data, "ts": time.time()}
            save_cache(extension.base_path, extension.cache)

            return self.render(data, extension, interface_mode)

        except Exception:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name="Erro ao obter clima",
                    on_enter=None
                )
            ])

    def render(self, data, extension, interface_mode):
        city_name = data.get("city_name") or "Desconhecida"
        country = data.get("country") or "BR"
        flag = country_flag(country)
        temp = data["current"]["temp"]
        desc = data["current"].get("desc", "desconhecido")  # minúscula
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
                ExtensionResultItem(
                    icon=extension.icon("icon.png"),
                    name=f"{line1}\n{line2}",
                    description=line3 if line3 else None,
                    on_enter=None
                )
            )

        elif interface_mode == "essential":
            line1 = f"{temp}º, {desc}"
            line2 = f"{city_name}, {country} {flag}"
            items.append(
                ExtensionResultItem(
                    icon=extension.icon("icon.png"),
                    name=line1,
                    description=line2,
                    on_enter=None
                )
            )

        elif interface_mode == "minimal":
            minimal_text = f"{temp}º – {city_name} {flag}"
            items.append(
                ExtensionSmallResultItem(
                    icon=extension.icon("icon.png"),
                    name=minimal_text
                )
            )

        return RenderResultListAction(items)


if __name__ == "__main__":
    UWeather().run()
