import json
import urllib.request
import urllib.parse
import time
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
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

# Códigos WMO (apenas os mais comuns)
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
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
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
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Erro na requisição: {e}")
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
    # Retorna None para todos os valores quando não encontra
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
# 🌤 WEATHER (Open-Meteo)
# =========================
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
    weather_code = current.get("weathercode")
    desc = WMO.get(weather_code, "")
    result = {
        "current_temp": current.get("temperature"),
        "current_desc": desc,
        "forecast": []
    }
    try:
        for i in range(1, min(4, len(daily["temperature_2m_max"]))):
            result["forecast"].append(
                f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}"
            )
    except:
        pass
    set_cache(cache_key, result)
    return result

# =========================
# 🚀 EXTENSÃO PRINCIPAL
# =========================
class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        # Obtém preferências
        unit = extension.preferences.get("unit", "metric")
        query = event.get_argument()

        # Se não há argumento, usa localização automática
        if not query:
            lat, lon, city, country = get_ip_location()
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Erro de localização",
                        description="Não foi possível obter sua localização automática.",
                        on_enter=DoNothingAction()
                    )
                ])
        else:
            lat, lon, city, country = geocode_city(query)
            # Se a cidade não for encontrada, exibe mensagem clara
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Cidade não encontrada",
                        description=f"'{query}' não é uma cidade válida.",
                        on_enter=DoNothingAction()
                    )
                ])

        # Obtém dados do clima
        weather = get_weather(lat, lon, unit)
        if not weather:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro ao buscar clima",
                    description="Tente novamente em instantes.",
                    on_enter=DoNothingAction()
                )
            ])

        # Formata a saída
        symbol = "°C" if unit == "metric" else "°F"
        flag = country_flag(country)
        current_desc = weather["current_desc"]
        current_temp = weather["current_temp"]
        forecast = " | ".join(weather["forecast"])

        if current_desc:
            first_line = f"{current_temp}{symbol} - {current_desc}"
        else:
            first_line = f"{current_temp}{symbol}"

        description = f"{first_line}\nPróximos dias: {forecast}"

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{flag} {city}, {country}",
                description=description,
                on_enter=DoNothingAction()
            )
        ])

if __name__ == "__main__":
    UWeatherExtension().run()
