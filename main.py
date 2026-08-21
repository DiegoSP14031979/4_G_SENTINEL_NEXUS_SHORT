import os
import smtplib
from email.mime.text import MIMEText
import google.generativeai as genai
import requests
import xml.etree.ElementTree as ET

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_ORIGEN = os.environ.get("EMAIL_ORIGEN")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")

def obtener_precios():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
    return requests.get(url).json()

def obtener_noticias():
    url = "https://news.google.com/rss/search?q=bitcoin+ethereum+criptomonedas&hl=es&gl=ES&ceid=ES:es"
    try:
        res = requests.get(url)
        root = ET.fromstring(res.content)
        titulares = []
        for item in root.findall('.//item')[:5]:
            titulares.append(item.find('title').text)
        return titulares
    except Exception as e:
        print("Error obteniendo noticias:", e)
        return []

def analizar(precios, noticias):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Actúa como un analista experto en criptomonedas.
    Datos actuales de mercado (precios en USD y cambio 24h): {precios}
    Últimas noticias del sector: {noticias}
    
    Proporciona un reporte en español con:
    1. Diagnóstico técnico breve de BTC y ETH.
    2. Impacto de las noticias en el mercado.
    3. Recomendación clara: [COMPRAR], [VENDER] o [MANTENER].
    4. Nivel de riesgo actual del 1 al 10.
    """
    return model.generate_content(prompt).text

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "🚨 Alerta e Informe Cripto"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    precios = obtener_precios()
    noticias = obtener_noticias()
    informe = analizar(precios, noticias)
    enviar_correo(informe)
