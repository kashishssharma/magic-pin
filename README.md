# Kashish Vera Bot — magicpin AI Challenge

## Architecture
4-context deterministic composition engine:
- **CategoryContext** — vertical voice, offer catalog, peer stats
- **MerchantContext** — salutation, language, performance metrics
- **TriggerContext** — "why now" specificity anchor
- **CustomerContext** — recall/appointment outreach on merchant's behalf

## Multi-turn Intelligence
- Auto-reply detection → graceful exit
- Intent transition → immediate action (no re-qualifying)
- Opt-out/hostile detection → polite end

## API Endpoints
- `GET /v1/healthz`
- `GET /v1/metadata`
- `POST /v1/context`
- `POST /v1/tick`
- `POST /v1/reply`

## Deploy to Render
```bash
# Just connect your GitHub repo on render.com
# It auto-reads render.yaml and deploys
```

## Local Run
```bash
pip install -r requirements.txt
uvicorn bot:app --host 0.0.0.0 --port 8080
```
