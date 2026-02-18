import logging
import requests
import time
import os
import threading
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

logger = logging.getLogger(__name__)
CACHE_TTL = 300

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
# WEATHER SERVICE
# ==============================
class WeatherService:

    @staticmethod
    def fetch_location(session):
        try:
            r = session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if "latitude" in geo:
                return geo
        except:
            pass
        try:
            r = session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {"latitude": geo["lat"], "longitude": geo["lon"], "city": geo.get("city", "Desconhecida")}
        except:
            pass
        raise Exception("Falha na localização")

    @staticmethod
    def fetch_weather_openweather(session, api_key, city=None, lat=None, lon=None, unit="C"):
        if city:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units={'metric' if unit=='C' else 'imperial'}&lang=pt_br"
        else:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units={'metric' if unit=='C' else 'imperial'}&lang=pt_br"

        r = session.get(url, timeout=5)
        data = r.json()
        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("Cidade não encontrada")
        return WeatherService.parse_weather(data)

    @staticmethod
    def parse_weather(data):
        current = data["list"][0]
        daily = {}
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            temp_max = item["main"]["temp_max"]
            temp_min = item["main"]["temp_min"]
            code = item["weather"][0]["id"]
            if date not in daily:
                daily[date] = {"max": temp_max, "min": temp_min, "code": code}
            else:
                daily[date]["max"] = max(daily[date]["max"], temp_max)
                daily[date]["min"] = min(daily[date]["min"], temp_min)
        sorted_dates = sorted(daily.keys())
        forecast = []
        for date in sorted_dates[1:3]:
            forecast.append({"max": int(daily[date]["max"]), "min": int(daily[date]["min"]), "code": daily[date]["code"]})
        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "current": {"temp": int(current["main"]["temp"]), "code": current["weather"][0]["id"]},
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
        self.cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.icon_default = os.path.join(self.base_path, "images", "icon.png")
        threading.Thread(target=self.preload_weather, daemon=True).start()

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else self.icon_default

    def preload_weather(self):
        try:
            api_key = self.preferences.get("api_key")
            if not api_key:
                return
            geo = WeatherService.fetch_location(self.session)
            data = WeatherService.fetch_weather_openweather(
                self.session, api_key, lat=geo["latitude"], lon=geo["longitude"]
            )
            self.cache["auto"] = (data, time.time())
        except Exception as e:
            logger.error(f"Preload falhou: {e}")

# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):

    def on_event(self, event, extension):
        try:
            provider = extension.preferences.get("provider") or "open-meteo"
            api_key = extension.preferences.get("api_key")
            unit = extension.preferences.get("unit") or "C"
            location_mode = extension.preferences.get("location_mode") or "auto"
            static_city = extension.preferences.get("static_city")
            interface_mode = extension.preferences.get("interface_mode") or "complete"

            query = event.get_argument()
            if location_mode == "manual" and static_city and not query:
                query = static_city

            key = query.lower().strip() if query else "auto"

            # cache
            if key in extension.cache:
                data, ts = extension.cache[key]
                if time.time() - ts < CACHE_TTL:
                    return self.render(data, extension, interface_mode, unit)

            # fetch weather
            if provider == "openweather":
                data = WeatherService.fetch_weather_openweather(
                    extension.session, api_key, city=query, unit=unit
                )
            else:
                # Placeholder for Open-Meteo implementation
                data = {"city": query or "Desconhecida", "current": {"temp": 0, "code": 0}, "forecast": []}

            extension.cache[key] = (data, time.time())
            return self.render(data, extension, interface_mode, unit)

        except Exception as e:
            msg = str(e)
            if "Cidade não encontrada" in msg:
                name = "Cidade não encontrada"
                desc = "Digite uma cidade válida para continuar"
                icon = extension.icon("icon.png")
            else:
                name = "Erro ao obter clima"
                desc = msg
                icon = extension.icon("error.png")
            return RenderResultListAction([
                ExtensionResultItem(icon=icon, name=name, description=desc, on_enter=None)
            ])

    # ==============================
    # RENDER
    # ==============================
    def render(self, data, extension, interface_mode, unit):
        city_name = data["city"]
        temp = data["current"]["temp"]
        forecast = data["forecast"]

        # Emojis para condições simples (exemplo)
        weather_emoji = {200:"⛈️", 300:"🌦️", 500:"🌧️", 600:"❄️", 700:"🌫️", 800:"☀️", 801:"🌤️", 802:"⛅", 803:"🌥️", 804:"☁️"}
        current_code = data["current"]["code"]
        current_emoji = weather_emoji.get(current_code, "🌡️")

        if interface_mode == "complete":
            desc_parts = []
            if forecast:
                tomorrow = forecast[0]
                after = forecast[1] if len(forecast)>1 else None
                if tomorrow:
                    desc_parts.append(f"Amanhã: {tomorrow['min']}º / {tomorrow['max']}º")
                if after:
                    desc_parts.append(f"Depois: {after['min']}º / {after['max']}º")
            description = " | ".join(desc_parts)
            name = f"{city_name} {temp}º {current_emoji}"

        elif interface_mode == "essential":
            name = f"{temp}º {current_emoji}"
            description = f"{city_name}"

        elif interface_mode == "minimal":
            name = f"{temp}º"
            description = f"{city_name}"

        return RenderResultListAction([
            ExtensionResultItem(
                icon=extension.icon("icon.png"),
                name=name,
                description=description,
                on_enter=None
            )
        ])


if __name__ == "__main__":
    UWeather().run()
