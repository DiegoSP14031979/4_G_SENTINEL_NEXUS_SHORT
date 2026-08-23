import os
import time
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

# --- CONECTORES MULTI-EXCHANGE ---

def obtener_top_coingecko():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 50,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h"
    }
    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        res.raise_for_status()
        datos = res.json()
        filtradas = [c for c in datos if c["id"] not in STABLECOINS]
        return filtradas[:25]  # Evaluamos las 25 más líquidas y activas
    except Exception as e:
        print("Error obteniendo CoinGecko:", e)
        return []

def obtener_datos_binance(symbol):
    # Binance Spot Ticker (ej: BTCUSDT)
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return {
                "binance_precio": float(data.get("lastPrice", 0)),
                "binance_volumen_usd": float(data.get("quoteVolume", 0)),
                "binance_cambio_24h": float(data.get("priceChangePercent", 0))
            }
    except Exception:
        pass
    return {}

def obtener_datos_bybit(symbol):
    # Bybit Linear Futures (Funding Rate y Sentimiento de Derivados)
    url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            list_data = data.get("result", {}).get("list", [])
            if list_data:
                item = list_data[0]
                return {
                    "bybit_funding_rate": float(item.get("fundingRate", 0)) * 100, # En %
                    "bybit_open_interest": float(item.get("openInterest", 0))
                }
    except Exception:
        pass
    return {}

def obtener_datos_coinbase(symbol):
    # Coinbase Public Market Data (Spread y Bid/Ask)
    url = f"https://api.exchange.coinbase.com/products/{symbol}-USD/ticker"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            bid = float(data.get("bid", 0))
            ask = float(data.get("ask", 0))
            spread = ask - bid
            return {
                "coinbase_precio": float(data.get("price", 0)),
                "coinbase_bid": bid,
                "coinbase_ask": ask,
                "coinbase_spread": round(spread, 4)
            }
    except Exception:
        pass
    return {}

def construir_matriz_consolidada():
    base_coins = obtener_top_coingecko()
    matriz_mercado = []

    for coin in base_coins:
        sym = coin["symbol"].upper()
        
        # Consultamos APIs adicionales
        b_data = obtener_datos_binance(sym)
        by_data = obtener_datos_bybit(sym)
        cb_data = obtener_datos_coinbase(sym)

        # Matriz combinada por cada activo
        matriz_mercado.append({
            "ticker": sym,
            "nombre": coin["name"],
            "coingecko_precio": coin["current_price"],
            "coingecko_cambio_24h_%": round(coin.get("price_change_percentage_24h") or 0, 2),
            "coinbase_precio": cb_data.get("coinbase_precio", coin["current_price"]),
            "coinbase_spread": cb_data.get("coinbase_spread", "N/A"),
            "binance_cambio_24h_%": b_data.get("binance_cambio_24h", "N/A"),
            "bybit_funding_rate_%": by_data.get("bybit_funding_rate", "N/A")
        })

    return matriz_mercado

# --- INTELIGENCIA ARTIFICIAL Y EVALUACIÓN ---

def analizar_oportunidades(matriz):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un trader cuantitativo institucional especializado en arbitrariedad, volumen y liquidez en Coinbase Advanced.
    
    Analiza la siguiente MATRIZ MULTI-EXCHANGE consolidada en tiempo real (CoinGecko, Coinbase, Binance y Bybit):
    {matriz}
    
    REGLAS DE EVALUACIÓN:
    1. Busca CONSENSO: La tendencia y el impulso deben ser coincidentes entre las plataformas.
    2. Atención al FUNDING RATE (Bybit): Si es extremadamente positivo (>0.05%), el mercado está sobrepalancado en compras (riesgo de caída). Si es negativo, hay presión vendedora excesiva.
    3. Selecciona ÚNICAMENTE 1 o 2 oportunidades de alta probabilidad técnica para operar en Coinbase.
    
    REGLAS DE SALIDA:
    Si encuentras una oportunidad clara, genera un informe directo con este formato exacto por moneda:
    
    🚨 OPORTUNIDAD DE CORTOPLAZO MULTI-EXCHANGE 🚨
    - Moneda: [Nombre y Ticker]
    - Acción: [COMPRAR / VENDER]
    - Consenso de Mercado: [Justificación cruzando datos de Coinbase, Binance y Bybit]
    - Precio de Entrada Sugerido: $X.XX
    - Stop Loss (Pérdida máx -2%): $X.XX
    - Take Profit (Objetivo +4%): $X.XX
    - Nivel de Riesgo (1 al 10): X
    
    Si el mercado está plano o sin consenso claro, responde únicamente: "MERCADO SIN SEÑALES DE CORTO PLAZO".
    """
    
    modelos = ['gemini-3.6-flash']
    
    for modelo in modelos:
        for intento in range(3):
            try:
                response = client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                )
                return response.text
            except APIError as e:
                print(f"Intento {intento + 1} con {modelo} falló: {e}")
                time.sleep(5)
    
    raise Exception("No se pudo obtener análisis de Gemini.")

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Multi-Exchange - Coinbase"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    matriz = construir_matriz_consolidada()
    if matriz:
        informe = analizar_oportunidades(matriz)
        enviar_correo(informe)
    else:
        print("No se pudo construir la matriz de mercado.")
