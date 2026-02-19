import logging
import requests
import time
import os
import json
import locale
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ulauncher.api.client.Extension import Extension
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import KeywordQueryEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.action.OpenUrlAction import OpenUrlAction

logger = logging.getLogger(__name__)
CACHE_TTL = 600
CACHE_FILE = "cache_weather.json"

# ==============================
# SESSÃO HTTP
# ==============================
def create_session():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[500,502,503,504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ==============================
# UTILITÁRIOS
# ==============================
def get_system_language():
    try:
        lang = locale.getdefaultlocale()[0]
        return lang.replace("_","-") if lang else "en-US"
    except:
        return "en-US"

def country_flag(country_code):
    if not country_code or len(country_code)!=2: return ""
    offset=127397
    return chr(ord(country_code[0].upper())+offset)+chr(ord(country_code[1].upper())+offset)

def load_cache(base_path):
    path=os.path.join(base_path,CACHE_FILE)
    if os.path.exists(path):
        try:
            with open(path,"r",encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_cache(base_path, cache_data):
    path=os.path.join(base_path,CACHE_FILE)
    try:
        with open(path,"w",encoding="utf-8") as f: json.dump(cache_data,f)
    except Exception as e: logger.error(f"Erro ao salvar cache: {e}")

def convert_temperature(temp, unit):
    return int(temp * 9/5 + 32) if unit=="f" else int(temp)

# ==============================
# CÓDIGOS METEO
# ==============================
OPEN_METEO_WEATHER_CODES = {
    0:"céu limpo",1:"parcialmente nublado",2:"nublado",3:"nublado",
    45:"neblina",48:"neblina com gelo",51:"chuva fraca",53:"chuva moderada",
    55:"chuva forte",56:"chuva congelante fraca",57:"chuva congelante forte",
    61:"chuva",63:"chuva forte",65:"chuva intensa",66:"chuva congelante leve",
    67:"chuva congelante intensa",71:"neve fraca",73:"neve moderada",
    75:"neve intensa",77:"granizo",80:"chuva forte",81:"chuva intensa",
    82:"chuva intensa",85:"neve leve",86:"neve intensa",95:"trovoada",
    96:"trovoada com granizo",99:"trovoada com granizo intenso"
}

def get_owm_description(code):
    if 200<=code<=232:return "tempestade"
    if 300<=code<=321:return "garoa"
    if 500<=code<=531:return "chuva"
    if 600<=code<=622:return "neve"
    if 701<=code<=781:return "neblina"
    if code==800:return "céu limpo"
    if code==801:return "poucas nuvens"
    if 802<=code<=804:return "nublado"
    return "desconhecido"

# ==============================
# WEATHER SERVICE
# ==============================
class WeatherService:
    @staticmethod
    def fetch_location(session):
        apis=[
            ("https://ip-api.com/json/",2),
            ("https://freeipapi.com/api/json",2),
            ("https://ipapi.co/json/",2)
        ]
        for url,timeout in apis:
            try:
                r=session.get(url,timeout=timeout)
                if r.status_code!=200: continue
                data=r.json()
                return {
                    "city": data.get("city") or data.get("cityName") or "Desconhecida",
                    "state": data.get("region") or "",
                    "country": (data.get("countryCode") or data.get("country_code") or "BR")[:2],
                    "latitude": data.get("lat") or data.get("latitude"),
                    "longitude": data.get("lon") or data.get("longitude")
                }
            except: continue
        return None

    @staticmethod
    def fetch_weather_openmeteo(session, lat, lon, unit="c"):
        try:
            r=session.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,weathercode&current_weather=true&timezone=auto",
                timeout=5
            )
            data=r.json()
            daily=data.get("daily",{})
            forecast=[{
                "max": convert_temperature(daily["temperature_2m_max"][i],unit),
                "min": convert_temperature(daily["temperature_2m_min"][i],unit),
                "desc": OPEN_METEO_WEATHER_CODES.get(daily["weathercode"][i],"desconhecido")
            } for i in range(min(2,len(daily.get("temperature_2m_max",[]))))]
            current=data.get("current_weather",{})
            return {"current":{"temp":convert_temperature(current.get("temperature",0),unit),
                               "desc":OPEN_METEO_WEATHER_CODES.get(current.get("weathercode",0),"desconhecido")},
                    "forecast":forecast}
        except Exception as e:
            logger.error(f"Erro Open-Meteo: {e}")
            return None

# ==============================
# EXTENSION
# ==============================
class UWeather(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(KeywordQueryEvent, WeatherListener())
        self.session = create_session()
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.cache = load_cache(self.base_path)
        ThreadPoolExecutor(max_workers=1).submit(self.update_auto_location)

    def icon(self, filename):
        path=os.path.join(self.base_path,"images",filename)
        return path if os.path.exists(path) else os.path.join(self.base_path,"images","icon.png")

    def get_weather_data(self, lat, lon, unit):
        provider=(self.preferences.get("provider") or "open-meteo").lower()
        if provider=="openweather":
            api_key=self.preferences.get("api_key")
            if not api_key: return {"error":"API Key ausente"}
        return WeatherService.fetch_weather_openmeteo(self.session, lat, lon, unit)

    def on_preferences_changed(self, key, value):
        """
        Atualiza imediatamente e limpa cache se mudar configuração relevante.
        """
        if key in ["provider","api_key","location_mode","static_location","unit"]:
            self.cache = {}
            save_cache(self.base_path,self.cache)
            ThreadPoolExecutor(max_workers=1).submit(self.update_auto_location)

    def update_auto_location(self):
        """
        Atualiza localização automática ou estática e salva no cache.
        """
        mode = (self.preferences.get("location_mode") or "auto").lower()
        unit = (self.preferences.get("unit") or "c").lower()
        provider = (self.preferences.get("provider") or "open-meteo").lower()

        if mode=="auto":
            geo = WeatherService.fetch_location(self.session)
            if geo:
                weather = self.get_weather_data(geo["latitude"],geo["longitude"],unit)
                if weather and "error" not in weather:
                    key = f"auto_{provider}_{unit}"
                    self.cache[key] = {"geo": geo, "data": weather, "ts": time.time()}
                    save_cache(self.base_path,self.cache)

        elif mode=="static":
            city = self.preferences.get("static_location")
            if city:
                try:
                    r=self.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                       params={"name": city, "count":1}, timeout=5)
                    res=r.json().get("results",[])
                    if res and (res[0].get("latitude") or res[0].get("lat")):
                        geo = {
                            "city": res[0].get("name"),
                            "state": res[0].get("admin1",""),
                            "country": res[0].get("country_code","BR"),
                            "latitude": res[0].get("latitude") or res[0].get("lat"),
                            "longitude": res[0].get("longitude") or res[0].get("lon")
                        }
                        weather = self.get_weather_data(geo["latitude"],geo["longitude"],unit)
                        if weather and "error" not in weather:
                            key = f"static_{provider}_{unit}"
                            self.cache[key] = {"geo": geo, "data": weather, "ts": time.time()}
                            save_cache(self.base_path,self.cache)
                except Exception as e:
                    logger.error(f"Erro localização estática: {e}")

# ==============================
# LISTENER
# ==============================
class WeatherListener(EventListener):
    def on_event(self,event,extension):
        unit=(extension.preferences.get("unit") or "c").lower()
        mode=(extension.preferences.get("location_mode") or "auto").lower()
        provider=(extension.preferences.get("provider") or "open-meteo").lower()
        interface=(extension.preferences.get("interface_mode") or "complete").lower()
        query=(event.get_argument() or "").strip()

        key=None
        if not query:
            key = f"{mode}_{provider}_{unit}"
            if key in extension.cache and time.time()-extension.cache[key]["ts"]<CACHE_TTL:
                return self.render(extension.cache[key],extension,interface)
            else:
                extension.update_auto_location()
                if key in extension.cache:
                    return self.render(extension.cache[key],extension,interface)

        else:  # busca manual
            city_query = query
            country_filter = None
            if "," in city_query:
                parts=[p.strip() for p in city_query.split(",")]
                city_query=parts[0]
                if len(parts)>1: country_filter=parts[1].upper()
            try:
                r=extension.session.get("https://geocoding-api.open-meteo.com/v1/search",
                                       params={"name": city_query, "count":5},timeout=5)
                results=r.json().get("results",[])
                if country_filter:
                    results=[res for res in results if res.get("country_code","").upper()==country_filter]

                results=[res for res in results if res.get("latitude") or res.get("lat")]

                if not results:
                    return RenderResultListAction([
                        ExtensionResultItem(icon=extension.icon("icon.png"),
                                            name="Cidade não encontrada",
                                            description="Digite uma cidade válida para continuar",
                                            on_enter=None)
                    ])

                items=[]
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_geo = {}
                    for res in results[:3]:
                        lat = res.get("latitude") or res.get("lat")
                        lon = res.get("longitude") or res.get("lon")
                        if lat is None or lon is None: continue
                        future = executor.submit(extension.get_weather_data, lat, lon, unit)
                        future_to_geo[future] = res

                    for future in as_completed(future_to_geo):
                        res = future_to_geo[future]
                        weather = future.result()
                        if weather and "error" not in weather:
                            geo = {
                                "city": res.get("name"),
                                "state": res.get("admin1", ""),
                                "country": res.get("country_code", "BR"),
                                "latitude": res.get("latitude") or res.get("lat"),
                                "longitude": res.get("longitude") or res.get("lon")
                            }
                            data = {"geo": geo, "data": weather, "ts":time.time()}
                            extension.cache[f"{geo['city'].lower()}_{provider}_{unit}"]=data
                            save_cache(extension.base_path,extension.cache)
                            items.append(self.render(data,extension,interface,return_item=True))

                if items:
                    return RenderResultListAction(items)

            except Exception as e:
                logger.error(f"Erro geocoding: {e}")

        return RenderResultListAction([
            ExtensionResultItem(icon=extension.icon("icon.png"),
                                name="Localização ou dados não disponíveis",
                                description=f"Provedor atual: {provider}",
                                on_enter=None)
        ])

    def render(self,cached_item,extension,interface_mode,return_item=False):
        geo=cached_item["geo"]
        weather=cached_item["data"]
        lang=get_system_language()
        url=f"https://weather.com/{lang}/weather/today/l/{geo['latitude']},{geo['longitude']}"
        temp=weather["current"]["temp"]
        desc=weather["current"]["desc"]
        flag=country_flag(geo["country"])
        loc_text=f"{geo['city']}, {geo['state']} {flag}" if geo.get("state") else f"{geo['city']} {flag}"

        if interface_mode=="complete":
            f=weather.get("forecast",[])
            desc_text=f"Amanhã: {f[0]['min']}º/{f[0]['max']}º" if f else "Clique para detalhes"
            item=ExtensionResultItem(icon=extension.icon("icon.png"),
                                     name=f"{loc_text} — {temp}º, {desc}",
                                     description=desc_text,
                                     on_enter=OpenUrlAction(url))
        elif interface_mode=="essential":
            item=ExtensionResultItem(icon=extension.icon("icon.png"),
                                     name=f"{temp}º, {desc}",
                                     description=loc_text,
                                     on_enter=OpenUrlAction(url))
        else:
            item=ExtensionSmallResultItem(icon=extension.icon("icon.png"),
                                          name=f"{temp}º – {loc_text}",
                                          on_enter=OpenUrlAction(url))
        return item if return_item else RenderResultListAction([item])

if __name__=="__main__":
    UWeather().run()
