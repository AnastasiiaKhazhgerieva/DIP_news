# -*- coding: utf-8 -*-
"""dip_news.ipynb 
is the same file, but more convenient for running  locally.
    
"""

# packages

import requests
import json
import time
import datetime
import os
import pandas as pd
#import google.generativeai as genai
import io
import base64
import re
from pathlib import Path
try: # google colab не запускается, когда раним через workflow, он там есть по умолчанию, поэтому имени в PyPL такого нет
    from google.colab import userdata, drive
except ImportError:
    userdata = None
    drive = None
from datetime import date, timedelta, datetime
from typing import List
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from typing import List
from pydantic import BaseModel


# Sandbox mode
# USE_SANDBOX = os.environ.get("USE_SANDBOX", "True").lower() == "true"
USE_SANDBOX = False  # Set to True to use sandbox folders
FOLDERS_JSON = os.environ.get("FOLDERS_SANDBOX") if USE_SANDBOX else os.environ.get("FOLDERS_MAIN")
print("Folders:", "SANDBOX (FOLDERS_SANDBOX)" if USE_SANDBOX else "MAIN (FOLDERS_MAIN)")


# Folders configuration - load from environment variable as JSON string
if not FOLDERS_JSON:
    raise ValueError("FOLDERS_JSON environment variable is required!")
try:
    folder = json.loads(FOLDERS_JSON)
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid FOLDERS_JSON format: {e}")

if not folder:
    raise ValueError("FOLDERS_JSON is empty!")



# Auxilliary
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


#PROXY

PROXY = os.environ.get('PROXY')
proxies = {'https':
        PROXY
        }

if not PROXY:
    raise ValueError("There is no proxy (check the file or environment variable)!")


# Set drive access https://console.cloud.google.com
# 1. Create
# 1.1 APIs and Services -> Credentials -> OAuth Client ID (if authorized, else - Servise)
# (explanation https://sky.pro/wiki/media/kak-ispolzovat-python-dlya-raboty-s-api-google/)
# 1.2 Client ID for Desktop -> Client secrets -> Dowload json (!avaliable only once while creating)
# 1.3 Give access to the email on the drive

# 2.Set secret
# 2.1 APIs and Services -> OAuth consent screen -> Audience -> Publishing Status- Testing -> add yourself to Test users!
# (https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification?hl=en#projects-used-in-dev-test-stage)
# 2.2 run 1auth.py than 2encode_token.py 
# for servisce account change to

# "from google.oauth2 import service_account

# SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
# SERVICE_ACCOUNT_FILE = '/path/to/service.json'

# credentials = service_account.Credentials.from_service_account_file(
#         SERVICE_ACCOUNT_FILE, scopes=SCOPES)"
# After creating the key, give the service account the rights to the folder in Drive!

encoded_token = os.environ.get("GOOGLE_TOKEN_B64")
if not encoded_token:
    raise RuntimeError("The OAuth token was not found. Make sure that the GOOGLE_TOKEN_B64 environment variable is set.")

token_bytes = base64.b64decode(encoded_token)
token_info = json.loads(token_bytes.decode("utf-8"))

creds = Credentials.from_authorized_user_info(token_info, scopes=["https://www.googleapis.com/auth/drive"])

if creds.expired and creds.refresh_token:
    creds.refresh(Request())
    
drive_service = build("drive", "v3", credentials=creds)

#print("✅ Credentials info:")
#print("  - token:", creds.token[:20] + "...")
#print("  - refresh_token:", bool(creds.refresh_token))
#print("  - client_id:", creds.client_id)
#print("  - quota_project_id:", creds.quota_project_id)
#print("  - valid:", creds.valid)
#print("  - expired:", creds.expired)
#print("  - scopes:", creds.scopes)

# Authorization?
about = drive_service.about().get(fields="user").execute()
print("✅ Authorization on behalf of:", about["user"]["displayName"], about["user"]["emailAddress"])


MY_FOLDER_ID = folder["5 news_lists"] # 5 new lists


API_KEY = os.environ.get("DEEPSEEK_API_KEY") 
#API_KEY = os.environ.get("OPENROUTER_API_KEY") 

if not API_KEY:
    raise ValueError("There is no API key (check the file or environment variable)!")

# Setting the endpoint and initial messages

#url = "https://api.perplexity.ai/chat/completions"
url = "https://api.deepseek.com/v1/chat/completions"
#url = "https://openrouter.ai/api/v1/chat/completions"


# Setting up models (to test and compare them)

model_lists = "deepseek/deepseek-chat-v3-0324"
model_bullets = "deepseek/deepseek-chat-v3-0324"
#model_bullets = "qwen/qwen-2.5-72b-instruct"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# gemini api key
#API_KEY = os.environ.get("GEMINI_API_KEY") # строка для запуска через workflow
#API_KEY = userdata.get('gemini_api_key') # строка для локального запуска
#genai.configure(api_key=API_KEY)
#model_obj = genai.GenerativeModel(
#    model_name="gemini-2.5-pro",
#    generation_config={
#        "response_mime_type": "application/json",  # ← важно!
#    }
#)


### TG Schedule bot

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") 

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. "
                       "Set them as environment variables or Colab secrets before running.")

def send_telegram_message(text: str,
                          parse_mode: str = "HTML",
                          timeout: int = 10,
                          escape_html: bool = False) -> dict:
    """
    Send a message using the Telegram Bot API.
    Returns the parsed JSON response on success, raises on failure.
    """
    if escape_html:
        text = html.escape(text)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        # use json=payload so requests sends proper JSON (Telegram accepts both form and JSON)
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()  # raises on HTTP 4xx/5xx
    except requests.RequestException as e:
        # You could log resp.text here if you keep resp in scope; but be careful not to leak secrets.
        raise RuntimeError(f"Failed to send Telegram message: {e}") from e

    data = resp.json()
    if not data.get("ok"):
        # Telegram sometimes returns 200 OK with {"ok": false, ...}
        raise RuntimeError(f"Telegram API returned an error: {data}")

    return data

def telegram_lists():
    link_news = f"https://drive.google.com/drive/folders/{folder['5 news_lists']}"
    text = f'Новостная записка обновлена. См. отчёты по <a href="{link_news}">ссылке</a>'
    send_telegram_message(text)

def telegram_bullets():
    link_bullets = f"https://drive.google.com/drive/folders/{folder['8 news_final']}"
    text = f'Готовы буллиты к новостной записке. См. отчёты по <a href="{link_bullets}">ссылке</a>'
    send_telegram_message(text)
    


### Functions for google drive

def find_file_in_drive(file_name: str, folder_id=folder["5 news_lists"]) -> str:
    """Look up a Drive file by exact name inside a folder.

    Args:
        file_name: Exact file name (e.g. ``world.json``).
        folder_id: Google Drive folder ID to search in; defaults to ``5 news_lists``.

    Returns:
        File ID if a matching file exists, otherwise ``None``.
    """
    try:
        resp = drive_service.files().list(
            q=(
                f"name = '{file_name}' "
                f"and '{folder_id}' in parents "
                f"and trashed = false"
            ),
            spaces="drive",
            fields="files(id, name)",
            pageSize=1
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Error accessing Drive API: {e}")

    items = resp.get("files", [])
    if items:
        return items[0]["id"]

    return None


def download_text_file(fid: str) -> str:
    """Download a Drive file by ID and return its contents as UTF-8 text.

    Args:
        fid: Google Drive file ID (from ``find_file_in_drive`` or similar).

    Returns:
        File body decoded as a string.
    """
    request = drive_service.files().get_media(fileId=fid)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return fh.getvalue().decode("utf-8")

def save_to_drive(file_name: str, data, my_folder=MY_FOLDER_ID, file_format: str = "json"):
    """Save a file to Google Drive. Supported formats: 'json' (default) and 'txt'.

    Args:
        file_name: File name.
        data: Data to write (dict or str).
        my_folder: Folder ID in Google Drive.
        file_format: File format: 'json' or 'txt'.
    """
    if file_format not in ("json", "txt"):
        raise ValueError("file_format должен быть 'json' или 'txt'")

    if file_format == "txt":
        content_bytes = data.encode("utf-8") if isinstance(data, str) else str(data).encode("utf-8")
        mime_type = "text/plain"
    else:
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        content_bytes = json_str.encode("utf-8")
        mime_type = "application/json"

    # Check if file already exists
    existing_file_id = None
    try:
        resp = drive_service.files().list(
            q=f"name = '{file_name}' and '{my_folder}' in parents and trashed = false",
            spaces="drive",
            fields="files(id, name)",
            pageSize=1
        ).execute()
        items = resp.get("files", [])
        if items:
            existing_file_id = items[0]["id"]
    except Exception as e:
        print("Warning: can't check if the file already exists:", e)

    fh = io.BytesIO(content_bytes)
    media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=False)

    if existing_file_id:
        try:
            # Try to update
            updated = drive_service.files().update(
                fileId=existing_file_id,
                media_body=media
            ).execute()
            print(f"File '{file_name}' updated (ID={updated['id']}).")
            return updated
        except HttpError as e:
            if e.resp.status == 403 and "storageQuotaExceeded" in str(e):
                print(f"⚠️ Quota error on update — deleting and recreating file '{file_name}'...")
                try:
                    drive_service.files().delete(fileId=existing_file_id).execute()
                    existing_file_id = None  # перейти к созданию
                except Exception as del_err:
                    print(f"Error deleting file '{file_name}': {del_err}")
                    raise
            else:
                print(f"Error updating file '{file_name}': {e}")
                raise

    # Create a new file
    file_metadata = {
        "name": file_name,
        "parents": [my_folder],
        "mimeType": mime_type
    }
    try:
        created = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink"
        ).execute()
        print(f"New file created: '{file_name}', (ID={created['id']}).")
        return created
    except Exception as e:
        print(f"Error creating new file '{file_name}': {e}")
        raise


### Functions for scrapping

## Defining and formatting dates
def get_last_dates(n_days=6, end_date=None):
    if end_date is None:
        end_date = date.today()
    return [end_date - timedelta(days=offset) for offset in range(n_days, -1, -1)]

def format_dates(dates_list, fmt="%Y-%m-%d"):
    return [d.strftime(fmt) for d in dates_list]

## Getting web page soup
def get_page_soup(url, headers=HEADERS, timeout=30):
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

## Getting web page soup using session to avoid 401
def get_proxy_page_soup(url, headers=HEADERS, proxies=proxies, timeout=30):
    # Use session to work with cookies and headers
    session = requests.Session()

    # First, make a GET on the main page to get the cookie and possibly tokens
    resp = session.get(url, headers=headers,
                        proxies=proxies
                        )
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

## Scrapers: Kommersant, Vedomosti, RBC, Agroinvestor, RG.ru, RIA, Autostat

# Kommersant scraper
def fetch_kom(rubrics, dates, output_file,
                   base_url_template="https://www.kommersant.ru/archive/rubric/{rubric}/day/{date}"):
    all_items = []
    seen_urls = set()

    for rubric in rubrics:
        for dt in dates:
            url = base_url_template.format(rubric=rubric, date=dt)
            print(f"Fetching Kommersant: {url}")
            try:
                soup = get_page_soup(url)
                scripts = soup.find_all("script", type="application/ld+json")

                for script in scripts:
                    raw = script.string
                    if not raw:
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    for entry in data.get("itemListElement", []):
                        title = entry.get("name") or entry.get("headline")
                        link = entry.get("url")
                        if title and link and link not in seen_urls:
                            seen_urls.add(link)
                            all_items.append({
                                "title": title,
                                "url": link,
                                "published_date": dt,
                            })
            except Exception as e:
                print(f"[ERROR] {e} when fetching {url}")

    save_to_drive(output_file, all_items, folder["1 news_jsons"]) # 1 news_jsons
    print(f"Saved Kommersant data to {output_file}")


# Vedomosti scraper
def fetch_ved(dates, output_file,
              base_url_template="https://www.vedomosti.ru/newspaper/{date}"):
    all_news = []
    for dt in dates:
        url = base_url_template.format(date=dt)
        print(f"Fetching Vedomosti: {url}")
        try:
            soup = get_page_soup(url)
            for item in soup.select("li.waterfall__item"):
                a = item.select_one("a.waterfall__item-title")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = a.get("href", "")
                full_url = href if href.startswith("http") else f"https://www.vedomosti.ru{href}"
                pub = dt.replace("/", "-") if isinstance(dt, str) else None
                all_news.append({"title": title, "url": full_url, "published_date": pub})
        except Exception as e:
            all_news.append({"error": str(e)})

    save_to_drive(output_file, all_news, folder["1 news_jsons"]) # 1 news_jsons
    print(f"Saved Vedomosti data to {output_file}")


# RBC scraper

def fetch_rbc(rubrics, dates, output_file,
              base_url_template="https://www.rbc.ru/{rubric}/?utm_source=topline"):

    ru_months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }
    today = date.today()
    collected = []

    for rubric in rubrics:
        page_url = base_url_template.format(rubric=rubric)
        print(f"Fetching RBC, {rubric}: {page_url}")
        soup = get_proxy_page_soup(page_url)

        anchors = soup.find_all("a", class_="news-feed__item")

        for idx, a in enumerate(anchors, start=1):
            # внутри anchor ищем span, у которого class содержит "news-feed__item__title"
            title_span = a.find(
                "span",
                class_=lambda c: c and "news-feed__item__title" in c
            )
            if not title_span:
                continue

            # Для даты: ищем span, у которого class содержит "news-feed__item__time"
            # или, если нет, "news-feed__item__date"
            date_span = a.find(
                "span",
                class_=lambda c: c and "news-feed__item__time" in c
            )
            if not date_span:
                date_span = a.find(
                    "span",
                    class_=lambda c: c and "news-feed__item__date" in c
                )
            if not date_span:
                continue

            title = title_span.get_text(strip=True)
            href = a.get("href", "").strip()
            if not href:
                continue

            full_url = href if href.startswith("http") else urljoin(page_url, href)

            # raw_date может быть вида "28 мая 17:52" или просто "17:52"
            raw_date = date_span.get_text(strip=True).replace("\xa0", " ").replace(",", "").strip()
            parts = raw_date.split()

            news_date = None
            if any(month in parts for month in ru_months):
                # формат ["28","мая","17:52"] или ["28","мая","2025","17:52"]
                try:
                    day = int(parts[0])
                except ValueError:
                    continue
                month_name = parts[1].lower()
                if month_name not in ru_months:
                    continue
                month = ru_months[month_name]
                year = today.year
                # если в parts[2] четвёрка цифр, считаем, что это год
                if len(parts) >= 3 and parts[2].isdigit() and len(parts[2]) == 4:
                    year = int(parts[2])
                try:
                    candidate = datetime.date(year, month, day)
                except ValueError:
                    continue
                # если эта дата уже в будущем, значит, год был прошлый
                if candidate > today:
                    candidate = datetime.date(year - 1, month, day)
                news_date = candidate
            else:
                # если нет названия месяца, значит raw_date = "HH:MM" сегодняшняя дата
                news_date = today

            if news_date not in dates:
                continue

            collected.append({
                "title": title,
                "url": full_url,
                "published_date": news_date.isoformat(),
            })

    # убираем дубликаты по URL
    unique = []
    seen = set()
    for item in collected:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    save_to_drive(output_file, unique, folder["1 news_jsons"]) # 1 news_jsons
    print(f"Saved RBC data to {output_file}")



# Agroinvestor scraper

def fetch_agro(dates, output_file,
               base_url="https://www.agroinvestor.ru/news/"):
    base_domain = "https://www.agroinvestor.ru"
    ru_months = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
        "мая": 5, "июня": 6, "июля": 7, "августа": 8,
        "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }

    def parse_once() -> list:
        soup = get_page_soup(base_url)
        if soup is None:
            print("❌ Failed to retrieve or parse the page.")
            return []

        news_list = []
        seen_urls = set()

        for block in soup.select("div.news__item-info"):
            a = block.find("a", class_="news__item-desc")
            if not a:
                continue
            href = a.get("href", "").strip()
            if not href:
                continue
            full_url = href if href.startswith("http") else base_domain + href
            if full_url in seen_urls:
                continue

            h3 = a.find("h3")
            if not h3:
                continue
            title = h3.get_text(strip=True)
            if not title:
                continue

            time_tag = block.find("time")
            if not time_tag:
                continue
            date_text = time_tag.get_text(strip=True).replace("\xa0", " ")
            parts = date_text.split()
            if len(parts) != 3:
                continue
            day_str, month_str, year_str = parts
            try:
                day = int(day_str)
                year = int(year_str)
            except ValueError:
                continue
            month_str = month_str.lower()
            if month_str not in ru_months:
                continue
            month = ru_months[month_str]
            try:
                news_date = date(year, month, day)
            except ValueError:
                continue

            if news_date not in dates:
                continue

            seen_urls.add(full_url)
            news_list.append({
                "title": title,
                "url": full_url,
                "published_date": news_date.isoformat(),
            })

        return news_list

    # первый проход
    news_list = parse_once()

    # если ничего не собрали — один ретрай
    if not news_list:
        print("⚠️ Agroinvestor: empty result, retrying once...")
        news_list = parse_once()

    save_to_drive(output_file, news_list, folder["1 news_jsons"]) # 1 news_jsons
    print(f"Saved {len(news_list)} Agroinvestor items to {output_file}")



# RG.ru scraper

def fetch_rg(rubrics, dates, output_file,
             base_url_template="https://rg.ru/tema/ekonomika/{rubric}"):
    all_news = []
    for rubric in rubrics:
        url = base_url_template.format(rubric=rubric)
        print(f"Fetching RG, {rubric}: {url}")
        soup = get_proxy_page_soup(url)
        for title_span in soup.find_all("span", class_="ItemOfListStandard_title__Ajjlf"):
            parent_a = title_span.find_parent("a")
            if not parent_a:
                continue
            href = parent_a.get("href", "").strip()
            if not href:
                continue
            full_url = href if href.startswith("http") else f"https://rg.ru{href}"

            date_a = title_span.find_previous("a", class_="ItemOfListStandard_datetime__GstJi")
            if not date_a:
                continue
            date_href = date_a.get("href", "").strip()
            parts = date_href.strip("/").split("/")  # ['2025','05','30',...]
            if len(parts) < 3:
                continue
            try:
                y, m, d = map(int, parts[:3])
                news_date = date(y, m, d)
            except ValueError:
                continue

            if news_date not in dates:
                continue

            all_news.append({
                "title": title_span.get_text(strip=True),
                "url": full_url,
                "published_date": news_date.isoformat(),
            })

    unique = []
    seen = set()
    for item in all_news:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    save_to_drive(output_file, unique, folder["1 news_jsons"]) # 1 news_jsons
    print(f"Saved RG data to {output_file}")


# RIA scraper

# RIA scraper

def fetch_ria(dates, output_file, base_url_template="https://ria.ru/economy/"):
    print("Fetching RIA: https://ria.ru/economy/")
    soup = get_page_soup(base_url_template)
    collected = []

    # Each news item has <a itemprop="url" href="..."></a>
    for a in soup.find_all("a", itemprop="url"):
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = href if href.startswith("http") else f"https://ria.ru{href}"

        # Next meta tag with itemprop="name" holds the title
        name_meta = a.find_next("meta", itemprop="name")
        if not name_meta:
            continue
        title = name_meta.get("content", "").strip()
        if not title:
            continue
        parsed = urlparse(full_url)
        parts = parsed.path.lstrip("/").split("/")
        if not parts or len(parts[0]) != 8 or not parts[0].isdigit():
            continue
        y, m, d = int(parts[0][:4]), int(parts[0][4:6]), int(parts[0][6:8])
        try:
            news_date = date(y, m, d)
        except ValueError:
            continue

        if news_date in dates:
            collected.append({
                "title": title,
                "url": full_url,
                "published_date": news_date.isoformat(),
            })

    unique = []
    seen = set()
    for item in collected:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    save_to_drive(output_file, unique, folder["1 news_jsons"]) # 1 news_jsons

    print(f"Saved RIA data to {output_file}")



# Autostat scraper

def fetch_autostat(dates, output_file,
                   rubrics=[21, 8, 13, 70, 71],
                   base_url_template="https://m.autostat.ru/news/themes-{rubric}/"):

    if dates is None:
        raise ValueError("Argument 'dates' must be provided as a list of datetime.date objects.")

    all_collected = []
    seen_urls = set()

    ru_months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }
    today = date.today()
    yesterday = today - timedelta(days=1)

    for rubric in rubrics:
        url = base_url_template.format(rubric=rubric)
        print(f"Fetching Autostat, {rubric}: {url}")
        soup = get_page_soup(url)
        if not soup:
            print(f"  (!) Failed to retrieve or parse page for rubric {rubric}")
            continue

        titles = soup.find_all("p", class_="Block-title")
        if not titles:
            print(f"    (!) No <p class='Block-title'> elements found on {url}")
            continue

        for title_p in titles:
            title = title_p.get_text(strip=True)
            if not title:
                continue

            link_a = title_p.find_parent("a", class_="Block-link")
            if not link_a:
                continue
            href = link_a.get("href", "").strip()
            if not href:
                continue
            full_url = urljoin("https://www.autostat.ru", href)

            date_p = title_p.find_next("p", class_="Block-date")
            if not date_p:
                continue
            date_text = date_p.get_text(strip=True)  # e.g. "Сегодня, 15:48" or "28 мая, 15:48"
            date_part = date_text.split(",")[0].strip().lower()

            if date_part == "сегодня":
                news_date = today
            elif date_part == "вчера":
                news_date = yesterday
            else:
                parts = date_part.split()
                if len(parts) != 2:
                    continue
                day_str, month_str = parts
                try:
                    day = int(day_str)
                    month = ru_months.get(month_str)
                    if not month:
                        continue
                    news_date = date(today.year, month, day)
                    if news_date > today:
                        news_date = date(today.year - 1, month, day)
                except Exception:
                    continue

            if news_date in dates and full_url not in seen_urls:
                all_collected.append({
                    "title": title,
                    "url": full_url,
                    "published_date": news_date.isoformat(),
                })
                seen_urls.add(full_url)

    save_to_drive(output_file, all_collected, folder["1 news_jsons"]) # 1 news_jsons

    print(f"Saved Autostat data to {output_file}")

#with open('agro.json', encoding='utf-8') as f:
#    data = json.load(f)
#print(json.dumps(data, ensure_ascii=False, indent=2))

# Parameters
days_before = 1
dates = get_last_dates(days_before)
dates_kom = format_dates(dates, fmt="%Y-%m-%d")
dates_ved = format_dates(dates, fmt="%Y/%m/%d")


rubrics_kom_econ = [3, 4, 40] # 3 - экономика, 4 - бизнеc,  40 - финансы (темы рубрик? для цен топливо в 4 https://www.kommersant.ru/theme/2913 )
rubrics_kom_world = [5] # 5 - мир 
rubrics_kom_markets = [41] # 41 - потребительский рынок

rubrics_rbc = ["economics", "business", "finances"]
rubrics_rg = ["politekonom", "industria", "business", "finansy", "kazna", "rabota", "pensii", "vnesh", "apk", "tovary", "turizm"]
rubrics_auto = [21, 8, 13, 70, 71]

#file creation may not work, there must be an empty blank file

# Fetching
fetch_kom(rubrics_kom_econ, dates_kom, "kom_econ.json")
fetch_kom(rubrics_kom_world, dates_kom, "kom_world.json")
fetch_kom(rubrics_kom_markets, dates_kom, "kom_markets.json")
fetch_ved(dates_ved, "ved.json")
fetch_rbc(rubrics_rbc, dates, "rbc.json")

try:
    fetch_agro(dates, "agro.json")
except Exception as e:

    pass
    
# fetch_rg(rubrics_rg, dates, "rg.json")
try:
    fetch_rg(rubrics_rg, dates, "rg.json")
except Exception as e:

    pass

fetch_ria(dates, "ria.json")
fetch_autostat(dates, "autostat.json", rubrics_auto)

# Kommersant, Vedomosti, RBC, Agroinvestor, RG.ru, RIA, Autostat
section_to_files = {
    "world": [
        "kom_world.json",
        "kom_econ.json",
        "ved.json",
        "rbc.json",
        "agro.json",
        #"rg.json",
        "ria.json"
    ],
    "rus": [
        "kom_econ.json",
        "ved.json",
        "rbc.json",
        "agro.json",
        #"rg.json",
        "ria.json"
    ],
    "prices": [
        "kom_markets.json",
        "kom_econ.json",
        "ved.json",
        "rbc.json",
        "agro.json",
        #"rg.json",
        "ria.json",
        "autostat.json"
    ]
}

# Prompts

## download prompts from drive

### news lists
file_id = find_file_in_drive("lists_world.txt", folder["0_prompts"]) # 0 prompts
try:
    lists_world = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    lists_world = ""

file_id = find_file_in_drive("lists_rus.txt", folder["0_prompts"])
try:
    lists_rus = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    lists_rus = ""

file_id = find_file_in_drive("lists_prices.txt", folder["0_prompts"])
try:
    lists_prices = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    lists_prices = ""

lists_prompts = {
        "world": lists_world,
        "rus": lists_rus,
        "prices": lists_prices
}

### prioritise
file_id = find_file_in_drive("prioritise_world.txt", folder["0_prompts"])
try:
    prioritise_world = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    prioritise_world = ""

file_id = find_file_in_drive("prioritise_rus.txt", folder["0_prompts"])
try:
    prioritise_rus = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    prioritise_rus = ""

file_id = find_file_in_drive("prioritise_prices.txt", folder["0_prompts"])
try:
    prioritise_prices = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    prioritise_prices = ""

prioritise_prompts = {
        "world": prioritise_world,
        "rus": prioritise_rus,
        "prices": prioritise_prices
}


### design


file_id = find_file_in_drive("design.txt", folder["0_prompts"])
try:
    prompt_design = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    prompt_design = ""


### top
file_id = find_file_in_drive("top_world.txt", folder["0_prompts"])
try:
    top_world = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    top_world = ""

file_id = find_file_in_drive("top_rus.txt", folder["0_prompts"])
try:
    top_rus = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    top_rus = ""

file_id = find_file_in_drive("top_prices.txt", folder["0_prompts"])
try:
    top_prices = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    top_prices = ""

top_prompts = {
        "world": top_world,
        "rus": top_rus,
        "prices": top_prices
}


### bullets
file_id = find_file_in_drive("bullets_world.txt", folder["0_prompts"])
try:
    bullets_world = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    bullets_world = ""

file_id = find_file_in_drive("bullets_rus.txt", folder["0_prompts"])
try:
    bullets_rus = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    bullets_rus = ""

file_id = find_file_in_drive("bullets_prices.txt", folder["0_prompts"])
try:
    bullets_prices = download_text_file(file_id)
except Exception as e:
    print("Error when downloading a file:", e)
    bullets_prices = ""

bullets_prompts = {
        "world": bullets_world,
        "rus": bullets_rus,
        "prices": bullets_prices
}

example = 'Пример верного оформления:\r\n1.\tРосстат зафиксировал стабилизацию выпуска базовых отраслей (day: 3) \r\nhttps://www.kommersant.ru/doc/7329366 \r\n2.\tСтроители просят смягчить правила распоряжения авансами (day: 1)\r\nhttps://www.rbc.ru/newspaper/2024/11/25/673f6abf9a7947de58a24847 \r\n3.\tВ Ульяновске открылся новый завод грузовиков Соллерс (day: 0) \r\nhttps://tass.ru/ekonomika/22497349 \r\n 4.\t Добыча газа за 9 месяцев выросла на 8% г/г в основном за счет Газпрома (day: 3) \r\nhttps://www.interfax.ru/business/994801 \r\n'

def extract_json(text: str):
    """Extract a valid JSON object or array from an arbitrary text string.

    The function tries several strategies, in order of reliability:

    1. Look for a fenced code block (``` ... ```) and parse its content.
    2. Find the longest balanced ``[...]`` or ``{...}`` fragment that
       parses as valid JSON.
    3. If the whole text is a JSON-encoded string, unescape it and try
       to parse the result.
    4. Brute-force scan: try every substring that starts with ``[``/``{``
       and ends with ``]``/``}`` (slow fallback for badly formatted output).

    Args:
        text: Raw string that may contain JSON mixed with other text
            (e.g. LLM response with explanations).

    Returns:
        Parsed Python object (``dict`` or ``list``) on success,
        ``None`` if no valid JSON fragment could be recovered.
    """
    if not isinstance(text, str):
        return None
    text = text.strip()
    # Шаг 1: Ищем кодовые блоки (наиболее надёжный способ)
    code_block_match = re.search(r"``````", text, re.IGNORECASE)
    if code_block_match:
        candidate = code_block_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            print(f"❌ JSON в кодовом блоке невалиден: {e}")
    # Шаг 2: Ищем самый длинный возможный JSON-массив или объект
    brackets = []
    for i, char in enumerate(text):
        if char in '[{':
            brackets.append((i, char))
        elif char in ']}':
            brackets.append((i, char))
    stack = []
    ranges = []
    for pos, char in brackets:
        if char in '[{':
            stack.append((pos, char))
        elif char == ']' and stack and stack[-1][1] == '[':
            start, _ = stack.pop()
            ranges.append((start, pos))
        elif char == '}' and stack and stack[-1][1] == '{':
            start, _ = stack.pop()
            ranges.append((start, pos))
    ranges.sort(key=lambda x: x[1] - x[0], reverse=True)
    for start, end in ranges:
        candidate = text[start:end+1]
        try:
            result = json.loads(candidate)
            if isinstance(result, (dict, list)) and len(result) >= 0:
                return result
        except json.JSONDecodeError:
            continue
    # Шаг 3: Фолбэк — попытка убрать экранирование
    if text.startswith('"') and text.endswith('"'):
        try:
            unescaped = text[1:-1].encode().decode('unicode_escape')
            if (unescaped.startswith('{') and unescaped.endswith('}')) or \
               (unescaped.startswith('[') and unescaped.endswith(']')):
                return json.loads(unescaped)
        except Exception:
            pass
    # Шаг 4: Крайний фолбэк — перебор подстрок (медленно)
    for start in range(len(text)):
        if text[start] not in '[{':
            continue
        for end in range(len(text), start, -1):
            if text[end-1] not in ']}':
                continue
            fragment = text[start:end]
            if len(fragment) < 3:
                continue
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                continue
    return None


def _normalize_url_key(u: str) -> str:
    """Normalize a URL so it can be used as a dictionary lookup key.

    Trims surrounding whitespace and strips a single trailing slash, so
    that ``https://site.ru/page`` and ``https://site.ru/page/`` map to the
    same key.

    Args:
        u: Raw URL string (or any value).

    Returns:
        Normalized URL, or an empty string for falsy/non-string input.
    """
    if not u or not isinstance(u, str):
        return ""
    u = u.strip()
    if len(u) > 1 and u.endswith("/"):
        u = u.rstrip("/")
    return u


def _published_date_map_from_feed(news_data) -> dict:
    """Build a ``{url: published_date}`` map from a raw news feed JSON.

    Used to restore the original publication date of a news item after the
    LLM has filtered/reformatted the feed (the model may drop the
    ``published_date`` field).

    Args:
        news_data: List of news dicts coming straight from a scraper file
            (each dict typically has ``url`` and ``published_date`` keys).

    Returns:
        Dict mapping normalized URL (see ``_normalize_url_key``) to the
        ``published_date`` string (``YYYY-MM-DD``).
    """
    out = {}
    rows = news_data if isinstance(news_data, list) else []
    for row in rows:
        if not isinstance(row, dict) or "error" in row:
            continue
        u = row.get("url")
        p = row.get("published_date")
        if u and p:
            out[_normalize_url_key(u)] = p
    return out


def create_news_lists(section):
    """Build a per-section news list by filtering raw scraper feeds with an LLM.

    For the given section (``"world"``, ``"rus"`` or ``"prices"``) the
    function:

    1. On any weekday except Saturday, loads the previously saved
       ``<section>.json`` from the ``2 4 new_lists_json`` Drive folder so
       results accumulate over the week. On Saturday it starts from an
       empty list.
    2. Iterates over the scraper feeds declared in
       ``section_to_files[section]`` (Kommersant, Vedomosti, RBC,
       Agroinvestor, RIA, Autostat, ...), loads each JSON from Drive and
       sends it to the chat completions API together with the
       section-specific prompt from ``lists_prompts[section]``.
    3. Parses the model response (expected to be a JSON list of
       ``{title, url}``), deduplicates by URL against items already kept,
       and re-attaches the original ``published_date`` from the raw feed
       via ``_published_date_map_from_feed``.
    4. Saves the combined result back to Drive as ``<section>.json``
       in the ``2 4 new_lists_json`` folder.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"`` — determines
            which feeds and which prompt are used.

    Returns:
        None. The function logs progress and writes the result to Drive.
    """
    current_weekday_num = datetime.today().weekday()

    # Если сегодня не суббота — пробуем прочитать уже сохранённый <section>.json
    if current_weekday_num != 5:  # 5 = Saturday
        try:
            existing_id = find_file_in_drive(f"{section}.json", folder["2 4 new_lists_json"]) # 2 4 news lists json 
            existing_text = download_text_file(existing_id)
            try:
                combined_items = json.loads(existing_text)
            except json.JSONDecodeError:
                combined_items = []
        except Exception:
            combined_items = []
    else:
        combined_items = []

    # Обновляем seen_urls и подготавливаем set для сохранённых URL
    seen_urls = {item["url"] for item in combined_items if isinstance(item, dict) and "url" in item}

    # Список файлов и промпт для секции
    json_files = section_to_files[section]
    prompt_list = lists_prompts.get(section, "")

    for json_filename in json_files:
        base_name, ext = os.path.splitext(json_filename)
        if ext.lower() != ".json":
            print(f"Пропускаем '{json_filename}', т.к. не .json-файл.")
            continue

        # Загружаем JSON-файл из Google Drive
        try:
            file_id = find_file_in_drive(json_filename, folder["1 news_jsons"]) # 1 news_jsons
            raw_text = download_text_file(file_id)
        except FileNotFoundError:
            print(f"Файл '{json_filename}' не найден. Пропускаем.")
            continue
        except Exception as e:
            print(f"Ошибка при скачивании '{json_filename}': {e}. Пропускаем.")
            continue

        if not isinstance(raw_text, str) or not raw_text.strip():
            print(f"JSON '{json_filename}' пустой. Пропускаем.")
            continue

        try:
            news_data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            print(f"Ошибка JSON в '{json_filename}': {e}. Пропускаем.")
            continue

        if isinstance(news_data, (list, dict)) and len(news_data) == 0:
            print(f"JSON '{json_filename}' содержит пустую структуру. Пропускаем.")
            continue

        rows_for_dates = (
            news_data
            if isinstance(news_data, list)
            else ([news_data] if isinstance(news_data, dict) else [])
        )
        published_map = _published_date_map_from_feed(rows_for_dates)

        # Формируем prompt для модели
        news_json_string = json.dumps(news_data, ensure_ascii=False, indent=2)
        prompt_parts = [
            str(prompt_list),
            str(news_json_string)
        ]

        # Запрос к model API
        try:
            payload = {
                "model": model_lists,
                "messages": [
                    {"role": "system", "content": "Отвечай строго в формате JSON. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
                    {"role": "user", "content": "\n".join(prompt_parts)}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()


        # # Запрос к Perplexity API
        # try:
        #     payload = {
        #         "model": "sonar-pro",
        #         "messages": [
        #             {"role": "system", "content": "Отвечай строго в формате JSON. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
        #             {"role": "user", "content": "\n".join(prompt_parts)}
        #         ],
        #         "temperature": 0.2,
        #         "response_mime_type": "application/json",
        #         "disable_search": True
        #     }
        #     response = requests.post(url, headers=headers, json=payload)
        #     response.raise_for_status()
        #     result = response.json()



            # Проверка, что модель вернула контент
            choices = result.get("choices")
            if not choices or not choices[0].get("message", {}).get("content"):
                print(f"Модель не вернула ответ для '{json_filename}'. Пропускаем.")
                continue

            assistant_json_str = choices[0]["message"]["content"]

            # Парсим JSON из строки (ожидается список словарей с ключами 'url' и 'title')
            try:
                items = json.loads(assistant_json_str)
            except json.JSONDecodeError as e:
                print(f"Ответ модели для '{json_filename}' не содержит валидный JSON: {e}")
                continue

            # Приводим к списку, если словарь
            if isinstance(items, dict):
                items = [items]

            if not isinstance(items, list):
                print(f"Ответ модели для '{json_filename}' вернул не список, а {type(items)}. Пропускаем.")
                continue

            # Фильтруем и добавляем новости; дата публикации берётся из сырого фида по URL
            for entry in items:
                url_val = entry.get("url")
                title_val = entry.get("title")
                if not title_val or not url_val or url_val in seen_urls:
                    continue
                seen_urls.add(url_val)
                pub = published_map.get(_normalize_url_key(url_val)) or entry.get("published_date")
                combined_items.append({
                    "title": title_val,
                    "url": url_val,
                    "published_date": pub,
                })

        except Exception as e:
            print(f"Ошибка при вызове модели для '{json_filename}': {e}. Пропускаем.")
            continue

    if not combined_items:
        print(f"For section '{section}', zero JSONs were successfully processed.")
        return

    # Сохраняем объединённый результат (published_date — дата публикации из фида, если была)
    output_file = f"{section}.json"
    save_to_drive(output_file, combined_items, my_folder=folder["2 4 new_lists_json"])
    print(f"✅ create_news_lists({section}) — успешно обработан и сохранён файл.")

    if not combined_items:
        print(f"For section '{section}', zero JSONs were successfully processed.")
        return

    # Сохраняем объединённый результат
    output_file = f"{section}.json"
    save_to_drive(output_file, combined_items, my_folder=folder["2 4 new_lists_json"])
    print(f"✅ create_news_lists({section}) — успешно обработан и сохранён файл.")


# Kommersant, Vedomosti, RBC, Agroinvestor, RG.ru, RIA, Autostat

create_news_lists("world")
time.sleep(60)
create_news_lists("rus")
time.sleep(60)
create_news_lists("prices")

def prioritise(section):
    """Re-rank the section news list with an LLM and keep the top 40 items.

    Loads ``<section>.json`` from the ``2 4 new_lists_json`` Drive folder,
    feeds it together with the section-specific prompt from
    ``prioritise_prompts[section]`` to the DeepSeek chat API, and expects
    the model to return a JSON array of ``{title, url, published_date, grade}``.

    The model output is:

    * stored as-is in the ``3 news_lists_json_grade`` folder (debug copy
      with grades);
    * sorted by ``grade`` descending and trimmed to 40 items
      (or simply truncated to 40 if grades are missing);
    * stripped to ``{title, url, published_date}`` and written back to
      ``<section>.json`` in the ``2 4 new_lists_json`` folder, replacing
      the previous list.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.

    Returns:
        None. Logs progress and writes results to Drive; aborts early on
        any I/O or model error.
    """
    file_name = f"{section}.json"
    folder_id = folder["2 4 new_lists_json"] # 2 4 new_lists_json
    temp_folder_id = folder["3 news_lists_json_grade"] # 3 grade
    combined_items = []
    # Загружаем файл с новостями
    try:
        file_id = find_file_in_drive(file_name, folder_id)
        news_list_raw = download_text_file(file_id)
    except FileNotFoundError:
        print(f"❌ Файл {file_name} не найден в папке {folder_id}.")
        return
    except Exception as e:
        print(f"❌ Ошибка при загрузке файла {file_name}: {e}")
        return
    if not news_list_raw.strip():
        print(f"❌ Файл {file_name} пустой.")
        return
    # Готовим prompt
    prompt_prioritise = prioritise_prompts.get(section, "")
    prompt_text = "\n".join([str(prompt_prioritise), news_list_raw])
    print(prompt_text[:3000])
    
    try:
        payload = {
            "model": model_bullets,
            "messages": [
               {"role": "system", "content": "Отвечай строго в формате JSON. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
                {"role": "user", "content": prompt_text}
             ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
    
    # try:
    #     payload = {
    #         "model": "sonar-pro",
    #         "messages": [
    #             {"role": "system", "content": "Отвечай строго в формате JSON. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
    #             {"role": "user", "content": prompt_text}
    #         ],
    #         "temperature": 0.2,
    #         "response_mime_type": "application/json",
    #         "disable_search": True
    #     }
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        
        
        # Проверка ответа
        choices = result.get("choices")
        if not choices or not choices[0].get("message", {}).get("content"):
            print(f"❌ Модель не вернула ответ для '{file_name}'.")
            return
        
        assistant_json_str = choices[0]["message"]["content"]
        # Отладка - вывод ответа модели перед парсингом JSON
        print("DEBUG: Ответ модели (первые 3000 символов):")
        print(assistant_json_str[:3000])
        
        try:
            items = json.loads(assistant_json_str)
        except json.JSONDecodeError as e:
            print(f"❌ Ответ модели для '{file_name}' не содержит валидный JSON: {e}")
            return
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            print(f"❌ Ответ модели для '{file_name}' вернул не список, а {type(items)}.")
            return
        
        # Сохраняем полный ответ в отдельную папку
        save_to_drive(file_name, items, temp_folder_id, file_format="json")
        # Обработка с grade
        if all(isinstance(entry, dict) and "grade" in entry for entry in items):
            items_sorted = sorted(items, key=lambda x: x["grade"], reverse=True)
            items_top40 = items_sorted[:40]
            combined_items = [
                {
                    "title": e.get("title"),
                    "url": e.get("url"),
                    "published_date": e.get("published_date"),
                }
                for e in items_top40 if e.get("url")
            ]
        else:
            # Нет grade — берем первые 40 записей с валидным url
            combined_items = [
                {
                    "title": e.get("title"),
                    "url": e.get("url"),
                    "published_date": e.get("published_date"),
                }
                for e in items if e.get("url")
            ][:40]
    except Exception as e:
        print(f"❌ Ошибка при вызове модели для '{file_name}': {e}")
        return
    # Сохраняем итоговый результат в исходную папку
    save_to_drive(file_name, combined_items, folder_id, file_format="json")
    print(f"✅ prioritise({section}) — сохранён корректный JSON.")


prioritise("world")
time.sleep(60)
prioritise("rus")
time.sleep(60)
prioritise("prices")

def design_wo_llm(section):
    """Render the section news list as a plain numbered text file (no LLM).

    Loads ``<section>.json`` from the ``2 4 new_lists_json`` Drive folder
    and formats every item as::

        N.\\t<title> (published: <published_date>)
        <url>

    Items without ``title`` or ``url`` are skipped. The resulting text is
    saved as ``<section>.txt`` in the ``5 news_lists`` Drive folder. This
    is the cheap fallback used in the daily pipeline; ``design`` is the
    LLM-based variant.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.

    Returns:
        None. Writes the formatted ``.txt`` to Drive.
    """
    file_name_json = f"{section}.json"
    try:
        file_id = find_file_in_drive(file_name_json, folder["2 4 new_lists_json"]) # 2 4 new_lists_json
        news_list_raw = download_text_file(file_id)
    except FileNotFoundError:
        print(f"Файл {file_name_json} не найден в папке.")
        return
    except Exception as e:
        print(f"Ошибка при загрузке файла {file_name_json}: {e}")
        return
    # Парсим входной JSON
    try:
        news_items = json.loads(news_list_raw)
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON: {e}")
        return
    # Формируем нумерованный список с датой публикации (или устаревшим полем day)
    formatted_lines = []
    for i, item in enumerate(news_items, 1):
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        pub = item.get("published_date")
        #day = item.get("day")
        if not title or not url:
            continue
        if pub:
            line = f"{i}.\t{title} (published: {pub})\n{url}"
        elif day is not None:
            line = f"{i}.\t{title} (day: {day})\n{url}"
        else:
            line = f"{i}.\t{title}\n{url}"
        formatted_lines.append(line)

    # Склеиваем результаты с переводом строки между ними
    result_text = "\r\n".join(formatted_lines) + "\r\n" if formatted_lines else ""
    file_name_txt = f"{section}.txt"
    save_to_drive(file_name_txt, result_text, folder["5 news_lists"], file_format="txt") # 5 news_lists
    print(f"✅ design({section}) — успешно сохранён файл с текстом.")


def design(section):
    """Render the section news list as a formatted text file via the LLM.

    LLM-based counterpart of ``design_wo_llm``. Loads ``<section>.json``
    from the ``2 4 new_lists_json`` Drive folder and asks the DeepSeek
    chat API to produce a nicely formatted numbered list using the
    ``prompt_design`` template plus the ``example`` reference layout.

    The model reply is saved as ``<section>.txt`` in the
    ``5 news_lists`` folder.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.

    Returns:
        None. Logs progress and writes the result to Drive; aborts on any
        I/O or model error.
    """
    file_name_json = f"{section}.json"
    try:
        file_id = find_file_in_drive(file_name_json, folder["2 4 new_lists_json"])
        news_list_raw = download_text_file(file_id)
    except FileNotFoundError:
        print(f"Файл {file_name_json} не найден в папке.")
        return
    except Exception as e:
        print(f"Ошибка при загрузке файла {file_name_json}: {e}")
        return
    raw_parts = [prompt_design, example, news_list_raw]
    prompt_parts = []
    for part in raw_parts:
        if isinstance(part, list):
            prompt_parts.append("\n".join(part))
        else:
            prompt_parts.append(str(part))
    prompt_text = "\n".join(prompt_parts)
    try:
        payload = {
            "model": model_lists,
            "messages": [
                {"role": "system", "content": "Отвечай лаконично и информативно. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.7
        }
    
    
    
        # payload = {
        #     "model": "sonar-pro",
        #     "messages": [
        #         {"role": "system", "content": "Отвечай лаконично и информативно. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
        #         {"role": "user", "content": prompt_text}
        #     ],
        #     "temperature": 0.7,
        #     "disable_search": True
        # }


        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        choices = result.get("choices")
        if not choices or not choices[0].get("message", {}).get("content"):
            print(f"Модель не вернула ответ для '{file_name_json}'.")
            return
        assistant_text = choices[0]["message"]["content"]
        file_name_txt = f"{section}.txt"
        save_to_drive(file_name_txt, assistant_text, folder["5 news_lists"], file_format="txt") # 5 news lists 
        print(f"✅ design({section}) — успешно сохранён файл с текстом.")
    except Exception as e:
        print(f"Ошибка при вызове модели для '{file_name_json}': {e}")
        return

for section in ["world", "rus", "prices"]:
    try:
        design_wo_llm(section)
    except Exception as e:
        print(f"⚠️ Ошибка в design_wo_llm для '{section}': {e}. Пробую через LLM.")
        design(section)
        time.sleep(60)
telegram_lists()


class NewsItem(BaseModel):
    """Pydantic schema for a single top-news item with its theme.

    Attributes:
        theme: Short topical label assigned by the LLM
            (e.g. ``"Регулирование"``, ``"Топливо"``).
        title: News headline in Russian, without the source name.
        url: Direct link to the article.
    """

    theme: str
    title: str
    url: str

def choose_top_urls(section):
    """Pick the 4 most important themes from the section list using the LLM.

    Loads ``<section>.json`` from ``2 4 new_lists_json`` and asks the
    DeepSeek chat API (with the ``top_prompts[section]`` prompt) to
    group the news into at most 4 themes with up to 3 articles each.
    Every returned item is validated against the ``NewsItem`` Pydantic
    model.

    Valid items are saved as ``<section>.json`` in the ``6 news_top``
    Drive folder. Invalid items are silently skipped with a warning.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.

    Returns:
        None. Writes a JSON file of ``{theme, title, url}`` entries to
        Drive; aborts on any I/O or model error.
    """
    file_name = f"{section}.json"
    folder_id = folder["2 4 new_lists_json"] # 2 4 
    try:
        file_id = find_file_in_drive(file_name, folder_id)
        news_list_raw = download_text_file(file_id)
    except FileNotFoundError:
        print(f"❌ Файл {file_name} не найден в папке {folder_id}.")
        return
    except Exception as e:
        print(f"❌ Ошибка при загрузке файла {file_name}: {e}")
        return
    if not news_list_raw.strip():
        print(f"❌ Файл {file_name} пустой.")
        return

    prompt_top = top_prompts.get(section, "")
    system_content = (
        "Анализируй предоставленный список новостей и выдели 4 ключевые темы. Верни список объектов с полями theme, title, url для каждой новости."
    )
#     system_content = (
#     "Анализируй предоставленный список новостей и выдели 4 ключевые темы. "
#     "Верни JSON массив объектов с полями theme, title, url для каждой новости. "
#     "Формат: [{\"theme\": \"...\", \"title\": \"...\", \"url\": \"...\"}, ...]"
# )




    prompt_text = "\n".join([str(prompt_top), news_list_raw])

    try:
        payload = {
            "model": model_bullets, 
            "messages": [
                {
                    "role": "system",
                    "content": system_content
                },
                {
                    "role": "user",
                    "content": prompt_text
                }
            ],
            "temperature": 0.2,
            "response_format": {
                "type": "json_object"
            }
        }

        # payload = {
        #     "model": "sonar-pro", 
        #     "messages": [
        #         {
        #             "role": "system",
        #             "content": system_content
        #         },
        #         {
        #             "role": "user",
        #             "content": prompt_text
        #         }
        #     ],
        #     "temperature": 0.2,
        #     "disable_search": True,
        #     "response_format": {
        #         "type": "json_schema",
        #         "json_schema": {
        #             "schema": {
        #                 "type": "array",
        #                 "items": NewsItem.model_json_schema()
        #             }
        #         }
        #     }
        # }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        choices = result.get("choices")
        if not choices:
            print("❌ В ответе API нет поля 'choices'.")
            return
        
        content = choices[0]["message"]["content"]
        if not content:
            print("❌ Модель вернула пустой ответ.")
            return
            
        # Парсим JSON и валидируем через Pydantic
        import json
        data = json.loads(content)
        
        # Валидируем каждый элемент через Pydantic
        valid_output = []
        for item_data in data:
            try:
                news_item = NewsItem.model_validate(item_data)
                valid_output.append({
                    "theme": news_item.theme,
                    "title": news_item.title,
                    "url": news_item.url
                })
            except Exception as e:
                print(f"⚠️ Пропускаем невалидный элемент: {e}")
                continue
                
        if not valid_output:
            print("❌ Итоговый JSON пуст.")
            return
            
    except Exception as e:
        print(f"❌ Ошибка при вызове модели для '{file_name}': {e}")
        return
    
    output_folder_id = folder["6 news_top"] # 6 news top
    save_to_drive(file_name, valid_output, output_folder_id, file_format="json")
    print(f"✅ choose_top_urls({section}) — сохранён корректный JSON с новостями и темами.")


if datetime.today().weekday() == 3: ################### 3 - Thu
    choose_top_urls("world")
    time.sleep(60)
    choose_top_urls("rus")
    time.sleep(60)
    choose_top_urls("prices")

def read_top_urls(section, max_chars=3000):
    """Download and extract the article body for every top URL of a section.

    Reads the file produced by ``choose_top_urls`` from the
    ``6 news_top`` Drive folder (``<section>.json``). For each item it
    fetches the article HTML, runs ``extract_main_text`` to keep only
    meaningful paragraphs, and stores ``{title, url, theme, text}`` in
    ``<section>.json`` inside the ``7 news_top_texts`` folder.

    Errors on individual URLs are logged and skipped — the rest of the
    items continue to be processed.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.
        max_chars: Maximum length of the extracted article body
            (truncated on the last whitespace before the limit).

    Returns:
        None. Writes the per-section text dump to Drive.
    """
    def extract_main_text(soup, max_chars=3000, min_paragraph_len=50, max_paragraphs=5):
        """Extract a short readable summary from a parsed HTML page.

        Iterates over ``<p>`` tags and keeps the first ``max_paragraphs``
        whose text is at least ``min_paragraph_len`` characters long and
        is not obviously a cookie/subscription/advertising notice. The
        kept paragraphs are joined with spaces and truncated to
        ``max_chars`` (cut on the last whitespace boundary).

        Args:
            soup: ``BeautifulSoup`` object built from the article page.
            max_chars: Hard cap on the returned text length.
            min_paragraph_len: Minimum length of a paragraph to be kept.
            max_paragraphs: Maximum number of paragraphs to collect.

        Returns:
            A single string with the cleaned article excerpt.
        """
        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(" ", strip=True)
            if len(text) < min_paragraph_len:
                continue
            low = text.lower()
            # Фильтр по рекламе/подпискам
            if any(word in low for word in ["cookie", "subscribe", "advert", "реклама", "подпишитесь"]):
                continue
            paragraphs.append(text)
            if len(paragraphs) >= max_paragraphs:
                break
        combined_text = " ".join(paragraphs)
        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars].rsplit(" ", 1)[0] + "..."
        return combined_text

    # Имя файла с топ ссылками для секции, например "world.json"
    file_name = f"{section}.json"

    # Находим ID файла в папке с топами
    file_id = find_file_in_drive(file_name, folder_id=folder["6 news_top"]) # 6 news top

    # Скачиваем содержимое файла — список словарей с title, url и темой
    json_text = download_text_file(file_id)
    try:
        items = json.loads(json_text)
    except Exception as e:
        print(f"Ошибка чтения JSON файла {file_name}: {e}")
        return

    results = []
    for item in items:
        url = item.get("url") or item.get("URL")
        title = item.get("title", "")
        theme = item.get("theme") or item.get("тема") or "undefined"
        if not url:
            continue
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.text, "html.parser")
            page_text = extract_main_text(soup, max_chars=max_chars)
            results.append({
                "title": title,
                "url": url,
                "theme": theme,
                "text": page_text
            })
        except Exception as e:
            print(f"Ошибка при обработке {url}: {e}")

    # Сохраняем результат в другую папку с текстами
    save_to_drive(
        file_name,
        results,
        my_folder=folder["7 news_top_texts"] , # 7 news_top_texts
        file_format="json"
    )
    print(f"{section}: сохранено {len(results)} ссылок с текстами.")

if datetime.today().weekday() == 3: ##################3 - Thu
    read_top_urls("world")
    read_top_urls("rus")
    read_top_urls("prices")


def create_bullets(section):
    """Generate the final analytical bullet points for a section via the LLM.

    Loads ``<section>.json`` (top articles with their bodies) from the
    ``7 news_top_texts`` Drive folder, sends it together with the
    ``bullets_prompts[section]`` prompt to the DeepSeek chat API, and
    writes the model's plain-text reply to
    ``report_<section>.txt`` in the ``8 news_final`` folder.

    Args:
        section: One of ``"world"``, ``"rus"``, ``"prices"``.

    Returns:
        None. Logs progress and saves the bullets file to Drive; aborts
        on any I/O or model error.
    """
    list_file = f"{section}.json"
    try:
        file_id = find_file_in_drive(list_file, folder["7 news_top_texts"]) # 7 news_top_texts
        list_content = download_text_file(file_id)
    except Exception as e:
        print(f"Ошибка загрузки файла {list_file}: {e}")
        return

    # Если пришёл JSON, делаем красиво (отступы для читаемости)
    try:
        parsed_json = json.loads(list_content)
        pretty_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        pretty_json = str(list_content)

    prompt_bullets = bullets_prompts.get(section, "")
    prompt_text = "\n".join([str(prompt_bullets), pretty_json])

    try:
        payload = {
            "model": model_bullets,
            "messages": [
                {"role": "system", "content": "Ты — профессиональный макроэкономический аналитик Департамента денежно-кредитной политики ЦБ РФ. Твоя задача — подготовить краткие, точные и фактологические буллиты на основе предоставленных новостей, которые будут использованы в еженедельной аналитической записке для руководства банка. Будь предельно объективен, избегай интерпретаций и сосредоточься только на фактах из предоставленных текстов. Твоя работа напрямую влияет на принятие решений по денежно-кредитной политике."},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.5,
        }


        # payload = {
        #     "model": "sonar-pro",
        #     "messages": [
        #         {"role": "system", "content": "Отвечай лаконично и информативно."},
        #         {"role": "user", "content": prompt_text}
        #     ],
        #     "temperature": 0.7,
        # }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        choices = result.get("choices")
        if not choices or not choices[0].get("message", {}).get("content"):
            print(f"Модель не вернула ответ для {section}.")
            return

        assistant_text = choices[0]["message"]["content"]

        file_name = f"report_{section}.txt"
        save_to_drive(file_name, assistant_text, my_folder=folder["8 news_final"], file_format="txt")

         # Сохраняем в локальный файл для архивации
        local_filename = f"report_{section}.txt"
        with open(local_filename, "w", encoding="utf-8") as f_local:
            f_local.write(assistant_text)
        print(f"Локально сохранено: {local_filename}")
        
        print(f"{section}: буллиты успешно записаны.")

    except Exception as e:
        print(f"Ошибка при вызове модели для {section}: {e}")
        return

if datetime.today().weekday() == 3: ###################3 - Thu
    create_bullets("world")
    time.sleep(60)
    create_bullets("rus")
    time.sleep(60)
    create_bullets("prices")
    telegram_bullets()  
