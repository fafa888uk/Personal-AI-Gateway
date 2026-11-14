# Personal AI Gateway — Web Chat

Next.js 15 (App Router) + TypeScript + Tailwind CSS v4 web client for the
Personal AI Gateway. Talks only to the gateway — never to an upstream
provider, and never holds an upstream OpenAI key.

## Run

```bash
cd apps/web
npm install
npm run dev        # http://localhost:3000
```

Default gateway URL is `http://localhost:8000` (override with
`NEXT_PUBLIC_GATEWAY_URL`). Start the local gateway first — see
`apps/api/README.md` (seed a dev client key with
`python -m gateway.seed_dev` from `apps/api`).

## Commands

```bash
npm run dev        # development server
npm run build      # production build
npm start          # serve the production build
npm test           # vitest unit + component tests (mocked fetch, no network)
npm run lint       # eslint (flat config, see eslint.config.mjs)
npm run typecheck  # tsc --noEmit
```

## How it works

- Login (`/`): enter the gateway address + gateway client key
  (`pag_sk_...`). Validation is a real `GET /v1/models` call — on failure
  the exact gateway error message is shown. On success the credentials
  are stored in **localStorage only** (base URL + client key) and the user
  goes to `/chat`. Logout clears them.
- Chat (`/chat`): sidebar (search, inline rename, two-step delete) +
  model picker (GET /v1/models, honest "暂无可用模型" empty state) +
  message list (Markdown GFM + highlighted code blocks with copy,
  per-message tokens) + composer (Enter send / Shift+Enter newline,
  Stop aborts the stream) + usage bar + version banner. Sending
  creates a session on the first message (title = first 24 chars);
  replies stream live via `streamChatCompletion` and are saved with
  their token counts; errors show an inline card with the exact
  gateway message + 重试; 重新生成 re-sends the last user turn;
  编辑重发 truncates local history at the edited message.
  Sync is v1 full pull: sessions + messages are re-fetched whole on
  load and after mutations; the server hard-deletes, there is no
  incremental sync or tombstones.
- Edit/regenerate honesty: the gateway has no truncate or
  message-delete endpoint, so edit/regenerate apply locally and only
  the new assistant reply is saved server-side; superseded messages
  stay in server history and may reappear on a fresh full pull
  (e.g. after reload). Nothing claims server-side truncation.
- File/image input is deferred (Phase 2): the composer has no
  attachment button, pending real model capability support.
- `src/lib/chat.ts` — pure helpers (title truncation, scroll-at-bottom,
  token line, cost-status labels copied from the Flutter UsageSummary
  model: a dollar figure is shown only when `cost_status` is "ok").
- `src/lib/theme.ts` — light/dark toggle persisted in localStorage
  (`pag.theme`), defaulting to the OS preference.
- `src/lib/version.ts` — `WEB_VERSION` ("0.1.1", matches package.json),
  compared against the server-reported `web` release by VersionBanner.
- UsageBar: today + month from GET /api/v1/usage/summary; cost is
  shown only when exact, otherwise the Flutter status label.
- VersionBanner: public GET /api/v1/app/version; renders nothing
  when `configured: false`; when the server's `web` release is newer
  it shows version + notes + "刷新获取新版" (SW SKIP_WAITING +
  reload).
- `src/lib/api.ts` — gateway client: `Authorization: Bearer <key>` on
  every authed call; `GET /api/v1/app/version` is public (no auth
  header). Non-streaming + streaming (`fetch` + `ReadableStream` +
  `AbortController`; abort = stop) `POST /v1/chat/completions`.
- `src/lib/sse.ts` — incremental SSE parser (mirrors the Flutter
  `sse.dart` semantics: delta, `[DONE]`, error events, split chunks,
  comments ignored).
- `src/lib/semver.ts` — version comparison for the update prompt.
- `src/lib/export.ts` — session export to Markdown / JSON.
- PWA: `public/manifest.webmanifest`, `public/sw.js` (versioned cache
  `pag-v1`; cache-first for same-origin static assets, network-first for
  `/api` and navigation), `public/icon-180.png` (Apple touch icon) +
  `public/icon.svg`. The service worker registers only in production.

## Known gaps (this stage)

- No icon larger than 180×180 is shipped; the manifest lists the 180px
  PNG for both 180 and 192 entries.
- Edit/regenerate are local-only truncations (see above): superseded
  messages remain in server history until a truncate/delete endpoint
  exists.
- File/image input is Phase 2, pending real model capability support.
