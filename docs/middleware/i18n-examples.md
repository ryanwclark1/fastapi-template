# I18n Middleware - Locale Detection Demo

This document demonstrates the I18n middleware in action with curl examples.

## Quick Setup

1. Enable I18n in your `.env` file:
```bash
I18N_ENABLED=true
I18N_DEFAULT_LOCALE=en
I18N_SUPPORTED_LOCALES=["en", "es", "fr"]
```

2. Add middleware to your FastAPI app:
```python
from example_service.core.settings import get_i18n_settings
from example_service.app.middleware import create_i18n_middleware

i18n_settings = get_i18n_settings()

if i18n_settings.enabled:
    middleware_class = create_i18n_middleware(
        default_locale=i18n_settings.default_locale,
        supported_locales=i18n_settings.supported_locales,
    )
    app.add_middleware(middleware_class)
```

3. Create a test endpoint:
```python
from fastapi import Request

@app.get("/hello")
async def hello(request: Request):
    locale = request.state.locale

    greetings = {
        "en": "Hello, World!",
        "es": "¡Hola, Mundo!",
        "fr": "Bonjour, le Monde!",
    }

    return {
        "message": greetings.get(locale, "Hello!"),
        "locale": locale,
    }
```

## Locale Detection Examples

### 1. Default Locale (No Headers)

**Request:**
```bash
curl -X GET http://localhost:8000/api/v1/hello
```

**Response:**
```json
{
  "message": "Hello, World!",
  "locale": "en"
}
```

**Headers:**
```
Content-Language: en
Set-Cookie: locale=en; Max-Age=2592000; Path=/; SameSite=Lax
```

---

### 2. Accept-Language Header (Spanish)

**Request:**
```bash
curl -X GET http://localhost:8000/api/v1/hello \
  -H "Accept-Language: es-ES"
```

**Response:**
```json
{
  "message": "¡Hola, Mundo!",
  "locale": "es"
}
```

**Headers:**
```
Content-Language: es
Set-Cookie: locale=es; Max-Age=2592000; Path=/; SameSite=Lax
```

---

### 3. Accept-Language with Quality Values

**Request:**
```bash
curl -X GET http://localhost:8000/api/v1/hello \
  -H "Accept-Language: de;q=0.9,fr-FR;q=0.8,en;q=0.7"
```

**Response:**
```json
{
  "message": "Bonjour, le Monde!",
  "locale": "fr"
}
```

**Explanation:** German (de) is not supported, so French (fr) is selected as the next highest quality supported language.

---

### 4. Query Parameter Override

**Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/hello?lang=fr"
```

**Response:**
```json
{
  "message": "Bonjour, le Monde!",
  "locale": "fr"
}
```

**Use Case:** Useful for sharing localized links or testing different languages.

---

### 5. Cookie-Based Persistence

**Request 1:** Set locale via query parameter
```bash
curl -X GET "http://localhost:8000/api/v1/hello?lang=es" \
  -c cookies.txt
```

**Request 2:** Subsequent requests use cookie
```bash
curl -X GET "http://localhost:8000/api/v1/hello" \
  -b cookies.txt
```

**Response:**
```json
{
  "message": "¡Hola, Mundo!",
  "locale": "es"
}
```

**Explanation:** The locale cookie persists the user's language preference across requests.

---

### 6. Priority Order Demonstration

**Request:** All detection sources present
```bash
curl -X GET "http://localhost:8000/api/v1/hello?lang=fr" \
  -H "Accept-Language: es" \
  -b "locale=de"
```

**Priority Resolution:**
1. User Preference: ❌ (not authenticated)
2. Accept-Language: ✅ `es` (Spanish)
3. Query Parameter: `fr` (French) - ignored
4. Cookie: `de` (German) - ignored

**Response:**
```json
{
  "message": "¡Hola, Mundo!",
  "locale": "es"
}
```

**Explanation:** Accept-Language header takes priority over query parameter and cookie.

---

### 7. Complex Accept-Language Header

**Request:**
```bash
curl -X GET http://localhost:8000/api/v1/hello \
  -H "Accept-Language: ja-JP,de-DE;q=0.9,fr-FR;q=0.8,en-US;q=0.7"
```

**Response:**
```json
{
  "message": "Bonjour, le Monde!",
  "locale": "fr"
}
```

**Parsing Logic:**
1. Japanese (ja): Not supported
2. German (de): Not supported
3. French (fr): ✅ Supported! (quality: 0.8)
4. English (en): Supported (quality: 0.7) - but French has higher quality

---

### 8. Unsupported Locale Fallback

**Request:**
```bash
curl -X GET "http://localhost:8000/api/v1/hello?lang=de"
```

**Response:**
```json
{
  "message": "Hello, World!",
  "locale": "en"
}
```

**Explanation:** German (de) is not in supported locales, so defaults to English (en).

---

## With Translations

### Setup with Translation Provider

```python
TRANSLATIONS = {
    "en": {
        "welcome": "Welcome to our application",
        "user_created": "User created successfully",
        "not_found": "Resource not found",
    },
    "es": {
        "welcome": "Bienvenido a nuestra aplicación",
        "user_created": "Usuario creado exitosamente",
        "not_found": "Recurso no encontrado",
    },
    "fr": {
        "welcome": "Bienvenue dans notre application",
        "user_created": "Utilisateur créé avec succès",
        "not_found": "Ressource introuvable",
    },
}

def load_translations(locale: str) -> dict[str, str]:
    return TRANSLATIONS.get(locale, TRANSLATIONS["en"])

app.add_middleware(
    I18nMiddleware,
    translation_provider=load_translations,
)

@app.get("/welcome")
async def welcome(request: Request):
    translations = request.state.translations
    return {
        "message": translations["welcome"],
        "locale": request.state.locale,
    }
```

### Translation Examples

**English:**
```bash
curl -X GET http://localhost:8000/api/v1/welcome
```
```json
{
  "message": "Welcome to our application",
  "locale": "en"
}
```

**Spanish:**
```bash
curl -X GET http://localhost:8000/api/v1/welcome \
  -H "Accept-Language: es"
```
```json
{
  "message": "Bienvenido a nuestra aplicación",
  "locale": "es"
}
```

**French:**
```bash
curl -X GET "http://localhost:8000/api/v1/welcome?lang=fr"
```
```json
{
  "message": "Bienvenue dans notre application",
  "locale": "fr"
}
```

---

## Browser Testing

### JavaScript Fetch Example

```javascript
// Default browser language
fetch('/api/v1/hello')
  .then(r => r.json())
  .then(data => console.log(data.message));

// Override with query parameter
fetch('/api/v1/hello?lang=es')
  .then(r => r.json())
  .then(data => console.log(data.message));

// Check locale cookie
console.log(document.cookie);
// Output: "locale=es; ..."
```

### Browser DevTools

1. **Check Request Headers:**
   - Open DevTools → Network tab
   - Look for `Accept-Language` header
   - Example: `Accept-Language: en-US,en;q=0.9`

2. **Check Response Headers:**
   - Look for `Content-Language` header
   - Example: `Content-Language: es`

3. **Check Cookies:**
   - Application tab → Cookies
   - Find `locale` cookie
   - Value: `es`, Max-Age: `2592000`

---

## Testing Different Scenarios

### Scenario 1: First-Time Visitor

```bash
# No cookies, browser's Accept-Language header used
curl -X GET http://localhost:8000/api/v1/hello \
  -H "Accept-Language: fr-FR,fr;q=0.9,en;q=0.8" \
  -c cookies.txt
# Result: French (fr)
```

### Scenario 2: Returning Visitor with Cookie

```bash
# Cookie from previous visit
curl -X GET http://localhost:8000/api/v1/hello \
  -b cookies.txt
# Result: French (fr) from cookie
```

### Scenario 3: Temporary Language Switch

```bash
# Override via query parameter (doesn't update cookie)
curl -X GET "http://localhost:8000/api/v1/hello?lang=es" \
  -b cookies.txt
# Result: Spanish (es) for this request only
```

### Scenario 4: Authenticated User Preference

```python
# User model with preferred language
class User:
    preferred_language = "es"

# Authentication middleware sets user
@app.middleware("http")
async def auth(request: Request, call_next):
    request.state.user = get_current_user(request)
    response = await call_next(request)
    return response
```

```bash
# User's preference overrides everything
curl -X GET http://localhost:8000/api/v1/hello \
  -H "Authorization: Bearer <token>" \
  -H "Accept-Language: fr" \
  -b "locale=en"
# Result: Spanish (es) - user preference wins
```

---

## Production Tips

### 1. Disable Query Parameter in Production

```python
app.add_middleware(
    I18nMiddleware,
    use_query_param=False,  # More secure
)
```

### 2. Monitor Locale Usage

```python
import logging

logger = logging.getLogger(__name__)

@app.get("/hello")
async def hello(request: Request):
    locale = request.state.locale
    logger.info(f"Locale: {locale}", extra={
        "locale": locale,
        "path": request.url.path,
        "user_agent": request.headers.get("user-agent"),
    })
    return {"message": f"Hello in {locale}"}
```

### 3. Cache Translations

```python
from functools import lru_cache

@lru_cache(maxsize=10)
def load_translations_cached(locale: str) -> dict[str, str]:
    return load_translations_from_file(locale)
```

### 4. Graceful Degradation

```python
def load_translations(locale: str) -> dict[str, str]:
    try:
        return load_from_database(locale)
    except Exception as e:
        logger.error(f"Translation load failed: {e}")
        return {}  # Empty dict, use fallback strings
```

---

## Summary

The I18n middleware provides:

- ✅ **Automatic locale detection** from multiple sources
- ✅ **RFC 7231 compliant** Accept-Language parsing
- ✅ **Cookie-based persistence** for better UX
- ✅ **Query parameter override** for testing/sharing
- ✅ **User preference support** for authenticated users
- ✅ **Translation provider integration** for dynamic content
- ✅ **Production-ready** with security and performance best practices

For more details, see:
- `/docs/middleware/i18n-middleware.md` - Complete documentation with 9 comprehensive usage examples
- `/tests/unit/test_middleware/test_i18n.py` - Test suite
