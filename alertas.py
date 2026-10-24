"""
Alertas por Telegram para Radar de Mercado.
Revisa tus símbolos y te avisa cuando cambia la señal (comprar, vender o esperar).

Uso:
  python alertas.py --prueba     envía un mensaje de prueba
  python alertas.py --una-vez    revisa una vez y termina (útil con un programador de tareas)
  python alertas.py              revisa cada INTERVALO_MIN minutos, sin parar

Variables de entorno:
  TELEGRAM_TOKEN y TELEGRAM_CHAT_ID   obligatorias
  SIMBOLOS        opcional, por ejemplo "BTC-USD,ETH-USD,AAPL"
  INTERVALO_MIN   opcional, minutos entre revisiones (por defecto 60)
  UMBRAL          opcional, exigencia de la señal de 1 a 4 (por defecto 2)

Solo análisis técnico. No es asesoría financiera.
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

SIMBOLOS = [s.strip().upper() for s in (os.getenv("SIMBOLOS") or "BTC-USD,ETH-USD,AAPL,NVDA").split(",") if s.strip()]
INTERVALO_MIN = int(os.getenv("INTERVALO_MIN") or "60")
UMBRAL = int(os.getenv("UMBRAL") or "2")
ESTADO = Path(__file__).with_name("estado_alertas.json")
ICONO = {"COMPRAR": "🟢", "VENDER": "🔴", "ESPERAR": "🟡"}


def etiqueta(p: int) -> str:
    return "COMPRAR" if p >= UMBRAL else "VENDER" if p <= -UMBRAL else "ESPERAR"


def analizar(tk: str):
    df = yf.download(tk, period="1y", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    if len(df) < 80:
        return None
    c = df["Close"]
    sma20, sma50 = c.rolling(20).mean(), c.rolling(50).mean()
    d = c.diff()
    gan = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    per = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float((100 - 100 / (1 + gan / per)).iloc[-1])
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = macd.ewm(span=9, adjust=False).mean()
    sd = c.rolling(20).std()
    banda_sup, banda_inf = (sma20 + 2 * sd).iloc[-1], (sma20 - 2 * sd).iloc[-1]
    px = float(c.iloc[-1])

    p = 1 if sma20.iloc[-1] > sma50.iloc[-1] else -1
    p += 1 if macd.iloc[-1] > sig.iloc[-1] else -1
    p += 1 if rsi < 30 else -1 if rsi > 70 else 0
    p += 1 if px < banda_inf else -1 if px > banda_sup else 0

    sop, res = float(c.tail(60).min()), float(c.tail(60).max())
    return {"simbolo": tk, "precio": px, "puntaje": int(p), "senal": etiqueta(int(p)),
            "rsi": rsi, "soporte": sop, "resistencia": res, "stop": sop * 0.97}


def mensaje(a: dict, anterior: str = None) -> str:
    cambio = f"Cambió de {anterior} a {a['senal']}." if anterior else "Señal actual."
    return (f"{ICONO[a['senal']]} {a['simbolo']}: {a['senal']} (puntaje {a['puntaje']:+d} de 4)\n"
            f"{cambio}\n"
            f"Precio: {a['precio']:,.2f} | RSI: {a['rsi']:.0f}\n"
            f"Soporte 60 días: {a['soporte']:,.2f} | Resistencia: {a['resistencia']:,.2f}\n"
            f"Tope de pérdida de referencia: {a['stop']:,.2f}\n"
            "Análisis técnico, no es asesoría financiera.")


def enviar(texto: str) -> bool:
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("Faltan TELEGRAM_TOKEN y TELEGRAM_CHAT_ID. Defínelas y vuelve a ejecutar.")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": texto}, timeout=20)
    except requests.RequestException:
        print("No se pudo conectar con Telegram. Revisa tu internet.")
        return False
    if not r.ok:
        print(f"Telegram devolvió un error ({r.status_code}). Revisa el token y el chat id.")
    return r.ok


def revisar():
    estado = json.loads(ESTADO.read_text()) if ESTADO.exists() else {}
    nuevo = dict(estado)
    primeras = []
    for tk in SIMBOLOS:
        try:
            a = analizar(tk)
        except Exception as e:
            print(f"{tk}: error al analizar ({type(e).__name__})")
            continue
        if a is None:
            print(f"{tk}: sin datos suficientes")
            continue
        ant = estado.get(tk)
        nuevo[tk] = a["senal"]
        print(f"{tk}: {a['senal']} ({a['puntaje']:+d}) precio {a['precio']:,.2f}")
        if ant is None:
            primeras.append(a)
        elif ant != a["senal"]:
            enviar(mensaje(a, ant))
    if primeras:
        lineas = [f"{ICONO[a['senal']]} {a['simbolo']}: {a['senal']} | {a['precio']:,.2f}" for a in primeras]
        enviar("📡 Radar de Mercado activo. Señales actuales:\n" + "\n".join(lineas) +
               "\n\nDesde ahora te aviso cuando cambie alguna.")
    ESTADO.write_text(json.dumps(nuevo, indent=2))


if __name__ == "__main__":
    if "--prueba" in sys.argv:
        print("Enviado." if enviar("✅ Prueba de Radar de Mercado: las alertas funcionan.") else "No se envió.")
    elif "--una-vez" in sys.argv:
        revisar()
    else:
        print(f"Vigilando {', '.join(SIMBOLOS)} cada {INTERVALO_MIN} min. Detén con Ctrl+C.")
        try:
            while True:
                revisar()
                time.sleep(INTERVALO_MIN * 60)
        except KeyboardInterrupt:
            print("Detenido.")
