import time
import requests
import threading

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.SmallResultItem import SmallResultItem
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction


# =========================
# CONFIG
# =========================

DEBOUNCE_DELAY = 0.4
LAST_QUERY_TIME = 0
CURRENT_REQUEST_ID = 0

# =========================
# MAPA WMO
# =========================

WMO_MAP = {
    0: "Céu limpo",
    1: "Principalmente limpo",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Nevoeiro",
    48: "Nevoeiro com geada",
    51: "Garoa leve",
    53: "Garoa moderada",
    55: "Garoa intensa",
    61: "Chuva leve",
    63: "Chuva moderada",
    65: "Chuva forte",
    71: "Neve leve",
    73: "Neve moderada",
    75: "Neve forte",
    80: "Pancadas leves",
    81: "Pancadas moderadas",
    82: "Pancadas fortes",
    95: "Tempestade",
}


# =========================
# EXTENSION
# =========================

class WeatherExtension(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())


# =========================
# LISTENER
# =========================

class WeatherListener(EventListener):

    def on_event(self, event, extension):

        global LAST_QUERY_TIME
        global CURRENT_REQUEST_ID

        if not isinstance(event, KeywordQueryEvent):
            return

        query = (event.get_argument() or "").strip()

        now = time.time()

        # =========================
        # DIGITAÇÃO RÁPIDA
        # =========================
        if now - LAST_QUERY_TIME < DEBOUNCE_DELAY:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Digitando...",
                    description="Aguardando você terminar",
                    on_enter=DoNothingAction()
                )
            ])

        LAST_QUERY_TIME = now

        # =========================
        # SEM CIDADE
        # =========================
        if not query:
            return RenderResultListAction([
                SmallResultItem(
                    icon='images/icon.png',
                    name="Digite uma cidade",
                    description="Exemplo: w São Paulo",
                    on_enter=DoNothingAction()
                )
            ])

        # =========================
        # NOVA REQUISIÇÃO
        # =========================
        CURRENT_REQUEST_ID += 1
        request_id = CURRENT_REQUEST_ID

        # Executa em thread
        threading.Thread(
            target=self.fetch_weather,
            args=(query, request_id)
        ).start()

        # Loading imediato
        return RenderResultListAction([
            SmallResultItem(
                icon='images/icon.png',
                name="Buscando clima...",
                description=f"Consultando {query}",
                on_enter=DoNothingAction()
            )
        ])


    # =========================
    # BUSCA CLIMA
    # =========================

    def fetch_weather(self, city, request_id):

        global CURRENT_REQUEST_ID

        try:
            # 1️⃣ Geocoding
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=pt&format=json"
            geo_resp = requests.get(geo_url, timeout=5)
            geo_data = geo_resp.json()

            if "results" not in geo_data:
                self.render_error("Cidade não encontrada", "Digite uma cidade válida", request_id)
                return

            result = geo_data["results"][0]
            lat = result["latitude"]
            lon = result["longitude"]
            city_name = result["name"]

            # 2️⃣ Clima
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&current_weather=true&timezone=auto"
            )

            weather_resp = requests.get(weather_url, timeout=5)
            weather_data = weather_resp.json()

            if "current_weather" not in weather_data:
                self.render_error("Erro clima", "Erro ao buscar clima", request_id)
                return

            # Se já existe requisição mais nova, ignora
            if request_id != CURRENT_REQUEST_ID:
                return

            current = weather_data["current_weather"]
            temp = current["temperature"]
            wmo = current["weathercode"]

            condition = WMO_MAP.get(wmo)

            if condition:
                title = f"{temp}°C • {condition}"
            else:
                # WMO não mapeado → NÃO mostra Weather
                title = f"{temp}°C"

            self.render_success(title, city_name)

        except Exception:
            self.render_error("Erro clima", "Erro ao buscar clima", request_id)


    # =========================
    # RENDER HELPERS
    # =========================

    def render_success(self, title, city):

        self.extension._result = RenderResultListAction([
            ExtensionResultItem(
                icon='images/icon.png',
                name=title,
                description=city,
                on_enter=DoNothingAction()
            )
        ])
        self.extension._emit()


    def render_error(self, title, description, request_id):

        global CURRENT_REQUEST_ID

        if request_id != CURRENT_REQUEST_ID:
            return

        self.extension._result = RenderResultListAction([
            SmallResultItem(
                icon='images/icon.png',
                name=title,
                description=description,
                on_enter=DoNothingAction()
            )
        ])
        self.extension._emit()


# =========================
# MAIN
# =========================

if __name__ == '__main__':
    WeatherExtension().run()
