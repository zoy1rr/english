# NOVA AI | English Academy Telegram bot

## Birinchi o'rnatish

1. Telegram'da [@BotFather](https://t.me/BotFather) orqali bot yarating va token oling.
2. Loyiha papkasida `setup.bat` ni ishga tushiring. U `.venv` yaratadi, `requirements.txt` dagi paketlarni o'rnatadi va `.env` faylini faqat u hali mavjud bo'lmasa yaratadi.
3. `.env` faylini ochib `BOT_TOKEN`, `ADMIN_ID` va `NOVA_API_KEY` qiymatlarini kiriting. Admin Telegram ID raqamini bot ishga tushgach `/id` buyrug'i bilan ko'rish mumkin.
4. Botni `run.bat` orqali boshlang yoki terminalda:

   ```powershell
   .\.venv\Scripts\python.exe bot.py
   ```

   Botni to'xtatish uchun `Ctrl+C` bosing. Bir token bilan bir vaqtda faqat bitta polling jarayoni ishlashi kerak.

## Railway hosting

1. Loyihani GitHub repozitoriyga yuklang. `.env` va SQLite baza fayllarini repozitoriyga qo'shmang.
2. Railway'da **New Project → Deploy from GitHub repo** orqali repozitoriyani tanlang. Railway root'dagi `Dockerfile`ni aniqlaydi, paketlarni `requirements.txt` orqali o'rnatadi va konteyner `python bot.py` buyrug'i bilan boshlanadi.
3. Railway service ichida quyidagi **Variables** ni kiriting:
   - `BOT_TOKEN` — BotFather tokeni
   - `ADMIN_ID` — admin Telegram ID raqami
   - `NOVA_API_KEY` — NOVA AI API kaliti
4. SQLite ma'lumotlarini deploylar orasida saqlash uchun service'ga **Volume** qo'shing va mount path'ni `/data` qiling. `DB_NAME` ni Railway Variables'da bo'sh qoldiring yoki umuman qo'shmang: bot `RAILWAY_VOLUME_MOUNT_PATH` ni aniqlab, bazani volume ichidagi `english_academy.db` ga saqlaydi. Agar `DB_NAME` ko'rsatilsa, u Railway avtomatik yo'lidan ustun turadi; doimiy saqlash uchun masalan `/data/english_academy.db` deb belgilang.
5. Railway'da faqat bitta bot service/replica ishlating. Bu bot Telegram long polling ishlatadi; bir token bilan ikki nusxa parallel ishga tushmasligi kerak. Public domain yoki HTTP port talab qilinmaydi.
6. Deploy logs'da `Telegram polling boshlandi`, `NOVA AI: ONLINE` va `Questions` sonini tekshiring. Botga Telegram'dan `/start` yuboring.

Railway Variables qiymatlarini repo `.env` faylidan alohida saqlang. SQLite volume qo'shilmasa, bot ishlashi mumkin, lekin qayta deploy yoki restartdan keyin foydalanuvchi ma'lumotlari saqlanmasligi mumkin.

Lokal `.db` fayllari xavfsizlik va deploy hajmi sabab Docker image'ga kiritilmaydi. Mavjud foydalanuvchilar, XP va tarixni ko'chirish kerak bo'lsa, botni to'xtatib, kerakli SQLite faylini Railway volume ichidagi `/data/english_academy.db` ga bir marta nusxalang; aks holda yangi baza yaratiladi.

## Telegram buyruqlari

- `/start` — botni boshlash va asosiy menyu
- `/help` — yordam
- `/cancel` — joriy mashq yoki amalni bekor qilish
- `/id` — Telegram foydalanuvchi ID raqamini ko'rsatish
- `/admin` — admin panel (faqat `ADMIN_ID`)
- `/novadiag` — NOVA AI ulanishini haqiqiy so'rov bilan tekshirish (faqat admin)

Ishga tushganda bot `/start`, `/help`, `/cancel`, `/id` buyruqlarini Telegram menyusiga qo'yadi; admin buyruqlari faqat admin chatida ko'rsatiladi.

## Ishlash va saqlash

- Birinchi ishga tushishda mazmunli offline savollar bazaga qo'shiladi; avvalgi noto'g'ri avtomatik ko'chirmalar yangi savol bankiga almashtiriladi.
- Har bir test yoki yozma mashq uchun NOVA AI tanlangan mavzuga mos kontekstli gaplarni va ularning ravon o'zbekcha tarjimasini yaratadi. AI vaqtincha ishlamasa, bot mavjud offline savollardan foydalanishga urinadi va bu haqda bildiradi.
- NOVA AI suhbatda foydalanuvchi yozgan tilda javob beradi va odatda qisqa, tushunarli javob qaytaradi.
- `📅 Kunlik reja` har kuni 5 daqiqalik, 3 savolli umumiy ingliz tili mashqini beradi. Imkon qadar avval oxirgi urinishda xato bo'lgan savollar qayta beriladi, qolgan savollar foydalanuvchining ko'proq qiynalayotgan mavzusidan tanlanadi.
- `⚙️ Sozlamalar` → `⏰ Kunlik eslatma` orqali eslatmani ixtiyoriy yoqib, vaqtini `HH:MM` ko'rinishida tanlash mumkin. Eslatma sukut bo'yicha o'chiq va Toshkent vaqti (UTC+5) bo'yicha yuboriladi.
- SQLite ma'lumotlar bazasi `DB_NAME` bilan belgilanadi; standart fayl `english_academy.db` bo'lib loyiha papkasida yaratiladi.
- Bot webhook o'rnatilgan bo'lsa, polling boshlashdan oldin webhookni pending xabarlarni tashlamasdan o'chiradi.
- NOVA AI faolligi uchun `NOVA_API_KEY` kerak; kalit bo'lmasa, bot offline savollar bilan ishlaydi, AI suhbat va AI yaratgan savollar ishlamaydi.
- Ma'lumotlar bazasining zaxira nusxasini olishdan oldin botni to'xtating, so'ng `.db` faylini nusxalang.

## Sozlamalar

`.env.example` — maxfiy kalitlarsiz namuna. Haqiqiy token va API kalitlarini `.env` ichida saqlang; ularni boshqalarga yubormang yoki ommaviy repozitoriyga qo'shmang.

- `BOT_TOKEN` — BotFather bergan token
- `ADMIN_ID` — Telegram raqamli foydalanuvchi ID
- `NOVA_API_KEY` — NOVA AI xizmatiga kirish kaliti. Oldingi sozlamalar uchun `GEMINI_API_KEY` nomi ham orqaga moslik sababli qabul qilinadi.
- `AI_MODEL` — ichki AI model sozlamasi; bo'sh qoldirilsa, bot ishlaydigan modelni o'zi tanlaydi.
- `DB_NAME` — SQLite fayl nomi yoki to'liq yo'li; bo'sh bo'lsa Railway volume yo'li avtomatik, aks holda loyiha papkasi ishlatiladi
- `AI_TIMEOUT` — AI so'rovi kutish vaqti, soniyada (5–300)
- `AI_HISTORY_LIMIT` — AI suhbat tarixidagi xabarlar soni (1–100)
- `QUESTIONS_PER_TEST` — testdagi savollar soni (1–50)
- `MIN_DATABASE_QUESTIONS` — minimal offline savollar soni (1–10000)
