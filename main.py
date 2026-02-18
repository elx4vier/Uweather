import json
import urllib.request
import urllib.parse
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction


# =========================
# 🔤 IDIOMAS
# =========================

TEXTS = {
    "pt": {
        "current": "Clima atual",
        "forecast": "Previsão",
        "fail_location": "Falha na localização",
        "fail_weather": "Falha ao obter clima",
        "provider_not_impl": "Provedor não implementado"
    },
    "en": {
        "current": "Current weather",
        "forecast": "Forecast",
        "fail_location": "Location failed",
        "fail_weather": "Weather request failed",
        "provider_not_impl": "Provider not implemented"
    },
    "es": {
        "current": "Clima actual",
        "forecast": "Pronóstico",
        "fail_location": "Error de ubicación",
        "fail_weather": "Error al obtener clima",
        "provider_not_impl": "Proveedor no implementado"
    },
    "ru": {
        "current": "Текущая погода",
        "forecast": "Прогноз",
        "fail_location": "Ошибка определения местоположения",
        "fail_weather": "Ошибка получения погоды",
        "provider_not_impl": "Провайдер не реализован"
    },
    "fr": {
        "current": "Météo actuelle",
        "forecast": "Prévision",
        "fail_location": "Échec de localisation",
        "fail_weather": "Échec récupération météo",
        "provider_not_impl": "Fournisseur non implémenté"
    }
}


# =========================
# 🌍 UTILIDADES
# =========================

def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            return json.loads(response.read().decode())
    except:
        return None


def get_ip_location():
    data = get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        return data["lat"], data["lon"], data["city"]
    return None, None, None


def geocode_city(city):
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1"
    data = get_json(url)
    if data and data.get("results"):
        r = data["results"][0]
        return r["latitude"], r["longitude"], r["name"]
    return None, None, None


# =========================
# ☁ OPENWEATHER
# =========================

def get_openweather(lat, lon, unit, api_key):
    if not api_key:
        return None

    units = "metric" if unit == "metric" else "imperial"

    url = (
        f"https://api.openweathermap.org/data/2.5/forecast?"
        f"lat={lat}&lon={lon}&units={units}&appid={api_key}"
    )

    data = get_json(url)
    if not data:
        return None

    try:
        current = data["list"][0]
        forecasts = data["list"][8:32:8]

        result = {
            "current_temp": current["main"]["temp"],
            "current_desc": current["weather"][0]["description"],
            "forecast": []
        }

        for f in forecasts[:3]:
            result["forecast"].append({
                "temp": f["main"]["temp"],
                "desc": f["weather"][0]["description"]
            })

        return result
    except:
        return None


# =========================
# 🌤 OPEN-METEO
# =========================

def get_open_meteo(lat, lon, unit):
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

    try:
        current = data["current_weather"]
        daily = data["daily"]

        result = {
            "current_temp": current["temperature"],
            "current_desc": f"WMO {current['weathercode']}",
            "forecast": []
        }

        for i in range(1, 4):
            result["forecast"].append({
                "temp": f"{daily['temperature_2m_max'][i]} / {daily['temperature_2m_min'][i]}",
                "desc": ""
            })

        return result
    except:
        return None


# =========================
# 🔎 EXTENSÃO
# =========================

class UWeatherExtension(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, UWeatherHandler())


class UWeatherHandler(EventListener):

    def on_event(self, event, extension):

        prefs = extension.preferences

        provider = prefs.get("provider", "openweather")
        unit = prefs.get("unit", "metric")
        location_mode = prefs.get("location_mode", "auto")
        static_city = prefs.get("static_city", "")
        api_key = prefs.get("api_key", "")
        language = prefs.get("language", "pt")
        view_mode = int(prefs.get("view_mode", 3))

        T = TEXTS.get(language, TEXTS["pt"])

        # =========================
        # LOCALIZAÇÃO
        # =========================

        if location_mode == "manual" and static_city:
            lat, lon, city = geocode_city(static_city)
        else:
            lat, lon, city = get_ip_location()

        if not lat or not lon:
            return SmallResultItem(
                icon='images/icon.png',
                name=T["fail_location"],
                description="",
                on_enter=DoNothingAction()
            )

        # =========================
        # PROVEDOR
        # =========================

        if provider == "openweather":
            weather = get_openweather(lat, lon, unit, api_key)
        elif provider == "openmeteo":
            weather = get_open_meteo(lat, lon, unit)
        else:
            return SmallResultItem(
                icon='images/icon.png',
                name=T["provider_not_impl"],
                description="",
                on_enter=DoNothingAction()
            )

        if not weather:
            return SmallResultItem(
                icon='images/icon.png',
                name=T["fail_weather"],
                description="",
                on_enter=DoNothingAction()
            )

        symbol = "°C" if unit == "metric" else "°F"

        # =========================
        # VISUALIZAÇÕES
        # =========================

        if view_mode == 1:
            desc = f"{weather['current_temp']}{symbol}"

        elif view_mode == 2:
            desc = f"{weather['current_temp']}{symbol} - {weather['current_desc']}"

        elif view_mode == 3:
            desc = f"{T['current']}: {weather['current_temp']}{symbol} - {weather['current_desc']}"

        elif view_mode == 4:
            forecast_text = " | ".join(
                f"{f['temp']}{symbol}" for f in weather["forecast"]
            )
            desc = f"{weather['current_temp']}{symbol} → {forecast_text}"

        else:
            forecast_text = " | ".join(
                f"{f['temp']}{symbol}" for f in weather["forecast"]
            )
            desc = (
                f"{T['current']}: {weather['current_temp']}{symbol} - {weather['current_desc']}\n"
                f"{T['forecast']}: {forecast_text}"
            )

        return ExtensionResultItem(
            icon='images/icon.png',
            name=f"📍 {city}",
            description=desc,
            on_enter=DoNothingAction()
        )


if __name__ == '__main__':
    UWeatherExtension().run()
