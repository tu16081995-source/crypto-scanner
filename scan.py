import os
import time
import requests

BASE = "https://www.okx.com"
TOP_N = 100
MIN_SCORE = 3
STABLES = {"USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDG"}
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def api(path, params):
    time.sleep(0.25)
    return requests.get(BASE + path, params=params, timeout=20).json()


def candles(inst):
    r = api("/api/v5/market/candles",
            {"instId": inst, "bar": "1Dutc", "limit": "300"})
    rows = [x for x in r.get("data", []) if x[8] == "1"]
    rows.reverse()
    return [(float(x[1]), float(x[2]), float(x[3]),
             float(x[4]), float(x[5])) for x in rows]


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


def analyze(inst):
    cs = candles(inst)
    if len(cs) < 210:
        return None
    closes = [x[3] for x in cs]
    es = [ema(closes, 34), ema(closes, 89), ema(closes, 200)]
    po, ph, pl, pc, pv = cs[-2]
    o, h, l, c, v = cs[-1]
    if c == o:
        return None
    side = None
    if pc > po and c < o and o >= pc and c <= po and c < min(es):
        side, sl = "SHORT", h
        dist = (min(es) - c) / c * 100
    elif pc < po and c > o and o <= pc and c >= po and c > max(es):
        side, sl = "LONG", l
        dist = (c - max(es)) / c * 100
    if not side:
        return None
    risk = abs(sl - c)
    if risk == 0:
        return None
    body = abs(c - o)
    avg_body = sum(abs(x[3] - x[0]) for x in cs[-12:-2]) / 10
    avg_vol = sum(x[4] for x in cs[-22:-2]) / 20
    r6 = rsi(closes, 6)
    score = 0
    why = []
    if body >= avg_body:
        score += 1
        why.append("thân nến lớn hơn trung bình")
    if v >= 1.2 * avg_vol:
        score += 1
        why.append("volume cao")
    if dist <= 4:
        score += 1
        why.append("gần EMA")
    if (side == "SHORT" and r6 >= 25) or (side == "LONG" and r6 <= 75):
        score += 1
        why.append("RSI chưa cực đoan")
    sgn = -1 if side == "SHORT" else 1
    return {
        "inst": inst, "side": side, "entry": c, "sl": sl,
        "risk_pct": risk / c * 100, "dist": dist, "rsi": r6,
        "tp2": c + sgn * 2 * risk, "tp3": c + sgn * 3 * risk,
        "score": score, "why": why,
    }


def send(text):
    print(text)
    if not (TOKEN and CHAT_ID):
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text[:4000]},
        timeout=15,
    )


def main():
    t = api("/api/v5/market/tickers", {"instType": "SPOT"})["data"]
    t = [x for x in t
         if x["instId"].endswith("-USDT")
         and x["instId"].split("-")[0] not in STABLES]
    t.sort(key=lambda x: float(x["volCcy24h"]), reverse=True)
    found = []
    for x in t[:TOP_N]:
        try:
            res = analyze(x["instId"])
            if res:
                found.append(res)
        except Exception as e:
            print("loi", x["instId"], e)
    found.sort(key=lambda r: (-r["score"], r["side"] != "SHORT", r["dist"]))
    picks = [r for r in found if r["score"] >= MIN_SCORE][:2]
    if not picks:
        send(f"Nến ngày vừa đóng: không có kèo nào đạt từ "
             f"{MIN_SCORE}/4 điểm.\n"
             f"({len(found)} coin nhấn chìm ngoài 3 EMA nhưng điểm thấp.)\n"
             "Không có kèo thì nghỉ, đừng ép vào lệnh.")
        return
    msg = ("Kèo chọn lọc nến ngày vừa đóng\n"
           "Theo backtest: SHORT có lợi thế, LONG gần hòa vốn.\n")
    for i, r in enumerate(picks, 1):
        tag = "" if r["side"] == "SHORT" else " (kèo yếu hơn)"
        msg += (
            f"\n{i}) {r['inst']} - {r['side']}{tag} "
            f"(điểm {r['score']}/4)\n"
            f"Vào ~{r['entry']:.6g}\n"
            f"SL tham khảo (đỉnh/đáy nến): {r['sl']:.6g} "
            f"({r['risk_pct']:.1f}%)\n"
            f"TP 2R: {r['tp2']:.6g} | TP 3R: {r['tp3']:.6g}\n"
            f"Cách EMA gần nhất: {r['dist']:.1f}% | "
            f"RSI6: {r['rsi']:.0f}\n"
            f"Lý do: {'; '.join(r['why'])}\n"
        )
    msg += ("\nTự xem biểu đồ, vùng cung cầu và SL trước khi vào lệnh. "
            "Không phải lời khuyên đầu tư.")
    send(msg)


main()
