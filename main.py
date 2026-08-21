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

# Criptomonedas estables que debemos ignorar en el escaneo
STABLECOINS = {"tether", "usd-coin", "first-digital-usd", "dai", "ethena-usde", "usdd", "pyusd", "tether-gold"}

def obtener_top_mercado_coingecko():
    # Obtiene las 100 criptomonedas con mayor volumen e impacto de mercado
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=15)
        res.raise_for_status()
        datos = res.json()
        
        # Filtrado para quedarnos solo con tickers volátiles relevantes
        monedas_filtradas = []
        for coin in datos:
            if coin["id"] not in STABLECOINS:
                monedas_filtradas.append({
                    "simbolo": coin["symbol"].upper(),
                    "nombre": coin["name"],
                    "precio": coin["current_price"],
                    "cambio_24h_%": round(coin.get("price_change_percentage_24h") or 0, 2),
                    "volumen_24h": coin["total_volume"]
                })
        return monedas_filtradas[:50]  # Enviamos el Top 50 más activo a la IA
    except Exception as e:
        print("Error obteniendo datos masivos del mercado:", e)
        return []

def analizar_oportunidades(datos_mercado):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un trader cuantitativo experto en Day Trading y Scalping para Coinbase.
    
    A continuación tienes la lista actualizada de las 50 criptomonedas con mayor volumen de mercado en tiempo real:
    {datos_mercado}
    
    TAREA:
    Escanea todo el listado e identifica ÚNICAMENTE las 2 o 3 mejores oportunidades operables.
    
    REGLAS DE SALIDA:
    Si detectas configuraciones de alta probabilidad, genera un reporte directo con este formato por cada oportunidad:
    
    🚨 OPORTUNIDAD DE CORTOPLAZO 🚨
    - Moneda: [Nombre y Ticker]
    - Acción: [COMPRAR / VENDER]
    - Razón Técnica: [Análisis técnico basado en volumen y cambio de %24h]
    - Precio de Entrada Sugerido: $X.XX
    - Stop Loss (Pérdida máx -2%): $X.XX
    - Take Profit (Objetivo +4%): $X.XX
    - Nivel de Riesgo (1 al 10): X
    
    Si el mercado general no muestra patrones claros de entrada, responde únicamente: "MERCADO SIN SEÑALES DE CORTO PLAZO".
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
                print(f"Intento {intento + 1} con {modelo} falló por sobrecarga: {e}")
                time.sleep(5)
    
    raise Exception("No se pudo completar el análisis tras varios intentos.")

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Masiva - Coinbase"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    datos_mercado = obtener_top_mercado_coingecko()
    if datos_mercado:
        informe = analizar_oportunidades(datos_mercado)
        enviar_correo(informe)
    else:
        print("No se pudieron obtener datos del mercado.")
