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
# SAFE SESSION
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
# TRANSLATIONS SAFE
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
        # Primeiro serviço
        try:
            r = session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if geo.get("latitude") and geo.get("longitude"):
                return geo
        except:
            pass

        # Segundo fallback
        try:
            r = session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            if geo.get("lat") and geo.get("lon"):
                return {
                    "latitude": geo["lat"],
                    "longitude": geo["lon"],
                    "city": geo.get("city", "Localização Atual")
                }
        except:
            pass

        return None

    @staticmethod
    def fetch_openweather(session, api_key, unit, city=None, lat=None, lon=None, lang="pt"):
        if not api_key:
            raise Exception("API Key não configurada")

        base = "https://api.openweathermap.org/data/2.5/forecast"

        if city:
            url = f"{base}?q={city}&appid={api_key}&units={unit}&lang={lang}"
        else:
            url = f"{base}?lat={lat}&lon={lon}&appid={api_key}&units={unit}&lang={lang}"

        r = session.get(url, timeout=5)

        try:
            data = r.json()
        except:
            raise Exception("Erro ao interpretar resposta da API")

        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("Cidade não encontrada")

        try:
            current = data["list"][0]
            city_name = f"{data['city']['name']}, {data['city']['country']}"
        except:
            raise Exception("Resposta inesperada da API")

        daily = {}
        for item in data.get("list", []):
            try:
                date = item["dt_txt"].split(" ")[0]
                temp_max = item["main"]["temp_max"]
                temp_min = item["main"]["temp_min"]
            except:
                continue

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

    def icon(self, name):
        path = os.path.join(self.base_path, "images", name)
        return path if os.path.exists(path) else self.icon_default


# =========================
# LISTENER
# =========================
class WeatherListener(EventListener):

    def safe_pref(self, prefs, key, default):
        return prefs.get(key) or default

    def on_event(self, event, extension):
        try:
            prefs = extension.preferences or {}

            provider = self.safe_pref(prefs, "provider", "openweather")
            unit = self.safe_pref(prefs, "unit", "metric")
            lang = self.safe_pref(prefs, "language", "pt")
            view = self.safe_pref(prefs, "view_mode", "full")
            location_mode = self.safe_pref(prefs, "location_mode", "auto")
            api_key = prefs.get("api_key")

            translations = TRANSLATIONS.get(lang, TRANSLATIONS["pt"])

            query = event.get_argument()
            cache_key = f"{provider}-{unit}-{query or 'auto'}"

            if cache_key in extension.cache:
                data, ts = extension.cache[cache_key]
                if time.time() - ts < CACHE_TTL:
                    return self.render(data, extension, view, translations)

            # LOCATION
            geo = None
            city = None

            if query:
                city = query
            elif location_mode == "static":
                city = prefs.get("static_city") or None
                if not city:
                    raise Exception("Defina uma cidade fixa nas configurações")
            else:
                geo = WeatherService.fetch_location(extension.session)
                if not geo:
                    raise Exception("Não foi possível detectar sua localização")

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
                raise Exception("Provedor não implementado ainda")

            extension.cache[cache_key] = (data, time.time())
            return self.render(data, extension, view, translations)

        except Exception as e:
            logger.error(f"Erro: {e}")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name=str(e),
                    description="",
                    on_enter=None
                )
            ])

    # =========================
    # SAFE RENDER
    # =========================
    def render(self, data, extension, view, t):

        city = data.get("city", "Local")
        temp = data.get("temp", "--")
        forecast = data.get("forecast", [])

        tomorrow = forecast[0] if len(forecast) > 0 else None
        after = forecast[1] if len(forecast) > 1 else None

        if view == "minimal":
            name = f"{city}\n{temp}°"
            desc = ""

        elif view == "ultra":
            name = f"{temp}°"
            desc = city

        elif view == "compact" and tomorrow:
            name = city
            desc = f"{temp}° | {t['tomorrow']}: {tomorrow['min']}°/{tomorrow['max']}°"

        elif view == "singleline" and tomorrow:
            name = f"{city} - {temp}° - {t['tomorrow']} {tomorrow['min']}/{tomorrow['max']}°"
            desc = ""

        else:
            desc = ""
            if tomorrow:
                desc += f"{t['tomorrow']}: {tomorrow['min']}°/{tomorrow['max']}°"
            if after:
                desc += f" | {t['after']}: {after['min']}°/{after['max']}°"

            name = f"{city}\n{temp}°"

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
