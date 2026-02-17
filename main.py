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


# ==========================
# Session com retry
# ==========================
def create_session():
    session = requests.Session()
    retries = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# ==========================
# Extension
# ==========================
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


# ==========================
# Listener
# ==========================
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
        else:
            return "🌤️"

    # ==========================
    # Evento principal
    # ==========================
    def on_event(self, event, extension):

        try:
            cidade_digitada = event.get_argument() or ""

            # Se usuário digitou cidade
            if cidade_digitada.strip():
                cidade = cidade_digitada.strip()
                clima = self.fetch_weather(extension, cidade, None, None)
            else:
                geo = self.fetch_location(extension)
                cidade = geo.get("city", "Desconhecida")
                clima = self.fetch_weather(
                    extension,
                    cidade,
                    geo.get("latitude"),
                    geo.get("longitude")
                )

            # Atual
            atual = clima["current"]
            temp = round(atual["temp"])
            feels = round(atual["feels_like"])
            desc = atual["weather"][0]["description"].capitalize()
            cond_id = atual["weather"][0]["id"]
            emoji_atual = self.weather_emoji(cond_id)

            # Próximas 3 horas
            horas_linha = []
            for h in clima["hourly"][:3]:
                hora = time.strftime("%H:%M", time.localtime(h["dt"]))
                temp_h = round(h["temp"])
                emoji_h = self.weather_emoji(h["weather"][0]["id"])
                horas_linha.append(f"{hora} - {temp_h}º {emoji_h}")

            horas_formatado = " | ".join(horas_linha)

            # Próximos 2 dias
            dias = clima["daily"][1:3]
            nomes_dias = ["Amanhã", "Depois de amanhã"]

            dias_texto = ""
            for i, d in enumerate(dias):
                tmax = round(d["temp"]["max"])
                tmin = round(d["temp"]["min"])
                emoji_d = self.weather_emoji(d["weather"][0]["id"])
                dias_texto += (
                    f"{nomes_dias[i]}: máx {tmax}º {emoji_d} / "
                    f"min {tmin}º {emoji_d}\n"
                )

            texto = (
                f"Clima em {cidade} agora:\n\n"
                f"{temp}º {emoji_atual}, {desc}\n"
                f"Sensação térmica: {feels}º\n\n"
                f"Próximas horas: {horas_formatado}\n\n"
                f"{dias_texto}\n"
                f"Fonte: OpenWeatherMap"
            )

            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("sun.png"),
                    name=texto.strip(),
                    description="Pressione Enter para copiar",
                    on_enter=CopyToClipboardAction(texto.strip())
                )
            ])

        except Exception as e:
            logger.error(f"Erro: {e}")
            return RenderResultListAction([
                ExtensionResultItem(
                    icon=extension.icon("error.png"),
                    name="Erro ao obter clima",
                    description="Verifique conexão ou cidade",
                    on_enter=CopyToClipboardAction("Erro")
                )
            ])

    # ==========================
    # Cache inteligente
    # ==========================
    def fetch_weather(self, extension, cidade, lat, lon):

        now = time.time()

        if lat and lon:
            cache_key = f"{lat},{lon}"
        else:
            cache_key = cidade.lower()

        # Verifica cache
        if cache_key in extension.weather_cache:
            cached = extension.weather_cache[cache_key]
            if now - cached["timestamp"] < CACHE_TTL:
                return cached["data"]

        api_key = extension.preferences.get("api_key")

        # Se não tem coordenada → busca via Geocoding
        if not lat or not lon:
            geo_url = (
                f"http://api.openweathermap.org/geo/1.0/direct?"
                f"q={cidade}&limit=1&appid={api_key}"
            )
            geo_r = extension.session.get(geo_url, timeout=5)
            geo_data = geo_r.json()

            if not geo_data:
                raise Exception("Cidade não encontrada")

            lat = geo_data[0]["lat"]
            lon = geo_data[0]["lon"]

        url = (
            f"https://api.openweathermap.org/data/3.0/onecall?"
            f"lat={lat}&lon={lon}"
            f"&units=metric&lang=pt_br"
            f"&appid={api_key}"
        )

        r = extension.session.get(url, timeout=5)
        data = r.json()

        # Salva no cache
        extension.weather_cache[cache_key] = {
            "timestamp": now,
            "data": data
        }

        return data

    # ==========================
    # Localização automática
    # ==========================
    def fetch_location(self, extension):

        try:
            r = extension.session.get("https://ipapi.co/json/", timeout=5)
            geo = r.json()
            if "latitude" in geo:
                return geo
        except:
            pass

        try:
            r = extension.session.get("http://ip-api.com/json/", timeout=5)
            geo = r.json()
            return {
                "latitude": geo["lat"],
                "longitude": geo["lon"],
                "city": geo.get("city", "Desconhecida")
            }
        except:
            raise Exception("Falha na localização")


if __name__ == "__main__":
    UWeatherExtension().run()
