import os
import time
import requests

BASE = "https://www.okx.com"
TOP_N = 100
PAGES = 10
MAXH = 30
STABLES = {"USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDG"}
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def load(inst):
    rows, after = [], None
    for _ in range(PAGES):
        p = {"instId": inst, "bar": "1Dutc", "limit": "100"}
        if after:
            p["after"] = after
        r = requests.get(BASE + "/api/v5/market/history-candles",
                         params=p, timeout=20).json()
        d = r.get("data", [])
        if not d:
            break
        rows += d
        after = d[-1][0]
        time.sleep(0.12)
        if len(d) < 100:
            break
    rows = [x for x in rows if x[8] == "1"]
    rows.sort(key=lambda x: int(x[0]))
    return [(int(x[0]), float(x[1]), float(x[2]),
             float(x[3]), float(x[4])) for x in rows]


def ema_series(vals, n):
    k = 2 / (n + 1)
    out, e = [], vals[0]
    for v in vals:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def signals(cs):
    cl = [x[4] for x in cs]
    E = [ema_series(cl, n) for n in (34, 89, 200)]
    sig = {}
    for i in range(210, len(cs)):
        _, po, _, _, pc = cs[i - 1]
        _, o, h, l, c = cs[i]
        if abs(c - o) == 0:
            continue
        es = [E[0][i], E[1][i], E[2][i]]
        if pc > po and c < o and o >= pc and c <= po and c < min(es):
            sig[i] = ("SHORT", h)
        elif pc < po and c > o and o <= pc and c >= po and c > max(es):
            sig[i] = ("LONG", l)
    return sig


def pivot_target(cs, i, side, entry):
    lo = max(3, i - 120)
    best = None
    for k in range(lo, i - 2):
        if side == "SHORT":
            v = cs[k][3]
            nb = [cs[j][3] for j in range(k - 3, k + 4) if j != k]
            if v < min(nb) and v < entry:
                best = v if best is None else max(best, v)
        else:
            v = cs[k][2]
            nb = [cs[j][2] for j in range(k - 3, k + 4) if j != k]
            if v > max(nb) and v > entry:
                best = v if best is None else min(best, v)
    return best


def simulate(cs, i, side, sl, tp_mode):
    entry = cs[i][4]
    risk = abs(sl - entry)
    if risk == 0:
        return None
    sgn = -1 if side == "SHORT" else 1
    if tp_mode == "swing":
        lvl = pivot_target(cs, i, side, entry)
        if lvl is None:
            return None
        rew = abs(entry - lvl) / risk
        if rew < 1:
            return None
        tp = lvl
    else:
        rew = tp_mode
        tp = entry + sgn * rew * risk
    last = min(i + MAXH, len(cs) - 1)
    for j in range(i + 1, last + 1):
        _, _, h, l, c = cs[j]
        if side == "SHORT":
            if h >= sl:
                return -1.0, j
            if l <= tp:
                return rew, j
        else:
            if l <= sl:
                return -1.0, j
            if h >= tp:
                return rew, j
    if i + MAXH >= len(cs):
        return None
    return sgn * (cs[last][4] - entry) / risk, last


def send(text):
    print(text)
    if not (TOKEN and CHAT_ID):
        return
    for k in range(0, len(text), 3800):
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text[k:k + 3800]},
            timeout=15)


def stats(tr, cutoff):
    if not tr:
        return "0 lệnh"
    n = len(tr)
    w = sum(1 for t in tr if t[0] > 0)
    avg = sum(t[0] for t in tr) / n
    rec = [t[0] for t in tr if t[1] >= cutoff]
    ra = f"{sum(rec) / len(rec):+.2f}R/{len(rec)}" if rec else "-"
    return (f"{n} lệnh | thắng {w / n * 100:.0f}% | TB {avg:+.2f}R"
            f" | 1 năm gần: {ra}")


def main():
    t = requests.get(BASE + "/api/v5/market/tickers",
                     params={"instType": "SPOT"}, timeout=20).json()["data"]
    t = [x for x in t if x["instId"].endswith("-USDT")
         and x["instId"].split("-")[0] not in STABLES]
    t.sort(key=lambda x: float(x["volCcy24h"]), reverse=True)
    data = {}
    for x in t[:TOP_N]:
        try:
            cs = load(x["instId"])
            if len(cs) >= 260:
                data[x["instId"]] = (cs, signals(cs))
        except Exception as e:
            print("loi", x["instId"], e)
    max_ts = max(cs[-1][0] for cs, _ in data.values())
    cutoff = max_ts - 365 * 86400000
    tps = [1, 1.5, 2, 3, "swing"]
    msg = (f"BACKTEST nến nhấn chìm khung ngày\n{len(data)} coin\n"
           "Luật: nhấn chìm bao trọn thân nến trước, đóng cửa ngoài "
           "cả 3 EMA. Không lọc râu, không lọc khoảng cách.\n"
           f"Vào ở giá đóng cửa, SL ở đỉnh/đáy nến, giữ tối đa {MAXH} ngày\n"
           "(TP: số = chốt theo R, swing = đáy/đỉnh gần nhất)\n")
    for tp in tps:
        trades = []
        for inst, (cs, sig) in data.items():
            i = 210
            while i < len(cs) - 1:
                s = sig.get(i)
                if s:
                    r = simulate(cs, i, s[0], s[1], tp)
                    if r:
                        trades.append((r[0], cs[i][0], s[0]))
                        i = r[1] + 1
                        continue
                i += 1
        lab = f"TP {tp}R" if tp != "swing" else "TP swing"
        msg += f"\n[{lab}]\n"
        msg += f"Tất cả: {stats(trades, cutoff)}\n"
        for sd in ("LONG", "SHORT"):
            msg += f"{sd}: {stats([x for x in trades if x[2] == sd], cutoff)}\n"
    msg += ("\nLưu ý: dữ liệu quá khứ của top coin hiện tại, "
            "chưa tính phí và trượt giá. Không phải lời khuyên đầu tư.")
    send(msg)


main()
