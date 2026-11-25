# LyftrAI — Full-stack chatbot assignment

## 1. Live URLs
- Frontend: add your Vercel URL
- Backend: add your Render URL

## 2. Run locally: with Docker and without
### Docker
1. Copy `.env.example` to `.env` and add two Gemini API keys (comma-separated).
2. `make up` — UI at http://localhost:3000 and API at http://localhost:8000.
3. `make down` stops services.

### Without Docker
Backend: create venv, `pip install -r backend/requirements.txt`, set environment variables, run `uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000`.
Frontend: `cd frontend`, `npm install`, set `VITE_API_URL`, `npm run dev`.

## 3. Design decisions: key fallback, caching, SQLite session storage
LiteLLM is used for provider requests and cache support. A sequential key pool attempts configured API keys and retries the next key when a provider call fails. SQLite persists session messages and metadata. Cache keys are hashes of model + full prompt/message list.

## 4. Verification: how to see failover, cache hits and per-message token usage
Send a prompt, then repeat the identical first prompt in a fresh session to see cache behavior. On the deployed API, use the `X-Simulate-Failure: key_1=429` header while failure simulation is enabled to verify fallback. Each assistant response displays source, model, latency, per-request input/output token counts, and fallback count.

## 5. Setup Used: your editor and AI tools
Document the tools you used here.

## 6. Bonus features (if any): what you added beyond the requirements and why
Optional system prompt, failover test button, responsive dark UI, and response cache table.

## Deploy
### Render
Deploy the repository as a Docker web service. Set `LLM_API_KEYS`, `LLM_MODEL`, `DATABASE_URL=sqlite:////data/app.db`, `ALLOWED_ORIGINS` to your Vercel URL, and `ENABLE_FAILURE_SIMULATION=true`. **Note:** Render's free web services may not provide persistent disks; attach a disk mounted at `/data` to ensure SQLite history persists across deploys/restarts.

### Vercel
Import the `frontend` folder as the project root. Add `VITE_API_URL` with your Render service URL (no trailing slash). Redeploy after setting it. Add your Vercel origin to Render `ALLOWED_ORIGINS`.
