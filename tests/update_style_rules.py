import os
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================

API_KEY = os.environ.get("DEEPSEEK_API_KEY")

if not API_KEY:
    raise ValueError("Нет API-ключа! Передай DEEPSEEK_API_KEY в переменные окружения.")

URL = "https://api.deepseek.com/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

CORRECTIONS_DIR = Path("corrections")
CORRECTIONS_FILE = CORRECTIONS_DIR / "corrections.txt"

# Логика твоего расписания: минус 5 дней от сегодня
DAYS_BACK = 5

def main():
    print(f"🔍 Поиск архивов за дату: (сегодня - {DAYS_BACK} дн.)")
    
    # 1. Вычисляем нужную дату
    target_date = datetime.now() - timedelta(days=DAYS_BACK)
    date_str = target_date.strftime('%Y-%m-%d')
    
    path_primary = Path(f"primary_versions/{date_str}_primary.txt")
    path_final = Path(f"final_versions/{date_str}_final.txt")

    # Проверка существования файлов
    if not path_primary.exists():
        print(f"⚠️ Пропуск: не найден черновик {path_primary}")
        return
        
    if not path_final.exists():
        print(f"⚠️ Пропуск: не найден финал {path_final}")
        return

    try:
        draft_text = path_primary.read_text(encoding='utf-8')
        final_text = path_final.read_text(encoding='utf-8')
        
        # Загружаем ТЕКУЩИЕ правила, если они есть
        if CORRECTIONS_FILE.exists():
            history_rules = CORRECTIONS_FILE.read_text(encoding='utf-8')
        else:
            history_rules = "Исторических правил пока нет. Сформируй новые с нуля."

    except Exception as e:
        print(f"❌ Ошибка чтения файлов: {e}")
        return

    # Формируем ЗАПРОС для объединения
    prompt = f"""
    Ты — главный редактор новостной аналитики. Твоя задача — поддерживать актуальный список стилистических правил корректности.

    ### СУЩЕСТВУЮЩИЙ СПИСОК ПРАВИЛ:
    {history_rules}

    ### НОВЫЕ ДАННЫЕ ДЛЯ АНАЛИЗА:
    [ЧЕРНОВИК]
    {draft_text}

    [ИСПРАВЛЕННЫЙ РУКОВОДИТЕЛЕМ ВАРИАНТ]
    {final_text}

    ### ЗАДАЧА:
    1. Сравни новые изменения с существующим списком правил.
    2. Если руководитель внес исправления, еще не описанные в правилах, добавь их в правила.
    3. Если правило противоречит новым примерам или дублирует уже написанное — обнови или удали его.
    4. Убери повторы и оставь только самые важные, конкретные инструкции.
    
    Верни ИТОГОВЫЙ ОБНОВЛЕННЫЙ СПИСОК (не пиши вступлений, только сами правила).
    """

    payload = {
        "model": "deepseek-chat", 
        "messages": [
            {"role": "system", "content": "Ты системный администратор базы знаний по стилю текстов."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2, 
    }

    try:
        print("⏳ Отправка запроса в DeepSeek для обновления базы знаний...")
        response = requests.post(URL, headers=HEADERS, json=payload)
        response.raise_for_status()
        
        ai_response = response.json()["choices"][0]["message"]["content"]
        print(f"\n💬 Обновленные правила:\n{ai_response}\n")

        # Сохраняем результат (ОБНОВЛЕНИЕ)
        CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(CORRECTIONS_FILE, 'w', encoding='utf-8') as f:
            f.write(ai_response)
            
        print(f"✅ Файл обновлен: {CORRECTIONS_FILE}")

    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка вызова DeepSeek API: {e}")

if __name__ == "__main__":
    main()
