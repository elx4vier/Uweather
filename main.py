import logging
import requests
import time
import os

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction

logger = logging.getLogger(__name__)

CACHE_TTL = 600  # 10 minutos


def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3,
                    status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class UWeatherExtension(Extension):

    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())
        self.session = create_session()
        self.weather_cache = {}
        self.base_path = os.path.dirname(os.path.abspath(__file__))

    def icon(self, filename):
        path = os.path.join(self.base_path, "images", filename)
        return path if os.path.exists(path) else ""


class KeywordQueryEventListener(EventListener):

    # ==========================
    # Emoji automático
    # ==========================
    def weather_emoji(self, condition_id):
        if 200 <= condition_id < 300:
            return "⛈️"
        elif 300 <= condition_id < 600:
            return "🌧️"
        elif 600 <= condition_id < 700:
            return "❄️"
        elif 700 <= condition_id < 800:
            return "🌫️"
        elif condition_id == 800:
            return "☀️"
        elif 801 <= condition_id <= 804:
            return "☁️"
        return "🌤️"

    # ==========================
    # Evento principal
    # ==========================
    def on_event(self, event, extension):

        try:
            cidade = event.get_argument().strip() if event.get_argument() else None

            if not cidade:
                cidade = self.fetch_location(extension)

            clima = self.fetch_weather(extension, cidade)

            texto = self.format_weather(clima, cidade)

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("sun.png"),
                    name=texto,
                    description="Pressione Enter para copiar",
                    on_enter=CopyToClipboardAction(texto)
                )
            ])

        except Exception as e:
            logger.error(f"Erro: {e}")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name="Erro ao obter clima",
                    description="Verifique conexão, API key ou cidade",
                    on_enter=CopyToClipboardAction("Erro")
                )
            ])

    # ==========================
    # Buscar clima (FREE API)
    # ==========================
    def fetch_weather(self, extension, cidade):

        now = time.time()
        cache_key = cidade.lower()

        if cache_key in extension.weather_cache:
            cached = extension.weather_cache[cache_key]
            if now - cached["timestamp"] < CACHE_TTL:
                return cached["data"]

        api_key = extension.preferences.get("api_key")

        # Clima atual
        weather_url = (
            f"https://api.openweathermap.org/data/2.5/weather?"
            f"q={cidade}&units=metric&lang=pt_br&appid={api_key}"
        )

        # Previsão 5 dias / 3 horas
        forecast_url = (
            f"https://api.openweathermap.org/data/2.5/forecast?"
            f"q={cidade}&units=metric&lang=pt_br&appid={api_key}"
        )

        w = extension.session.get(weather_url, timeout=5)
        f = extension.session.get(forecast_url, timeout=5)

        if w.status_code != 200:
            raise Exception(w.text)

        if f.status_code != 200:
            raise Exception(f.text)

        data = {
            "current": w.json(),
            "forecast": f.json()
        }

        extension.weather_cache[cache_key] = {
            "timestamp": now,
            "data": data
        }

        return data

    # ==========================
    # Formatar saída
    # ==========================
    def format_weather(self, data, cidade):

        current = data["current"]
        forecast = data["forecast"]

        temp = round(current["main"]["temp"])
        feels = round(current["main"]["feels_like"])
        desc = current["weather"][0]["description"].capitalize()
        cond_id = current["weather"][0]["id"]
        emoji = self.weather_emoji(cond_id)

        # Próximas 3 horas
        horas = forecast["list"][:3]
        horas_formatadas = []
        for h in horas:
            hora = h["dt_txt"][11:16]
            t = round(h["main"]["temp"])
            e = self.weather_emoji(h["weather"][0]["id"])
            horas_formatadas.append(f"{hora} - {t}º {e}")

        horas_texto = " | ".join(horas_formatadas)

        # Próximos 2 dias (pega horário fixo 12:00)
        dias = {}
        for item in forecast["list"]:
            if "12:00:00" in item["dt_txt"]:
                data_dia = item["dt_txt"][:10]
                dias[data_dia] = item

        dias_lista = list(dias.values())[:2]

        nomes = ["Amanhã", "Depois de amanhã"]
        dias_texto = ""

        for i, d in enumerate(dias_lista):
            tmax = round(d["main"]["temp_max"])
            tmin = round(d["main"]["temp_min"])
            e = self.weather_emoji(d["weather"][0]["id"])
            dias_texto += (
                f"{nomes[i]}: máx {tmax}º {e} / "
                f"min {tmin}º {e}\n"
            )

        return (
            f"Clima em {cidade} agora:\n\n"
            f"{temp}º {emoji}, {desc}\n"
            f"Sensação térmica: {feels}º\n\n"
            f"Próximas horas: {horas_texto}\n\n"
            f"{dias_texto}\n"
            f"Fonte: OpenWeatherMap"
        )

    # ==========================
    # Localização por IP
    # ==========================
    def fetch_location(self, extension):

        try:
            r = extension.session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            return geo.get("city")
        except:
            raise Exception("Falha na localização")


if __name__ == "__main__":
    UWeatherExtension().run()
