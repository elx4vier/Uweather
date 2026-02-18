import json
import urllib.request
import urllib.parse
import time
import logging

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

# =========================
# ⚡ CONFIGURAÇÕES
# =========================
CACHE = {}
CACHE_TTL = 600  # 10 minutos
LOG = logging.getLogger(__name__)
WMO = {
    0: "Céu limpo",
    1: "Principalmente limpo",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Nevoeiro",
    61: "Chuva fraca",
    63: "Chuva",
    65: "Chuva forte",
    71: "Neve",
    95: "Tempestade"
}

# =========================
# ⚡ FUNÇÕES AUXILIARES
# =========================
def get_cache(key):
    entry = CACHE.get(key)
    if entry and (time.time() - entry["time"] < CACHE_TTL):
        return entry["data"]
    return None

def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}

def country_flag(code):
    if not code:
        return ""
    return "".join(chr(127397 + ord(c)) for c in code.upper())

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        LOG.warning(f"Erro na requisição: {e}")
        return None

# =========================
# 📍 GEOCODING
# =========================
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

# =========================
# 🌤 WEATHER
# =========================
def get_weather_openmeteo(lat, lon, unit="metric"):
    cache_key = f"weather-om-{lat}-{lon}-{unit}"
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

    weather_code = current.get("weathercode")
    desc = WMO.get(weather_code, "")

    forecast = []
    try:
        for i in range(1, min(4, len(daily["temperature_2m_max"]))):
            max_temp = daily["temperature_2m_max"][i]
            min_temp = daily["temperature_2m_min"][i]
            forecast.append(f"{max_temp} / {min_temp}")
    except Exception as e:
        LOG.warning(f"Erro ao montar forecast Open-Meteo: {e}")

    result = {
        "current_temp": current.get("temperature"),
        "current_desc": desc,
        "forecast": forecast
    }
    set_cache(cache_key, result)
    return result

def get_weather_openweather(lat, lon, api_key, unit="metric"):
    if not api_key:
        return None
    cache_key = f"weather-ow-{lat}-{lon}-{unit}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    url = (
        f"http://api.openweathermap.org/data/2.5/onecall?"
        f"lat={lat}&lon={lon}&appid={api_key}&units={unit}&exclude=minutely,hourly,alerts"
    )
    data = get_json(url)
    if not data or "current" not in data:
        return None

    current = data["current"]
    daily = data.get("daily", [])

    weather_code = current.get("weather", [{}])[0].get("id")
    desc = current.get("weather", [{}])[0].get("description", "")
    
    forecast = []
    try:
        for day in daily[1:4]:
            max_temp = day.get("temp", {}).get("max")
            min_temp = day.get("temp", {}).get("min")
            if max_temp is not None and min_temp is not None:
                forecast.append(f"{round(max_temp)} / {round(min_temp)}")
    except Exception as e:
        LOG.warning(f"Erro ao montar forecast OpenWeather: {e}")

    result = {
        "current_temp": round(current.get("temp", 0)),
        "current_desc": desc.capitalize(),
        "forecast": forecast
    }
    set_cache(cache_key, result)
    return result

def get_weather(lat, lon, provider="openmeteo", api_key="", unit="metric"):
    if provider == "openweather":
        return get_weather_openweather(lat, lon, api_key, unit)
    return get_weather_openmeteo(lat, lon, unit)

# =========================
# 🚀 EXTENSÃO PRINCIPAL
# =========================
class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        # Preferências
        unit = extension.preferences.get("unit", "metric")
        location_mode = extension.preferences.get("location_mode", "auto")
        static_city = extension.preferences.get("static_city", "").strip()
        provider = extension.preferences.get("provider", "openmeteo")
        api_key = extension.preferences.get("api_key", "").strip()
        query = event.get_argument()

        # Determina cidade / coordenadas
        if location_mode == "manual" and static_city:
            lat, lon, city, country = geocode_city(static_city)
            if not lat:
                return render_error(f"Cidade manual inválida: '{static_city}'")
        elif query:
            lat, lon, city, country = geocode_city(query)
            if not lat:
                return render_error(f"Cidade não encontrada: '{query}'")
        else:
            lat, lon, city, country = get_ip_location()
            if not lat:
                return render_error("Não foi possível obter sua localização automática.")

        # Obter clima
        weather = get_weather(lat, lon, provider=provider, api_key=api_key, unit=unit)
        if not weather:
            return render_error("Erro ao buscar clima. Confira provider e API Key.")

        # Formatar saída
        symbol = "°C" if unit == "metric" else "°F"
        flag = country_flag(country)
        current_temp = weather["current_temp"]
        current_desc = weather["current_desc"] or ""
        forecast = " | ".join(weather["forecast"])

        first_line = f"{current_temp}{symbol} - {current_desc}" if current_desc else f"{current_temp}{symbol}"
        description = f"{first_line}\nPróximos dias: {forecast}" if forecast else first_line

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{flag} {city}, {country}",
                description=description,
                on_enter=DoNothingAction()
            )
        ])

def render_error(message):
    return RenderResultListAction([
        SmallResultItem(
            icon='images/icon.png',
            name="Erro",
            description=message,
            on_enter=DoNothingAction()
        )
    ])

if __name__ == "__main__":
    UWeatherExtension().run()
