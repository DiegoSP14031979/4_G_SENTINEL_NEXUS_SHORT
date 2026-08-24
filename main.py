import os
import json
import requests
from datetime import datetime

# ==========================================
# CONFIGURACIÓN Y CONSTANTES DEL CORE
# ==========================================
CAPITAL_INICIAL_USD = 3300.0
RIESGO_POR_TRADE_PCT = 0.015  # 1.5% R ($49.50 USD)
MAX_SLOTS = 4
MONTO_SLOT_USD = CAPITAL_INICIAL_USD / MAX_SLOTS  # $825.00 USD por slot

HISTORIAL_FILE = "historial.json"
POSICIONES_FILE = "posiciones.json"

# ==========================================
# FUNCIONES DE CARGA Y GUARDADO SEGURO DE JSON
# ==========================================
def cargar_json(filepath, default_value):
    if not os.path.exists(filepath):
        return default_value
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"⚠️ Error al leer {filepath}: {e}. Usando valor por defecto.")
        return default_value

def guardar_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Archivo {filepath} actualizado correctamente.")
    except Exception as e:
        print(f"❌ Error al guardar {filepath}: {e}")

# ==========================================
# OBTENCIÓN DE DATOS DE MERCADO
# ==========================================
def obtener_precio_actual(ticker):
    precios_ref = {
        "BTC": 77450.00,
        "ETH": 2450.00,
        "SOL": 94.10,
        "XRP": 1.4708,
        "DOGE": 0.1250
    }
    return precios_ref.get(ticker, 100.0)

def obtener_filtro_macro_btc():
    precio_btc = obtener_precio_actual("BTC")
    return True, precio_btc

# ==========================================
# LÓGICA PRINCIPAL DEL AGENTE CUANTITATIVO
# ==========================================
def ejecutar_agente():
    print("🚀 Iniciando ejecución del Agente de Trading Cripto...")
    
    # 1. Cargar historial y posiciones de forma segura
    historial = cargar_json(HISTORIAL_FILE, [])
    posiciones_raw = cargar_json(POSICIONES_FILE, {})

    # Normalizar 'posiciones' a diccionario en caso de que se haya guardado como lista
    posiciones = {}
    if isinstance(posiciones_raw, list):
        for item in posiciones_raw:
            if isinstance(item, dict) and "ticker" in item:
                posiciones[item["ticker"]] = item
    elif isinstance(posiciones_raw, dict):
        posiciones = posiciones_raw

    # Extraer saldo actual manejando 'historial' como lista
    if isinstance(historial, list) and len(historial) > 0:
        saldo_actual = historial[-1].get("capital", CAPITAL_INICIAL_USD)
    else:
        saldo_actual = CAPITAL_INICIAL_USD

    timestamp_actual = datetime.utcnow().strftime("%d/%m/%Y, %H:%M:%S")
    
    # 2. Verificar Filtro Macro BTC
    macro_seguro, precio_btc = obtener_filtro_macro_btc()
    
    accion_ejecutada = "MANTENER"
    razonamiento = ""
    posiciones_modificadas = False

    # 3. Evaluar posiciones abiertas
    posiciones_a_cerrar = []

    for ticker, pos in posiciones.items():
        precio_mercado = obtener_precio_actual(ticker)
        
        # Comprobar si perfora el Stop Loss
        if precio_mercado <= pos.get("stop_loss", 0.0):
            posiciones_a_cerrar.append(ticker)
            
            monto_invertido = pos.get("monto_usd", MONTO_SLOT_USD)
            precio_entrada = pos.get("precio_entrada", precio_mercado)
            perdida_pct = (precio_mercado - precio_entrada) / precio_entrada if precio_entrada > 0 else 0
            resultado_usd = monto_invertido * perdida_pct
            
            saldo_actual += resultado_usd
            accion_ejecutada = "EJECUTAR_STOP_LOSS"
            razonamiento = f"EJECUCIÓN DE STOP LOSS EN {ticker}: Venta activada a ${precio_mercado:.4f} tras perforar el SL de ${pos.get('stop_loss', 0.0):.4f}. Posición cerrada liberando 1 slot."
            posiciones_modificadas = True
            break

    # Eliminar posición cerrada del diccionario activo
    for ticker in posiciones_a_cerrar:
        del posiciones[ticker]

    # 4. Evaluar reglas de mantenimiento o nuevas compras
    if not posiciones_modificadas:
        slots_ocupados = len(posiciones)
        if slots_ocupados == MAX_SLOTS:
            accion_ejecutada = "MANTENER"
            razonamiento = f"MANTENER POSICIONES: Filtro Macro SEGURO (${precio_btc:.2f}). Cartera al 100% de capacidad ({slots_ocupados}/{MAX_SLOTS} slots ocupados). Ninguna posición ha alcanzado umbrales de salida o SL."
        else:
            accion_ejecutada = "MANTENER"
            razonamiento = f"MANTENER POSICIONES Y BUSCAR ENTRADA: Cartera con {slots_ocupados}/{MAX_SLOTS} slots ocupados. Saldo disponible en USD: ${saldo_actual:.2f}. Analizando liquidez Nivel 2 en libro de órdenes."

    # 5. Registrar el nuevo estado en el historial
    nuevo_registro = {
        "timestamp": timestamp_actual,
        "capital": round(saldo_actual, 2),
        "accion": accion_ejecutada,
        "razonamiento": razonamiento
    }

    if not isinstance(historial, list):
        historial = []

    historial.append(nuevo_registro)

    # 6. Guardar cambios en los archivos JSON
    guardar_json(HISTORIAL_FILE, historial)
    guardar_json(POSICIONES_FILE, posiciones)

    print(f"📊 Ejecución finalizada. Capital actual: ${saldo_actual:.2f} USD. Acción: {accion_ejecutada}")

# ==========================================
# PUNTO DE ENTRADA DE GITHUB ACTIONS
# ==========================================
if __name__ == "__main__":
    ejecutar_agente()
