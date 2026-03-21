# EZ
Info Comercial EZ

## OpenClaw + WhatsApp Integration

Asistente AI personal conectado a WhatsApp usando [OpenClaw](https://github.com/openclaw/openclaw) con Docker.

### Que hace

- Recibe mensajes de WhatsApp y responde automaticamente con Claude AI
- Permite controlar el asistente desde WhatsApp
- Recibe y responde comentarios de clientes

### Requisitos

- Docker Desktop o Docker Engine + Docker Compose v2
- API Key de Anthropic ([consiguela aqui](https://console.anthropic.com/))
- Un telefono con WhatsApp

### Instalacion rapida

```bash
# 1. Clona el repositorio
git clone https://github.com/juanez2024/EZ.git
cd EZ

# 2. Configura tus credenciales
cp .env.example .env
nano .env   # Agrega tu ANTHROPIC_API_KEY

# 3. Ejecuta el setup
./setup.sh

# 4. Completa el onboarding interactivo
docker compose run --rm openclaw-cli onboard

# 5. Conecta WhatsApp (escanea el QR con tu telefono)
docker compose run --rm openclaw-cli channels login
```

### Uso diario

```bash
# Iniciar el servicio
docker compose up -d

# Ver logs
docker compose logs -f openclaw-gateway

# Detener
docker compose down

# Dashboard web
# Abre http://localhost:18789/
```

### Conectar WhatsApp

Al ejecutar `channels login`, aparecera un codigo QR en la terminal.
Escanealo desde tu telefono:

1. Abre WhatsApp en tu telefono
2. Ve a **Configuracion > Dispositivos vinculados**
3. Toca **Vincular un dispositivo**
4. Escanea el codigo QR

Una vez vinculado, el asistente respondera automaticamente a los mensajes.

### Archivos

| Archivo | Descripcion |
|---------|-------------|
| `docker-compose.yml` | Configuracion de servicios Docker |
| `.env.example` | Plantilla de variables de entorno |
| `setup.sh` | Script de instalacion rapida |
| `.gitignore` | Excluye secrets y datos locales |
