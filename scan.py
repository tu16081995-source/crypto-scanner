import os
import time
import requests

BASE = "https://www.okx.com"
TOP_N = 100
STABLES = {"USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDG"}
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def ema(values, n):
    k = 2 / (n + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, n=6):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def get_candles(inst):
    r = requests.get(
        BASE + "/api/v5/market/candles",
        params={"instId": inst, "bar": "1Dutc", "limit": "300"},
        timeout=15,
    ).json()
    rows = [x for x in r.get("data", []) if x[8] == "1"]
    rows.reverse()
    return [(float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in rows]


def analyze(inst):
    cs = get_candles(inst)
    if len(cs) < 210:
        return None
    closes = [c[3] for c in cs]
    e34, e89, e200 = ema(closes, 34), ema(closes, 89), ema(closes, 200)
    po, ph, pl, pc = cs[-2]
    o, h, l, c = cs[-1]
    side = None
    if pc > po and c < o and o >= pc and c <= po and c < min(e34, e89, e200):
        side = "SHORT"
        sl = h
    elif pc < po and c > o and o <= pc and c >= po and c > max(e34, e89, e200):
        side = "LONG"
        sl = l
    if not side:
        return None
    risk = abs(sl - c)
    if risk == 0:
        return None
    sign = -1 if side == "SHORT" else 1
    r6 = rsi(closes, 6)
    warn = ""
    if side == "SHORT" and r6 < 25:
        warn = " (quá bán, dễ hồi)"
    if side == "LONG" and r6 > 75:
        warn = " (quá mua, dễ điều chỉnh)"
    return {
        "inst": inst,
        "side": side,
        "entry": c,
        "sl": sl,
        "risk_pct": risk / c * 100,
        "tp1": c + sign * risk * 1.5,
        "tp2": c + sign * risk * 2.5,
        "rsi": r6,
        "warn": warn,
    }


def send(text):
    if not TOKEN:
        print(text)
        return
    chat = CHAT_ID
    if not chat:
        u = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15
        ).json()
        chat = str(u["result"][-1]["message"]["chat"]["id"])
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": chat, "text": text},
        timeout=15,
    )


def main():
    t = requests.get(
        BASE + "/api/v5/market/tickers", params={"instType": "SPOT"}, timeout=15
    ).json()["data"]
    t = [
        x
        for x in t
        if x["instId"].endswith("-USDT")
        and x["instId"].split("-")[0] not in STABLES
    ]
    t.sort(key=lambda x: float(x["volCcy24h"]), reverse=True)
    found = []
    for x in t[:TOP_N]:
        try:
            res = analyze(x["instId"])
            if res:
                found.append(res)
        except Exception as e:
            print("loi", x["instId"], e)
        time.sleep(0.15)
    found.sort(key=lambda r: r["risk_pct"])
    if not found:
        send("Nến ngày vừa đóng: không có kèo nhấn chìm nào đạt điều kiện.")
        return
    msg = f"Kèo nến nhấn chìm khung ngày ({len(found)} coin):\n"
    for r in found[:15]:
        msg += (
            f"\n{r['inst']} - {r['side']}\n"
            f"Vào: {r['entry']:.6g}\n"
            f"SL: {r['sl']:.6g} ({r['risk_pct']:.1f}%)\n"
            f"TP1: {r['tp1']:.6g} | TP2: {r['tp2']:.6g}\n"
            f"RSI6: {r['rsi']:.0f}{r['warn']}\n"
        )
    msg += "\nChỉ để tham khảo, không phải lời khuyên đầu tư."
    send(msg)


main()
