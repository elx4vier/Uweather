import json
import urllib.request
import urllib.parse
import time
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent, PreferencesEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction

# =========================
# ⚡ CONFIGURAÇÕES GLOBAIS
# =========================
CACHE = {}
CACHE_TTL = 600  # 10 minutos

# Códigos WMO e traduções
WMO_CODES = {
    0: {"en": "Clear sky", "pt": "Céu limpo", "es": "Cielo despejado", "fr": "Ciel dégagé", "ru": "Ясно"},
    1: {"en": "Mainly clear", "pt": "Parcialmente limpo", "es": "Mayormente despejado", "fr": "Principalement dégagé", "ru": "Преимущественно ясно"},
    2: {"en": "Partly cloudy", "pt": "Parcialmente nublado", "es": "Parcialmente nublado", "fr": "Partiellement nuageux", "ru": "Переменная облачность"},
    3: {"en": "Overcast", "pt": "Nublado", "es": "Nublado", "fr": "Couvert", "ru": "Пасмурно"},
    45: {"en": "Fog", "pt": "Nevoeiro", "es": "Niebla", "fr": "Brouillard", "ru": "Туман"},
    61: {"en": "Light rain", "pt": "Chuva fraca", "es": "Lluvia ligera", "fr": "Pluie légère", "ru": "Небольшой дождь"},
    63: {"en": "Rain", "pt": "Chuva", "es": "Lluvia", "fr": "Pluie", "ru": "Дождь"},
    65: {"en": "Heavy rain", "pt": "Chuva forte", "es": "Lluvia intensa", "fr": "Pluie forte", "ru": "Сильный дождь"},
    71: {"en": "Snow", "pt": "Neve", "es": "Nieve", "fr": "Neige", "ru": "Снег"},
    95: {"en": "Thunderstorm", "pt": "Tempestade", "es": "Tormenta", "fr": "Orage", "ru": "Гроза"},
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

def get_json(url, headers=None):
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"Erro na requisição: {e}")
        return None

# =========================
# 📍 GEOCODING (apenas Open-Meteo, pois é gratuito e não requer chave)
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
# 🌤 WEATHER (Open-Meteo)
# =========================
def get_weather_openmeteo(lat, lon, unit, lang):
    cache_key = f"weather-om-{lat}-{lon}-{unit}-{lang}"
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
    desc = WMO_CODES.get(weather_code, {}).get(lang, WMO_CODES.get(weather_code, {}).get("en", ""))
    result = {
        "current_temp": current.get("temperature"),
        "current_desc": desc,
        "forecast": []
    }
    try:
        for i in range(1, min(4, len(daily["temperature_2m_max"]))):
            max_temp = daily["temperature_2m_max"][i]
            min_temp = daily["temperature_2m_min"][i]
            result["forecast"].append(f"{max_temp} / {min_temp}")
    except:
        pass
    set_cache(cache_key, result)
    return result

# =========================
# 🌤 WEATHER (OpenWeather)
# =========================
def get_weather_openweather(lat, lon, unit, lang, api_key):
    cache_key = f"weather-ow-{lat}-{lon}-{unit}-{lang}"
    cached = get_cache(cache_key)
    if cached:
        return cached
    units = "metric" if unit == "metric" else "imperial"
    url = (
        f"https://api.openweathermap.org/data/2.5/onecall?"
        f"lat={lat}&lon={lon}&exclude=minutely,hourly,alerts"
        f"&units={units}&lang={lang}&appid={api_key}"
    )
    data = get_json(url)
    if not data:
        return None
    current = data.get("current")
    daily = data.get("daily", [])
    if not current or not daily:
        return None
    desc = current.get("weather", [{}])[0].get("description", "").capitalize()
    result = {
        "current_temp": current.get("temp"),
        "current_desc": desc,
        "forecast": []
    }
    try:
        for i in range(1, min(4, len(daily))):
            max_temp = daily[i]["temp"]["max"]
            min_temp = daily[i]["temp"]["min"]
            result["forecast"].append(f"{max_temp} / {min_temp}")
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
        self.subscribe(PreferencesEvent, PreferencesEventListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesUpdateEventListener())

class PreferencesEventListener(EventListener):
    def on_event(self, event, extension):
        # Atualiza as preferências quando a extensão é carregada
        pass

class PreferencesUpdateEventListener(EventListener):
    def on_event(self, event, extension):
        # Atualiza preferências em tempo real
        pass

class KeywordQueryEventListener(EventListener):
    def on_event(self, event, extension):
        # Obtém preferências
        prefs = extension.preferences
        unit = prefs.get("unit", "metric")
        lang = prefs.get("language", "en")
        provider = prefs.get("provider", "openmeteo")
        api_key = prefs.get("api_key", "")
        location_mode = prefs.get("location_mode", "auto")
        static_city = prefs.get("static_city", "").strip()
        view_mode = prefs.get("view_mode", "3")
        query = event.get_argument()  # argumento após a keyword (ex: "w londres")

        # Determina a cidade a ser pesquisada
        if location_mode == "manual" and static_city:
            city_to_search = static_city
        elif query:
            city_to_search = query
        else:
            city_to_search = None  # usará localização automática

        # Obtém coordenadas
        if city_to_search:
            lat, lon, city, country = geocode_city(city_to_search)
            if not lat:
                # Cidade não encontrada
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name=self._get_text("city_not_found", lang),
                        description=self._get_text("enter_valid_city", lang),
                        on_enter=DoNothingAction()
                    )
                ])
        else:
            lat, lon, city, country = get_ip_location()
            if not lat:
                return RenderResultListAction([
                    SmallResultItem(
                        icon='images/icon.png',
                        name=self._get_text("location_failed", lang),
                        description=self._get_text("check_connection", lang),
                        on_enter=DoNothingAction()
                    )
                ])

        # Obtém dados do clima conforme provedor
        weather = None
        if provider == "openweather" and api_key:
            weather = get_weather_openweather(lat, lon, unit, lang, api_key)
        if not weather:  # fallback para openmeteo
            weather = get_weather_openmeteo(lat, lon, unit, lang)

        if not weather:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name=self._get_text("weather_error", lang),
                    description=self._get_text("try_again", lang),
                    on_enter=DoNothingAction()
                )
            ])

        # Formata a saída conforme view_mode
        symbol = "°C" if unit == "metric" else "°F"
        flag = country_flag(country)

        # Linha atual
        if weather["current_desc"]:
            current_line = f"{weather['current_temp']}{symbol} - {weather['current_desc']}"
        else:
            current_line = f"{weather['current_temp']}{symbol}"

        # Previsão
        forecast_str = " | ".join(weather["forecast"])

        # Monta descrição de acordo com o modo de exibição
        if view_mode == "1":  # Ultra Minimal
            description = f"{weather['current_temp']}{symbol}"
        elif view_mode == "2":  # Minimal
            description = current_line
        elif view_mode == "3":  # Compact
            description = f"{current_line} | {forecast_str}"
        elif view_mode == "4":  # Full
            description = f"{current_line}\nPróximos dias: {forecast_str}"
        else:  # Detailed (5)
            description = f"{current_line}\n{self._get_text('next_days', lang)}: {forecast_str}"

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{flag} {city}, {country}",
                description=description,
                on_enter=DoNothingAction()
            )
        ])

    def _get_text(self, key, lang):
        texts = {
            "city_not_found": {
                "en": "City not found",
                "pt": "Cidade não encontrada",
                "es": "Ciudad no encontrada",
                "fr": "Ville non trouvée",
                "ru": "Город не найден"
            },
            "enter_valid_city": {
                "en": "Enter a valid city",
                "pt": "Digite uma cidade válida",
                "es": "Ingrese una ciudad válida",
                "fr": "Entrez une ville valide",
                "ru": "Введите правильный город"
            },
            "location_failed": {
                "en": "Could not find your location",
                "pt": "Não foi possível encontrar sua localização",
                "es": "No se pudo encontrar su ubicación",
                "fr": "Impossible de trouver votre position",
                "ru": "Не удалось определить ваше местоположение"
            },
            "check_connection": {
                "en": "Check your internet connection",
                "pt": "Verifique sua conexão com a internet",
                "es": "Verifique su conexión a internet",
                "fr": "Vérifiez votre connexion internet",
                "ru": "Проверьте подключение к интернету"
            },
            "weather_error": {
                "en": "Error fetching weather",
                "pt": "Erro ao buscar clima",
                "es": "Error al obtener el clima",
                "fr": "Erreur lors de la récupération de la météo",
                "ru": "Ошибка получения погоды"
            },
            "try_again": {
                "en": "Please try again later",
                "pt": "Tente novamente mais tarde",
                "es": "Inténtelo de nuevo más tarde",
                "fr": "Veuillez réessayer plus tard",
                "ru": "Пожалуйста, повторите попытку позже"
            },
            "next_days": {
                "en": "Next days",
                "pt": "Próximos dias",
                "es": "Próximos días",
                "fr": "Prochains jours",
                "ru": "Ближайшие дни"
            }
        }
        return texts.get(key, {}).get(lang, texts.get(key, {}).get("en", key))

if __name__ == "__main__":
    UWeatherExtension().run()
