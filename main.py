import logging
import requests
import time
import os
from collections import Counter

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
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
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

    def weather_emoji(self, code):
        if code == 0:
            return "☀️"
        elif code in [1, 2, 3, 45, 48]:
            return "☁️"
        elif code in [51, 53, 55, 61, 63, 65]:
            return "🌧️"
        elif code in [71, 73, 75]:
            return "❄️"
        elif code in [95, 96, 99]:
            return "⛈️"
        else:
            return "🌤️"

    def weather_text(self, code):
        if code == 0:
            return "Céu limpo"
        elif code in [1, 2, 3, 45, 48]:
            return "Nublado"
        elif code in [51, 53, 55, 61, 63, 65]:
            return "Chuva"
        elif code in [71, 73, 75]:
            return "Neve"
        elif code in [95, 96, 99]:
            return "Tempestade"
        else:
            return "Parcialmente nublado"

    def on_event(self, event, extension):
        try:
            city_query = event.get_argument()
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

            texto = self.format_block(data)

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("sun.png"),
                    name=texto,
                    description="",  # sem texto extra
                    on_enter=None
                )
            ])

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
    # BUSCA MANUAL POR CIDADE
    # =============================

    def fetch_by_city(self, extension, city):
        api_key = extension.preferences.get("api_key")
        if not api_key:
            raise Exception("Configure sua API Key nas preferências.")

        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=pt_br"
        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Cidade não encontrada.")

        return self.parse_openweather(r.json())

    # =============================
    # BUSCA POR COORDENADAS
    # =============================

    def fetch_by_coords(self, extension, lat, lon, city):
        try:
            return self.fetch_open_meteo(extension, lat, lon, city)
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
                return {"latitude": geo["lat"], "longitude": geo["lon"], "city": geo.get("city", "Desconhecida")}
        except Exception:
            pass
        raise Exception("Falha na localização")

    # =============================
    # OPENWEATHERMAP (principal e fallback)
    # =============================

    def fetch_openweather(self, extension, lat, lon):
        api_key = extension.preferences.get("api_key")
        if not api_key:
            raise Exception("Configure sua API Key nas preferências.")

        url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"
        r = extension.session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("OpenWeatherMap falhou")
        return self.parse_openweather(r.json())

    def parse_openweather(self, data):
        current = data["list"][0]
        forecast = []
        used_dates = set()
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in used_dates:
                forecast.append({
                    "date": date,
                    "max": int(item["main"]["temp_max"]),
                    "min": int(item["main"]["temp_min"]),
                    "code": 1
                })
                used_dates.add(date)
            if len(forecast) == 3:
                break

        # Próximas horas: usar condições e probabilidade de chuva
        next_hours = data["list"][:6]  # próximas 6 horas
        conditions = [1 for i in next_hours]  # simplificado: todos code=1
        pop = [int(i.get("pop", 0)*100) for i in next_hours]  # probabilidade de chuva %

        most_common_code = Counter(conditions).most_common(1)[0][0]
        rain_chance = max(pop) if pop else 0

        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "current": {
                "temp": int(current["main"]["temp"]),
                "code": 1,
                "text": "Céu limpo",
            },
            "forecast": forecast[1:],  # Amanhã e Depois
            "next_condition": most_common_code,
            "rain_chance": rain_chance
        }

    # =============================
    # FORMATAR BLOCO CLEAN
    # =============================

    def format_block(self, data):
        cur = data["current"]
        emoji = self.weather_emoji(cur["code"])
        block = f"{data['city']}\n"
        block += f"{cur['temp']}º, {cur['text']}\n\n"
        block += f"Próximas horas: {emoji}\n"
        block += f"Possibilidade de chuva: {data['rain_chance']}%\n\n"
        for i, day in enumerate(data["forecast"]):
            day_emoji = self.weather_emoji(day["code"])
            dias = ["Amanhã", "Depois"]
            block += f"{dias[i]}: {day['max']}º / {day['min']}º {day_emoji}\n"
        block += "\nFonte: OpenWeatherMap"
        return block


if __name__ == "__main__":
    UWeather().run()
