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
NAMES = ["Nhấn chìm", "Evening Star", "Evening Doji Star", "Two Crows",
         "Morning Star", "Morning Doji Star", "Abandoned Baby"]


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


def green(x):
    return x[4] > x[1]


def red(x):
    return x[4] < x[1]


def body(x):
    return abs(x[4] - x[1])


def blo(x):
    return min(x[1], x[4])


def bhi(x):
    return max(x[1], x[4])


def signals(cs):
    cl = [x[4] for x in cs]
    E = [ema_series(cl, n) for n in (34, 89, 200)]
    sig = {n: {} for n in NAMES}
    for i in range(210, len(cs)):
        a, b, c = cs[i - 2], cs[i - 1], cs[i]
        es = [E[0][i], E[1][i], E[2][i]]
        avg = sum(body(x) for x in cs[i - 12:i - 2]) / 10
        b1, b2 = body(a), body(b)
        rng2 = b[2] - b[3]
        mid1 = (a[1] + a[4]) / 2
        top = max(a[2], b[2], c[2])
        bot = min(a[3], b[3], c[3])
        doji = rng2 > 0 and b2 <= 0.1 * rng2
        small = b2 <= 0.5 * b1
        big = b1 >= avg and b1 > 0
        short_pos = c[4] < min(es) and top >= min(es)
        long_pos = c[4] > max(es) and bot <= max(es)
        # nhấn chìm (2 nến cuối)
        if body(c) > 0:
            if green(b) and red(c) and c[1] >= b[4] and c[4] <= b[1] \
                    and c[4] < min(es):
                sig["Nhấn chìm"][i] = ("SHORT", c[2])
            elif red(b) and green(c) and c[1] <= b[4] and c[4] >= b[1] \
                    and c[4] > max(es):
                sig["Nhấn chìm"][i] = ("LONG", c[3])
        if short_pos and big and green(a) and red(c) and c[4] < mid1:
            star_up = min(b[1], b[4]) >= mid1
            if star_up and small:
                sig["Evening Star"][i] = ("SHORT", top)
            if star_up and doji:
                sig["Evening Doji Star"][i] = ("SHORT", top)
            if red(b) and b[1] > a[4] and b[4] > a[4] \
                    and b[4] <= c[1] <= b[1] and c[4] < a[4]:
                sig["Two Crows"][i] = ("SHORT", top)
        if long_pos and big and red(a) and green(c) and c[4] > mid1:
            star_dn = max(b[1], b[4]) <= mid1
            if star_dn and small:
                sig["Morning Star"][i] = ("LONG", bot)
            if star_dn and doji:
                sig["Morning Doji Star"][i] = ("LONG", bot)
        # Abandoned Baby (thân doji nằm ngoài thân 2 nến kề)
        if doji and big:
            if short_pos and green(a) and red(c) and c[4] < mid1 \
                    and blo(b) > bhi(a) and blo(b) > bhi(c):
                sig["Abandoned Baby"][i] = ("SHORT", top)
            if long_pos and red(a) and green(c) and c[4] > mid1 \
                    and bhi(b) < blo(a) and bhi(b) < blo(c):
                sig["Abandoned Baby"][i] = ("LONG", bot)
    return sig


def simulate(cs, i, side, sl, rew):
    entry = cs[i][4]
    risk = abs(sl - entry)
    if risk == 0:
        return None
    sgn = -1 if side == "SHORT" else 1
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
            f" | 1 năm: {ra}")


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
    msg = (f"BACKTEST mô hình nến, khung ngày, {len(data)} coin\n"
           "Giảm: nến cuối đóng dưới 3 EMA. Tăng: đóng trên 3 EMA. "
           "Cụm nến chạm vùng EMA. SL đỉnh/đáy cụm, "
           f"giữ tối đa {MAXH} ngày.\n")
    for name in NAMES:
        msg += f"\n=== {name} ===\n"
        for rew in (1.5, 2, 3):
            trades = []
            for inst, (cs, sig) in data.items():
                s = sig[name]
                i = 210
                while i < len(cs) - 1:
                    if i in s:
                        r = simulate(cs, i, s[i][0], s[i][1], rew)
                        if r:
                            trades.append((r[0], cs[i][0], s[i][0]))
                            i = r[1] + 1
                            continue
                    i += 1
            msg += f"[TP {rew}R] Tất cả: {stats(trades, cutoff)}\n"
            for sd in ("LONG", "SHORT"):
                sub = [x for x in trades if x[2] == sd]
                if sub:
                    msg += f"  {sd}: {stats(sub, cutoff)}\n"
    msg += ("\nDữ liệu quá khứ của top coin hiện tại, chưa tính phí và "
            "trượt giá. Không phải lời khuyên đầu tư.")
    send(msg)


main()
