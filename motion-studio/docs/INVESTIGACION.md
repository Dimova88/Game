# Investigación: repositorios para motion graphics faceless

Búsqueda realizada en GitHub y la web (octubre 2026). Datos de GitHub obtenidos vía API el 22/10/2026.

## Resumen

| Proyecto | Enfoque | Licencia | ★ | Qué aprovechamos / por qué no lo usamos directamente |
|---|---|---|---|---|
| [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) | Sistema agentic completo de producción de vídeo (12 pipelines, Remotion/HyperFrames) | AGPL-3.0 | 70 859 | Muy completo, pero es un sistema de agente enorme y AGPL. Referencia de arquitectura por etapas. |
| [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | Vídeo programático en React | Propietaria (gratis para particulares y pequeñas empresas) | 66 332 | Motor de render de referencia. Necesita Node y Chrome; lo descartamos para una app Python testable en local. |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | Whisper + alineación forzada por palabra | BSD-2-Clause | 24 783 | Tiempos por palabra muy precisos, con diarización. Lo dejamos como mejora futura (requiere más dependencias). |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Whisper con CTranslate2, rápido en CPU | MIT | 26 052 | **Elegido** para transcribir con `word_timestamps`. |
| [francozanardi/pycaps](https://github.com/francozanardi/pycaps) | Subtítulos animados con Python y CSS | MIT | 230 | Buena referencia de subtítulos animados; no genera motion graphics a partir del contenido. |
| [philippprimisser-max/whisper-word-captions](https://github.com/philippprimisser-max/whisper-word-captions) | Subtítulos palabra a palabra con faster-whisper + ASS | MIT | 0 | Ejemplo claro de agrupar palabras y resaltar la activa. Inspiró la lógica de subtítulos. |
| [thegreatLUCY/voiceover-motion-graphics](https://github.com/thegreatLUCY/voiceover-motion-graphics) | Skill de agente: HTML+GSAP sincronizado con faster-whisper | MIT | 0 | Idea clave: cada animación se dispara en la palabra hablada. |
| [AhmedSafwat97/Video-MotionGraphics](https://github.com/AhmedSafwat97/Video-MotionGraphics) | Pipeline Remotion + Whisper + FFmpeg; escenas con palabra clave | Sin licencia declarada | 0 | Confirma el patrón storyboard → timeline por palabra clave. |
| [floomhq/opencut](https://github.com/floomhq/opencut) | Edición de vídeo en código con Whisper y Remotion | MIT | 7 | Referencia de transcripción → subtítulos en un pipeline de render. |
| [oriastanjung/caption-your-video](https://github.com/oriastanjung/caption-your-video) | Subtítulos animados con Whisper local y LLM para planificar | MIT | 2 | Muestra un LLM que decide la presentación; nuestra opción LLM sigue la misma idea, sin reescribir el texto. |
| [matheus-giordani/purffle-shorts](https://github.com/matheus-giordani/purffle-shorts) | Generador de Shorts faceless (guion, voz, b-roll, subtítulos) | — | — | Ejemplo de pipeline faceless completo; orientado a generar el guion, no a animar una narración existente. |

## Conclusiones para esta app

1. **Casi todo lo que existe** se divide en dos grupos: (a) subtítulos animados palabra a palabra, o (b) motores de render programático (Remotion) que requieren escribir cada escena a mano. Ninguno hace bien las dos cosas de forma automática y sin dependencias pesadas.
2. Por eso construimos un **planificador de escenas** que convierte la transcripción en escenas tipadas (cifra, lista, comparación, pregunta, texto) y un **motor de render propio** en Python que sincroniza cada animación con su palabra.
3. **Stack elegido**: FastAPI + faster-whisper (`word_timestamps`) + Pillow + ffmpeg. Se instala con `pip` y no requiere Node ni navegador headless.
4. **Mejoras futuras** tomadas de los proyectos revisados: alineación forzada con WhisperX, diarización para vídeos con dos voces, y un renderizador HTML/GSAP si se quieren efectos más complejos.
