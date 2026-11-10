import os
import time
import requests

BASE = "https://www.okx.com"
TOP_N = 100
STABLES = {"USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDG"}
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def api(path, params):
    time.sleep(0.25)
    return requests.get(BASE + path, params=params, timeout=20).json()


def candles(inst, bar, limit=300, only_closed=True):
    r = api("/api/v5/market/candles",
            {"instId": inst, "bar": bar, "limit": str(limit)})
    rows = r.get("data", [])
    if only_closed:
        rows = [x for x in rows if x[8] == "1"]
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


def btc_trend():
    try:
        cl = [c[3] for c in candles("BTC-USDT", "1Dutc")]
        e = ema(cl, 34)
        return ("down" if cl[-1] < e else "up"), cl[-1], e
    except Exception:
        return "flat", 0, 0


def analyze(inst, btc_dir):
    cs = candles(inst, "1Dutc")
    if len(cs) < 210:
        return None
    closes = [x[3] for x in cs]
    e34, e89, e200 = ema(closes, 34), ema(closes, 89), ema(closes, 200)
    po, ph, pl, pc, pv = cs[-2]
    o, h, l, c, v = cs[-1]
    body = abs(c - o)
    pbody = abs(pc - po)
    if body == 0 or pbody == 0:
        return None
    avg_body = sum(abs(x[3] - x[0]) for x in cs[-12:-2]) / 10
    avg_vol = sum(x[4] for x in cs[-22:-2]) / 20
    m = 0.003
    side = None
    if pc > po and c < o and o >= pc and c <= po \
            and c < min(e34, e89, e200) * (1 - m):
        side, sl, wick, extreme = "SHORT", h, c - l, max(h, ph)
    elif pc < po and c > o and o <= pc and c >= po \
            and c > max(e34, e89, e200) * (1 + m):
        side, sl, wick, extreme = "LONG", l, h - c, min(l, pl)
    if not side:
        return None
    if body < 1.2 * pbody or body < 1.2 * avg_body:
        return None
    if wick > 0.35 * body:
        return None
    risk = abs(sl - c)
    risk_pct = risk / c * 100
    if risk == 0 or risk_pct > 10:
        return None
    wk = candles(inst, "1Wutc", 100, False)
    if len(wk) < 40:
        return None
    wc = [x[3] for x in wk]
    w34 = ema(wc, 34)
    if side == "SHORT" and wc[-1] >= w34:
        return None
    if side == "LONG" and wc[-1] <= w34:
        return None
    score = 0
    why = ["khung tuần cùng chiều"]
    if body >= 1.5 * pbody:
        score += 1
        why.append("thân nến lớn gấp 1,5 lần nến trước")
    if v >= 1.2 * avg_vol:
        score += 1
        why.append("volume cao hơn trung bình")
    near = min(abs(extreme - e) / e for e in (e34, e89, e200))
    if near <= 0.015:
        score += 1
        why.append("nhấn chìm tại vùng EMA")
    if (side == "SHORT" and btc_dir == "down") or \
            (side == "LONG" and btc_dir == "up"):
        score += 1
        why.append("cùng chiều BTC")
    r6 = rsi(closes, 6)
    if (side == "SHORT" and r6 >= 25) or (side == "LONG" and r6 <= 75):
        score += 1
        why.append(f"RSI6 {r6:.0f}, chưa cực đoan")
    if risk_pct <= 6:
        score += 1
        why.append(f"SL gần ({risk_pct:.1f}%)")
    sign = -1 if side == "SHORT" else 1
    return {
        "inst": inst, "side": side, "entry": c, "sl": sl,
        "risk_pct": risk_pct, "tp1": c + sign * risk * 1.5,
        "tp2": c + sign * risk * 2.5, "score": score, "why": why,
    }


def send(text):
    print(text)
    if not TOKEN:
        return
    chat = CHAT_ID
    if not chat:
        u = requests.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates", timeout=15
        ).json()
        for item in reversed(u.get("result", [])):
            if "message" in item:
                chat = str(item["message"]["chat"]["id"])
                break
    if not chat:
        print("Khong co chat id")
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": chat, "text": text},
        timeout=15,
    )


def main():
    t = api("/api/v5/market/tickers", {"instType": "SPOT"})["data"]
    t = [x for x in t
         if x["instId"].endswith("-USDT")
         and x["instId"].split("-")[0] not in STABLES]
    t.sort(key=lambda x: float(x["volCcy24h"]), reverse=True)
    btc_dir, btc_c, btc_e = btc_trend()
    found = []
    for x in t[:TOP_N]:
        try:
            res = analyze(x["instId"], btc_dir)
            if res:
                found.append(res)
        except Exception as e:
            print("loi", x["instId"], e)
    found.sort(key=lambda r: (-r["score"], r["risk_pct"]))
    picks = [r for r in found if r["score"] >= 4][:2]
    btc_txt = {"down": "BTC dưới EMA34 ngày (ngắn hạn yếu)",
               "up": "BTC trên EMA34 ngày (ngắn hạn mạnh)",
               "flat": "Không đọc được BTC"}[btc_dir]
    if not picks:
        send(f"Nến ngày vừa đóng: không có kèo nào đủ chuẩn.\n"
             f"{btc_txt}\n"
             f"(Có {len(found)} coin qua bộ lọc cơ bản nhưng điểm thấp.)\n"
             "Không có kèo cũng là một kết quả tốt, đừng ép vào lệnh.")
        return
    msg = f"Kèo chọn lọc nến ngày vừa đóng\n{btc_txt}\n"
    for i, r in enumerate(picks, 1):
        msg += (
            f"\n{i}) {r['inst']} - {r['side']} (điểm {r['score']}/6)\n"
            f"Vào ~{r['entry']:.6g}\n"
            f"SL: {r['sl']:.6g} ({r['risk_pct']:.1f}%)\n"
            f"TP1: {r['tp1']:.6g} | TP2: {r['tp2']:.6g}\n"
            f"Lý do: {'; '.join(r['why'])}\n"
        )
    msg += ("\nHãy tự xem lại biểu đồ trước khi vào lệnh. "
            "Chỉ để tham khảo, không phải lời khuyên đầu tư.")
    send(msg)


main()
