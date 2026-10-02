# Deploying to Google Cloud Run

One container (see `Dockerfile`) runs both servers: the public FastAPI app and the MCP server, which stays on
localhost inside the container. Secrets come from the environment at runtime and are never built into the image.

## Try the image locally with Docker

```bash
docker build -t relaypay-support .
docker run --rm -p 8080:8080 --env-file .env -e HOST=0.0.0.0 -e PORT=8080 -e LOG_FILE= -e DATABASE_SCHEMA=test relaypay-support
# check: http://127.0.0.1:8080/health/ready  →  {"status":"ok","database":"ok"}
```

## Deploy

The example uses region `europe-west1`, close to a Supabase project in `eu-west-1`. Pick the region nearest your
database.

1. Enable the APIs:
   `gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com`
2. In **Secret Manager**, create one secret per value: `ANTHROPIC_API_KEY`, `DATABASE_URL`, `VAPI_LLM_SECRET`,
   `MCP_AUTH_TOKEN` and `CONSOLE_SESSION_SECRET`. Give the Cloud Run service account the
   **Secret Manager Secret Accessor** role.
3. Deploy:

   ```bash
   gcloud run deploy relaypay-support --source . --region europe-west1 --allow-unauthenticated \
     --min-instances 1 --max-instances 1 --no-cpu-throttling --cpu 2 --memory 4Gi --timeout 300 \
     --set-secrets "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,DATABASE_URL=DATABASE_URL:latest,VAPI_LLM_SECRET=VAPI_LLM_SECRET:latest,MCP_AUTH_TOKEN=MCP_AUTH_TOKEN:latest,CONSOLE_SESSION_SECRET=CONSOLE_SESSION_SECRET:latest" \
     --set-env-vars "DATABASE_SCHEMA=public,AGENT_MODEL=claude-haiku-4-5-20251001,AGENT_MAX_SESSIONS=3,VAPI_PUBLIC_KEY=<public key>,VAPI_ASSISTANT_ID=<assistant id>"
   ```

4. Set the base URL used in invite links to the service URL the deploy prints:
   `gcloud run services update relaypay-support --region europe-west1 --update-env-vars PUBLIC_BASE_URL=https://<service-url>`
5. In Vapi, point the Custom LLM URL and the server URL (`/vapi/events`) at the service URL.
6. Create the console owner on the real tables: `DATABASE_SCHEMA=public poetry run relaypay-admin --email owner@example.com`,
   then open the printed link.

## Why these settings

- **One instance:** each call's agent session, the per-call limits and the rate limits are kept in memory.
- **CPU always allocated:** call records are written after each response is sent.
- **Minimum one instance:** the first call of the day has no cold start.
- **4 GiB and 2 vCPU:** room for about three concurrent agent sessions.

## After deploying

- Restrict Vapi's public key to the site's domain and the assistant in the Vapi dashboard.
- Check `https://<service-url>/health/ready` returns `{"status":"ok","database":"ok"}`.
