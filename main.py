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

CACHE_TTL = 300  # 5 minutos


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

            geo = data["geo"]
            weather = data["weather"]

            cidade = geo.get("city", "Desconhecida")

            current = weather["current_weather"]
            temp = current.get("temperature", "?")
            wind = current.get("windspeed", "?")
            code = current.get("weathercode", 0)

            forecast = weather["daily"]

            results = []

            # Clima atual
            results.append(
                ExtensionResultItem(
                    icon=extension.icon(self.get_icon(code)),
                    name=f"{cidade} agora: {temp}°C",
                    description=f"Vento: {wind} km/h",
                    on_enter=None
                )
            )

            # Próximos 3 dias
            for i in range(1, 4):
                date = forecast["time"][i]
                tmax = forecast["temperature_2m_max"][i]
                tmin = forecast["temperature_2m_min"][i]
                code = forecast["weathercode"][i]

                results.append(
                    ExtensionResultItem(
                        icon=extension.icon(self.get_icon(code)),
                        name=f"{date}",
                        description=f"Máx: {tmax}°C | Mín: {tmin}°C",
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
                    description="Verifique sua conexão",
                    on_enter=None
                )
            ])

    def fetch_all(self, extension):
        geo = self.fetch_location(extension)

        lat = geo.get("latitude")
        lon = geo.get("longitude")

        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true"
            "&daily=weathercode,temperature_2m_max,temperature_2m_min"
            "&timezone=auto"
        )

        r = extension.session.get(url, timeout=3)
        weather = r.json()

        return {"geo": geo, "weather": weather}

    def fetch_location(self, extension):
        r = extension.session.get("https://ipapi.co/json/", timeout=2)
        return r.json()

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
