# Motion Studio

App local para crear **vídeos faceless de motion graphics para YouTube**.

1. Subes el **audio** de tu narración (o importas una transcripción `.json` / `.srt` / `.vtt`).
2. La app **transcribe** el audio con Whisper (local) y obtiene el tiempo exacto de cada palabra.
3. Convierte cada frase en una **escena de motion graphics** (texto cinético, cifra destacada, lista, comparación, pregunta o cita) según su contenido.
4. Eliges un **estilo visual** (Neon Tech, Editorial minimalista, Bold Pop, Corporativo limpio) y el formato.
5. Renderiza un **MP4** con el audio original. Cada animación aparece cuando se pronuncia su palabra.

La investigación de proyectos de referencia está en [`docs/INVESTIGACION.md`](docs/INVESTIGACION.md).

## Instalación

Requisitos: Python 3.10+ y, opcionalmente, un ffmpeg en el PATH (si no, se usa el binario que trae `imageio-ffmpeg`).

```bash
cd motion-studio
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py --open               # abre http://127.0.0.1:8765
```

La primera transcripción descarga el modelo de Whisper desde Hugging Face (necesita internet una vez).
Modelos: `small` (por defecto, buen equilibrio), `base`/`tiny` (rápidos) o `medium`/`large-v3` (más precisos, más lentos).
En CPU se usa `int8`; si hay GPU CUDA se usa automáticamente.

## Uso

En la interfaz:

- **Nuevo proyecto**: sube audio y/o transcripción, elige idioma y modelo, y pulsa *Transcribir y crear escenas*.
- **Escenas**: revisa la tabla. Cada fila muestra el tiempo, el tipo visual y el texto narrado. Puedes cambiar el tipo o las palabras a resaltar (los tiempos no cambian). *Guardar cambios*.
- **Estilo**: selecciona el estilo, formato (16:9 · 9:16 · 1:1), resolución (720p / 1080p), FPS y subtítulos. *Renderizar vídeo*.
- El vídeo queda en `projects/<id>/output/` y se puede descargar desde la app.

Analizar y renderizar son pasos separados: puedes probar varios estilos sin volver a transcribir.

### Sincronización

- Cada palabra tiene su `start` y `end` (Whisper con `word_timestamps`).
- La escena empieza ~0.25 s antes de su primera palabra y dura hasta la siguiente escena (sin huecos).
- Dentro de cada escena, las palabras, elementos de lista y barras aparecen en el instante de su palabra.
- Los subtítulos se resaltan palabra a palabra.

### Tipos de escena (detección heurística)

| Tipo | Cuándo se elige | Animación |
|---|---|---|
| Texto cinético (`title`) | Frase normal | Palabras clave resaltadas; cada palabra entra en su momento |
| Cifra destacada (`stat`) | Número con %, €, $, k, M… | Cifra en grande con barra si es porcentaje |
| Lista (`bullets`) | 3 o más elementos separados por comas y "y" | Cada elemento entra en su momento con número |
| Comparación (`comparison`) | "frente a", "vs", "mientras que", "en cambio", "a diferencia de" | Dos tarjetas + "VS" |
| Pregunta (`question`) | Termina en `?` | Círculo con "?" + texto |
| Cita (`quote`) | Elegida manualmente | Comilla grande + texto |

### Planificador con LLM (opcional)

Con un LLM compatible con la API de OpenAI (OpenAI, Ollama, LM Studio…) el modelo decide el tipo de escena y las palabras a resaltar según el **significado** de cada frase. No reescribe el texto ni los tiempos, así que la sincronía no se pierde. Si el LLM falla, se usa la heurística y aparece un aviso.

```bash
export MOTION_LLM_BASE_URL=http://localhost:11434/v1   # Ollama, por ejemplo
export MOTION_LLM_MODEL=llama3.1
export MOTION_LLM_API_KEY=...                           # opcional
```

## Variables de entorno

| Variable | Para qué |
|---|---|
| `MOTION_PROJECTS_DIR` | Carpeta de proyectos (por defecto `projects/`) |
| `MOTION_WHISPER_MODEL` | Modelo de Whisper por defecto |
| `FFMPEG_BIN` | Ruta a un ffmpeg propio |
| `MOTION_FONT_BOLD` / `MOTION_FONT_REGULAR` | Fuentes `.ttf` concretas (si no, busca Arial/DejaVu/Helvetica del sistema o usa una fuente integrada) |
| `MOTION_LLM_BASE_URL`, `MOTION_LLM_MODEL`, `MOTION_LLM_API_KEY` | LLM opcional para el planificador |

## Añadir un estilo

Edita `studio/styles.py` y añade un `Style(...)` con colores, animación de entrada (`slide_up`, `pop`, `fade`, `typewriter`), transición (`fade`, `slide`, `zoom`, `cut`), decoración (`grid`, `particles`, `circles`, `lines`) y opciones de tarjetas, resaltados y subtítulos. Aparecerá automáticamente en la interfaz.

## Transcripciones importadas

- `.json` con `{"words":[{"text","start","end"}]}` (formato de Whisper/WhisperX adaptado) o `{"segments":[...]}`.
- `.srt` / `.vtt`: funciona, pero sin tiempos por palabra la sincronía es aproximada (la app lo avisa).

Para probar sin audio ni Whisper: `python examples/make_demo_transcript.py > examples/demo_transcript.json` (ya incluido) y súbelo como transcripción.

## Estructura

```
app.py                 arranque (uvicorn)
studio/
  config.py            rutas, formatos, ffmpeg, configuración LLM
  transcript.py        modelo de palabras con tiempos + lectores JSON/SRT/VTT
  transcribe.py        faster-whisper (word_timestamps)
  planner.py           frases -> escenas (tipo, tokens con tiempos, reparto de tiempos)
  llm.py               clasificador opcional con LLM
  styles.py            estilos visuales
  renderer.py          motor de frames (Pillow) + ffmpeg
  pipeline.py          proyecto: analizar -> editar plan -> renderizar
  server.py            API FastAPI
web/                   interfaz (HTML + JS sin dependencias)
tests/                 pruebas (pytest)
examples/              transcripción de demostración
```

## API

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/meta` | Estilos, modelos, formatos, estado del LLM |
| POST | `/api/projects` | Crea proyecto (audio y/o transcripción) y lanza el análisis |
| GET | `/api/projects/{id}` | Proyecto, transcripción y plan |
| PUT | `/api/projects/{id}/plan` | Cambia tipo/resaltados de escenas |
| POST | `/api/projects/{id}/render` | Lanza el render con estilo y formato |
| GET | `/api/jobs/{job}` | Progreso de un trabajo |
| GET | `/api/projects/{id}/files/{name}` | Descarga el MP4 o el audio |

## Tests

```bash
pip install pytest httpx
pytest -q
```

## Limitaciones conocidas

- Renderizado en CPU con Pillow: en el entorno de pruebas (2 vCPU) un vídeo de 40 s a 1080p tardó unos 35 s. Usa 720p para borradores.
- Las escenas se generan una por frase: frases muy largas se parten por comas, pero no se reescriben.
- La detección heurística es sencilla (reglas en español e inglés). Para un guion complejo, conviene el planificador LLM o ajustar los tipos en la tabla.
- Sin voz en off generada: la app usa tu audio. Si quieres voz sintética, genera el audio con tu herramienta favorita y súbelo.
- Licencias: Whisper (MIT), faster-whisper (MIT), Pillow (HPND), FFmpeg (LGPL/GPL según build). Revisa la licencia de las fuentes que uses.
