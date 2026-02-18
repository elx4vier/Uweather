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
# ⚡ CONFIG
# =========================
CACHE = {}
CACHE_TTL = 600           # 10 minutos

# =========================
# ⚡ CACHE
# =========================
def get_cache(key):
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
    return None

def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}

# =========================
# 🏳 COUNTRY FLAG
# =========================
def country_flag(code):
    if not code:
        return ""
    return "".join(chr(127397 + ord(c)) for c in code.upper())

# =========================
# 🌐 REQUEST
# =========================
def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Ulauncher Weather)"})
        with urllib.request.urlopen(req, timeout=6) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

# =========================
# 📍 GEOLOCATION
# =========================
def geocode_city(city):
    if not city.strip():
        return None, None, None, None

    cache_key = f"geo-{city.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=pt"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        result = (
            r["latitude"],
            r["longitude"],
            r["name"],
            r.get("country_code", "")
        )
        set_cache(cache_key, result)
        return result
    return None, None, None, None

def get_ip_location():
    cached = get_cache("ip-location")
    if cached:
        return cached

    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        result = (
            data["lat"],
            data["lon"],
            data["city"],
            data["countryCode"]
        )
        set_cache("ip-location", result)
        return result
    return None, None, None, None

# =========================
# 🌤 WEATHER (OPEN-METEO)
# =========================
WMO = {
    0: "Céu claro",
    1: "Predominantemente claro",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Nevoeiro",
    48: "Nevoeiro denso",
    51: "Garoa leve",
    53: "Garoa moderada",
    55: "Garoa intensa",
    56: "Garoa congelante leve",
    57: "Garoa congelante intensa",
    61: "Chuva leve",
    63: "Chuva moderada",
    65: "Chuva forte",
    66: "Chuva congelante leve",
    67: "Chuva congelante intensa",
    71: "Neve leve",
    73: "Neve moderada",
    75: "Neve forte",
    77: "Grãos de neve",
    80: "Chuva leve em pancadas",
    81: "Chuva moderada em pancadas",
    82: "Chuva forte em pancadas",
    85: "Neve leve em pancadas",
    86: "Neve forte em pancadas",
    95: "Tempestade",
    96: "Tempestade com granizo leve",
    99: "Tempestade com granizo forte"
}

def get_weather(lat, lon, unit):
    cache_key = f"weather-{lat:.4f}-{lon:.4f}-{unit}"
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

    result = {
        "current_temp": current.get("temperature"),
        "current_desc": WMO.get(current.get("weathercode"), "Condição desconhecida"),
        "forecast": []
    }

    try:
        for i in range(1, 4):
            max_t = daily['temperature_2m_max'][i]
            min_t = daily['temperature_2m_min'][i]
            result["forecast"].append(f"{max_t:.0f} / {min_t:.0f}")
    except IndexError:
        pass

    set_cache(cache_key, result)
    return result

# =========================
# 🚀 EXTENSION
# =========================
class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())

class WeatherHandler(EventListener):
    def on_event(self, event, extension):
        unit = extension.preferences.get("unit", "metric")
        query = (event.get_argument() or "").strip()

        # ── Caso 1: query vazia → localização por IP
        if not query:
            lat, lon, city, country = get_ip_location()
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Não foi possível detectar sua localização",
                        description="Verifique internet ou digite o nome da cidade",
                        on_enter=DoNothingAction()
                    )
                ])

        # ── Caso 2: query preenchida → geocodificação
        else:
            lat, lon, city, country = geocode_city(query)
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Cidade não encontrada",
                        description=f"Nenhum resultado para '{query}'. Tente outro nome.",
                        on_enter=DoNothingAction()
                    )
                ])

        # ── Buscar clima
        weather = get_weather(lat, lon, unit)
        if not weather or weather["current_temp"] is None:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro ao obter o clima",
                    description="Tente novamente em alguns segundos ou verifique a conexão.",
                    on_enter=DoNothingAction()
                )
            ])

        # ── Montar resultado
        symbol = "°C" if unit == "metric" else "°F"
        flag = country_flag(country)

        first_line = f"{weather['current_temp']}{symbol}"
        if weather["current_desc"]:
            first_line += f" – {weather['current_desc']}"

        forecast_str = " | ".join(weather["forecast"]) if weather["forecast"] else "Sem previsão disponível"
        desc = f"{first_line}\nPróximos dias: {forecast_str}"

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{flag} {city}, {country}",
                description=desc,
                on_enter=DoNothingAction()
            )
        ])

if __name__ == "__main__":
    UWeatherExtension().run()
