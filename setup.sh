#!/bin/bash
# =============================================
# Setup rapido de OpenClaw con WhatsApp
# =============================================

set -e

echo "=== OpenClaw + WhatsApp Setup ==="
echo ""

# 1. Verificar Docker
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker no esta instalado."
    echo "Instala Docker desde: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose v2 no esta disponible."
    exit 1
fi

echo "[OK] Docker y Docker Compose detectados"

# 2. Verificar .env
if [ ! -f .env ]; then
    echo ""
    echo "No se encontro archivo .env"
    echo "Copiando .env.example a .env ..."
    cp .env.example .env
    echo "IMPORTANTE: Edita el archivo .env con tu ANTHROPIC_API_KEY"
    echo "  nano .env"
    exit 1
fi

echo "[OK] Archivo .env encontrado"

# 3. Crear directorios
mkdir -p openclaw-config openclaw-workspace

# 4. Descargar imagen y levantar gateway
echo ""
echo "Descargando imagen de OpenClaw..."
docker compose pull openclaw-gateway

echo ""
echo "Iniciando gateway..."
docker compose up -d openclaw-gateway

echo ""
echo "Esperando que el gateway este listo..."
sleep 5

# 5. Onboarding
echo ""
echo "=== Configuracion inicial ==="
echo "Ejecuta el onboarding interactivo:"
echo "  docker compose run --rm openclaw-cli onboard"
echo ""

# 6. Conectar WhatsApp
echo "=== Conectar WhatsApp ==="
echo "Despues del onboarding, conecta WhatsApp con:"
echo "  docker compose run --rm openclaw-cli channels login"
echo ""
echo "Esto mostrara un codigo QR que debes escanear"
echo "con tu telefono desde WhatsApp > Dispositivos vinculados."
echo ""

echo "=== Interfaz Web ==="
echo "Dashboard disponible en: http://localhost:18789/"
echo ""
echo "Setup completado. Sigue los pasos anteriores para finalizar."
