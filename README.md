# 🤖 Telegram AI News Bot (Python)

Цей бот автоматично збирає останні новини про штучний інтелект (ChatGPT, Claude, Gemini, Google, Copilot тощо), аналізує їх за допомогою **Gemini API** (з пошуком в реальному часі) і щоранку о 8:00 надсилає структурований дайджест українською мовою у ваші особисті повідомлення Telegram.

У разі обмежень квоти або помилок API, бот автоматично перемикається в **резервний режим (RSS)**, збираючи та відправляючи свіжі україномовні IT-новини напряму.

Бойовий файл бота: `digest.py`. Папка `archive/` містить старі експериментальні реалізації лише для історії.

---

## 🛠️ Налаштування перед запуском

Для роботи бота потрібні три параметри:

1. **Telegram Bot Token**: Отримайте у [@BotFather](https://t.me/BotFather) в Telegram. Надішліть команду `/newbot` та отримайте API токен.
2. **Telegram Chat ID**: Отримайте свій ID через бот [@userinfobot](https://t.me/userinfobot) або [@getmyid_bot](https://t.me/getmyid_bot).
3. **Gemini API Key**: Створіть безкоштовний ключ в [Google AI Studio](https://aistudio.google.com/).

---

## 🚀 Варіант 1: Безкоштовний хмарний запуск через GitHub Actions (Рекомендовано)

Цей варіант дозволяє не тримати комп'ютер увімкненим. Сценарій запускається серверами GitHub щодня автоматично.

1. Залийте цей проект у свій репозиторій на GitHub:
   ```bash
   git init
   git remote add origin https://github.com/igsamchenko-cmyk/ai-digest-bot.git
   git branch -M main
   git add .
   git commit -m "Initial commit"
   git push -u origin main
   ```
2. Перейдіть до вашого репозиторію на сайті GitHub.
3. Відкрийте вкладку **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
4. Додайте три секрети:
   * Назва: `TELEGRAM_BOT_TOKEN` | Значення: ваш токен з BotFather
   * Назва: `TELEGRAM_CHAT_ID` | Значення: ваш Telegram chat ID *(необов'язково, якщо ви вже написали боту `/start`; скрипт спробує визначити ID автоматично)*
   * Назва: `GEMINI_API_KEY` | Значення: ваш ключ Gemini API
5. Перейдіть на вкладку **Actions** у вашому GitHub-репозиторії, оберіть **AI Digest** і натисніть **Run workflow**, щоб перевірити роботу бота вручну.

> Ніколи не додавайте реальні токени або API-ключі в код чи README. Якщо ключ випадково потрапив у публічний репозиторій, його потрібно одразу перевипустити.

Бот запускатиметься автоматично щодня о **08:00 за київським часом**. Workflow має два UTC-запуски для літнього та зимового часу, а скрипт сам пропускає зайвий запуск.

---

## 💻 Варіант 2: Локальний запуск (на вашому комп'ютері)

1. Перейдіть до каталогу бота:
   ```bash
   cd ai-digest-bot
   ```
2. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```
3. Створіть файл конфігурації `.env` на основі шаблону та пропишіть свої ключі:
   ```ini
   TELEGRAM_BOT_TOKEN=ваш_telegram_bot_token
   TELEGRAM_CHAT_ID=ваш_telegram_chat_id
   GEMINI_API_KEY=ваш_ключ_gemini
   ```
4. Запустіть один раз для тестування (будь-який варіант еквівалентний):
   ```bash
   python digest.py --run-once
   python -m ai_digest --run-once
   ai-digest --run-once          # після pip install -e .
   ```
5. Для щоденного автозапуску у **daemon-режимі** (тримає процес):
   ```bash
   python digest.py
   # або
   python -m ai_digest
   ```
   Для налаштування у Windows скористайтеся **Планувальником завдань** (Task Scheduler):
   - Програма: `python`, аргументи: `digest.py`
   - Або `ai-digest` після `pip install -e .`
   - Робоча папка: повний шлях до каталогу бота.

---

## ✅ Перевірка коду

Перед запуском розсилки GitHub Actions автоматично виконує:

```bash
ruff check .              # лінтер
black --check .           # форматування
mypy ai_digest digest.py  # статичні типи
pip-audit -r requirements.txt  # аудит безпеки
pytest -q --cov=ai_digest # тести з покриттям
```

Запустити локально:
```bash
pip install -r requirements-dev.txt
pytest -q
```

### 🔁 Локальне повторне тестування

Якщо `ENFORCE_KYIV_HOUR=true` і маркер уже записаний, `--run-once` **не** обходить перевірку маркера — дайджест буде пропущений (це нормальна поведінка для захисту від дублювання у GitHub Actions).

Для повторного тестового запуску:
```bash
ENFORCE_KYIV_HOUR=false python digest.py --run-once
```

---

## 📰 Актуальність новин

Бот фільтрує RSS-новини за датою публікації. За замовчуванням беруться лише матеріали за останні `72` години:

```ini
NEWS_LOOKBACK_HOURS=72
```

Пошук пріоритезує релізи моделей, оновлення LLM, конкурентні запуски та важливі AI-продукти від OpenAI, Anthropic/Claude, Google/Gemini, Meta/Llama, Mistral, DeepSeek, Qwen, xAI/Grok, Microsoft і Perplexity.

---

## РљС–Р»СЊРєС–СЃС‚СЊ РЅРѕРІРёРЅ Сѓ РґР°Р№РґР¶РµСЃС‚С–

| Р РµР¶РёРј | Р—РјС–РЅРЅР° | Default | РћРїРёСЃ |
|-------|--------|---------|------|
| Gemini path | `NEWS_COUNT` | 10 | AI-curated РґР°Р№РґР¶РµСЃС‚ Р· summary С‚Р° "why matters" |
| RSS fallback | `RSS_FALLBACK_NEWS_COUNT` | 10 | Р РµР·РµСЂРІРЅРёР№ СЂРµР¶РёРј: Р·Р°РіРѕР»РѕРІРєРё + РїРѕСЃРёР»Р°РЅРЅСЏ Р±РµР· AI |

> `rss_items=N` Сѓ СЂСЏРґРєСѓ `RUN SUMMARY` вЂ” С†Рµ СЃРёСЂС– items Сѓ pipeline (`NEWS_COUNT x 4`),
> Р° **РЅРµ** РєС–Р»СЊРєС–СЃС‚СЊ РЅРѕРІРёРЅ, РІС–РґРїСЂР°РІР»РµРЅРёС… Сѓ Telegram.
