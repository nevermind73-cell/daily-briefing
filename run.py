#!/usr/bin/env python3
"""Daily Briefing — GitHub Actions 버전 (Python 표준 라이브러리만 사용)"""
import json, os, ssl, datetime, re, xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

CFG = {
    "openweathermap_key": os.environ["OPENWEATHERMAP_KEY"],
    "newsapi_key":        os.environ["NEWSAPI_KEY"],
    "alphavantage_key":   os.environ["ALPHAVANTAGE_KEY"],
    "pushover_user_key":  os.environ["PUSHOVER_USER_KEY"],
    "pushover_app_token": os.environ["PUSHOVER_APP_TOKEN"],
    "city": "Seoul",
}

_SSL = ssl.create_default_context()

def get(url, headers=None, timeout=15):
    req = Request(url, headers=headers or {})
    with urlopen(req, context=_SSL, timeout=timeout) as r:
        return r.read()

def getj(url):
    return json.loads(get(url).decode())

# ── 날씨 ──────────────────────────────────────────────────────────────────────

def fetch_weather():
    try:
        d = getj(
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={CFG['city']}&appid={CFG['openweathermap_key']}&units=metric"
        )
        cond = {"Clear":"맑음","Clouds":"흐림","Rain":"비","Snow":"눈",
                "Drizzle":"이슬비","Thunderstorm":"천둥번개","Mist":"안개",
                "Fog":"안개","Haze":"연무"}.get(d["weather"][0]["main"],
                                                d["weather"][0]["main"])
        return (f"서울 {round(d['main']['temp'],1)}°C "
                f"(체감 {round(d['main']['feels_like'],1)}°C) {cond}")
    except Exception as e:
        return f"수집 실패: {e}"

# ── 시장 ──────────────────────────────────────────────────────────────────────

def fetch_market():
    key = CFG["alphavantage_key"]
    parts = []
    try:
        q = getj(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
                 f"&symbol=^IXIC&apikey={key}").get("Global Quote", {})
        parts.append(f"나스닥 {float(q.get('05. price',0)):,.0f} "
                     f"({q.get('10. change percent','').strip()})")
    except: pass
    try:
        q = getj(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
                 f"&symbol=EWY&apikey={key}").get("Global Quote", {})
        parts.append(f"코스피(EWY) {float(q.get('05. price',0)):.2f}")
    except: pass
    try:
        r = getj(f"https://www.alphavantage.co/query"
                 f"?function=CURRENCY_EXCHANGE_RATE"
                 f"&from_currency=USD&to_currency=KRW&apikey={key}"
                 ).get("Realtime Currency Exchange Rate", {})
        parts.append(f"USD/KRW {float(r.get('5. Exchange Rate',0)):,.0f}")
    except: pass
    return " | ".join(parts) if parts else "수집 실패"

# ── 뉴스 ──────────────────────────────────────────────────────────────────────

def fetch_news(query=None, country=None, n=5):
    try:
        key = CFG["newsapi_key"]
        today = datetime.date.today().isoformat()
        if country:
            params = urlencode({"country": country, "pageSize": n,
                                "apiKey": key, "from": today})
            url = f"https://newsapi.org/v2/top-headlines?{params}"
        else:
            params = urlencode({"q": query, "pageSize": n,
                                "sortBy": "publishedAt", "apiKey": key})
            url = f"https://newsapi.org/v2/everything?{params}"
        return [a.get("title", "") for a in getj(url).get("articles", [])[:n]]
    except:
        return []

# ── arXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv():
    try:
        root = ET.fromstring(
            get("https://arxiv.org/rss/eess.IV",
                headers={"User-Agent": "Mozilla/5.0"})
        )
        return [
            re.sub(r"\s+", " ", (i.findtext("title") or "").strip())
            for i in (root.find("channel") or root).findall("item")[:3]
            if i.findtext("title")
        ]
    except:
        return []

# ── 경쟁사 ────────────────────────────────────────────────────────────────────

def fetch_competitors():
    short = {"GE Healthcare": "GE", "Siemens Healthineers": "Siemens",
             "Philips Healthcare": "Philips", "Ziehm Imaging": "Ziehm",
             "Hologic": "Hologic"}
    lines = []
    for co, label in short.items():
        try:
            root = ET.fromstring(
                get(f"https://news.google.com/rss/search"
                    f"?q={quote(co)}&hl=en-US&gl=US&ceid=US:en",
                    headers={"User-Agent": "Mozilla/5.0"})
            )
            items = (root.find("channel") or root).findall("item")
            if items:
                t = re.sub(r"\s+-\s+\S.*$", "",
                           (items[0].findtext("title") or "").strip())
                if t:
                    lines.append(f"• {label}: {t[:60]}…"
                                 if len(t) > 60 else f"• {label}: {t}")
        except:
            pass
    return lines

# ── FDA 510k ──────────────────────────────────────────────────────────────────

def fetch_fda():
    try:
        codes = ["IYO", "JAK", "IYN", "MRZ", "JAY", "IZB", "OZO"]
        d7 = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
        td = datetime.date.today().strftime("%Y%m%d")
        data = getj(
            f"https://api.fda.gov/device/510k.json"
            f"?search=product_code:({'+'.join(codes)})"
            f"+AND+decision_date:[{d7}+TO+{td}]"
            f"&limit=5&sort=decision_date:desc"
        )
        return [f"• {r.get('k_number','')} {r.get('device_name','')[:50]}"
                for r in data.get("results", [])[:3]]
    except HTTPError as e:
        return ["• 최근 7일 신규 허가 없음"] if e.code == 404 else [f"• 오류: {e}"]
    except Exception as e:
        return [f"• 오류: {e}"]

# ── Pushover 발송 ─────────────────────────────────────────────────────────────

def send_pushover(message):
    payload = urlencode({
        "token":   CFG["pushover_app_token"],
        "user":    CFG["pushover_user_key"],
        "message": message,
        "title":   "📋 Daily Briefing",
        "html":    "1",
        "priority": 0,
    }).encode()
    req = Request(
        "https://api.pushover.net/1/messages.json",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(req, context=_SSL, timeout=15) as r:
        return json.loads(r.read())

# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    L = [f"<b>📋 {today}</b>\n"]

    print("날씨 수집 중...")
    L.append(f"🌤 <b>날씨</b> {fetch_weather()}")

    print("시장 수집 중...")
    L.append(f"📈 <b>시장</b> {fetch_market()}")
    L.append("")

    print("한국 뉴스 수집 중...")
    kr = fetch_news(country="kr", n=5)
    L.append("📰 <b>한국 뉴스</b>")
    for t in kr:
        L.append(f"• {t[:65]}…" if len(t) > 65 else f"• {t}")
    if not kr:
        L.append("• 수집 실패")
    L.append("")

    print("AI 뉴스 수집 중...")
    ai = fetch_news(query="의료 AI OR medical AI OR LLM OR GPT OR Claude AI", n=3)
    ax = fetch_arxiv()
    L.append("🤖 <b>AI 동향</b>")
    for t in ai:
        L.append(f"• {t[:65]}…" if len(t) > 65 else f"• {t}")
    for t in ax[:2]:
        L.append(f"• [arXiv] {t[:55]}…" if len(t) > 55 else f"• [arXiv] {t}")
    if not ai and not ax:
        L.append("• 수집 실패")
    L.append("")

    print("경쟁사 수집 중...")
    comp = fetch_competitors()
    L.append("🏢 <b>경쟁사</b>")
    L.extend(comp if comp else ["• 수집 실패"])
    L.append("")

    print("FDA 수집 중...")
    L.append("🏥 <b>FDA 510k</b>")
    L.extend(fetch_fda())

    message = "\n".join(L)
    if len(message) > 1020:
        message = message[:1017] + "..."

    print("Pushover 발송 중...")
    result = send_pushover(message)
    print(f"완료: {result}")

if __name__ == "__main__":
    main()
