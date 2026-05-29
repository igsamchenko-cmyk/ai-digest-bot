# AI Дайджест — Telegram бот

Щодня о заданий час надсилає свіжі новини зі світу ШІ у Telegram.

## Встановлення

### 1. Встанови Python (якщо немає)
Завантаж з https://python.org — версія 3.9+

### 2. Встанови залежності
Відкрий термінал у папці з файлами і виконай:
```
pip install -r requirements.txt
```

### 3. Встав свій Anthropic API Key
Відкрий `ai_digest_bot.py` будь-яким текстовим редактором.
Знайди рядок:
```python
ANTHROPIC_API_KEY = "YOUR_ANTHROPIC_API_KEY"
```
Заміни `YOUR_ANTHROPIC_API_KEY` на свій ключ з console.anthropic.com

### 4. Запуск
```
python ai_digest_bot.py
```

При першому запуску бот надішле тестове повідомлення і запитає чи запустити дайджест зараз.

## Налаштування (у файлі ai_digest_bot.py)

| Параметр | За замовчуванням | Опис |
|----------|-----------------|------|
| `SEND_TIME` | `"07:00"` | Час відправки (24-год формат) |
| `NEWS_COUNT` | `5` | Кількість новин |
| `TOPIC` | AI загальне | Тема для пошуку |

## Автозапуск при старті комп'ютера

### Windows
1. Натисни Win+R → введи `shell:startup`
2. Створи файл `digest.bat`:
```
@echo off
python C:\шлях\до\ai_digest_bot.py
```

### Mac/Linux
Додай до crontab (`crontab -e`):
```
@reboot python3 /шлях/до/ai_digest_bot.py
```

## Вартість
Один дайджест (5 новин) ≈ $0.01–0.02 на місяць ≈ $0.30–0.60
