# Quick Start - API Keys Not Required

## Easiest Way (API keys not required)

You can run the site without API keys!

### 1. Install packages:

```bash
pip install -r requirements.txt
```

### 2. Run the site:

```bash
python app.py
```

### 3. Open in browser:

```
http://localhost:5000
```

**Note:**

- Weather information is shown in test mode (mock data)
- Telegram reminders are logged to console
- All other features work fully!

## Add API Keys Later

If you want to get real weather information:

1. **OpenWeatherMap API:**

   - Go to https://openweathermap.org/api
   - Create free account and get API key
   - Add to `.env` file: `WEATHER_API_KEY=your-key`

2. **Telegram Bot:**
   - Write to @BotFather
   - Create new bot
   - Get token
   - `.env` faylga qo'shing: `TELEGRAM_BOT_TOKEN=your-token`

## .env Fayl Yaratish (Ixtiyoriy)

Agar API kalitlarini qo'shmoqchi bo'lsangiz:

1. `.env` fayl yarating
2. Quyidagilarni kiriting:

```
WEATHER_API_KEY=your-openweathermap-key
TELEGRAM_BOT_TOKEN=your-telegram-token
```

**Eslatma:** `.env` fayl bo'lmasa ham sayt ishlaydi (test rejimida)!
