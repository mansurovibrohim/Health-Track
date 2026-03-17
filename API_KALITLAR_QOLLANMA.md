# Getting API Keys - Step-by-Step Guide

## 1. OpenWeatherMap API Kaliti (Ob-havo uchun)

### Usul 1: Bepul API Kalit Olish

1. **Veb-saytga kiring:**

   - https://openweathermap.org/api ga kiring

2. **Ro'yxatdan o'ting:**

   - "Sign Up" tugmasini bosing
   - Email, username va parol kiriting
   - Emailni tasdiqlang

3. **API kalitni oling:**

   - Kirishdan keyin "API keys" bo'limiga kiring
   - Yoki to'g'ridan-to'g'ri: https://home.openweathermap.org/api_keys
   - "Create key" tugmasini bosing
   - Key nomini kiriting (masalan: "Health Track")
   - "Generate" tugmasini bosing
   - **API Key** ni ko'chirib oling (masalan: `abc123def456ghi789`)

4. **Eslatma:**
   - Bepul rejada kuniga 60 soat ichida 1000 so'rov limiti bor
   - Bu sizning loyihangiz uchun yetarli

### Usul 2: Test uchun Mock API (API kalit kerak emas)

Agar API kalit olishni istamasangiz, test uchun mock ob-havo ma'lumotlarini ishlatishingiz mumkin.

## 2. Telegram Bot Token Olish

### Qadamma-qadam:

1. **Telegram'da @BotFather ni toping:**

   - Telegram ilovasida qidiring: `@BotFather`
   - Yoki to'g'ridan-to'g'ri: https://t.me/botfather

2. **Bot yarating:**

   - `/start` yozing
   - `/newbot` yozing
   - Bot nomini kiriting (masalan: "Mening Health Track Botim")
   - Bot username kiriting (oxirida `bot` bo'lishi kerak, masalan: `my_health_track_bot`)

3. **Token oling:**

   - BotFather sizga token beradi (masalan: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
   - Bu tokenni ko'chirib oling

4. **Chat ID olish (foydalanuvchi uchun):**
   - Telegram'da @userinfobot ni toping
   - `/start` yozing
   - U sizga Chat ID ni beradi (masalan: `123456789`)
   - Bu ID ni profil sahifasida kiriting

## 3. Konfiguratsiya

`.env` fayl yarating va kalitlarni kiriting:

```env
WEATHER_API_KEY=your-openweathermap-api-key-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
```

## 4. Test Rejimi (API kalitlarisiz)

Agar hozircha API kalitlarini olishni istamasangiz, test rejimida ishlatishingiz mumkin.
Sayt ishlaydi, lekin:

- Ob-havo ma'lumotlari ko'rsatilmaydi (yoki mock ma'lumotlar)
- Telegram eslatmalar ishlamaydi
