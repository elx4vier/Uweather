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
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500,502,503,504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

class UWeather(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.session = create_session()
        self.cache = {}  # {"key": (data, timestamp)}
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""

class WeatherListener(EventListener):

    EMOJI_MAP = {
        "clear": "☀️",
        "clouds": "☁️",
        "rain": "🌧️",
        "snow": "❄️",
        "thunderstorm": "⛈️",
        "partial": "🌤️"
    }

    def weather_emoji(self, code):
        # converte código OpenWeather em categoria
        if code < 300: return self.EMOJI_MAP["thunderstorm"]
        elif code < 600: return self.EMOJI_MAP["rain"]
        elif code < 700: return self.EMOJI_MAP["snow"]
        elif code == 800: return self.EMOJI_MAP["clear"]
        elif code <= 804: return self.EMOJI_MAP["clouds"]
        else: return self.EMOJI_MAP["partial"]

    def weather_text(self, code):
        if code < 300: return "Tempestade"
        elif code < 600: return "Chuva"
        elif code < 700: return "Neve"
        elif code == 800: return "Céu limpo"
        elif code <= 804: return "Nublado"
        else: return "Parcialmente nublado"

    def on_event(self, event, extension):
        try:
            api_key = extension.preferences.get("api_key")
            if not api_key:
                raise Exception("Configure sua API Key do OpenWeatherMap.")

            city_query = event.get_argument()
            cache_key = (city_query.lower().strip() if city_query else "auto")

            # Verifica cache
            if cache_key in extension.cache:
                data, ts = extension.cache[cache_key]
                if time.time() - ts < CACHE_TTL:
                    return self.render_weather(data, extension)

            # Busca dados
            if city_query:
                data = self.fetch_weather(city=city_query, api_key=api_key, session=extension.session)
            else:
                geo = self.fetch_location(extension)
                data = self.fetch_weather(lat=geo["latitude"], lon=geo["longitude"], city_name=geo.get("city"), api_key=api_key, session=extension.session)

            # Atualiza cache
            extension.cache[cache_key] = (data, time.time())

            return self.render_weather(data, extension)

        except Exception as e:
            logger.error(str(e))
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name="Erro ao obter clima",
                    description=str(e),
                    on_enter=None
                )
            ])

    # =====================
    # FETCH WEATHER
    # =====================
    def fetch_weather(self, city=None, lat=None, lon=None, city_name=None, api_key=None, session=None):
        if city:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=pt_br"
        else:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"

        r = session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Cidade não encontrada." if city else "Falha ao buscar clima.")

        data = r.json()
        parsed = self.parse_owm(data)

        # Ajusta cidade caso use coords
        if city_name and not city:
            parsed["city"] = f"{city_name}, {parsed['city'].split(',')[1]}"

        return parsed

    # =====================
    # PARSE OPENWEATHER
    # =====================
    def parse_owm(self, data):
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

        # Previsão amanhã + depois
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
            "current": {
                "temp": int(current["main"]["temp"]),
                "text": self.weather_text(current["weather"][0]["id"]),
                "code": current["weather"][0]["id"]
            },
            "forecast": forecast
        }

    # =====================
    # RENDER WEATHER
    # =====================
    def render_weather(self, data, extension):
        forecast = data["forecast"]
        description = (
            f"Amanhã: {forecast[0]['min']}º / {forecast[0]['max']}º {self.weather_emoji(forecast[0]['code'])} | "
            f"Depois: {forecast[1]['min']}º / {forecast[1]['max']}º {self.weather_emoji(forecast[1]['code'])} "
            " "  # espaço sutil
        )
        return RenderResultListAction([
            ExtensionResultItem(
                icon=extension.icon("sun.png"),
                name=f"{data['city']}\n{data['current']['temp']}º — {data['current']['text']}",
                description=description,
                on_enter=None
            )
        ])

    # =====================
    # LOCALIZAÇÃO
    # =====================
    def fetch_location(self, extension):
        try:
            r = extension.session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if "latitude" in geo and "longitude" in geo:
                return geo
        except: pass
        try:
            r = extension.session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {"latitude": geo["lat"], "longitude": geo["lon"], "city": geo.get("city", "Desconhecida")}
        except: pass
        raise Exception("Falha na localização")


if __name__ == "__main__":
    UWeather().run()
