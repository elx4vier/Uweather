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

# ==============================
# SESSION
# ==============================
def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500,502,503,504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ==============================
# UTILITÁRIOS
# ==============================
def country_flag(country_code):
    if not country_code or len(country_code)!=2:
        return ""
    offset = 127397
    return chr(ord(country_code[0].upper())+offset) + chr(ord(country_code[1].upper())+offset)

# ==============================
# WEATHER SERVICE
# ==============================
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
        try:
            r = session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {"latitude": geo["lat"], "longitude": geo["lon"], "city": geo.get("city","Desconhecida"), "country": geo.get("countryCode","BR")}
        except:
            pass
        raise Exception("Falha na localização")

    # ------------------------------
    # OpenWeather
    # ------------------------------
    @staticmethod
    def fetch_weather_openweather(session, api_key, city=None, lat=None, lon=None, unit="C"):
        if city:
            url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={api_key}&units={'metric' if unit=='C' else 'imperial'}&lang=pt_br"
        else:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={api_key}&units={'metric' if unit=='C' else 'imperial'}&lang=pt_br"

        r = session.get(url, timeout=5)
        data = r.json()
        if r.status_code != 200 or data.get("cod") != "200":
            raise Exception("Cidade não encontrada")
        return WeatherService.parse_weather(data)

    # ------------------------------
    # Open-Meteo
    # ------------------------------
    @staticmethod
    def fetch_weather_openmeteo(session, city=None, lat=None, lon=None, unit="C"):
        if city and not lat and not lon:
            # Busca coordenadas via geocoding gratuito
            r = session.get(f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1", timeout=5)
            geo = r.json().get("results")
            if not geo:
                raise Exception("Cidade não encontrada")
            lat = geo[0]["latitude"]
            lon = geo[0]["longitude"]
            city_name = geo[0]["name"]
            country = geo[0]["country_code"]
        else:
            city_name = city or "Desconhecida"
            country = "BR"

        # Previsão diária
        r = session.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,weathercode&current_weather=true&timezone=auto", timeout=5)
        data = r.json()

        forecast_list = []
        daily = data.get("daily", {})
        if "temperature_2m_max" in daily and "temperature_2m_min" in daily:
            for i in range(min(2, len(daily["temperature_2m_max"]))):
                forecast_list.append({"max": int(daily["temperature_2m_max"][i]), "min": int(daily["temperature_2m_min"][i]), "code": daily["weathercode"][i]})

        current = data.get("current_weather", {})
        return {
            "city": f"{city_name}, {country}",
            "city_name": city_name,
            "country": country,
            "current": {
                "temp": int(current.get("temperature",0)),
                "code": current.get("weathercode",0),
                "desc": "Desconhecido"
            },
            "forecast": forecast_list
        }

    @staticmethod
    def parse_weather(data):
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
        sorted_dates = sorted(daily.keys())
        forecast = []
        for date in sorted_dates[1:3]:
            forecast.append({"max": int(daily[date]["max"]), "min": int(daily[date]["min"]), "code": daily[date]["code"]})
        return {
            "city": f"{data['city']['name']}, {data['city']['country']}",
            "city_name": data['city']['name'],
            "country": data['city']['country'],
            "current": {"temp": int(current["main"]["temp"]), "code": current["weather"][0]["id"], "desc": current["weather"][0]["description"]},
            "forecast": forecast
        }

# ==============================
# EXTENSION
# ==============================
class UWeather(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.session = create_session()
        self.cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.icon_default = os.path.join(self.base_path,"images","icon.png")
        threading.Thread(target=self.preload_weather, daemon=True).start()

    def icon(self, filename):
        path = os.path.join(self.base_path,"images",filename)
        return path if os.path.exists(path) else self.icon_default

    def preload_weather(self):
        try:
            api_key = self.preferences.get("api_key")
            if not api_key:
                return
            geo = WeatherService.fetch_location(self.session)
            data = WeatherService.fetch_weather_openweather(self.session, api_key, lat=geo["latitude"], lon=geo["longitude"])
            self.cache["auto"] = (data,time.time())
        except Exception as e:
            logger.error(f"Preload falhou: {e}")

# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):

    def on_event(self, event, extension):
        try:
            provider = extension.preferences.get("provider") or "openweather"
            api_key = extension.preferences.get("api_key")
            unit = extension.preferences.get("unit") or "C"
            location_mode = extension.preferences.get("location_mode") or "auto"
            static_location = extension.preferences.get("static_location")
            interface_mode = extension.preferences.get("interface_mode") or "complete"

            query = event.get_argument()
            geo = None

            if (not query or query.strip()=="") and location_mode=="auto":
                query = None
                geo = WeatherService.fetch_location(extension.session)
                key = "auto"
            elif (not query or query.strip()=="") and location_mode=="manual" and static_location:
                query = static_location
                key = query.lower()
            else:
                key = query.lower().strip()

            if key in extension.cache:
                data, ts = extension.cache[key]
                if time.time()-ts < CACHE_TTL:
                    return self.render(data, extension, interface_mode)

            if provider=="openweather":
                if query:
                    data = WeatherService.fetch_weather_openweather(extension.session, api_key, city=query, unit=unit)
                else:
                    data = WeatherService.fetch_weather_openweather(extension.session, api_key, lat=geo["latitude"], lon=geo["longitude"], unit=unit)
            else:
                data = WeatherService.fetch_weather_openmeteo(extension.session, city=query, lat=geo["latitude"] if geo else None, lon=geo["longitude"] if geo else None, unit=unit)

            extension.cache[key] = (data,time.time())
            return self.render(data, extension, interface_mode)

        except Exception as e:
            msg = str(e)
            name = "Erro ao obter clima"
            desc = msg
            icon = extension.icon("error.png")
            return RenderResultListAction([
                ExtensionResultItem(icon=icon, name=name, description=desc, on_enter=None)
            ])

    # ==============================
    # RENDER
    # ==============================
def render(self, data, extension, interface_mode):
    city_name = data.get("city_name") or "Desconhecida"
    country = data.get("country") or "BR"
    flag = country_flag(country)
    temp = data["current"]["temp"]
    desc = data["current"]["desc"]
    forecast = data.get("forecast", [])

    # -----------------------------
    # Completo: 3 linhas, 3ª linha em fonte menor
    # -----------------------------
    if interface_mode=="complete":
        line1 = f"{city_name}, {country} {flag}"
        line2 = f"{temp}º, {desc}"
        line3 = ""
        if forecast:
            tomorrow = forecast[0]
            after = forecast[1] if len(forecast)>1 else None
            parts = []
            if tomorrow:
                parts.append(f"Amanhã: {tomorrow['min']}º / {tomorrow['max']}º")
            if after:
                parts.append(f"Depois: {after['min']}º / {after['max']}º")
            line3 = " | ".join(parts)
        # terceira linha em description → fonte menor
        name = f"{line1}\n{line2}"
        description = line3

    # -----------------------------
    # Essencial: duas linhas, vírgula após temperatura
    # -----------------------------
    elif interface_mode=="essential":
        line1 = f"{temp}º, {desc}"
        line2 = f"{city_name}, {country} {flag}"
        name = line1
        description = line2

    # -----------------------------
    # Mínimo: linha pequena, fonte simulada menor
    # -----------------------------
    elif interface_mode=="minimal":
        # colocar texto principal em description para reduzir altura
        name = f"{temp}º - {city_name} {flag}"
        description = ""  # vazio, ou poderia colocar mesmo texto aqui para compactar ainda mais

    return RenderResultListAction([
        ExtensionResultItem(
            icon=extension.icon("icon.png"),
            name=name,
            description=description,
            on_enter=None
        )
    ])

if __name__=="__main__":
    UWeather().run()
