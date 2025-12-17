# AI Content Hub — инструкция пользователя

## 1) Что делает приложение
AI Content Hub:
- берёт контент из **YouTube / RSS / Telegram**,
- генерирует **SEO‑статью на русском** в формате **JSON**:
  - `seo_title`, `seo_description`, `focus_keyword`, `html_content` (HTML + классы `.ai-alert`, `.ai-summary`, `.ai-list`, `.ai-table`),
- публикует в **WordPress** через REST API **как черновик**,
- автоматически делает и прикрепляет **обложку**:
  - генерирует картинку (OpenAI или Google Vertex Imagen),
  - загружает в **Медиафайлы** WordPress,
  - ставит как **Featured image** и вставляет в начало статьи,
- хранит историю ссылок в SQLite, чтобы **не публиковать дубли**.

## 2) Запуск (один раз)
В терминале в папке проекта:
- создать окружение: `python3 -m venv .venv`
- активировать: `source .venv/bin/activate`
- установить зависимости: `python -m pip install -r requirements.txt`
- запустить: `streamlit run main.py`

## 3) Где лежат настройки и почему “секреты” не уходят в Git
- Настройки сохраняются в `settings.json` (создаётся автоматически).
- `settings.json` **в .gitignore**, чтобы ключи/пароли не попадали в репозиторий.
- Шаблон настроек: `settings.example.json`.

## 4) Настройки WordPress (самое важное)
В админке приложения → Sidebar → **Настройки** → блок **WordPress**.

### Поля
**Сайт (URL)**
- Вводи корень сайта: `https://it-tip.ru`
- Не вводи `/wp-admin/` и не вводи `/home/blog/` и т.п.

**Логин WP**
- Вводи username (имя пользователя в WordPress), например `KeaBot`.

**Пароль приложения WP**
- Это не обычный пароль от входа.
- Нужно создать **Application Password** в WordPress:
  1) `WP Admin → Пользователи → Профиль` (профиль нужного пользователя)
  2) блок **“Пароли приложений”**
  3) создать новый пароль (например имя `AI Content Hub`)
  4) WordPress покажет пароль вида `xxxx xxxx xxxx xxxx xxxx xxxx` → его и вставляешь сюда

### Если “Пароли приложений отключены Wordfence”
- В Wordfence нужно включить Application Passwords (отключить запрет).
- После этого снова создать пароль приложения.

### Типовые ошибки WP
- **401 rest_cannot_create**: у пользователя нет прав публиковать записи → поставь роль **Редактор** или **Администратор**.
- **Media upload ошибка**: обычно Wordfence/WAF блокирует REST `/wp/v2/media` или у пользователя нет прав `upload_files`.

## 5) Настройки AI текста (OpenAI‑compatible)
Sidebar → **Настройки** → блок **AI (OpenAI-compatible)**

### Вариант A: OpenAI
- **API Key**: ключ OpenAI
- **Base URL**: оставь `https://api.openai.com/v1`
- **Model**: например `gpt-4o` (или любая доступная у тебя)

Где взять ключ OpenAI:
- `https://platform.openai.com/api-keys` → Create new secret key

### Вариант B: Perplexity / Kie (OpenAI‑compatible)
- **API Key**: ключ именно этого сервиса
- **Base URL**: их endpoint (обычно с `/v1`)
- **Model**: имя модели из документации сервиса

## 6) Промпт статьи (можно менять без кода)
Sidebar → **Настройки** → блок **Промпт статьи**

- Это главный системный промпт: структура JSON + HTML + design system.
- Если видишь косяки типа “до встречи в следующем видео” — добавь в промпт запреты, например:
  - “Запрещено: упоминать «видео», «подписывайтесь», «канал», «лайк», «до встречи…».”

## 7) Настройка генерации изображений (обложка)
Sidebar → **Настройки** → блок **Изображения (обложка)**

### Вариант A: OpenAI Images API
- **Генерировать и загружать обложку**: включено
- **Image provider**: `openai`
- **Image API Key**: ключ OpenAI (можно оставить пустым — тогда будет использоваться основной API Key)
- **Image Base URL**: `https://api.openai.com/v1`
- **Image Model**: `gpt-image-1`
- **Image size**: 1024×1024 (или другое)

Если видишь ошибку про “organization must be verified” — нужно пройти **Verify Organization** в OpenAI, либо использовать Google Imagen.

### Вариант B: Google Vertex AI Imagen (рекомендуется если есть кредиты GCP)
Что нужно:
1) В GCP включить **Vertex AI API**
2) Создать **Service Account** и скачать JSON
3) Положить JSON в проект, например: `secrets/gcp-sa.json` (эта папка игнорируется git)

Поля:
- **Image provider**: `vertex_imagen`
- **GCP project id**: например `my-project-contenthub`
- **GCP location**: обычно `us-central1`
- **Path to service account JSON**: `secrets/gcp-sa.json`
- **Image Model**: из Model Garden, например:
  - `publishers/google/models/imagen-4.0-generate-001`

Примечание: поля **Image API Key** и **Image Base URL** для `vertex_imagen` не важны.

## 8) Telegram (Telethon): что вставлять
Sidebar → **Настройки** → блок **Telegram (Telethon)**

Нужны **api_id** и **api_hash** (не bot token):
1) `https://my.telegram.org`
2) `API development tools`
3) Create application
4) Скопировать:
- **Telegram API ID** (число)
- **Telegram API Hash** (строка)

### Авторизация Telegram (первый запуск на сервере)
При первом использовании Telegram Telethon должен авторизоваться и создать файл сессии.
Теперь это делается **в интерфейсе**, без терминала:
1) Sidebar → **Настройки** → **Telegram (Telethon)** → раскрыть “Telegram авторизация (первый запуск)”
2) Ввести телефон `+7...` → нажать **Отправить код**
3) Ввести код из Telegram → нажать **Войти**
4) Если включена двухфакторка (2FA) — ввести пароль 2FA и нажать **Войти** ещё раз

После успешной авторизации создастся файл `telegram_session_path` (по умолчанию `secrets/telethon.session`), и дальше код/номер спрашиваться не будет.

## 9) Управление источниками
Sidebar → **Управление источниками**

### RSS
- Вставляй RSS‑URL, по одному в строке, например:
  - `https://habr.com/ru/rss/all/all/?fl=ru`
  - `https://lenta.ru/rss`

### Telegram‑каналы
- Вставляй username публичных каналов, по одному в строке:
  - `@durov`

Нажать **Сохранить источники**.

## 10) Генератор: как пользоваться
Sidebar → **Генератор** → выбираешь режим:

### YouTube
- вставь ссылку → **Start**
- появится статья → **Опубликовать в WordPress (черновик)**

### RSS
- **Проверить ленты** → появится список новостей
- отметь чекбоксы → **Генерировать выбранное**
- затем **Опубликовать…**

### Telegram
- **Получить посты** → отметь → **Генерировать выбранное**
- затем **Опубликовать…**

## 11) Где искать результат в WordPress
- `WP Admin → Записи → Все записи` → фильтр по **Черновики**
- Картинки: `WP Admin → Медиафайлы`
- Featured image:
  - в записи справа блок “Изображение записи”
  - плюс картинка вставляется в начало контента как `<img class="ai-cover" ...>`

## 12) Дубли (почему “новых нет”)
Приложение хранит историю URL в `content_hub.sqlite3`.
Если ссылка уже встречалась — она не покажется повторно.
Для теста можно:
- добавить новую RSS‑ленту/канал,
- или удалить `content_hub.sqlite3` (сбросит историю).
