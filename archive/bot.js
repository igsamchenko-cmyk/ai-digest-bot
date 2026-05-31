import cron from 'node-cron';
import dotenv from 'dotenv';
import Parser from 'rss-parser';
import path from 'path';
import { fileURLToPath } from 'url';

// Resolve directory name in ESM
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load environment variables
dotenv.config({ path: path.join(__dirname, '.env') });

const parser = new Parser();

// RSS feed URL for AI news
const FEED_URL = 'https://news.google.com/rss/search?q=ChatGPT+OR+Claude+OR+Gemini+OR+OpenAI+OR+Codex+OR+Copilot+OR+Google+AI&hl=en-US&gl=US&ceid=US:en';

/**
 * Formats a list of news items as a raw HTML list in case of Gemini failure.
 */
function getFallbackHtml(items) {
  const dateStr = new Date().toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric' });
  let html = `☀️ <b>Ранковий дайджест новин ШІ — ${dateStr} (Резервний випуск)</b>\n\n`;
  html += `<i>На жаль, сервіс генерації дайджесту Gemini тимчасово недоступний. Ось прямий список останніх новин:</i>\n\n`;

  items.forEach((item, idx) => {
    const title = item.title.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const source = (item.source?.name || 'Джерело').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    html += `${idx + 1}. <b>${title}</b>\n🔗 <a href="${item.link}">Читати на ${source}</a>\n\n`;
  });

  html += `🤖 <i>Бажаємо вам чудового дня!</i>`;
  return html;
}

/**
 * Main function to fetch news, summarize them via Gemini, and send to Telegram.
 */
export async function sendDailyNews() {
  const botToken = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  const geminiApiKey = process.env.GEMINI_API_KEY;

  if (!botToken || !chatId) {
    console.error('Помилка: Налаштуйте TELEGRAM_BOT_TOKEN та TELEGRAM_CHAT_ID у файлі .env');
    process.exit(1);
  }

  console.log(`[${new Date().toISOString()}] Початок збору новин...`);

  let feed;
  try {
    feed = await parser.parseURL(FEED_URL);
  } catch (error) {
    console.error('Помилка завантаження RSS-стрічки:', error);
    // Send alert to Telegram if possible
    await sendToTelegram(botToken, chatId, '⚠️ <b>Помилка бота новин ШІ:</b> Не вдалося завантажити свіжу RSS-стрічку новин.');
    return;
  }

  if (!feed.items || feed.items.length === 0) {
    console.log('Нових новин не знайдено.');
    await sendToTelegram(botToken, chatId, '☀️ <b>Ранковий дайджест новин ШІ:</b> Сьогодні немає нових новин у стрічці.');
    return;
  }

  // Filter items from the last 24 hours. Fallback to 48 hours if fewer than 5 items.
  const now = new Date();
  const oneDayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const twoDaysAgo = new Date(now.getTime() - 2 * 24 * 60 * 60 * 1000);

  let targetItems = feed.items.filter(item => new Date(item.pubDate) >= oneDayAgo);
  if (targetItems.length < 5) {
    console.log('Мало новин за останні 24 години, розширюємо пошук до 48 годин.');
    targetItems = feed.items.filter(item => new Date(item.pubDate) >= twoDaysAgo);
  }

  // Limit to top 15 items to stay within Gemini token and context constraints
  targetItems = targetItems.slice(0, 15);
  console.log(`Знайдено ${targetItems.length} актуальних новин для обробки.`);

  // If Gemini API Key is missing, send fallback raw news directly
  if (!geminiApiKey) {
    console.warn('GEMINI_API_KEY не вказано. Відправка сирого списку новин.');
    const fallbackHtml = getFallbackHtml(targetItems);
    await sendToTelegram(botToken, chatId, fallbackHtml);
    return;
  }

  // Construct prompt for Gemini
  const newsListString = targetItems.map((item, idx) => {
    return `${idx + 1}. Title: ${item.title}\nSource: ${item.source?.name || 'Unknown'}\nLink: ${item.link}\n`;
  }).join('\n');

  const dateStr = now.toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric' });

  const prompt = `You are a professional AI news editor and translator.
I will provide you with a list of recent artificial intelligence news articles from an RSS feed.
Your goal is to:
1. Review the articles, eliminate duplicates, and select the top 6-10 most interesting and significant news items (focus on OpenAI/ChatGPT, Claude/Anthropic, Gemini/Google, Codex/GitHub Copilot, and other major AI breakthroughs or releases).
2. Group the selected articles into 3-4 logical categories, each representing a clear topic (e.g., "🤖 OpenAI & ChatGPT", "🧠 Google & Gemini", "🎨 Anthropic & Claude", "💻 Інші ШІ інструменти").
3. For each selected news item:
   - Translate the title and core news to Ukrainian.
   - Write a brief, informative 1-2 sentence summary/explanation in Ukrainian.
   - Provide a clickable HTML link to the article using the exact link provided in the list. You must format the link like this: <a href="NEWS_URL">Джерело</a> or use the source name: <a href="NEWS_URL">TechCrunch</a>.
4. Format the final output to be sent via Telegram. You must use ONLY the following allowed Telegram HTML tags: <b>, <i>, <a>, <code>, <pre>. DO NOT use any markdown characters like **, *, or \` (backticks) as they will crash the Telegram bot parser.
5. Make sure the message is engaging, starting with this exact header and date:
"☀️ <b>Ранковий дайджест новин ШІ — ${dateStr}</b>\n\nПривіт! Ось найважливіші новини зі світу штучного інтелекту за останні 24 години:\n\n"
And end with a warm sign-off:
"\n🤖 <i>Дайджест підготовлено автоматично за допомогою Gemini. Гарного дня!</i>"
6. Ensure the entire message length is under 3500 characters.

Here is the news list:
${newsListString}`;

  let telegramMessage;
  try {
    console.log('Надсилання запиту до Gemini...');
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${geminiApiKey}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        contents: [{
          parts: [{
            text: prompt
          }]
        }],
        generationConfig: {
          temperature: 0.2
        }
      })
    });

    if (!response.ok) {
      throw new Error(`Gemini API HTTP Error: ${response.status}`);
    }

    const data = await response.json();
    telegramMessage = data.candidates?.[0]?.content?.parts?.[0]?.text;

    if (!telegramMessage) {
      throw new Error('Отримано пусту відповідь від Gemini API.');
    }
  } catch (error) {
    console.error('Помилка при зверненні до Gemini, відправляємо резервний випуск:', error);
    telegramMessage = getFallbackHtml(targetItems);
  }

  // Send message to Telegram
  await sendToTelegram(botToken, chatId, telegramMessage);
}

/**
 * Sends HTML message to Telegram API.
 */
async function sendToTelegram(token, chatId, text) {
  const url = `https://api.telegram.org/bot${token}/sendMessage`;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: 'HTML',
        disable_web_page_preview: true
      })
    });

    const data = await response.json();

    if (!response.ok || !data.ok) {
      throw new Error(data.description || `HTTP Status ${response.status}`);
    }

    console.log('Повідомлення успішно надіслано в Telegram!');
  } catch (error) {
    console.error('Помилка відправки повідомлення в Telegram:', error);
  }
}

// Check flags
const runOnce = process.argv.includes('--run-once') || process.env.RUN_ONCE === 'true';

if (runOnce) {
  console.log('Запуск в одноразовому тестовому режимі (--run-once)...');
  sendDailyNews()
    .then(() => {
      console.log('Одноразовий запуск завершено.');
      process.exit(0);
    })
    .catch((err) => {
      console.error('Критична помилка виконання:', err);
      process.exit(1);
    });
} else {
  // Cron schedule: Every day at 08:00 AM
  console.log('Запуск планувальника новин ШІ (щодня о 08:00 ранку)...');
  cron.schedule('0 8 * * *', () => {
    console.log('Планувальник активовано: надсилання щоденних новин...');
    sendDailyNews().catch(console.error);
  });
}
