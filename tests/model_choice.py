### In this script, we compare different models to find the best one

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


# Folders configuration - load from environment variable as JSON string
#FOLDERS_JSON = os.environ.get("FOLDERS_SANDBOX")
print(FOLDERS_JSON)
if not FOLDERS_JSON:
    raise ValueError("FOLDERS_JSON environment variable is required!")
try:
    folder = json.loads(FOLDERS_JSON)
except json.JSONDecodeError as e:
    raise ValueError(f"Invalid FOLDERS_JSON format: {e}")

if not folder:
    raise ValueError("FOLDERS_JSON is empty!")
print(folder)
print(folder['8 news_final'])


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


encoded_token = os.environ.get("GOOGLE_TOKEN_B64")
if not encoded_token:
    raise RuntimeError("OAuth токен не найден. Убедитесь, что переменная окружения GOOGLE_TOKEN_B64 задана.")

token_bytes = base64.b64decode(encoded_token)
token_info = json.loads(token_bytes.decode("utf-8"))

creds = Credentials.from_authorized_user_info(token_info, scopes=["https://www.googleapis.com/auth/drive"])

if creds.expired and creds.refresh_token:
    creds.refresh(Request())
    
drive_service = build("drive", "v3", credentials=creds)

print("✅ Credentials info:")
print("  - token:", creds.token[:20] + "...")
print("  - refresh_token:", bool(creds.refresh_token))
print("  - client_id:", creds.client_id)
print("  - quota_project_id:", creds.quota_project_id)
print("  - valid:", creds.valid)
print("  - expired:", creds.expired)
print("  - scopes:", creds.scopes)
# Кто залогинен?
about = drive_service.about().get(fields="user").execute()
print("✅ Авторизация от имени:", about["user"]["displayName"], about["user"]["emailAddress"])


MY_FOLDER_ID = folder["5 news_lists"] # 5 new lists

API_KEY = os.environ.get("OPENROUTER_API_KEY") 

if not API_KEY:
    raise ValueError("Нет API-ключа (проверьте файл или переменную окружения)!")

# Задаем эндпоинт и исходные сообщения
url = "https://openrouter.ai/api/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

### Functions for google drive

def find_file_in_drive(file_name: str, folder_id = folder["5 news_lists"]) -> str: # 5 new lists 
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

    #raise FileNotFoundError(f"File '{file_name}' not found in folder {folder_id}.")


def download_text_file(fid: str) -> str:
    request = drive_service.files().get_media(fileId=fid)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return fh.getvalue().decode("utf-8")

def save_to_drive(file_name: str, data, my_folder=MY_FOLDER_ID, file_format: str = "json"):
    """
    Сохраняет файл на Google Drive. Поддерживаются форматы: 'json' (по умолчанию) и 'txt'.

    :param file_name: Имя файла.
    :param data: Данные для записи (dict или str).
    :param my_folder: ID папки в Google Drive.
    :param file_format: Формат файла: 'json' или 'txt'.
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

    # Ищем, существует ли уже файл
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
            # Пытаемся обновить
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
                    print(f"Ошибка при удалении файла '{file_name}': {del_err}")
                    raise
            else:
                print(f"Ошибка при обновлении файла '{file_name}': {e}")
                raise

    # Создание нового файла
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
        print(f"Ошибка при создании нового файла '{file_name}': {e}")
        raise


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
    # Используем сессию для работы с cookies и заголовками
    session = requests.Session()

    # Сначала делаем GET на главную страницу, чтобы получить cookie и возможно токены
    resp = session.get(url, headers=headers,
                        proxies=proxies
                        )
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

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

## Prompts

## download prompts from drive

### news lists
file_id = find_file_in_drive("lists_world.txt", folder["0_prompts"]) # 0 prompts
try:
    lists_world = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    lists_world = ""

file_id = find_file_in_drive("lists_rus.txt", folder["0_prompts"])
try:
    lists_rus = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    lists_rus = ""

file_id = find_file_in_drive("lists_prices.txt", folder["0_prompts"])
try:
    lists_prices = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
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
    print("Ошибка при скачивании файла:", e)
    prioritise_world = ""

file_id = find_file_in_drive("prioritise_rus.txt", folder["0_prompts"])
try:
    prioritise_rus = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    prioritise_rus = ""

file_id = find_file_in_drive("prioritise_prices.txt", folder["0_prompts"])
try:
    prioritise_prices = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
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
    print("Ошибка при скачивании файла:", e)
    prompt_design = ""


### top
file_id = find_file_in_drive("top_world.txt", folder["0_prompts"])
try:
    top_world = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    top_world = ""

file_id = find_file_in_drive("top_rus.txt", folder["0_prompts"])
try:
    top_rus = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    top_rus = ""

file_id = find_file_in_drive("top_prices.txt", folder["0_prompts"])
try:
    top_prices = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
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
    print("Ошибка при скачивании файла:", e)
    bullets_world = ""

file_id = find_file_in_drive("bullets_rus.txt", folder["0_prompts"])
try:
    bullets_rus = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    bullets_rus = ""

file_id = find_file_in_drive("bullets_prices.txt", folder["0_prompts"])
try:
    bullets_prices = download_text_file(file_id)
except Exception as e:
    print("Ошибка при скачивании файла:", e)
    bullets_prices = ""

bullets_prompts = {
        "world": bullets_world,
        "rus": bullets_rus,
        "prices": bullets_prices
}

example = 'Пример верного оформления:\r\n1.\tРосстат зафиксировал стабилизацию выпуска базовых отраслей (day: 3) \r\nhttps://www.kommersant.ru/doc/7329366 \r\n2.\tСтроители просят смягчить правила распоряжения авансами (day: 1)\r\nhttps://www.rbc.ru/newspaper/2024/11/25/673f6abf9a7947de58a24847 \r\n3.\tВ Ульяновске открылся новый завод грузовиков Соллерс (day: 0) \r\nhttps://tass.ru/ekonomika/22497349 \r\n 4.\t Добыча газа за 9 месяцев выросла на 8% г/г в основном за счет Газпрома (day: 3) \r\nhttps://www.interfax.ru/business/994801 \r\n'

def extract_json(text: str):
    """
    Извлекает валидный JSON (объект или массив) из строки.
    Приоритет:
    1. Кодовые блоки: `````` или ``````
    2. Самый длинный валидный фрагмент, начинающийся с [ или { и заканчивающийся на ] или }
    3. Перебор всех возможных подстрок (на случай битого форматирования)
    Возвращает: dict | list | None
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

####################################################################################
# Functions relevant for test

def prioritise(section, model_bullets):
    file_name = f"{section}.json"
    file_name_initial = f"{section}_initial.json"
    folder_id = folder["2 4 new_lists_json"] # 2 4 new_lists_json
    temp_folder_id = folder["3 news_lists_json_grade"] # 3 grade
    combined_items = []
    # Загружаем файл с новостями
    try:
        file_id = find_file_in_drive(file_name_initial, folder_id)
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
                {"title": e.get("title"), "url": e.get("url"), "day": e.get("day")}
                for e in items_top40 if e.get("url")
            ]
        else:
            # Нет grade — берем первые 40 записей с валидным url
            combined_items = [
                {"title": e.get("title"), "url": e.get("url"), "day": e.get("day")}
                for e in items if e.get("url")
            ][:40]
    except Exception as e:
        print(f"❌ Ошибка при вызове модели для '{file_name}': {e}")
        return
    # Сохраняем итоговый результат в исходную папку
    save_to_drive(file_name, combined_items, folder_id, file_format="json")
    print(f"✅ prioritise({section}) — сохранён корректный JSON.")

def design_wo_llm(section):
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
    # Формируем нумерованный список, как в примере, с сохранением day
    formatted_lines = []
    for i, item in enumerate(news_items, 1):
        title = item.get("title", "").strip()
        url = item.get("url", "").strip()
        day = item.get("day")  # сохраняем поле day, если есть
        if not title or not url:
            continue
        if day is not None:
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
            "model": "deepseek/deepseek-chat-v3-0324",
            "messages": [
                {"role": "system", "content": "Отвечай лаконично и информативно. Никогда не добавляй в списки новостей источники, найденные в интернете - отбирай новости только из приложенного списка."},
                {"role": "user", "content": prompt_text}
            ],
            "temperature": 0.7
        }

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

class NewsItem(BaseModel):
    theme: str
    title: str
    url: str

def choose_top_urls(section, model_bullets):
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


def read_top_urls(section, max_chars=3000):
    def extract_main_text(soup, max_chars=3000, min_paragraph_len=50, max_paragraphs=5):
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

def create_bullets(section, model_bullets):
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
            "temperature": 0.1,
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        choices = result.get("choices")
        if not choices or not choices[0].get("message", {}).get("content"):
            print(f"Модель не вернула ответ для {section}.")
            return

        assistant_text = choices[0]["message"]["content"]
        
        # Сохраняем в локальный файл для архивации
        output_dir = Path(__file__).resolve().parent / "model_choice"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        model_name = model_bullets.replace("/", "_").strip()
        local_filename = output_dir / f"report_{section}_{model_name}.txt"
        
        with open(local_filename, "w", encoding="utf-8") as f_local:
            f_local.write(assistant_text)
            
        print(f"✅ Сохранено: {local_filename}")

    except Exception as e:
        print(f"Ошибка при вызове модели для {section}: {e}")
        return

####################################################################################
# Here begins our test

# save initial version of list
#file_name = "prices.json"
#folder_id = folder["2 4 new_lists_json"] # 2 4 new_lists_json
#file_id = find_file_in_drive(file_name, folder_id)
#news_list_raw_initial = download_text_file(file_id)
#try:
#    initial_data = json.loads(news_list_raw_initial)
#except json.JSONDecodeError as e:
#   raise ValueError(f"Файл {file_name} не является валидным JSON: {e}")

# models = ["qwen/qwen-2.5-72b-instruct", "qwen/qwen3.5-35b-a3b", "anthropic/claude-sonnet-4.6", "openai/gpt-5.5", "deepseek/deepseek-v4-pro"]
models = ["qwen/qwen3.5-35b-a3b"]

for model_bullets in models:
    print(f"Starting test for model:{model_bullets}")
    #save_to_drive(file_name, initial_data, folder_id, file_format="json")
    
    prioritise("prices", model_bullets)
    try:
        design_wo_llm("prices")
    except Exception as e:
        print(f"⚠️ Ошибка в design_wo_llm: {e}. Пробую через LLM.")
        design("prices")
    
    choose_top_urls("prices", model_bullets)
    read_top_urls("prices")
    create_bullets("prices", model_bullets)    
