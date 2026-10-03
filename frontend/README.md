# Frontend

Next.js (App Router) + TypeScript + Tailwind CSS UI for the Hinglish Voice Sales Agent.

| Route | Purpose |
|---|---|
| `/` | Voice agent: prompt-strategy picker, hold-to-speak mic, transcript, live STT/LLM/TTS latency |
| `/evaluation` | Benchmark dashboard: strategy comparison, charts, scenario heatmap, run controls |
| `/conversations` | Conversation explorer with filters; deep-link with `?id=<conversation id>` |

```bash
npm install
npm run dev      # http://localhost:3000
npm run lint
npm run build
```

The API base URL comes from `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). The backend must allow the frontend origin in its `CORS_ORIGINS`.

Microphone capture requires `localhost` or HTTPS. With mock providers the voice page shows a text box so the flow can be demoed without a microphone.
