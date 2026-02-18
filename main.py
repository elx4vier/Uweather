import json
import urllib.request
import urllib.parse
import time

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item import ExtensionResultItem, SmallResultItem
from ulauncher.api.shared.action import DoNothingAction, RenderResultListAction


# =========================
# ⚡ CONFIG
# =========================

CACHE = {}
CACHE_TTL = 600


# =========================
# 🌍 TRANSLATIONS
# =========================

TEXTS = {
    "en": {
        "city_not_found": "City not found",
        "type_valid_city": "Type a valid city name",
        "location_error": "Could not detect your location",
        "weather_error": "Error fetching weather",
        "check_connection": "Check your internet connection",
        "try_again": "Try again shortly",
        "next_days": "Next days"
    },
    "pt": {
        "city_not_found": "Cidade não encontrada",
        "type_valid_city": "Digite uma cidade válida",
        "location_error": "Não foi possível encontrar sua localização",
        "weather_error": "Erro ao buscar clima",
        "check_connection": "Verifique sua conexão com a internet",
        "try_again": "Tente novamente em instantes",
        "next_days": "Próximos dias"
    },
    "es": {
        "city_not_found": "Ciudad no encontrada",
        "type_valid_city": "Escribe una ciudad válida",
        "location_error": "No se pudo detectar tu ubicación",
        "weather_error": "Error al obtener el clima",
        "check_connection": "Verifica tu conexión a internet",
        "try_again": "Inténtalo de nuevo en breve",
        "next_days": "Próximos días"
    },
    "fr": {
        "city_not_found": "Ville non trouvée",
        "type_valid_city": "Tapez une ville valide",
        "location_error": "Impossible de détecter votre position",
        "weather_error": "Erreur lors de la récupération météo",
        "check_connection": "Vérifiez votre connexion internet",
        "try_again": "Réessayez dans un instant",
        "next_days": "Prochains jours"
    },
    "ru": {
        "city_not_found": "Город не найден",
        "type_valid_city": "Введите корректный город",
        "location_error": "Не удалось определить ваше местоположение",
        "weather_error": "Ошибка получения погоды",
        "check_connection": "Проверьте интернет-соединение",
        "try_again": "Попробуйте снова позже",
        "next_days": "Ближайшие дни"
    }
}


# =========================
# 🌦 WMO CONDITIONS
# =========================

WMO = {
    0: {"en": "Clear sky", "pt": "Céu limpo", "es": "Cielo despejado", "fr": "Ciel dégagé", "ru": "Ясно"},
    1: {"en": "Mainly clear", "pt": "Predominantemente limpo", "es": "Mayormente despejado", "fr": "Principalement dégagé", "ru": "Преимущественно ясно"},
    2: {"en": "Partly cloudy", "pt": "Parcialmente nublado", "es": "Parcialmente nublado", "fr": "Partiellement nuageux", "ru": "Переменная облачность"},
    3: {"en": "Overcast", "pt": "Nublado", "es": "Nublado", "fr": "Couvert", "ru": "Пасмурно"},
    45: {"en": "Fog", "pt": "Névoa", "es": "Niebla", "fr": "Brouillard", "ru": "Туман"},
    61: {"en": "Light rain", "pt": "Chuva fraca", "es": "Lluvia ligera", "fr": "Pluie légère", "ru": "Небольшой дождь"},
    63: {"en": "Rain", "pt": "Chuva", "es": "Lluvia", "fr": "Pluie", "ru": "Дождь"},
    65: {"en": "Heavy rain", "pt": "Chuva forte", "es": "Lluvia intensa", "fr": "Forte pluie", "ru": "Сильный дождь"},
    71: {"en": "Snow", "pt": "Neve", "es": "Nieve", "fr": "Neige", "ru": "Снег"},
    95: {"en": "Thunderstorm", "pt": "Tempestade", "es": "Tormenta", "fr": "Orage", "ru": "Гроза"},
}


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
# 🌐 REQUEST
# =========================

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.loads(response.read().decode())
    except:
        return None


# =========================
# 📍 GEOLOCATION
# =========================

def geocode_city(city):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        return r["latitude"], r["longitude"], r["name"], r.get("country_code", "")
    return None, None, None, None


def get_ip_location():
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        return data["lat"], data["lon"], data["city"], data["countryCode"]
    return None, None, None, None


# =========================
# 🌤 WEATHER PROVIDERS
# =========================

def get_weather_openmeteo(lat, lon, unit, lang):

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

    current = data["current_weather"]
    daily = data["daily"]

    desc = None
    if current["weathercode"] in WMO:
        desc = WMO[current["weathercode"]].get(lang)

    return {
        "temp": current["temperature"],
        "desc": desc,
        "forecast": [
            f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}"
            for i in range(1, 4)
        ]
    }


def get_weather_openweather(lat, lon, unit, api_key, lang):

    if not api_key:
        return None

    url = (
        f"https://api.openweathermap.org/data/2.5/onecall?"
        f"lat={lat}&lon={lon}&units={unit}&lang={lang}&appid={api_key}"
    )

    data = get_json(url)
    if not data:
        return None

    return {
        "temp": data["current"]["temp"],
        "desc": data["current"]["weather"][0]["description"].capitalize(),
        "forecast": [
            f"{d['temp']['max']} / {d['temp']['min']}"
            for d in data["daily"][1:4]
        ]
    }


# =========================
# 🚀 EXTENSION
# =========================

class UWeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherHandler())


class WeatherHandler(EventListener):

    def on_event(self, event, extension):

        prefs = extension.preferences
        lang = prefs.get("language", "en")
        texts = TEXTS.get(lang, TEXTS["en"])

        unit = prefs.get("unit", "metric")
        provider = prefs.get("provider", "openmeteo")
        location_mode = prefs.get("location_mode", "auto")
        static_city = prefs.get("static_city", "")
        api_key = prefs.get("api_key", "")
        view_mode = prefs.get("view_mode", "3")

        query = event.get_argument()

        # LOCATION
        if location_mode == "manual" and static_city:
            lat, lon, city, country = geocode_city(static_city)
        elif query:
            lat, lon, city, country = geocode_city(query)
        else:
            lat, lon, city, country = get_ip_location()

        if not lat:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name=texts["city_not_found"],
                    description=texts["type_valid_city"],
                    on_enter=DoNothingAction()
                )
            ])

        # WEATHER
        if provider == "openweather":
            weather = get_weather_openweather(lat, lon, unit, api_key, lang)
        else:
            weather = get_weather_openmeteo(lat, lon, unit, lang)

        if not weather:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name=texts["weather_error"],
                    description=texts["try_again"],
                    on_enter=DoNothingAction()
                )
            ])

        symbol = "°C" if unit == "metric" else "°F"

        if weather["desc"]:
            first_line = f"{weather['temp']}{symbol} - {weather['desc']}"
        else:
            first_line = f"{weather['temp']}{symbol}"

        description = first_line

        if view_mode in ["4", "5"]:
            description += f"\n{texts['next_days']}: {' | '.join(weather['forecast'])}"

        return RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=f"{city}, {country}",
                description=description,
                on_enter=DoNothingAction()
            )
        ])


if __name__ == "__main__":
    UWeatherExtension().run()
