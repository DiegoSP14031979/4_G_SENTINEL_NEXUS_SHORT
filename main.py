import urllib.request
import json
import os
from datetime import datetime

UNIVERSO = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]
MAPA_SIMBOLOS = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL", "ripple": "XRP", "dogecoin": "DOGE"}

CAPITAL_SLOT = 825.0  # $825 USD por posición (4 slots dinámicos)
RISK_REWARD_RATIO = 2.2
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def get_market_data(coin_id):
    """Obtiene datos de 90 días de CoinGecko para calcular EMA 200 de 1h y ATR 14"""
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=90"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as response:
            data = json.loads(response.read().decode('utf-8'))
            raw_prices = [p[1] for p in data.get("prices", [])]
            
            # Tomar muestras horarias para alinear con la vela de 1h (cada 12 registros de 5 min)
            prices = raw_prices[::12] if len(raw_prices) > 500 else raw_prices

            if len(prices) >= 200:
                price_current = prices[-1]
                ema_200 = sum(prices[-200:]) / 200
                
                # Impulso respecto a la hora anterior
                impulse_pct = ((price_current - prices[-2]) / prices[-2]) * 100
                
                # ATR aproximado (14 periodos de 1h)
                diffs = [abs(prices[i] - prices[i-1]) / prices[i-1] for i in range(len(prices)-14, len(prices))]
                atr_pct = (sum(diffs) / 14) * 100
                
                return {
                    "price": price_current,
                    "ema_200": ema_200,
                    "impulse_pct": impulse_pct,
                    "atr_pct": atr_pct
                }
    except Exception as e:
        print(f"[ERROR API {coin_id}]: {e}")
    return None

def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] Ejecutando G-SENTINEL NEXUS SHORT Engine...")

    # Cargar Posiciones
    posiciones = {}
    if os.path.exists("posiciones.json"):
        try:
            with open("posiciones.json", "r", encoding="utf-8") as f:
                posiciones = json.load(f)
        except Exception:
            posiciones = {}

    historial = []
    if os.path.exists("historial.json"):
        try:
            with open("historial.json", "r", encoding="utf-8") as f:
                historial = json.load(f)
        except Exception:
            historial = []

    logs = []

    # 1. EVALUAR SL/TP DE POSICIONES CORTAS ACTIVAS
    activos_a_cerrar = []
    for coin, pos in posiciones.items():
        data = get_market_data(coin)
        if not data:
            continue

        price = data["price"]
        entry = pos["entry_price"]
        sl_pct = pos["sl_pct"]
        tp_pct = pos["tp_pct"]

        # En SHORT: Ganamos si el precio cae respecto a la entrada
        pnl_pct = ((entry - price) / entry) * 100

        if pnl_pct >= tp_pct:
            pnl_usd = round(CAPITAL_SLOT * (tp_pct / 100), 2)
            historial.append({
                "fecha": timestamp,
                "asset": MAPA_SIMBOLOS.get(coin, coin),
                "type": "SHORT",
                "result": "TAKE_PROFIT",
                "pnl_usd": pnl_usd,
                "pnl_pct": round(tp_pct, 2)
            })
            activos_a_cerrar.append(coin)
            logs.append(f"[TP CERRADO] {MAPA_SIMBOLOS.get(coin, coin)} SHORT +{tp_pct:.2f}% (${pnl_usd})")

        elif pnl_pct <= -sl_pct:
            pnl_usd = round(-CAPITAL_SLOT * (sl_pct / 100), 2)
            historial.append({
                "fecha": timestamp,
                "asset": MAPA_SIMBOLOS.get(coin, coin),
                "type": "SHORT",
                "result": "STOP_LOSS",
                "pnl_usd": pnl_usd,
                "pnl_pct": round(-sl_pct, 2)
            })
            activos_a_cerrar.append(coin)
            logs.append(f"[SL CERRADO] {MAPA_SIMBOLOS.get(coin, coin)} SHORT -{sl_pct:.2f}% (${pnl_usd})")

    for c in activos_a_cerrar:
        del posiciones[c]

    # 2. EVALUAR NUEVAS ENTRADAS SHORT SI HAY SLOTS LIBRES (< 4)
    if len(posiciones) < 4:
        for coin in UNIVERSO:
            if coin in posiciones:
                continue
            if len(posiciones) >= 4:
                break

            data = get_market_data(coin)
            if not data:
                continue

            # Reglas SHORT: Precio < EMA 200 e Impulso a la baja < -0.8%
            if data["price"] < data["ema_200"] and data["impulse_pct"] < -0.8:
                sl_dynamic = max(2.5, min(5.0, data["atr_pct"] * 1.5))
                tp_dynamic = sl_dynamic * RISK_REWARD_RATIO

                posiciones[coin] = {
                    "entry_price": data["price"],
                    "sl_pct": round(sl_dynamic, 2),
                    "tp_pct": round(tp_dynamic, 2),
                    "timestamp": timestamp
                }
                logs.append(f"[SHORT ENTRADA] {MAPA_SIMBOLOS.get(coin, coin)} a ${data['price']} | SL: {sl_dynamic:.2f}% | TP: {tp_dynamic:.2f}%")

    # GUARDAR ARCHIVOS JSON
    with open("posiciones.json", "w", encoding="utf-8") as f:
        json.dump(posiciones, f, indent=4, ensure_ascii=False)

    with open("historial.json", "w", encoding="utf-8") as f:
        json.dump(historial, f, indent=4, ensure_ascii=False)

    print(" -> Engine SHORT ejecutado correctamente.")

if __name__ == "__main__":
    main()
