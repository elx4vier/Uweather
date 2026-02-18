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


# =========================
# TRANSLATIONS
# =========================
TRANSLATIONS = {
    "en": {
        "tomorrow": "Tomorrow",
        "after": "Next",
        "location_error": "Could not detect your location",
        "city_not_found": "City not found",
        "set_static_city": "Set a static city in settings",
        "api_missing": "Define your OpenWeather API key",
        "provider_invalid": "Invalid provider"
    },
    "pt": {
        "tomorrow": "Amanhã",
        "after": "Depois",
        "location_error": "Não foi possível detectar sua localização",
        "city_not_found": "Cidade não encontrada",
        "set_static_city": "Defina uma cidade fixa nas configurações",
        "api_missing": "Defina sua API Key do OpenWeather",
        "provider_invalid": "Provedor inválido"
    },
    "es": {
        "tomorrow": "Mañana",
        "after": "Después",
        "location_error": "No se pudo detectar su ubicación",
        "city_not_found": "Ciudad no encontrada",
        "set_static_city": "Defina una ciudad fija en la configuración",
        "api_missing": "Defina su API Key de OpenWeather",
        "provider_invalid": "Proveedor inválido"
    },
    "ru": {
        "tomorrow": "Завтра",
        "after": "Далее",
        "location_error": "Не удалось определить местоположение",
        "city_not_found": "Город не найден",
        "set_static_city": "Укажите фиксированный город в настройках",
        "api_missing": "Укажите API ключ OpenWeather",
        "provider_invalid": "Неверный провайдер"
    },
    "fr": {
        "tomorrow": "Demain",
        "after": "Après",
        "location_error": "Impossible de détecter votre position",
        "city_not_found": "Ville introuvable",
        "set_static_city": "Définissez une ville fixe dans les paramètres",
        "api_missing": "Définissez votre clé API OpenWeather",
        "provider_invalid": "Fournisseur invalide"
    }
}


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
# WEATHER SERVICE
# =========================
class WeatherService:

    @staticmethod
    def fetch_location(session):
        try:
            r = session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if geo.get("latitude") and geo.get("longitude"):
                return {
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "city": geo.get("city")
                }
        except:
            pass

        try:
            r = session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            if geo.get("lat") and geo.get("lon"):
                return {
                    "latitude": geo["lat"],
                    "longitude": geo["lon"],
                    "city": geo.get("city")
                }
        except:
            pass

        return None

    @staticmethod
    def fetch_openweather(session, api_key, unit, lang, city=None, lat=None, lon=None):

        if not api_key:
            raise Exception("api_missing")

        base = "https://api.openweathermap.org/data/2.5/forecast"

        if city:
            url = f"{base}?q={city}&appid={api_key}&units={unit}&lang={lang}"
        else:
            url = f"{base}?lat={lat}&lon={lon}&appid={api_key}&units={unit}&lang={lang}"

        r = session.get(url, timeout=6)
        data = r.json()

        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("city_not_found")

        current = data["list"][0]
        city_name = f"{data['city']['name']}, {data['city']['country']}"

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

        forecast = []
        dates = sorted(daily.keys())[1:3]

        for d in dates:
            forecast.append({
                "min": int(daily[d]["min"]),
                "max": int(daily[d]["max"])
            })

        return {
            "city": city_name,
            "temp": int(current["main"]["temp"]),
            "forecast": forecast
        }

    @staticmethod
    def geocode_openmeteo(session, city):
        url = "https://geocoding-api.open-meteo.com/v1/search"
        r = session.get(url, params={"name": city, "count": 1}, timeout=5)
        data = r.json()

        if not data.get("results"):
            raise Exception("city_not_found")

        result = data["results"][0]

        return {
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "city": result["name"]
        }

    @staticmethod
    def fetch_openmeteo(session, lat, lon, unit):

        base = "https://api.open-meteo.com/v1/forecast"
        temp_unit = "celsius" if unit == "metric" else "fahrenheit"

        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": temp_unit,
            "timezone": "auto"
        }

        r = session.get(base, params=params, timeout=6)
        data = r.json()

        if "current_weather" not in data:
            raise Exception("city_not_found")

        current_temp = int(data["current_weather"]["temperature"])
        daily_max = data["daily"]["temperature_2m_max"]
        daily_min = data["daily"]["temperature_2m_min"]

        forecast = []
        for i in range(1, 3):
            forecast.append({
                "min": int(daily_min[i]),
                "max": int(daily_max[i])
            })

        return {
            "city": "",
            "temp": current_temp,
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

    def icon(self):
        return os.path.join(self.base_path, "images", "icon.png")


# =========================
# LISTENER
# =========================
class WeatherListener(EventListener):

    def safe(self, prefs, key, default):
        return prefs.get(key) or default

    def on_event(self, event, extension):

        prefs = extension.preferences or {}
        lang = self.safe(prefs, "language", "en")
        T = TRANSLATIONS.get(lang, TRANSLATIONS["en"])

        try:
            provider = self.safe(prefs, "provider", "openweather")
            unit = self.safe(prefs, "unit", "metric")
            location_mode = self.safe(prefs, "location_mode", "auto")
            api_key = prefs.get("api_key")

            query = event.get_argument()

            cache_key = f"{provider}-{unit}-{query or 'auto'}-{lang}"

            if cache_key in extension.cache:
                data, ts = extension.cache[cache_key]
                if time.time() - ts < CACHE_TTL:
                    return self.render(data, extension, T)

            geo = None
            city = None

            if query:
                city = query
            elif location_mode == "static":
                city = prefs.get("static_city")
                if not city:
                    raise Exception("set_static_city")
            else:
                geo = WeatherService.fetch_location(extension.session)
                if not geo:
                    raise Exception("location_error")

            if provider == "openweather":
                data = WeatherService.fetch_openweather(
                    extension.session, api_key, unit, lang,
                    city=city,
                    lat=geo["latitude"] if geo else None,
                    lon=geo["longitude"] if geo else None
                )

            elif provider == "openmeteo":

                if city:
                    geo = WeatherService.geocode_openmeteo(extension.session, city)

                if not geo:
                    geo = WeatherService.fetch_location(extension.session)

                data = WeatherService.fetch_openmeteo(
                    extension.session,
                    geo["latitude"],
                    geo["longitude"],
                    unit
                )

                if geo.get("city"):
                    data["city"] = geo["city"]

            else:
                raise Exception("provider_invalid")

            extension.cache[cache_key] = (data, time.time())
            return self.render(data, extension, T)

        except Exception as e:
            key = str(e)
            message = T.get(key, key)

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon(),
                    name=message,
                    description="",
                    on_enter=None
                )
            ])

    def render(self, data, extension, T):

        city = data["city"] or ""
        temp = data["temp"]
        forecast = data["forecast"]

        tomorrow = forecast[0] if len(forecast) > 0 else None
        after = forecast[1] if len(forecast) > 1 else None

        desc = ""
        if tomorrow:
            desc += f"{T['tomorrow']}: {tomorrow['min']}°/{tomorrow['max']}°"
        if after:
            desc += f" | {T['after']}: {after['min']}°/{after['max']}°"

        name = f"{city}\n{temp}°"

        return RenderResultListAction([
            ExtensionResultItem(
                icon=extension.icon(),
                name=name,
                description=desc,
                on_enter=None
            )
        ])


if __name__ == "__main__":
    UWeather().run()
