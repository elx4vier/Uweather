import logging
import requests
import time
import os

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

logger = logging.getLogger(__name__)

CACHE_TTL = 300
OWM_API_KEY = "4e984b8d646f78243e905469f3ebd800"


def create_session():
    session = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class UWeather(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())

        self.session = create_session()
        self.cache = None
        self.cache_time = 0
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""


class WeatherListener(EventListener):

    def on_event(self, event, extension):
        try:
            now = time.time()

            if extension.cache and (now - extension.cache_time < CACHE_TTL):
                data = extension.cache
            else:
                data = self.fetch_all(extension)
                extension.cache = data
                extension.cache_time = now

            cidade = data["city"]
            current = data["current"]
            forecast = data["forecast"]

            results = []

            results.append(
                ExtensionResultItem(
                    icon=extension.icon(self.get_icon(current["code"])),
                    name=f"{cidade} agora: {current['temp']}°C",
                    description=f"Vento: {current['wind']} km/h",
                    on_enter=None
                )
            )

            for day in forecast:
                results.append(
                    ExtensionResultItem(
                        icon=extension.icon(self.get_icon(day["code"])),
                        name=day["date"],
                        description=f"Máx: {day['max']}°C | Mín: {day['min']}°C",
                        on_enter=None
                    )
                )

            return RenderResultListAction(results)

        except Exception as e:
            logger.error(f"Erro clima: {e}")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name="Erro ao obter clima",
                    description=str(e),
                    on_enter=None
                )
            ])

    # ==============================
    # BUSCA COMPLETA (com fallback)
    # ==============================

    def fetch_all(self, extension):
        geo = self.fetch_location(extension)

        lat = geo.get("latitude")
        lon = geo.get("longitude")
        cidade = geo.get("city", "Desconhecida")

        try:
            return self.fetch_open_meteo(extension, lat, lon, cidade)
        except Exception:
            return self.fetch_openweather(extension, lat, lon, cidade)

    # ==============================
    # API PRINCIPAL (Open-Meteo)
    # ==============================

    def fetch_open_meteo(self, extension, lat, lon, cidade):
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true"
            "&daily=weathercode,temperature_2m_max,temperature_2m_min"
            "&timezone=auto"
        )

        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Open-Meteo falhou")

        data = r.json()

        current = data["current_weather"]
        daily = data["daily"]

        forecast = []
        for i in range(1, 4):
            forecast.append({
                "date": daily["time"][i],
                "max": daily["temperature_2m_max"][i],
                "min": daily["temperature_2m_min"][i],
                "code": daily["weathercode"][i]
            })

        return {
            "city": cidade,
            "current": {
                "temp": current["temperature"],
                "wind": current["windspeed"],
                "code": current["weathercode"]
            },
            "forecast": forecast
        }

    # ==============================
    # FALLBACK (OpenWeatherMap)
    # ==============================

    def fetch_openweather(self, extension, lat, lon, cidade):
        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}"
            f"&appid={OWM_API_KEY}"
            "&units=metric&lang=pt_br"
        )

        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("OpenWeatherMap falhou")

        data = r.json()

        current = data["list"][0]

        forecast = []
        days_added = set()

        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]

            if date not in days_added:
                forecast.append({
                    "date": date,
                    "max": item["main"]["temp_max"],
                    "min": item["main"]["temp_min"],
                    "code": 1  # simplificado
                })
                days_added.add(date)

            if len(forecast) == 3:
                break

        return {
            "city": data["city"]["name"],
            "current": {
                "temp": current["main"]["temp"],
                "wind": current["wind"]["speed"],
                "code": 1
            },
            "forecast": forecast
        }

    # ==============================
    # LOCALIZAÇÃO
    # ==============================

    def fetch_location(self, extension):
        r = extension.session.get("https://ipapi.co/json/", timeout=5)
        geo = r.json()

        if "latitude" not in geo:
            raise Exception("Falha na localização")

        return geo

    # ==============================
    # ÍCONES
    # ==============================

    def get_icon(self, code):
        if code == 0:
            return "sun.png"
        elif code in [1, 2, 3, 45, 48]:
            return "cloud.png"
        elif code in [51, 53, 55, 61, 63, 65]:
            return "rain.png"
        elif code in [71, 73, 75]:
            return "snow.png"
        elif code in [95, 96, 99]:
            return "storm.png"
        else:
            return "cloud.png"


if __name__ == "__main__":
    UWeather().run()
