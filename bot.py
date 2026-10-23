import html
import os
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ==========================================
# 1. TELEGRAM CONFIGURATION (GitHub Secrets -> env vars, no defaults)
# ==========================================
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ==========================================
# 2. KEYWORDS & SETTINGS
# ==========================================
KEYWORDS = [
    'python', 'بايثون', 'سكربت', 'script', 'bot', 'بوت',
    'automation', 'أتمتة', 'scraping', 'سحب', 'بيانات', 'داتا',
    'cisco', 'سيسكو', 'packet tracer', 'شبكات', 'network',
    'penetration', 'اختراق', 'security', 'أمن', 'ثغرات',
    'اختبار', 'testing', 'cyber', 'vulnerability', 'api'
]

EXCLUDED_WORDS = [
    'متابعين', 'لايكات', 'تصويت', 'followers', 'تداول', 'تيك توك',
    'فوركس', 'تسويق', 'مبيعات', 'marketing', 'تصميم', 'لوجو', 'سوشيال'
]

SEEN_FILE = "seen_jobs.txt"
MAX_SEEN = 1000
TIMEOUT = 15

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
})

# ==========================================
# 3. SEEN-JOBS STATE (ordered, so trimming keeps the newest)
# ==========================================
seen_list = []
if os.path.exists(SEEN_FILE):
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        seen_list = [line.strip() for line in f if line.strip()]
seen_set = set(seen_list)

# Empty state = first run: record everything currently listed, alert on nothing.
FIRST_RUN = not seen_list


def mark_seen(url):
    if url not in seen_set:
        seen_set.add(url)
        seen_list.append(url)


def save_seen_jobs():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(seen_list[-MAX_SEEN:]) + "\n")


# ==========================================
# 4. CORE FUNCTIONS
# ==========================================
def send_telegram_message(text):
    # Never print the URL or exception text: both can contain the bot token.
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for _ in range(2):
        try:
            r = SESSION.post(url, json=payload, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"Telegram request failed: {type(e).__name__}")
            return False
        if r.status_code == 200:
            return True
        if r.status_code == 429:
            try:
                wait = int(r.json().get("parameters", {}).get("retry_after", 5))
            except ValueError:
                wait = 5
            time.sleep(min(wait, 30))
            continue
        print(f"Telegram HTTP {r.status_code}: {r.text[:200]}")
        return False
    return False


def process_job_post(title, full_url, platform_name):
    if full_url in seen_set:
        return

    title_lower = title.lower()

    if any(w in title_lower for w in EXCLUDED_WORDS):
        mark_seen(full_url)
        return

    if any(k in title_lower for k in KEYWORDS):
        if not FIRST_RUN:
            message = (
                f"🎯 <b>New Project Found! [{platform_name}]</b>\n\n"
                f"📌 <b>Title:</b> {html.escape(title)}\n"
                f"🔗 <b>Link:</b> {full_url}"
            )
            if not send_telegram_message(message):
                return  # not marked seen -> retried next cycle
            print(f"Match sent: {title}")

    mark_seen(full_url)


def fetch_soup(url):
    r = SESSION.get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        print(f"{url} -> {r.status_code} server={r.headers.get('server')} "
              f"cf-mitigated={r.headers.get('cf-mitigated')} body={r.text[:150]!r}")
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def check_khamsat_requests():
    url = "https://khamsat.com/community/requests"
    try:
        soup = fetch_soup(url)
        links = soup.select("table.forum-table tbody tr td.title a")
        for link in links:
            title = link.get_text(strip=True)
            href = link.get("href")
            if title and href:
                process_job_post(title, urljoin("https://khamsat.com", href), "Khamsat 🟢")
        print(f"Khamsat OK: {len(links)} links")
        return True
    except requests.HTTPError as e:
        print(f"Khamsat HTTP {e.response.status_code}")
    except Exception as e:
        print(f"Khamsat error: {type(e).__name__}: {e}")
    return False


def check_nafezly_projects():
    url = "https://nafezly.com/projects"
    try:
        soup = fetch_soup(url)
        count = 0
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/project/" in href and not href.endswith("/projects"):
                title = link.get_text(strip=True)
                if title:
                    count += 1
                    process_job_post(title, urljoin("https://nafezly.com", href), "Nafezly 🔵")
        print(f"Nafezly OK: {count} links")
        return True
    except requests.HTTPError as e:
        print(f"Nafezly HTTP {e.response.status_code}")
    except Exception as e:
        print(f"Nafezly error: {type(e).__name__}: {e}")
    return False


# ==========================================
# 5. SINGLE RUN (GitHub Actions calls this every ~5 min)
# ==========================================
if __name__ == "__main__":
    results = [check_khamsat_requests(), check_nafezly_projects()]
    save_seen_jobs()
    if FIRST_RUN:
        print(f"First run: seeded {len(seen_list)} jobs, no alerts sent.")
    if not any(results):
        sys.exit(1)  # both sites failed -> run shows red in the Actions tab