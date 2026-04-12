# PC Optimizer AI - Railway Deployment

## Quick Deploy

1. **Create Railway Project:**
   - Go to [Railway](https://railway.com)
   - Click "New Project" → "Empty Project"

2. **Add GitHub Repo:**
   - Connect your GitHub account
   - Select this repository

3. **Deploy:**
   - Railway will auto-detect Python/FastAPI
   - Click "Deploy"

4. **Get URL:**
   - Go to Settings → Networking
   - Click "Generate Domain"

---

## Local Development

```bash
cd pc-optimizer-cloud
pip install -r requirements.txt
python main.py
# Open http://localhost:8000
```

---

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `PORT` | Server port (auto-set by Railway) | No |
| `DATABASE_URL` | PostgreSQL connection string | Yes (for production) |
| `OLLAMA_URL` | Ollama API URL for AI | No |
| `SECRET_KEY` | JWT secret key | Recommended |
| `OPENAI_API_KEY` | OpenAI API for cloud AI | No |

---

## Database Setup (PostgreSQL)

1. In Railway dashboard, click "New" → "Database" → "PostgreSQL"
2. Copy the connection URL
3. Add as `DATABASE_URL` environment variable

---

## Project Structure

```
pc-optimizer-cloud/
├── main.py           # FastAPI application
├── requirements.txt  # Python dependencies
├── railway.json      # Railway configuration
├── Dockerfile        # Container configuration
├── .env.example      # Environment template
├── static/
│   └── index.html    # Dashboard frontend
└── README.md
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard |
| `/health` | GET | Health check |
| `/devices` | GET | List devices |
| `/command` | POST | Send command to device |
| `/execute/{device_id}/{task}` | POST | Execute task |
| `/analyze` | POST | AI analysis |
| `/device/{id}/history` | GET | Device history |

---

## Notes

- On Railway, tasks are **simulated** (mock data) since the agent runs locally
- For full functionality, the agent must run on each client PC
- The agent connects to this cloud API over the internet