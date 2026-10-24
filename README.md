# LinkedIn Easy Apply Bot

Bot de postulación autónoma para LinkedIn Easy Apply, con evaluación inteligente por Gemini.

## ¿Qué hace?

- Busca ofertas de **"Solicitud sencilla" (Easy Apply)** en LinkedIn Jobs
- **57 queries de búsqueda** cubriendo roles Junior, Pasantías, Trainee, QA, Soporte, etc.
- Evalúa cada oferta con **Gemini** según tu perfil y criterios
- **Rellena el formulario multi-paso** de forma autónoma:
  - Datos de contacto
  - CV ya guardado en LinkedIn
  - Preguntas de screening (experiencia, disponibilidad, idiomas, etc.)
  - Carta de presentación generada por IA
- Guarda historial en **SQLite** para no repetir postulaciones
- **Anti-detección**: delays humanos, tipeo char-a-char, scroll orgánico

---

## Setup (una sola vez)

### 1. Crear entorno virtual e instalar dependencias

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configurar credenciales

```bash
copy .env.example .env
```
Editá `.env` y completá tu `GEMINI_API_KEY`.

### 3. Completar tu perfil

Copiá la plantilla y completá tus datos reales:
```bash
copy config\profile.example.json config\profile.json
```
Editá `config/profile.json` con tus datos:
- `full_name`, `first_name`, `last_name`
- `email`, `phone`
- `linkedin_url`, `github`
- Tus skills, educación y respuestas frecuentes

### 4. Subir tu CV a LinkedIn

Asegurate de tener tu CV subido al perfil de LinkedIn antes de ejecutar el bot.
LinkedIn lo usará automáticamente en el formulario Easy Apply.

---

## Uso

### Paso 1: Abrir Chrome con sesión de LinkedIn

```
launch_chrome.bat
```
Se abre Chrome con tu perfil real. Si no estás logueado, loguéate ahora. Luego cerrá esta ventana del prompt (no Chrome).

### Paso 2: Ejecutar el bot

```
run_bot.bat
```

Esto lanza el bot en modo automático completo.

### Modos disponibles

| Comando | Modo |
|---|---|
| `python main.py --auto` | 100% automático (por defecto) |
| `python main.py --dry-run` | Auditoría: evalúa sin postular |
| `python main.py --interactive` | Confirmación manual antes de cada postulación |
| `python main.py --max-apps 5` | Limitar a 5 postulaciones en esta sesión |

---

## Estructura del proyecto

```
linkedin-job-bot/
├── config/
│   ├── profile.json         # ← TUS DATOS (completar)
│   ├── criteria.json        # Filtros y umbrales de score
│   └── search_queries.json  # Queries de búsqueda (57 variantes)
├── data/
│   └── job_history.db       # Historial SQLite (auto-generado)
├── src/
│   ├── browser.py           # ChromeConnector con anti-detección
│   ├── linkedin_scraper.py  # Scraping de tarjetas Easy Apply
│   ├── form_filler.py       # Rellena formularios multi-paso
│   ├── evaluator.py         # Evaluación con Gemini
│   ├── storage.py           # Historial SQLite
│   └── ui.py                # Rich UI en consola
├── tests/
│   └── test_config.py       # Validación de configuración
├── .env                     # Credenciales (no commitear)
├── .env.example             # Plantilla
├── main.py                  # Orquestador principal
├── launch_chrome.bat        # Abre Chrome con tu sesión
└── run_bot.bat              # Ejecuta el bot
```

---

## Configuración avanzada

### `config/criteria.json`
- `min_fit_score`: Score mínimo para postularse (default: 65)
- `max_applications_per_run`: Máximo de postulaciones por ejecución (default: 20)
- `excluded_disciplines`: Disciplinas que el bot ignorará automáticamente

### `config/search_queries.json`
- `queries`: Lista de términos de búsqueda (57 incluidos por defecto)
- `location`: Ciudad de búsqueda
- `max_results_per_query`: Ofertas máximas por query (default: 25)
- `easy_apply_only`: Solo ofertas Easy Apply (default: true)

### `.env`
| Variable | Default | Descripción |
|---|---|---|
| `GEMINI_API_KEY` | — | **Requerido** — Tu API Key de Google Gemini |
| `CDP_URL` | `http://localhost:9222` | Puerto CDP de Chrome |
| `MIN_FIT_SCORE` | 65 | Score mínimo para postular |
| `MAX_APPLICATIONS_PER_RUN` | 20 | Límite de postulaciones por sesión |
| `DEFAULT_MODE` | auto | Modo de ejecución |

---

## Tests

```bash
pytest tests/test_config.py -v
```

---

## Notas importantes

- LinkedIn puede detectar comportamiento automatizado si la velocidad es muy alta. El bot incluye delays aleatorios entre 20-45 segundos entre postulaciones.
- LinkedIn actualiza sus selectores CSS frecuentemente. Si el bot deja de funcionar, los selectores en `linkedin_scraper.py` y `form_filler.py` pueden necesitar actualización.
- Uso responsable: Respetá los Términos de Servicio de LinkedIn y no abuses del volumen de postulaciones.
