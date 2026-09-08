import os
import json
import time
import urllib.request
import numpy as np
import pandas as pd
from datetime import datetime, timezone

# -------------------------------------------------------------------
# CONFIGURACIÓN G-CORE: PATA 4 (NEXUS SHORT // COINBASE ENGINE V4.2)
# -------------------------------------------------------------------
CAPITAL_INICIAL = 3300.0
SLOTS_TOTALES = 4
CAPITAL_POR_SLOT = CAPITAL_INICIAL / SLOTS_TOTALES
RIESGO_BASE_SLOT = CAPITAL_INICIAL * 0.015

# Pares oficial en Coinbase (Resistente a Rate-Limits)
UNIVERSO_CRYPTO = {
    "BTC-USD": {"symbol": "BTC", "label": "Bitcoin"},
    "ETH-USD": {"symbol": "ETH", "label": "Ethereum"},
    "SOL-USD": {"symbol": "SOL", "label": "Solana"},
    "XRP-USD": {"symbol": "XRP", "label": "Ripple"},
    "DOGE-USD": {"symbol": "DOGE", "label": "Dogecoin"}
}

POSICIONES_FILE = "posiciones.json"
HISTORIAL_FILE = "historial.json"
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def cargar_json(filename, default_data):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default_data
    return default_data

def guardar_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_coinbase_candles(pair, granularity=3600):
    """Obtiene velas horarias directo de Coinbase Pro public API"""
    try:
        url = f"https://api.exchange.coinbase.com/products/{pair}/candles?granularity={granularity}"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if not data or len(data) < 30:
                return None
            
            # Coinbase retorna: [time, low, high, open, close, volume]
            df = pd.DataFrame(data, columns=['time', 'Low', 'High', 'Open', 'Close', 'Volume'])
            df = df.sort_values('time').reset_index(drop=True)
            return df
    except Exception as e:
        print(f"[ERROR COINBASE API {pair}]: {e}")
        return None

def obtener_regimen_macro_btc():
    df_btc = get_coinbase_candles("BTC-USD", granularity=3600)
    if df_btc is None or len(df_btc) < 50:
        return "NEUTRAL", 0.0, 1.0

    df_btc['EMA20'] = df_btc['Close'].ewm(span=20, adjust=False).mean()
    df_btc['EMA50'] = df_btc['Close'].ewm(span=50, adjust=False).mean()
    
    precio = df_btc['Close'].iloc[-1]
    ema20 = df_btc['EMA20'].iloc[-1]
    ema50 = df_btc['EMA50'].iloc[-1]
    
    distancia_pct = ((precio - ema50) / ema50) * 100
    
    if precio < ema20 and ema20 < ema50:
        regimen = "STRONG_BEARISH_CRYPTO"
        sizing_factor = 1.0
    elif precio < ema20 or precio < ema50:
        regimen = "WEAK_BEARISH_CRYPTO"
        sizing_factor = 0.75
    else:
        regimen = "BULLISH_TREND_CRYPTO"
        sizing_factor = 0.5
        
    return regimen, distancia_pct, sizing_factor

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def ejecutar_motor_cuantitativo_short_crypto():
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    
    posiciones = cargar_json(POSICIONES_FILE, {"slots_activos": [], "capital_libre": CAPITAL_INICIAL})
    historial = cargar_json(HISTORIAL_FILE, {"operaciones": [], "metricas": {"win_rate": 0.0, "profit_factor": 1.0}})
    
    regimen_macro, distancia_btc, sizing_factor = obtener_regimen_macro_btc()
    riesgo_actual_slot = RIESGO_BASE_SLOT * sizing_factor
    
    decisiones_log = []
    decisiones_log.append(f"⚡ G-CORE NEXUS SHORT V4.2 // MACRO BTC: {regimen_macro} | Risk Factor: {sizing_factor*100:.0f}% (${riesgo_actual_slot:.2f})")
    
    slots_restantes = []
    capital_acumulado = posiciones.get("capital_libre", CAPITAL_INICIAL)
    
    # 1. Monitoreo de Posiciones Activas
    for pos in posiciones.get("slots_activos", []):
        pair = pos.get("pair", f"{pos.get('symbol', 'BTC')}-USD")
        df = get_coinbase_candles(pair)
        time.sleep(0.3)
        
        if df is None or df.empty:
            slots_restantes.append(pos)
            continue
            
        precio_actual = df['Close'].iloc[-1]
        precio_entrada = pos["entry_price"]
        
        rendimiento_pct = ((precio_entrada - precio_actual) / precio_entrada) * 100
        stop_loss = pos["stop_loss"]
        take_profit = pos["take_profit"]
        
        if stop_loss <= precio_entrada:
            stop_loss = round(precio_entrada * 1.02, 4)
            pos["stop_loss"] = stop_loss
        
        if rendimiento_pct >= 1.0 and stop_loss > precio_entrada:
            pos["stop_loss"] = precio_entrada
            decisiones_log.append(f"🛡️ Break-Even activado para SHORT {pos['symbol']} a ${precio_entrada:.4f}")
            
        if precio_actual >= pos["stop_loss"]:
            pnl_usd = -pos.get("risk_allocated", RIESGO_BASE_SLOT)
            capital_acumulado += pnl_usd
            historial["operaciones"].append({
                "timestamp": timestamp_str, "symbol": pos['symbol'], "side": "SHORT",
                "pnl_usd": round(pnl_usd, 2), "reason": "STOP_LOSS"
            })
            decisiones_log.append(f"❌ SL CERRADO en SHORT {pos['symbol']} | PnL: ${pnl_usd:.2f}")
            
        elif precio_actual <= take_profit:
            pnl_usd = pos.get("risk_allocated", RIESGO_BASE_SLOT) * 2.2
            capital_acumulado += pnl_usd
            historial["operaciones"].append({
                "timestamp": timestamp_str, "symbol": pos['symbol'], "side": "SHORT",
                "pnl_usd": round(pnl_usd, 2), "reason": "TAKE_PROFIT"
            })
            decisiones_log.append(f"🎯 TP CERRADO en SHORT {pos['symbol']} | PnL: +${pnl_usd:.2f}")
        else:
            pos["precio_actual"] = round(precio_actual, 4)
            slots_restantes.append(pos)
            
    # 2. Scanner de Nuevas Oportunidades
    slots_disponibles = SLOTS_TOTALES - len(slots_restantes)
    
    for pair, datos in UNIVERSO_CRYPTO.items():
        if any(p.get("symbol") == datos["symbol"] for p in slots_restantes):
            continue
            
        df = get_coinbase_candles(pair)
        time.sleep(0.3)
        
        if df is None or len(df) < 30:
            continue
            
        close = df['Close'].iloc[-1]
        ema20 = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
        rsi_series = calcular_rsi(df['Close'])
        rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50
        atr = calcular_atr(df)
        
        gatillo_a = (close < ema20) and (ema20 < ema50)
        gatillo_b = (rsi > 65)
        gatillo_c = (close < ema20)
        
        if slots_disponibles > 0 and (gatillo_a or gatillo_b or gatillo_c):
            motivo = "BREAKOUT_BEARISH" if gatillo_a else ("EXHAUSTION_REVERSAL" if gatillo_b else "LOCAL_WEAKNESS")
            
            sl_price = round(close + (atr * 1.5), 4)
            tp_price = round(close - (atr * 1.5 * 2.2), 4)
            
            nuevo_slot = {
                "pair": pair,
                "symbol": datos["symbol"],
                "label": datos["label"],
                "side": "SHORT",
                "entry_price": round(close, 4),
                "precio_actual": round(close, 4),
                "stop_loss": sl_price,
                "take_profit": tp_price,
                "timestamp": timestamp_str,
                "allocated_capital": CAPITAL_POR_SLOT,
                "risk_allocated": round(riesgo_actual_slot, 2),
                "trigger_type": motivo,
                "rsi": round(rsi, 1)
            }
            slots_restantes.append(nuevo_slot)
            slots_disponibles -= 1
            decisiones_log.append(f"🚀 SHORT ENTRY: {datos['symbol']} a ${close:.4f} | SL: ${sl_price:.4f} | TP: ${tp_price:.4f}")

    posiciones["slots_activos"] = slots_restantes
    posiciones["capital_libre"] = round(capital_acumulado, 2)
    posiciones["last_update"] = timestamp_str
    posiciones["macro_status"] = regimen_macro
    posiciones["decisiones_log"] = decisiones_log

    guardar_json(POSICIONES_FILE, posiciones)
    guardar_json(HISTORIAL_FILE, historial)
    print(" -> Engine NEXUS SHORT ejecutado correctamente vía Coinbase API.")

if __name__ == "__main__":
    ejecutar_motor_cuantitativo_short_crypto()
