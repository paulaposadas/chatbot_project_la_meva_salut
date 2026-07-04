# Cómo desplegar "La Meva Salut" como demo online

Este chatbot necesita 2 servidores corriendo (Rasa + Actions) más una página
web de chat. Aquí están los pasos completos usando **Render.com** (tiene plan
gratuito, aunque los servicios gratuitos "duermen" tras 15 min sin uso — la
primera respuesta tras estar dormido puede tardar ~1 minuto en despertar).

## 0. Requisitos que ya tienes
- ✅ Licencia de Rasa Pro
- ⬜ Una API key de Anthropic (la necesitas para `ANTHROPIC_API_KEY`,
  se genera en https://console.anthropic.com/settings/keys)

## 1. Sube el proyecto a GitHub
Sube TODA la carpeta `medical_chatbot` (incluyendo los Dockerfiles nuevos,
`.dockerignore`, `endpoints.yml` y `credentials.yml` actualizados) a un
repositorio de GitHub. Este repo puede ser privado si prefieres, ya que
contiene lógica de tu proyecto (Render puede conectarse a repos privados).

**No subas tu API key ni tu licencia directamente en los archivos** — se
configuran como variables de entorno en Render (paso 3), nunca en el código.

## 2. Crea el servicio de Actions en Render
1. Ve a https://render.com → New → Web Service
2. Conecta tu repositorio de GitHub
3. En "Runtime" elige **Docker**
4. En "Dockerfile Path" pon: `Dockerfile.actions`
5. Nombre sugerido: `medical-chatbot-actions`
6. En "Environment Variables" añade:
   - `ANTHROPIC_API_KEY` = tu api key de Anthropic
7. Deploy. Cuando termine, copia la URL pública (algo como
   `https://medical-chatbot-actions.onrender.com`)

## 3. Crea el servicio de Rasa en Render
1. New → Web Service (mismo repo)
2. Runtime: **Docker**
3. Dockerfile Path: `Dockerfile.rasa`
4. Nombre sugerido: `medical-chatbot-rasa`
5. Environment Variables:
   - `RASA_PRO_LICENSE` = tu licencia de Rasa Pro
   - `ACTIONS_SERVER_URL` = `https://medical-chatbot-actions.onrender.com/webhook`
     (la URL del paso 2, con `/webhook` al final)
6. Deploy (el build tardará varios minutos porque entrena el modelo)

## 4. Conecta el frontend
1. Abre `deploy/index.html`
2. Cambia esta línea con la URL de tu servicio de Rasa del paso 3:
   ```js
   const RASA_SERVER_URL = "https://medical-chatbot-rasa.onrender.com";
   ```
3. Sube ese `index.html` a un repositorio (puede ser otro repo, o una carpeta
   `docs/` del mismo) y activa GitHub Pages apuntando a él — igual que
   hicimos con Simi Bot.

## 5. Prueba
Abre tu página de GitHub Pages. Debería aparecer un botón de chat abajo a la
derecha (el widget de rasa-webchat). Si el mensaje de estado dice que no se
pudo conectar, espera 1 minuto (el servicio gratuito de Render puede estar
"despertando") y recarga.

## Notas importantes
- **Costos**: Render gratis tiene límites de horas/mes y los servicios se
  duermen. Para una demo puntual (ej. presentación de clase) es suficiente.
- **Privacidad**: este bot recoge datos de salud simulados para la demo.
  Si vas a compartir el link públicamente, añade un aviso visible de que es
  un proyecto académico y que no se debe introducir información médica real.
- Si `rasa train` falla en el build de Render por falta de memoria, puede
  que necesites subir el modelo ya entrenado (`models/*.tar.gz`) al repo
  en vez de entrenarlo en el build, y cambiar el `CMD` del Dockerfile.rasa
  para usar ese modelo directamente.
