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
        self.cache = {}  # cache por cidade
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""


class WeatherListener(EventListener):

    def on_event(self, event, extension):
        try:
            city_query = event.get_argument()  # texto após palavra-chave
            cache_key = city_query.lower().strip() if city_query else "auto"

            now = time.time()

            if cache_key in extension.cache:
                cached_data, cache_time = extension.cache[cache_key]
                if now - cache_time < CACHE_TTL:
                    data = cached_data
                else:
                    data = self.fetch_all(extension, city_query)
                    extension.cache[cache_key] = (data, now)
            else:
                data = self.fetch_all(extension, city_query)
                extension.cache[cache_key] = (data, now)

            results = []

            results.append(
                ExtensionResultItem(
                    icon=extension.icon(self.get_icon(data["current"]["code"])),
                    name=f'{data["city"]} agora: {data["current"]["temp"]}°C',
                    description=f'Vento: {data["current"]["wind"]} km/h',
                    on_enter=None
                )
            )

            for day in data["forecast"]:
                results.append(
                    ExtensionResultItem(
                        icon=extension.icon(self.get_icon(day["code"])),
                        name=day["date"],
                        description=f'Máx: {day["max"]}°C | Mín: {day["min"]}°C',
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

    # =============================
    # BUSCA PRINCIPAL
    # =============================

    def fetch_all(self, extension, city_query=None):

        if city_query:
            return self.fetch_by_city(extension, city_query)
        else:
            geo = self.fetch_location(extension)
            return self.fetch_by_coords(extension, geo["latitude"], geo["longitude"], geo.get("city"))

    # =============================
    # BUSCA POR CIDADE (manual)
    # =============================

    def fetch_by_city(self, extension, city):
        api_key = extension.preferences.get("api_key")

        if not api_key:
            raise Exception("Configure sua API Key nas preferências.")

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?q={city}"
            f"&appid={api_key}"
            "&units=metric"
        )

        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Cidade não encontrada.")

        data = r.json()
        return self.parse_openweather(data)

    # =============================
    # BUSCA POR COORDENADAS
    # =============================

    def fetch_by_coords(self, extension, lat, lon, cidade):

        try:
            return self.fetch_open_meteo(extension, lat, lon, cidade)
        except Exception:
            return self.fetch_openweather(extension, lat, lon)

    # =============================
    # LOCALIZAÇÃO AUTOMÁTICA
    # =============================

    def fetch_location(self, extension):

        try:
            r = extension.session.get("https://ipapi.co/json/", timeout=5)
            if r.status_code == 200:
                geo = r.json()
                if "latitude" in geo and "longitude" in geo:
                    return geo
        except Exception:
            pass

        try:
            r = extension.session.get("http://ip-api.com/json/", timeout=5)
            if r.status_code == 200:
                geo = r.json()
                return {
                    "latitude": geo["lat"],
                    "longitude": geo["lon"],
                    "city": geo.get("city", "Desconhecida")
                }
        except Exception:
            pass

        raise Exception("Não foi possível detectar localização")

    # =============================
    # OPEN-METEO (principal)
    # =============================

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

        forecast = []
        for i in range(1, 4):
            forecast.append({
                "date": data["daily"]["time"][i],
                "max": data["daily"]["temperature_2m_max"][i],
                "min": data["daily"]["temperature_2m_min"][i],
                "code": data["daily"]["weathercode"][i]
            })

        return {
            "city": cidade or "Localização atual",
            "current": {
                "temp": data["current_weather"]["temperature"],
                "wind": data["current_weather"]["windspeed"],
                "code": data["current_weather"]["weathercode"]
            },
            "forecast": forecast
        }

    # =============================
    # OPENWEATHER (fallback)
    # =============================

    def fetch_openweather(self, extension, lat, lon):

        api_key = extension.preferences.get("api_key")

        if not api_key:
            raise Exception("Configure sua API Key nas preferências.")

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={lat}&lon={lon}"
            f"&appid={api_key}"
            "&units=metric"
        )

        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("OpenWeatherMap falhou")

        data = r.json()
        return self.parse_openweather(data)

    def parse_openweather(self, data):

        current = data["list"][0]

        forecast = []
        used_dates = set()

        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]

            if date not in used_dates:
                forecast.append({
                    "date": date,
                    "max": item["main"]["temp_max"],
                    "min": item["main"]["temp_min"],
                    "code": 1
                })
                used_dates.add(date)

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

    # =============================
    # ÍCONES
    # =============================

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
