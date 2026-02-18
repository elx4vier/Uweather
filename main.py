import json
import urllib.request
import urllib.parse
import time
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

# Cache simples
CACHE = {}
CACHE_TTL = 600

def get_cache(key):
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
    return None

def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except:
        return None

def geocode_city(city):
    cache_key = f"geo-{city.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        result = (r["latitude"], r["longitude"], r["name"], r.get("country_code", ""))
        set_cache(cache_key, result)
        return result
    return None, None, None, None

def get_ip_location():
    cached = get_cache("ip-location")
    if cached:
        return cached
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        result = (data["lat"], data["lon"], data["city"], data["countryCode"])
        set_cache("ip-location", result)
        return result
    return None, None, None, None

def get_weather(lat, lon, unit):
    cache_key = f"weather-{lat}-{lon}-{unit}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    temp_unit = "celsius" if unit == "metric" else "fahrenheit"
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&current_weather=true"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit={temp_unit}"
        f"&timezone=auto"
    )
    data = get_json(url)
    if not data:
        return None
    current = data.get("current_weather")
    daily = data.get("daily")
    if not current or not daily:
        return None
    wmo = {
        0: "Céu limpo", 1: "Poucas nuvens", 2: "Parcialmente nublado", 3: "Nublado",
        45: "Nevoeiro", 61: "Chuva fraca", 63: "Chuva", 65: "Chuva forte",
        71: "Neve", 95: "Tempestade"
    }
    result = {
        "temp": current.get("temperature"),
        "desc": wmo.get(current.get("weathercode"), "Desconhecido"),
        "max": daily.get("temperature_2m_max", [])[1:4],
        "min": daily.get("temperature_2m_min", [])[1:4]
    }
    set_cache(cache_key, result)
    return result

class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())

class WeatherHandler(EventListener):
    def on_event(self, event, extension):
        # Sempre retornar uma lista com pelo menos um item
        try:
            unit = extension.preferences.get("unit", "metric")
            query = event.get_argument()

            if query:
                lat, lon, city, country = geocode_city(query)
                if not lat:
                    return RenderResultListAction([
                        SmallResultItem(
                            name="Cidade não encontrada",
                            description=f"'{query}' não é uma cidade válida",
                            on_enter=DoNothingAction()
                        )
                    ])
            else:
                lat, lon, city, country = get_ip_location()
                if not lat:
                    return RenderResultListAction([
                        SmallResultItem(
                            name="Localização não disponível",
                            description="Verifique sua conexão",
                            on_enter=DoNothingAction()
                        )
                    ])

            weather = get_weather(lat, lon, unit)
            if not weather:
                return RenderResultListAction([
                    SmallResultItem(
                        name="Erro no clima",
                        description="Não foi possível obter dados",
                        on_enter=DoNothingAction()
                    )
                ])

            symbol = "°C" if unit == "metric" else "°F"
            flag = "".join(chr(127397 + ord(c)) for c in country.upper()) if country else ""
            forecast = " | ".join([f"{max}/{min}" for max, min in zip(weather['max'], weather['min'])])
            desc = f"{weather['temp']}{symbol} - {weather['desc']}\nPróximos dias: {forecast}"
            name = f"{flag} {city}, {country}" if flag else f"{city}, {country}"

            return RenderResultListAction([
                SmallResultItem(
                    name=name,
                    description=desc,
                    on_enter=DoNothingAction()
                )
            ])
        except Exception as e:
            # Em caso de erro inesperado, mostra mensagem amigável
            return RenderResultListAction([
                SmallResultItem(
                    name="Erro inesperado",
                    description=str(e),
                    on_enter=DoNothingAction()
                )
            ])

if __name__ == "__main__":
    UWeatherExtension().run()
