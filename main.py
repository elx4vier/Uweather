import json
import urllib.request
import urllib.parse
import time
import traceback
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
CACHE_TTL = 600  # 10 min

# =========================
# ⚡ CACHE SIMPLES
# =========================
def get_cache(key):
    if key in CACHE and time.time() - CACHE[key]["time"] < CACHE_TTL:
        return CACHE[key]["data"]
    return None

def set_cache(key, data):
    CACHE[key] = {"time": time.time(), "data": data}

# =========================
# 🏳 BANDEIRA
# =========================
def country_flag(code):
    if not code or len(code) != 2:
        return ""
    return "".join(chr(127397 + ord(c.upper())) for c in code)

# =========================
# 🌐 GET JSON COM TRATAMENTO
# =========================
def get_json(url):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Ulauncher-Weather/1.0 (compatible)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None

# =========================
# 📍 GEOCODE
# =========================
def geocode_city(city):
    city = city.strip()
    if not city:
        return None, None, None, None

    cache_key = f"geo-{city.lower()}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    try:
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=pt"
        data = get_json(url)
        if data and isinstance(data, dict) and data.get("results"):
            r = data["results"][0]
            result = (
                r.get("latitude"),
                r.get("longitude"),
                r.get("name"),
                r.get("country_code", "")
            )
            if result[0] is not None and result[1] is not None:
                set_cache(cache_key, result)
                return result
    except Exception:
        pass

    return None, None, None, None

# =========================
# 📍 IP LOCATION
# =========================
def get_ip_location():
    cached = get_cache("ip-loc")
    if cached:
        return cached

    try:
        data = get_json("http://ip-api.com/json/")
        if data and data.get("status") == "success":
            result = (
                data.get("lat"),
                data.get("lon"),
                data.get("city"),
                data.get("countryCode")
            )
            if result[0] is not None:
                set_cache("ip-loc", result)
                return result
    except Exception:
        pass
    return None, None, None, None

# =========================
# 🌤 WEATHER
# =========================
WMO_PT = {
    0: "Céu claro",
    1: "Predominante claro",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Nevoeiro",
    48: "Nevoeiro denso",
    51: "Garoa leve",
    61: "Chuva leve",
    63: "Chuva",
    65: "Chuva forte",
    71: "Neve leve",
    73: "Neve",
    95: "Tempestade",
    # ... pode adicionar mais se quiser
}

def get_weather(lat, lon, unit):
    if lat is None or lon is None:
        return None

    cache_key = f"wx-{lat:.4f}-{lon:.4f}-{unit}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    try:
        temp_unit = "celsius" if unit == "metric" else "fahrenheit"
        url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            f"&current_weather=true"
            f"&daily=temperature_2m_max,temperature_2m_min"
            f"&temperature_unit={temp_unit}&timezone=auto"
        )
        data = get_json(url)
        if not data or "current_weather" not in data:
            return None

        current = data["current_weather"]
        daily = data.get("daily", {})

        desc = WMO_PT.get(current.get("weathercode"), "Desconhecido")

        forecast = []
        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])
        for i in range(1, min(4, len(temps_max))):
            forecast.append(f"{temps_max[i]:.0f} / {temps_min[i]:.0f}")

        result = {
            "temp": current.get("temperature"),
            "desc": desc,
            "forecast": forecast
        }
        set_cache(cache_key, result)
        return result
    except Exception:
        return None

# =========================
# 🚀 EXTENSÃO PRINCIPAL
# =========================
class WeatherExt(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())

class WeatherHandler(EventListener):
    def on_event(self, event, extension):
        try:
            unit = extension.preferences.get("unit", "metric") or "metric"
            query = (event.get_argument() or "").strip()

            # 1. Sem query → IP
            if not query:
                lat, lon, city, country = get_ip_location()
                source = "Sua localização (IP)"
            else:
                lat, lon, city, country = geocode_city(query)
                source = f"Pesquisa: {query}"

            if lat is None or lon is None:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Localização não encontrada",
                        description=f"Não achei '{query or 'sua localização'}'. Tente outra cidade.",
                        on_enter=DoNothingAction()
                    )
                ])

            # 2. Busca clima
            weather = get_weather(lat, lon, unit)
            if weather is None or weather.get("temp") is None:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name="Falha ao obter o clima",
                        description="Problema na API do Open-Meteo. Tente mais tarde.",
                        on_enter=DoNothingAction()
                    )
                ])

            # 3. Monta resultado
            symbol = "°C" if unit == "metric" else "°F"
            flag = country_flag(country)
            first = f"{weather['temp']}{symbol}"
            if weather['desc']:
                first += f" – {weather['desc']}"

            forecast_str = " | ".join(weather['forecast']) if weather['forecast'] else "—"
            desc = f"{first}\nPróximos 3 dias: {forecast_str}"

            return RenderResultListAction([
                ExtensionResultItem(
                    icon='images/icon.png',
                    name=f"{flag} {city}, {country or '?'}",
                    description=desc,
                    on_enter=DoNothingAction()
                )
            ])

        except Exception as ex:
            # ÚLTIMO RECURSO: mostra erro no popup + log
            error_text = str(ex)
            try:
                print("WEATHER EXT ERRO:", error_text, traceback.format_exc())
            except:
                pass

            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Erro interno na extensão",
                    description=f"{error_text[:120]}... (veja terminal)",
                    on_enter=DoNothingAction()
                )
            ])

if __name__ == "__main__":
    WeatherExt().run()
