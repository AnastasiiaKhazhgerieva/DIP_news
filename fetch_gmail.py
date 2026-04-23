import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import os
from datetime import datetime

def decode_mime_words(s):
    """Безопасно декодирует тему и заголовки письма"""
    if not s:
        return ""
    parts = decode_header(s)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or 'utf-8', errors='ignore'))
        else:
            decoded.append(part)
    return " ".join(decoded)

def main():
    host = os.environ['gmail_imap_host']
    port = int(os.environ['gmail_imap_port'])
    user = os.environ['gmail_user']
    password = os.environ['gmail_password']

    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select('inbox')
        status, data = imap.search(None, '(UNSEEN)')
        
        if status != 'OK' or not data[0]:
            print("📭 Нет непрочитанных писем")
            return

        for e_id in data[0].split():
            process_email(imap, e_id)

def process_email(imap, e_id):
    status, msg_data = imap.fetch(e_id, '(RFC822)')
    if status != 'OK':
        return
        
    msg = email.message_from_bytes(msg_data[0][1])

    # 1. Фильтр по теме
    subject = decode_mime_words(msg.get('Subject', ''))
    if "Подборка важных новостей" not in subject:
        print(f"⏭ Пропускаю (не та тема): {subject}")
        mark_seen(imap, e_id)
        return

    # 2. Дата письма (из заголовка или сегодняшняя)
    date_header = msg.get('Date')
    if date_header:
        try:
            dt = parsedate_to_datetime(date_header)
            date_str = dt.strftime('%Y-%m-%d')
        except Exception:
            date_str = datetime.now().strftime('%Y-%m-%d')
    else:
        date_str = datetime.now().strftime('%Y-%m-%d')

    # 3. Извлекаем ТОЛЬКО plain-text, игнорируя вложения и HTML
    text_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cd = str(part.get('Content-Disposition', ''))
            if ctype == 'text/plain' and 'attachment' not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or 'utf-8'
                text_parts.append(payload.decode(charset, errors='ignore'))
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or 'utf-8'
        if payload:
            text_parts.append(payload.decode(charset, errors='ignore'))

    full_text = "\n".join(text_parts).strip()
    if not full_text or len(full_text) < 30:
        print("⚠️ Текст пустой или слишком короткий, пропускаю")
        mark_seen(imap, e_id)
        return

    # 4. Сохраняем в одну корневую папку
    TARGET_FOLDER = "final_versions"
    os.makedirs(TARGET_FOLDER, exist_ok=True)

    # Безопасное имя файла: дата + порядковый номер
    counter = 1
    file_name = f"{date_str}_{counter}.txt"
    while os.path.exists(os.path.join(TARGET_FOLDER, file_name)):
        counter += 1
        file_name = f"{date_str}_{counter}.txt"
    file_path = os.path.join(TARGET_FOLDER, file_name)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
    print(f"✅ Сохранено: {file_path} ({len(full_text)} символов)")

    mark_seen(imap, e_id)

def mark_seen(imap, e_id):
    """Помечает письмо как прочитанное, чтобы не обрабатывать повторно"""
    try:
        imap.store(e_id, '+FLAGS', '\\Seen')
    except Exception as e:
        print(f"⚠️ Не удалось пометить как прочитанное: {e}")

if __name__ == "__main__":
    main()
