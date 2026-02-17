import logging
import requests
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
        self.cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""


class WeatherListener(EventListener):

    def weather_emoji(self, code):
        """Retorna emoji do clima baseado no código."""
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
        """Retorna texto do clima baseado no código."""
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
            api_key = extension.preferences.get("api_key")
            if not api_key:
                raise Exception("Configure sua API Key do OpenWeatherMap nas preferências.")

            city = event.get_argument() or "Paris"  # Default Paris se não passar cidade
            cache_key = city.lower().strip()
            import time
            now = time.time()

            # Cache inteligente
            if cache_key in extension.cache:
                cached_data, cache_time = extension.cache[cache_key]
                if now - cache_time < CACHE_TTL:
                    data = cached_data
                else:
                    data = self.fetch_weather(city, api_key, extension.session)
                    extension.cache[cache_key] = (data, now)
            else:
                data = self.fetch_weather(city, api_key, extension.session)
                extension.cache[cache_key] = (data, now)

            # Monta bloco clean
            name = f"{data['city']}\n{data['current']['temp']}º, {data['current']['text']}"
            description = f"Amanhã: {data['forecast'][0]['max']}º / {data['forecast'][0]['min']}º {self.weather_emoji(data['forecast'][0]['code'])} | " \
                          f"Depois: {data['forecast'][1]['max']}º / {data['forecast'][1]['min']}º {self.weather_emoji(data['forecast'][1]['code'])}"

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("sun.png"),
                    name=name,
                    description=description,  # aparece em fonte menor
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

    def fetch_weather(self, city, api_key, session):
        """Busca clima pelo OpenWeatherMap."""
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units=metric&lang=pt_br"
        r = session.get(url, timeout=5)
        if r.status_code != 200:
            raise Exception("Cidade não encontrada ou erro na API.")

        data = r.json()
        current = data["list"][0]

        forecast = []
        used_dates = set()
        for item in data["list"]:
            date = item["dt_txt"].split(" ")[0]
            if date not in used_dates:
                forecast.append({
                    "max": int(item["main"]["temp_max"]),
                    "min": int(item["main"]["temp_min"]),
                    "code": 1  # Pode melhorar para usar código real
                })
                used_dates.add(date)
            if len(forecast) == 3:  # Amanhã + Depois
                break

        return {
            "city": f"{data['city']['name']} — {data['city']['country']}",
            "current": {
                "temp": int(current["main"]["temp"]),
                "text": "Céu limpo",  # Pode melhorar para pegar condição real
                "code": 0
            },
            "forecast": forecast[1:]  # Pega Amanhã e Depois
        }


if __name__ == "__main__":
    UWeather().run()
