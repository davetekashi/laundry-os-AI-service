# Cloudflare Container Deployment

The FastAPI service runs inside one Cloudflare Container. Its associated Durable Object stores prepared context and Anne conversation history, allowing the container to sleep without losing either.

## Required Cloudflare secrets

Configure these under the Worker's **Settings > Variables and Secrets** as encrypted secrets:

- `OPENAI_API_KEY`
- `MONGODB_URI`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_ENDPOINT`
- `R2_BUCKET_NAME`
- `RUNTIME_STATE_TOKEN` (a new long random value shared only between the Worker and container)

Optional model overrides can be configured as ordinary variables:

- `OPENAI_VISION_MODEL`
- `OPENAI_MATCHING_MODEL`
- `OPENAI_CHAT_MODEL`
- `OPENAI_ANNE_MODEL`

If omitted, the defaults in `app/core/config.py` are used.

## Deployment

Docker Desktop must be running because Wrangler builds and uploads the container image.

```bash
npm install
npx wrangler login
npx wrangler deploy
```

After deployment, allow several minutes for the first container rollout, then verify:

```bash
curl https://laundry-os-ai-service.<workers-subdomain>.workers.dev/health
```

The expected response is `{"status":"ok"}`. Swagger remains available at `/docs`.

## Runtime behavior

- `/api/v1/context/prepare` reads current business data from MongoDB, builds the snapshot, and persists it in the Durable Object.
- `/api/v1/chat` uses the live in-container cache while the container is awake.
- After a container restart or sleep, the Worker restores the required context and conversation from Durable Object storage before forwarding the chat request.
- Every completed chat turn is persisted to the Durable Object. Chat turns do not write to MongoDB.
- Calling `/prepare` again replaces that scope's snapshot and removes its previous conversations.
