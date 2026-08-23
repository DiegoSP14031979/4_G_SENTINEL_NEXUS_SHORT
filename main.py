import os
import json
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from google import genai
from google.genai.errors import APIError
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_ORIGEN = os.environ.get("EMAIL_ORIGEN")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")

STABLECOINS = {"tether", "usd-coin", "first-digital-usd", "dai", "ethena-usde", "usdd", "pyusd", "tether-gold"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FILE_POSICIONES = "posiciones.json"
FILE_HISTORIAL = "historial.json"

FEE_TAKER_PCT = 0.0060
FEE_ROUNDTRIP_PCT = (FEE_TAKER_PCT * 2) * 100

def cargar_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def guardar_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def obtener_candidatas_coingecko():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 50, "page": 1, "sparkline": False, "price_change_percentage": "24h"}
    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return [c["symbol"].upper() for c in res.json() if c["id"] not in STABLECOINS]
    except Exception as e:
        print("Error CoinGecko:", e)
        return []

def obtener_profundidad_libro_coinbase(symbol):
    url_ticker = f"https://api.exchange.coinbase.com/products/{symbol}-USD/ticker"
    url_book = f"https://api.exchange.coinbase.com/products/{symbol}-USD/book?level=2"
    
    try:
        res_t = requests.get(url_ticker, headers=HEADERS, timeout=4)
        if res_t.status_code != 200:
            return None
        t_data = res_t.json()
        precio_real = float(t_data.get("price", 0))
        bid = float(t_data.get("bid", 0))
        ask = float(t_data.get("ask", 0))
        if precio_real == 0:
            return None
            
        spread_pct = ((ask - bid) / precio_real) * 100
        if spread_pct > 0.3:
            return None
            
        res_b = requests.get(url_book, headers=HEADERS, timeout=4)
        liquidez_ask_usd, liquidez_bid_usd = 0, 0
        
        if res_b.status_code == 200:
            b_data = res_b.json()
            bids = b_data.get("bids", [])[:15]
            asks = b_data.get("asks", [])[:15]
            liquidez_bid_usd = sum(float(b[0]) * float(b[1]) for b in bids)
            liquidez_ask_usd = sum(float(a[0]) * float(a[1]) for a in asks)
            
        return {
            "symbol": symbol,
            "precio_vivido": precio_real,
            "spread_pct": round(spread_pct, 3),
            "profundidad_compra_usd": round(liquidez_bid_usd, 2),
            "profundidad_venta_usd": round(liquidez_ask_usd, 2)
        }
    except Exception:
        pass
    return None

def construir_embudo_mercado():
    candidatas = obtener_candidatas_coingecko()
    matriz_filtrada = []
    for sym in candidatas:
        datos_depth = obtener_profundidad_libro_coinbase(sym)
        if datos_depth and datos_depth["profundidad_compra_usd"] >= 10000:
            matriz_filtrada.append(datos_depth)
        if len(matriz_filtrada) >= 5:
            break
    return matriz_filtrada

def analizar_oportunidades_y_cartera(matriz_fina, posiciones_actuales):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un gestor cuantitativo avanzado especializado en ejecuciones sin deslizamiento (Slippage) en Coinbase.
    
    PARÁMETROS DE COMISIÓN:
    - Coste ida/vuelta: {FEE_ROUNDTRIP_PCT:.2f}%
    
    POSICIONES ACTIVAS EN CARTERA:
    {posiciones_actuales}
    
    MATRIZ PRE-FILTRADA LIVE (COINBASE ORDER BOOK LEVEL 2):
    {matriz_fina}
    
    TAREA:
    1. Evalúa ventas o mantenimiento de cartera.
    2. Identifica si hay alguna oportunidad de compra neta (>+2.5% libre de fees).
    
    REGLAS DE SALIDA:
    Genera el informe claro para el correo.
    
    INCLUYE OBLIGATORIAMENTE AL FINAL DEL TEXTO ESTOS DOS BLOQUES JSON EXACTOS:

    ===JSON_CARTERA===
    [
      {{"ticker": "BTC", "precio_entrada": 64000.0, "stop_loss": 62720.0, "take_profit": 66560.0}}
    ]
    ===JSON_CARTERA===

    ===JSON_DECISION===
    {{
      "accion": "COMPRAR",
      "resumen": "COMPRA BTC: Ruptura de volumen con soporte de $320k en libro de Coinbase."
    }}
    ===JSON_DECISION===
    (En "accion" pon COMPRAR, VENDER o MANTENER. En "resumen" explica brevemente en 1 frase la razón técnica).
    """
    
    modelos = ['gemini-3.6-flash']
    for modelo in modelos:
        for intento in range(3):
            try:
                response = client.models.generate_content(model=modelo, contents=prompt)
                return response.text
            except APIError as e:
                print(f"Intento {intento + 1} falló: {e}")
                time.sleep(5)
    raise Exception("Error consultando Gemini.")

def actualizar_historial_y_cartera(respuesta_ia, posiciones_actuales):
    texto_correo = respuesta_ia
    
    # 1. Extraer y guardar cartera
    if "===JSON_CARTERA===" in respuesta_ia:
        partes = respuesta_ia.split("===JSON_CARTERA===")
        texto_correo = partes[0].strip()
        json_cartera_str = partes[1].strip()
        try:
            nuevas_pos = json.loads(json_cartera_str)
            guardar_json(FILE_POSICIONES, nuevas_pos)
            posiciones_actuales = nuevas_pos
        except Exception as e:
            print("Error parseando JSON cartera:", e)

    # 2. Extraer y guardar decisión/historial
    historial = cargar_json(FILE_HISTORIAL, {"capital_inicial": 1000.0, "registro_saldo": [], "decisiones": []})
    fecha_iso = datetime.datetime.utcnow().isoformat() + "Z"

    if "===JSON_DECISION===" in respuesta_ia:
        try:
            partes_dec = respuesta_ia.split("===JSON_DECISION===")
            json_dec_str = partes_dec[1].strip()
            dec_data = json.loads(json_dec_str)
            dec_data["fecha"] = fecha_iso
            historial["decisiones"].append(dec_data)
        except Exception as e:
            print("Error parseando JSON decisión:", e)

    # Registro de valoración aproximada del saldo
    saldo_estimado = historial.get("capital_inicial", 1000.0)
    historial["registro_saldo"].append({
        "fecha": fecha_iso,
        "saldo": round(saldo_estimado, 2)
    })
    
    guardar_json(FILE_HISTORIAL, historial)
    return texto_correo

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Validado - Dashboard Sync"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    posiciones = cargar_json(FILE_POSICIONES, [])
    matriz_fina = construir_embudo_mercado()
    if matriz_fina:
        respuesta_raw = analizar_oportunidades_y_cartera(matriz_fina, posiciones)
        informe_limpio = actualizar_historial_y_cartera(respuesta_raw, posiciones)
        enviar_correo(informe_limpio)
    else:
        print("No se encontraron activos válidos.")
