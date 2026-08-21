Python
import os
import smtplib
from email.mime.text import MIMEText
from google import genai
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_ORIGEN = os.environ.get("EMAIL_ORIGEN")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")

# Criptomonedas de alto volumen y volatilidad en Coinbase
CRIPTOS = ["bitcoin", "ethereum", "solana", "avalanche-2", "chainlink", "near", "render-token"]

def obtener_datos_coinbase():
    ids = ",".join(CRIPTOS)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true"
    try:
        res = requests.get(url)
        return res.json()
    except Exception as e:
        print("Error obteniendo datos:", e)
        return {}

def analizar_oportunidades(datos):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un trader cuantitativo de corto plazo (Day Trading) para operar en Coinbase.
    
    Analiza la siguiente matriz de precios, cambios en 24h y volumen:
    {datos}
    
    TAREA:
    Escanéalas y selecciona ÚNICAMENTE las 1 o 2 mejores oportunidades con mayor potencial de trading a corto plazo.
    
    REGLAS DE SALIDA:
    Si encuentras una oportunidad clara, genera un informe súper directo con este formato exacto por cada moneda seleccionada:
    
    🚨 OPORTUNIDAD DE CORTOPLAZO 🚨
    - Moneda: [Nombre]
    - Acción: [COMPRAR / VENDER / ESPERAR]
    - Razón Técnica: [Breve justificación según volatilidad/cambio]
    - Precio de Entrada Sugerido: $X.XX
    - Stop Loss (Pérdida máx -2%): $X.XX
    - Take Profit (Objetivo +4%): $X.XX
    - Nivel de Riesgo (1 al 10): X
    
    Si el mercado está plano o sin oportunidades claras, indica: "MERCADO SIN SEÑALES DE CORTO PLAZO".
    """
    
    response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt,
    )
    return response.text

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Corto Plazo - Coinbase"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    datos = obtener_datos_coinbase()
    if datos:
        informe = analizar_oportunidades(datos)
        enviar_correo(informe)
