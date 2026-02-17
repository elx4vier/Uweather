import logging
import requests
import time
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

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
        self.cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""

class WeatherListener(EventListener):

    def weather_emoji(self, code):
        if code == 0: return "☀️"
        elif code in [1,2,3,45,48]: return "☁️"
        elif code in [51,53,55,61,63,65]: return "🌧️"
        elif code in [71,73,75]: return "❄️"
        elif code in [95,96,99]: return "⛈️"
        else: return "🌤️"

    def weather_text(self, code):
        if code == 0: return "Céu limpo"
        elif code in [1,2,3,45,48]: return "Nublado"
        elif code in [51,53,55,61,63,65]: return "Chuva"
        elif code in [71,73,75]: return "Neve"
        elif code in [95,96,99]: return "Tempestade"
        else: return "Parcialmente nublado"

    def on_event(self, event, extension):
        try:
            api_key = extension.preferences.get("api_key")
            if not api_key:
                raise Exception("Configure sua API Key do OpenWeatherMap.")

            city_query = event.get_argument()
            if city_query:
                # busca clima da cidade digitada
                data = self.fetch_city(city_query, api_key, extension.session)
            else:
                # busca clima da localização atual
                geo = self.fetch_location(extension)
                data = self.fetch_coords(geo["latitude"], geo["longitude"], geo.get("city"), api_key, extension.session)

            # cache
            cache_key = city_query.lower().strip() if city_query else "auto"
            extension.cache[cache_key] = (data, time.time())

            # monta bloco
            name = f"{data['city']}\n{data['current']['temp']}º — {data['current']['text']}"
            forecast = data["forecast"]
            description = f"Amanhã: {forecast[0]['min']}º / {forecast[0]['max']}º {self.weather_emoji(forecast[0]['code'])} | " \
                          f"Depois: {forecast[1]['min']}º / {forecast[1]['max']}º {self.weather_emoji(forecast[1]['code'])}"

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("sun.png"),
                    name=name,
                    description=description,
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

    # =====================
    # FETCH CIDADE / COORDS
    # =====================
    def fetch_city(self, city, api_key, session):
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=pt_br"
        r = session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Cidade não encontrada.")
        return self.parse_owm(r.json())

    def fetch_coords(self, lat, lon, city, api_key, session):
        url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=pt_br"
        r = session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Falha ao buscar clima.")
        data = self.parse_owm(r.json())
        data["city"] = f"{city}, {data['city'].split(',')[1]}"  # mantém sigla país
        return data

    # =====================
    # PARSE OPENWEATHER
    # =====================
    def parse_owm(self, data):
        current = data["list"][0]
        forecast = []
        used_dates = set()
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in used_dates:
                forecast.append({
                    "max": int(item["main"]["temp_max"]),
                    "min": int(item["main"]["temp_min"]),
                    "code": 1  # placeholder para emoji
                })
                used_dates.add(date)
            if len(forecast) == 3:
                break
        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "current": {
                "temp": int(current["main"]["temp"]),
                "text": "Céu limpo",
                "code": 0
            },
            "forecast": forecast[1:]  # Amanhã + Depois
        }

    # =====================
    # LOCALIZAÇÃO
    # =====================
    def fetch_location(self, extension):
        # ipapi
        try:
            r = extension.session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if "latitude" in geo and "longitude" in geo:
                return geo
        except: pass
        # ip-api fallback
        try:
            r = extension.session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {"latitude": geo["lat"], "longitude": geo["lon"], "city": geo.get("city", "Desconhecida")}
        except: pass
        raise Exception("Falha na localização")


if __name__ == "__main__":
    UWeather().run()
