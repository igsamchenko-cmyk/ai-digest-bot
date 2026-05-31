# 🤖 Telegram AI News Bot (Python)

Цей бот автоматично збирає останні новини про штучний інтелект (ChatGPT, Claude, Gemini, Google, Copilot тощо), аналізує їх за допомогою **Gemini API** (з пошуком в реальному часі) і щоранку о 8:00 надсилає структурований дайджест українською мовою у ваші особисті повідомлення Telegram.

У разі обмежень квоти або помилок API, бот автоматично перемикається в **резервний режим (RSS)**, збираючи та відправляючи свіжі україномовні IT-новини напряму.

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
   * Назва: `TELEGRAM_BOT_TOKEN` | Значення: `8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU`
   * Назва: `TELEGRAM_CHAT_ID` | Значення: `1039798805`
   * Назва: `GEMINI_API_KEY` | Значення: `AQ.Ab8RN6ISB_cL1bEucLFp49PPtgdO2WeNMGJz5XDbgPC2hBGDxw` *(або ваш новий робочий ключ Gemini API)*
5. Перейдіть на вкладку **Actions** у вашому GitHub-репозиторії, оберіть **Daily AI News Bot** (або **AI Digest**) і натисніть **Run workflow**, щоб перевірити роботу бота вручну.

Бот запускатиметься автоматично щодня о **08:00 за київським часом** (05:00 UTC).

---

## 💻 Варіант 2: Локальний запуск (на вашому комп'ютері)

1. Перейдіть до каталогу бота:
   ```bash
   cd ai-news-bot
   ```
2. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```
3. Створіть файл конфігурації `.env` на основі шаблону та пропишіть свої ключі:
   ```ini
   TELEGRAM_BOT_TOKEN=8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU
   TELEGRAM_CHAT_ID=1039798805
   GOOGLE_API_KEY=ваш_ключ_gemini
   ```
4. Запустіть один раз для тестування:
   ```bash
   python digest.py
   ```
5. Для налаштування щоденного автозапуску у Windows скористайтеся **Планувальником завдань** (Task Scheduler):
   - Оберіть запуск програми: `python`
   - Аргументи: `digest.py`
   - Робоча папка: повний шлях до каталогу бота.
