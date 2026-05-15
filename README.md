# DocuMind

AI-powered document intelligence platform with RAG and real-time quality monitoring.

## Quick Start

```bash
./setup.sh
```

This will:
- Verify AWS credentials (auto-login if needed)
- Create S3 bucket in us-east-1
- Build and start all services
- Seed admin user

## Access

- **Frontend**: http://localhost:5180
- **Backend API**: http://localhost:8010/docs
- **Admin**: admin@documind.ai / Admin123!

## Tech Stack

- **Frontend**: React, TypeScript, TailwindCSS
- **Backend**: FastAPI, PostgreSQL, Redis, Celery
- **AI**: AWS Bedrock (Claude Sonnet 4.5)
- **Storage**: AWS S3
- **Infrastructure**: Docker Compose

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Frontend | 5180 | React UI |
| Backend | 8010 | FastAPI API |
| PostgreSQL | 5440 | Database |
| Redis | 6380 | Cache/Queue |
| Celery | - | Document processing (8 workers) |

## Key Features

- Multi-format document processing (PDF, DOCX, TXT, MD)
- AI chat with document citations
- Real-time quality evaluation (DeepEval + Bedrock)
- Multi-user workspaces
- Async S3 uploads
- KB management with S3 cleanup

## Environment

Key variables in `.env`:

```bash
AWS_PROFILE=default
AWS_REGION=us-east-1
AWS_BEDROCK_REGION=us-east-1
S3_BUCKET=documind-app-storage-2026
DATABASE_URL=postgresql+asyncpg://documind:documind@localhost:5440/documind
REDIS_URL=redis://localhost:6380/0
```

## Useful Commands

```bash
make setup          # Complete setup
make up             # Start services
make down           # Stop services
make logs           # View logs
make reset          # Clean slate restart
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design details.

## Troubleshooting

**AWS Issues**
```bash
aws sso login --profile your-profile
docker-compose restart backend celery-worker
```

**Reset Everything**
```bash
./setup.sh  # Cleans S3, Docker, and restarts
```

## License

MIT
