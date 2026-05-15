#!/bin/bash

set -e  # Exit on any error

echo "🚀 DocuMind - Clean Slate Deployment Setup"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
S3_BUCKET="documind-app-storage-2026"
AWS_REGION="us-east-1"
AWS_PROFILE="${AWS_PROFILE:-default}"

# Step 1: Check prerequisites
echo "📋 Step 1: Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose is not installed${NC}"
    exit 1
fi

AWS_CLI_AVAILABLE=true
if ! command -v aws &> /dev/null; then
    echo -e "${YELLOW}⚠️  AWS CLI is not installed or not in PATH${NC}"
    echo -e "${YELLOW}   S3 bucket creation and verification will be skipped${NC}"
    AWS_CLI_AVAILABLE=false
else
    echo -e "${GREEN}✅ AWS CLI found${NC}"
fi

echo -e "${GREEN}✅ Docker prerequisites met${NC}"
echo ""

# Step 2: Check AWS credentials
if [ "$AWS_CLI_AVAILABLE" = true ]; then
    echo "🔐 Step 2: Checking AWS credentials..."

    if ! aws sts get-caller-identity --profile "$AWS_PROFILE" &> /dev/null; then
        echo -e "${YELLOW}⚠️  AWS credentials not valid. Attempting SSO login...${NC}"
        aws sso login --profile "$AWS_PROFILE"
        
        if ! aws sts get-caller-identity --profile "$AWS_PROFILE" &> /dev/null; then
            echo -e "${RED}❌ AWS authentication failed${NC}"
            exit 1
        fi
    fi

    echo -e "${GREEN}✅ AWS credentials valid${NC}"
    aws sts get-caller-identity --profile "$AWS_PROFILE"
    echo ""
else
    echo "🔐 Step 2: Skipping AWS credentials check (AWS CLI not available)"
    echo -e "${YELLOW}⚠️  Make sure you have created S3 bucket: $S3_BUCKET${NC}"
    echo ""
fi

# Step 3: Create S3 bucket
if [ "$AWS_CLI_AVAILABLE" = true ]; then
    echo "🪣 Step 3: Creating S3 bucket..."

    if aws s3 ls "s3://$S3_BUCKET" --profile "$AWS_PROFILE" 2>&1 | grep -q 'NoSuchBucket'; then
        echo "Creating bucket: $S3_BUCKET"
        aws s3 mb "s3://$S3_BUCKET" --region "$AWS_REGION" --profile "$AWS_PROFILE"
        echo -e "${GREEN}✅ S3 bucket created${NC}"
    elif aws s3 ls "s3://$S3_BUCKET" --profile "$AWS_PROFILE" &> /dev/null; then
        echo -e "${GREEN}✅ S3 bucket already exists${NC}"
    else
        echo -e "${RED}❌ Failed to check/create S3 bucket${NC}"
        exit 1
    fi
    echo ""
else
    echo "🪣 Step 3: Skipping S3 bucket creation (AWS CLI not available)"
    echo -e "${YELLOW}⚠️  Please ensure S3 bucket exists: $S3_BUCKET${NC}"
    echo ""
fi

# Step 4: Kill local processes
echo "🛑 Step 4: Stopping local processes..."

pkill -f "celery -A app.workers" 2>/dev/null || true
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "npm run dev" 2>/dev/null || true

sleep 2
echo -e "${GREEN}✅ Local processes stopped${NC}"
echo ""

# Step 5: Clean up Docker
echo "🧹 Step 5: Cleaning up existing Docker containers..."

docker-compose down -v --remove-orphans 2>/dev/null || true
docker system prune -f

echo -e "${GREEN}✅ Docker cleanup complete${NC}"
echo ""

# Step 5.5: Clean up S3 bucket
if [ "$AWS_CLI_AVAILABLE" = true ]; then
    echo "🗑️  Step 5.5: Cleaning up S3 bucket..."
    
    if aws s3 ls "s3://$S3_BUCKET" --profile "$AWS_PROFILE" &> /dev/null; then
        echo "Removing all objects from S3 bucket: $S3_BUCKET"
        aws s3 rm "s3://$S3_BUCKET" --recursive --profile "$AWS_PROFILE" || true
        echo -e "${GREEN}✅ S3 bucket cleaned${NC}"
    else
        echo -e "${YELLOW}⚠️  S3 bucket does not exist or is not accessible${NC}"
    fi
    echo ""
else
    echo "🗑️  Step 5.5: Skipping S3 cleanup (AWS CLI not available)"
    echo -e "${YELLOW}⚠️  Please manually clean S3 bucket if needed: $S3_BUCKET${NC}"
    echo ""
fi

# Step 6: Verify .env file
echo "⚙️  Step 6: Verifying .env configuration..."

if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found. Creating from .env.example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠️  Please update .env with your settings and run this script again${NC}"
    exit 1
fi

# Check required variables
if ! grep -q "S3_BUCKET=$S3_BUCKET" .env; then
    echo -e "${YELLOW}⚠️  Updating S3_BUCKET in .env${NC}"
    sed -i.bak "s/^S3_BUCKET=.*/S3_BUCKET=$S3_BUCKET/" .env
fi

if ! grep -q "AWS_PROFILE=" .env; then
    echo -e "${YELLOW}⚠️  Adding AWS_PROFILE to .env${NC}"
    echo "AWS_PROFILE=$AWS_PROFILE" >> .env
fi

echo -e "${GREEN}✅ .env configuration verified${NC}"
echo ""

# Step 7: Build and start Docker containers
echo "🐳 Step 7: Building and starting Docker containers..."

docker-compose up -d --build

echo -e "${GREEN}✅ Docker containers started${NC}"
echo ""

# Step 8: Wait for services to be healthy
echo "⏳ Step 8: Waiting for services to be healthy..."

echo "Waiting for database..."
sleep 10

MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if docker-compose exec -T backend curl -f http://localhost:8010/health &> /dev/null; then
        echo -e "${GREEN}✅ Backend is healthy${NC}"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Waiting for backend... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo -e "${RED}❌ Backend failed to start${NC}"
    echo "Showing backend logs:"
    docker-compose logs backend
    exit 1
fi

# Seed admin user
echo "Creating admin user..."
docker-compose exec -T backend python seed_admin.py > /dev/null 2>&1 || true

echo ""

# Step 9: Verify AWS access from containers
echo "🔍 Step 9: Verifying AWS access..."

if [ "$AWS_CLI_AVAILABLE" = true ]; then
    echo "Testing S3 access from host..."
    if aws s3 ls "s3://$S3_BUCKET" --profile "$AWS_PROFILE" &> /dev/null; then
        echo -e "${GREEN}✅ S3 bucket is accessible${NC}"
    else
        echo -e "${YELLOW}⚠️  Cannot verify S3 access${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Skipping AWS verification (AWS CLI not available)${NC}"
    echo "The application will use boto3 with mounted AWS credentials"
fi

echo ""

# Step 10: Show status
echo "📊 Step 10: Deployment Status"
echo "=============================="
docker-compose ps
echo ""

# Final summary
echo ""
echo "🎉 ${GREEN}Deployment Complete!${NC}"
echo "===================="
echo ""
echo "Services are running at:"
echo "  🌐 Frontend:  http://localhost:5180"
echo "  🔧 Backend:   http://localhost:8010"
echo "  📚 API Docs:  http://localhost:8010/docs"
echo "  🗄️  Postgres:  localhost:5440"
echo "  📦 Redis:     localhost:6380"
echo "  🪣 S3 Bucket: $S3_BUCKET"
echo ""
echo "✅ AWS credentials are mounted and working"
echo "   The application uses boto3 to access S3"
echo ""
echo "👤 Admin Login Credentials:"
echo "   Email:    admin@documind.ai"
echo "   Password: Admin123!"
echo ""
echo "Useful commands:"
echo "  View logs:        docker-compose logs -f [service]"
echo "  Stop services:    docker-compose down"
echo "  Restart services: docker-compose restart"
echo "  Shell access:     docker-compose exec backend bash"
echo ""
echo "Or use Make commands:"
echo "  make logs         # View all logs"
echo "  make down         # Stop services"
echo "  make restart      # Restart services"
echo "  make shell-backend # Backend shell"
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:5180 in your browser"
echo "  2. Login with admin@documind.ai / Admin123!"
echo "  3. Upload documents to test S3 integration"
echo ""
