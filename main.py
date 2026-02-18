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


# =========================
# SESSION
# =========================
def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3,
                    status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# =========================
# TRANSLATIONS
# =========================
TRANSLATIONS = {
    "pt": {"tomorrow": "Amanhã", "after": "Depois", "city_not_found": "Cidade não encontrada"},
    "en": {"tomorrow": "Tomorrow", "after": "Next", "city_not_found": "City not found"},
    "es": {"tomorrow": "Mañana", "after": "Después", "city_not_found": "Ciudad no encontrada"},
    "ru": {"tomorrow": "Завтра", "after": "Далее", "city_not_found": "Город не найден"},
    "fr": {"tomorrow": "Demain", "after": "Après", "city_not_found": "Ville non trouvée"},
}


# =========================
# WEATHER SERVICE
# =========================
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
        raise Exception("Falha na localização")

    # -------- OPENWEATHER --------
    @staticmethod
    def fetch_openweather(session, api_key, unit, city=None, lat=None, lon=None, lang="pt"):
        if not api_key:
            raise Exception("API Key necessária para OpenWeather")

        base = "https://api.openweathermap.org/data/2.5/forecast"
        if city:
            url = f"{base}?q={city}&appid={api_key}&units={unit}&lang={lang}"
        else:
            url = f"{base}?lat={lat}&lon={lon}&appid={api_key}&units={unit}&lang={lang}"

        r = session.get(url, timeout=5)
        data = r.json()

        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("Cidade não encontrada")

        return WeatherService.parse_openweather(data)

    @staticmethod
    def parse_openweather(data):
        current = data["list"][0]
        daily = {}

        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            temp_max = item["main"]["temp_max"]
            temp_min = item["main"]["temp_min"]

            if date not in daily:
                daily[date] = {"max": temp_max, "min": temp_min}
            else:
                daily[date]["max"] = max(daily[date]["max"], temp_max)
                daily[date]["min"] = min(daily[date]["min"], temp_min)

        dates = sorted(daily.keys())[1:3]
        forecast = [
            {"min": int(daily[d]["min"]), "max": int(daily[d]["max"])}
            for d in dates
        ]

        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "temp": int(current["main"]["temp"]),
            "forecast": forecast
        }

    # -------- OPEN-METEO --------
    @staticmethod
    def fetch_openmeteo(session, lat, lon, unit):
        temp_unit = "fahrenheit" if unit == "imperial" else "celsius"

        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current_weather=true"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&temperature_unit={temp_unit}"
            f"&timezone=auto"
        )

        r = session.get(url, timeout=5)
        data = r.json()

        current = int(data["current_weather"]["temperature"])

        forecast = []
        for i in range(1, 3):
            forecast.append({
                "min": int(data["daily"]["temperature_2m_min"][i]),
                "max": int(data["daily"]["temperature_2m_max"][i]),
            })

        return {
            "city": "Localização Atual",
            "temp": current,
            "forecast": forecast
        }


# =========================
# EXTENSION
# =========================
class UWeather(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.session = create_session()
        self.cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.icon_default = os.path.join(self.base_path, "images", "icon.png")

        threading.Thread(target=self.preload, daemon=True).start()

    def icon(self, name):
        path = os.path.join(self.base_path, "images", name)
        return path if os.path.exists(path) else self.icon_default

    def preload(self):
        try:
            self.cache["auto"] = ({"preloaded": True}, time.time())
        except:
            pass


# =========================
# LISTENER
# =========================
class WeatherListener(EventListener):

    def on_event(self, event, extension):
        try:
            prefs = extension.preferences

            provider = prefs.get("provider", "openweather")
            unit = prefs.get("unit", "metric")
            lang = prefs.get("language", "pt")
            view = prefs.get("view_mode", "full")
            location_mode = prefs.get("location_mode", "auto")
            api_key = prefs.get("api_key")

            t = TRANSLATIONS.get(lang, TRANSLATIONS["pt"])

            query = event.get_argument()
            cache_key = f"{provider}-{unit}-{query or 'auto'}"

            if cache_key in extension.cache:
                data, ts = extension.cache[cache_key]
                if time.time() - ts < CACHE_TTL:
                    return self.render(data, extension, view, t)

            # LOCATION
            if query:
                city = query
                geo = None
            elif location_mode == "static":
                city = prefs.get("static_city")
                if not city:
                    raise Exception("Defina uma cidade fixa nas configurações")
                geo = None
            else:
                geo = WeatherService.fetch_location(extension.session)
                city = None

            # PROVIDER
            if provider == "openweather":
                if city:
                    data = WeatherService.fetch_openweather(
                        extension.session, api_key, unit, city=city, lang=lang
                    )
                else:
                    data = WeatherService.fetch_openweather(
                        extension.session, api_key, unit,
                        lat=geo["latitude"], lon=geo["longitude"], lang=lang
                    )
            else:
                if not geo:
                    geo = WeatherService.fetch_location(extension.session)
                data = WeatherService.fetch_openmeteo(
                    extension.session, geo["latitude"], geo["longitude"], unit
                )

            extension.cache[cache_key] = (data, time.time())
            return self.render(data, extension, view, t)

        except Exception as e:
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name=str(e),
                    description="",
                    on_enter=None
                )
            ])

    # =========================
    # RENDER MODES
    # =========================
    def render(self, data, extension, view, t):

        city = data["city"]
        temp = data["temp"]
        forecast = data["forecast"]

        if view == "minimal":
            name = f"{city}\n{temp}°"
            desc = ""

        elif view == "ultra":
            name = f"{temp}°"
            desc = city

        elif view == "compact":
            name = f"{city}"
            desc = f"{temp}° | {t['tomorrow']}: {forecast[0]['min']}°/{forecast[0]['max']}°"

        elif view == "singleline":
            name = f"{city} - {temp}° - {t['tomorrow']} {forecast[0]['min']}/{forecast[0]['max']}°"
            desc = ""

        else:  # FULL
            name = f"{city}\n{temp}°"
            desc = (
                f"{t['tomorrow']}: {forecast[0]['min']}°/{forecast[0]['max']}° | "
                f"{t['after']}: {forecast[1]['min']}°/{forecast[1]['max']}°"
            )

        return RenderResultListAction([
            ExtensionResultItem(
                icon=extension.icon("icon.png"),
                name=name,
                description=desc,
                on_enter=None
            )
        ])


if __name__ == "__main__":
    UWeather().run()
