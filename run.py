#!/usr/bin/env python3
"""Daily Briefing — GitHub Actions 버전"""
import json, os, ssl, datetime, re, time, xml.etree.ElementTree as ET
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote, urlparse, parse_qs
from urllib.error import HTTPError

CFG = {
    "openweathermap_key": os.environ["OPENWEATHERMAP_KEY"],
    "newsapi_key":        os.environ["NEWSAPI_KEY"],
    "alphavantage_key":   os.environ["ALPHAVANTAGE_KEY"],
    "gmail_user":         os.environ.get("GMAIL_USER", ""),
    "gmail_password":     os.environ.get("GMAIL_APP_PASSWORD", ""),
    "email_to":           os.environ.get("EMAIL_TO", ""),
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
        d = getj(f"https://api.openweathermap.org/data/2.5/weather"
                 f"?q=Seoul&appid={CFG['openweathermap_key']}&units=metric")
        cond = {"Clear":"맑음","Clouds":"흐림","Rain":"비","Snow":"눈",
                "Drizzle":"이슬비","Thunderstorm":"천둥번개",
                "Mist":"안개","Fog":"안개","Haze":"연무"
                }.get(d["weather"][0]["main"], d["weather"][0]["main"])
        return {
            "temp": round(d["main"]["temp"], 1),
            "feels": round(d["main"]["feels_like"], 1),
            "humidity": d["main"]["humidity"],
            "cond": cond,
        }
    except Exception as e:
        return {"error": str(e)}

# ── 시장 ──────────────────────────────────────────────────────────────────────

def fetch_market():
    key = CFG["alphavantage_key"]
    result = {}
    for label, sym in [("nasdaq", "QQQ"), ("kospi", "EWY")]:
        try:
            q = getj(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
                     f"&symbol={sym}&apikey={key}").get("Global Quote", {})
            p = float(q.get("05. price", 0))
            if p:
                result[label] = {"price": p, "pct": q.get("10. change percent","").strip()}
        except: pass
        time.sleep(1)
    try:
        r = getj(f"https://www.alphavantage.co/query"
                 f"?function=CURRENCY_EXCHANGE_RATE"
                 f"&from_currency=USD&to_currency=KRW&apikey={key}"
                 ).get("Realtime Currency Exchange Rate", {})
        rate = float(r.get("5. Exchange Rate", 0))
        if rate:
            result["usd_krw"] = rate
    except: pass
    return result

# ── 뉴스 ──────────────────────────────────────────────────────────────────────

def fetch_news(query=None, country=None, n=5):
    try:
        key = CFG["newsapi_key"]
        if country == "kr":
            params = urlencode({"q": "한국 OR Korea", "language": "ko",
                                "pageSize": n, "sortBy": "publishedAt", "apiKey": key})
            url = f"https://newsapi.org/v2/everything?{params}"
        elif country:
            params = urlencode({"country": country, "pageSize": n, "apiKey": key})
            url = f"https://newsapi.org/v2/top-headlines?{params}"
        else:
            params = urlencode({"q": query, "pageSize": n,
                                "sortBy": "publishedAt", "apiKey": key})
            url = f"https://newsapi.org/v2/everything?{params}"
        return [{"title": a.get("title",""), "url": a.get("url","")}
                for a in getj(url).get("articles", [])[:n]
                if a.get("title") and "[Removed]" not in a.get("title","")]
    except:
        return []

# ── GitHub Trending ───────────────────────────────────────────────────────────

def fetch_github_trending():
    try:
        week_ago = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        url = (f"https://api.github.com/search/repositories"
               f"?q=created:>{week_ago}&sort=stars&order=desc&per_page=5")
        data = getj(url)
        results = []
        for repo in data.get("items", [])[:5]:
            name  = repo["full_name"]
            desc  = (repo.get("description") or "")[:60]
            stars = repo.get("stargazers_count", 0)
            link  = repo["html_url"]
            title = f"⭐{stars:,} {name}" + (f" — {desc}" if desc else "")
            results.append({"title": title, "url": link})
        return results
    except:
        return []

# ── arXiv ─────────────────────────────────────────────────────────────────────

def fetch_arxiv():
    try:
        root = ET.fromstring(
            get("https://arxiv.org/rss/eess.IV", headers={"User-Agent": "Mozilla/5.0"}))
        results = []
        ch = root.find("channel")
        items = ch.findall("item") if ch is not None else root.findall("item")
        for i in items[:3]:
            t = re.sub(r"\s+", " ", (i.findtext("title") or "").strip())
            l = (i.findtext("link") or i.findtext("guid") or "").strip()
            if t:
                results.append({"title": t, "url": l})
        return results
    except:
        return []

# ── 번역 ──────────────────────────────────────────────────────────────────────

def _is_korean(text):
    ko = sum(1 for c in text if '가' <= c <= '힣')
    return ko / max(len(text), 1) > 0.1

def translate_ko(text):
    if _is_korean(text):
        return text
    try:
        url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair=en|ko"
        d = getj(url)
        return d["responseData"]["translatedText"] or text
    except:
        return text

# ── 경쟁사 ────────────────────────────────────────────────────────────────────

def fetch_competitors():
    companies = {
        "GE Healthcare":       "GE",
        "Siemens Healthineers":"Siemens",
        "Philips Healthcare":  "Philips",
        "Ziehm Imaging":       "Ziehm",
        "Hologic":             "Hologic",
    }
    results = {}
    for co, label in companies.items():
        try:
            # Bing News RSS — 실제 기사 URL 반환
            url = f"https://www.bing.com/news/search?q={quote(co)}&format=rss"
            root = ET.fromstring(get(url, headers={"User-Agent": "Mozilla/5.0"}))
            ch = root.find("channel")
            items = ch.findall("item") if ch is not None else root.findall("item")
            news = []
            for item in items[:2]:
                t = (item.findtext("title") or "").strip()
                raw_u = (item.findtext("link") or "").strip()
                qs = parse_qs(urlparse(raw_u).query)
                u = qs.get("url", [raw_u])[0]
                if t and u:
                    news.append({"title": translate_ko(t), "url": u})
            results[label] = news
        except:
            results[label] = []
    return results

# ── FDA 510k ──────────────────────────────────────────────────────────────────

def fetch_fda():
    try:
        codes = ["IYO", "JAK", "IYN", "MRZ", "JAY", "IZB", "OZO"]
        d7 = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y%m%d")
        td = datetime.date.today().strftime("%Y%m%d")
        data = getj(f"https://api.fda.gov/device/510k.json"
                    f"?search=product_code:({'+'.join(codes)})"
                    f"+AND+decision_date:[{d7}+TO+{td}]&limit=5&sort=decision_date:desc")
        return [{"k": r.get("k_number",""), "name": r.get("device_name",""),
                 "date": r.get("decision_date",""),
                 "url": f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={r.get('k_number','')}"}
                for r in data.get("results", [])[:5]]
    except HTTPError as e:
        return [] if e.code == 404 else []
    except:
        return []

# ── HTML 생성 ─────────────────────────────────────────────────────────────────

def build_html(weather, market, kr_news, ai_news, arxiv, github_trending, competitors, fda):
    today = datetime.date.today().strftime("%Y년 %m월 %d일")
    now = datetime.datetime.now().strftime("%H:%M")

    def lnk(url, text):
        return f'<a href="{url}" target="_blank">{text}</a>' if url else text

    def section(icon, title, content):
        return f"""<div class="card"><h2>{icon} {title}</h2>{content}</div>"""

    # 날씨
    if "error" not in weather:
        w_html = (f'<div class="big-temp">{weather["temp"]}°C</div>'
                  f'<p>{weather["cond"]} · 체감 {weather["feels"]}°C · 습도 {weather["humidity"]}%</p>')
    else:
        w_html = f'<p class="err">수집 실패: {weather["error"]}</p>'

    # 시장
    m_parts = []
    if "nasdaq" in market:
        m_parts.append(f'나스닥(QQQ) <b>{market["nasdaq"]["price"]:,.2f}</b> '
                       f'<span class="chg">{market["nasdaq"]["pct"]}</span>')
    if "kospi" in market:
        m_parts.append(f'코스피(EWY) <b>{market["kospi"]["price"]:.2f}</b> '
                       f'<span class="chg">{market["kospi"]["pct"]}</span>')
    if "usd_krw" in market:
        m_parts.append(f'USD/KRW <b>{market["usd_krw"]:,.0f}</b>')
    m_html = "<p>" + " &nbsp;|&nbsp; ".join(m_parts) + "</p>" if m_parts else '<p class="err">수집 실패</p>'

    # 뉴스 목록
    def news_list(items):
        if not items:
            return '<p class="err">수집 실패</p>'
        return "<ul>" + "".join(f'<li>{lnk(a["url"], a["title"])}</li>' for a in items) + "</ul>"

    # arXiv
    ax_html = news_list(arxiv)

    # 경쟁사
    comp_html = ""
    for label, items in competitors.items():
        comp_html += f"<h3>{label}</h3>"
        if items:
            comp_html += "<ul>" + "".join(f'<li>{lnk(i["url"], i["title"])}</li>' for i in items) + "</ul>"
        else:
            comp_html += '<p class="err">뉴스 없음</p>'

    # FDA
    if fda:
        fda_items = []
        for i in fda:
            label = i["k"] + " " + i["name"]
            date = i["date"][:8] if i["date"] else ""
            fda_items.append(f'<li>{lnk(i["url"], label)} ({date})</li>')
        fda_html = "<ul>" + "".join(fda_items) + "</ul>"
    else:
        fda_html = "<p>최근 7일 신규 허가 없음</p>"

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Briefing {today}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f7;color:#1d1d1f;font-size:15px;line-height:1.6}}
header{{background:#0071e3;color:#fff;padding:18px 16px;position:sticky;top:0;z-index:10}}
header h1{{font-size:1.2rem;font-weight:700}}
header p{{font-size:.8rem;opacity:.85;margin-top:2px}}
main{{padding:12px 16px 40px;max-width:860px;margin:0 auto}}
.card{{background:#fff;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card h2{{font-size:.95rem;font-weight:700;color:#0071e3;border-bottom:1px solid #e5e5ea;padding-bottom:8px;margin-bottom:12px}}
.card h3{{font-size:.85rem;font-weight:600;color:#6e6e73;margin:10px 0 4px}}
.big-temp{{font-size:2.5rem;font-weight:300;text-align:center;padding:8px 0}}
ul{{padding-left:18px}}
li{{margin:5px 0;font-size:.9rem}}
a{{color:#0071e3;text-decoration:none}}
a:hover{{text-decoration:underline}}
.chg{{font-size:.85rem;color:#34c759}}
.err{{color:#ff3b30;font-size:.85rem}}
@media(max-width:600px){{.big-temp{{font-size:2rem}}}}
</style>
</head>
<body>
<header>
  <h1>📋 Daily Briefing</h1>
  <p>{today} · {now} 기준</p>
</header>
<main>
{section("🌤","날씨",w_html)}
{section("📈","시장",m_html)}
{section("📰","한국 뉴스",news_list(kr_news))}
{section("🤖","AI 뉴스",news_list(ai_news))}
{section("🔬","arXiv · eess.IV",ax_html)}
{section("🐙","GitHub 인기 프로젝트",news_list(github_trending))}
{section("🏢","경쟁사 동향",comp_html)}
{section("🏥","FDA 510k",fda_html)}
</main>
</body>
</html>"""

# ── 이메일 발송 ───────────────────────────────────────────────────────────────

def send_email(subject, html_body):
    gmail_user = CFG["gmail_user"]
    gmail_pw   = CFG["gmail_password"]
    email_to   = CFG["email_to"]
    if not (gmail_user and gmail_pw and email_to):
        print("  이메일 설정 없음, 건너뜀")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = gmail_user
    msg["To"]      = email_to
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(gmail_user, gmail_pw)
        server.sendmail(gmail_user, email_to, msg.as_bytes())
    print(f"  → {email_to} 발송 완료")

# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Daily Briefing 시작 ===")

    print("[1] 날씨...")
    weather = fetch_weather()
    print(" →", weather)

    print("[2] 시장...")
    market = fetch_market()
    print(" →", market)

    print("[3] 한국 뉴스...")
    kr_news = fetch_news(country="kr", n=5)
    print(f" → {len(kr_news)}건")

    print("[4] AI 뉴스...")
    ai_news = fetch_news(query="의료 AI OR medical AI OR LLM OR GPT OR Claude AI", n=5)
    arxiv = fetch_arxiv()
    print(f" → AI {len(ai_news)}건, arXiv {len(arxiv)}건")

    print("[5] GitHub Trending...")
    github_trending = fetch_github_trending()
    print(f" → {len(github_trending)}건")

    print("[6] 경쟁사...")
    competitors = fetch_competitors()
    print(f" → {sum(len(v) for v in competitors.values())}건")

    print("[7] FDA...")
    fda = fetch_fda()
    print(f" → {len(fda)}건")

    # HTML 저장
    html = build_html(weather, market, kr_news, ai_news, arxiv, github_trending, competitors, fda)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("[8] index.html 저장 완료")

    print("[9] 이메일 발송...")
    today_str = datetime.date.today().strftime("%Y년 %m월 %d일")
    send_email(f"📋 Daily Briefing {today_str}", html)

    print("=== 완료 ===")

if __name__ == "__main__":
    main()
