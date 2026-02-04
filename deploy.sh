#!/bin/bash
set -e

# Configuration
SERVER_IP="95.81.99.222"
SERVER_USER="root"
DEPLOY_PATH="/opt/wp-seo"

echo "🚀 Starting deployment to $SERVER_IP..."
echo ""

# Ask user if they want to copy settings and secrets
echo "📋 Configuration options:"
read -p "Copy settings.json to server? (y/n): " copy_settings
read -p "Copy secrets/ folder to server? (y/n): " copy_secrets
echo ""

# Create deployment directory on server
echo "📁 Creating deployment directory on server..."
ssh ${SERVER_USER}@${SERVER_IP} "mkdir -p ${DEPLOY_PATH}"

# Copy project files, excluding unnecessary files
echo "📦 Copying project files to server..."

# Build exclude list
EXCLUDES=(
  '--exclude=.git'
  '--exclude=.venv'
  '--exclude=__pycache__'
  '--exclude=*.pyc'
  '--exclude=.DS_Store'
  '--exclude=content_hub.sqlite3'
  '--exclude=*.session-journal'
)

# Conditionally exclude settings and secrets
if [ "$copy_settings" != "y" ]; then
  EXCLUDES+=('--exclude=settings.json')
  echo "⚠️  Skipping settings.json"
fi

if [ "$copy_secrets" != "y" ]; then
  EXCLUDES+=('--exclude=secrets')
  echo "⚠️  Skipping secrets/"
fi

rsync -avz --progress \
  "${EXCLUDES[@]}" \
  ./ ${SERVER_USER}@${SERVER_IP}:${DEPLOY_PATH}/

# Check if Docker is installed on the server
echo ""
echo "🐳 Checking Docker installation..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Docker Compose not found. Installing Docker Compose plugin..."
    apt-get update
    apt-get install -y docker-compose-plugin
fi

echo "✅ Docker is ready"
ENDSSH

# Create settings.json if it doesn't exist
echo ""
echo "⚙️ Checking configuration on server..."
ssh ${SERVER_USER}@${SERVER_IP} << ENDSSH
cd ${DEPLOY_PATH}

# Create secrets directory if it doesn't exist
mkdir -p secrets

# Check settings.json
if [ ! -f settings.json ]; then
    echo "Creating settings.json from template..."
    cp settings.example.json settings.json
    echo "⚠️  WARNING: Please configure settings.json before starting services!"
else
    echo "✅ settings.json exists"
fi
ENDSSH

# Deploy and start services
echo ""
echo "🚢 Deploying and starting services..."
ssh ${SERVER_USER}@${SERVER_IP} << ENDSSH
cd ${DEPLOY_PATH}
echo "Building and starting containers..."
docker compose down 2>/dev/null || true
docker compose up -d --build

echo ""
echo "⏳ Waiting for services to start..."
sleep 5

echo ""
echo "📊 Container status:"
docker compose ps

echo ""
echo "✅ Services started successfully!"
ENDSSH

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deployment completed successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🌐 Access the app at: http://${SERVER_IP}:8501"
echo ""
echo "📝 Useful commands:"
echo "  • View Streamlit logs:  docker compose logs -f app"
echo "  • View Autopilot logs:  docker compose logs -f autopilot"
echo "  • Restart services:     docker compose restart"
echo "  • Stop services:        docker compose down"
echo ""

if [ "$copy_settings" != "y" ] || [ "$copy_secrets" != "y" ]; then
  echo "⚠️  IMPORTANT: You skipped copying some configuration files!"
  echo ""
  if [ "$copy_settings" != "y" ]; then
    echo "  • Configure settings.json on the server:"
    echo "    ssh ${SERVER_USER}@${SERVER_IP}"
    echo "    cd ${DEPLOY_PATH}"
    echo "    nano settings.json"
  fi
  if [ "$copy_secrets" != "y" ]; then
    echo "  • Copy secrets to server manually:"
    echo "    scp -r ./secrets ${SERVER_USER}@${SERVER_IP}:${DEPLOY_PATH}/"
  fi
  echo ""
  echo "  • Then restart services:"
  echo "    docker compose restart"
  echo ""
fi

echo "📖 For detailed instructions, see INSTRUCTION.md"

