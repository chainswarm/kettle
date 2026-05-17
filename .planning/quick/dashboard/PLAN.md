---
phase: quick
plan: dashboard
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard/package.json
  - dashboard/vite.config.ts
  - dashboard/tsconfig.json
  - dashboard/index.html
  - dashboard/tailwind.config.js
  - dashboard/postcss.config.js
  - dashboard/src/main.ts
  - dashboard/src/App.vue
  - dashboard/src/router/index.ts
  - dashboard/src/stores/network.ts
  - dashboard/src/stores/auth.ts
  - dashboard/src/types/index.ts
  - dashboard/src/composables/useWebSocket.ts
  - dashboard/src/views/ExplorerView.vue
  - dashboard/src/views/AdminView.vue
  - dashboard/src/views/LoginView.vue
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/components/NodeCard.vue
  - dashboard/src/components/EventFeed.vue
  - dashboard/src/components/NetworkTopology.vue
  - dashboard/src/components/OverwatchFeed.vue
  - dashboard/src/components/StatusBadge.vue
  - dashboard/src/components/AppHeader.vue
  - dashboard/Dockerfile
  - subnet/dashboard/__init__.py
  - subnet/dashboard/ws_bridge.py
  - subnet/dashboard/rest_api.py
  - subnet/dashboard/cli.py
  - docker-compose.tee-dev.yml
autonomous: false
requirements: [DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06, DASH-07]

must_haves:
  truths:
    - "Public explorer shows all connected nodes with status badges (online/offline, TEE score)"
    - "Live event feed updates in real-time as nodes publish heartbeats, TEE quotes, and work records"
    - "Clicking a node shows detail view with attestation status, hardware_id, GPU info"
    - "Overwatch activity feed shows audit results and slash events"
    - "Network topology shows which nodes are connected"
    - "Admin view requires authentication, public explorer does not"
    - "Dashboard uses white and light green color theme"
  artifacts:
    - path: "dashboard/src/App.vue"
      provides: "Vue.js 3 SPA entry point"
    - path: "subnet/dashboard/ws_bridge.py"
      provides: "WebSocket bridge from GossipSub to dashboard clients"
      exports: ["create_dashboard_app"]
    - path: "dashboard/src/stores/network.ts"
      provides: "Pinia store for node state and events"
    - path: "dashboard/src/composables/useWebSocket.ts"
      provides: "WebSocket connection composable"
  key_links:
    - from: "dashboard/src/composables/useWebSocket.ts"
      to: "subnet/dashboard/ws_bridge.py"
      via: "WebSocket connection on ws://dashboard-api:8100/ws"
      pattern: "new WebSocket.*ws"
    - from: "subnet/dashboard/ws_bridge.py"
      to: "subnet/utils/gossipsub/gossip_receiver.py"
      via: "Subscribes to same GossipSub topics and reads RocksDB nmaps"
      pattern: "nmap_get_all"
    - from: "dashboard/src/views/ExplorerView.vue"
      to: "dashboard/src/stores/network.ts"
      via: "Pinia store subscription"
      pattern: "useNetworkStore"
---

<objective>
Build a real-time monitoring dashboard for TEE subnet nodes.

Purpose: Provide visibility into the decentralized subnet — node status, GossipSub events (heartbeats, TEE quotes, work records), attestation verification, overwatch fraud detection, and network topology. Essential for operators to monitor subnet health.

Output: A Vue.js 3 + Tailwind CSS dashboard in `dashboard/` with a Python WebSocket bridge backend in `subnet/dashboard/`, integrated into docker-compose.tee-dev.yml.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/REQUIREMENTS.md
@.planning/codebase/ARCHITECTURE.md
@.planning/codebase/INTEGRATIONS.md
@docker-compose.tee-dev.yml
@subnet/utils/gossipsub/gossip_receiver.py
@subnet/utils/pubsub/heartbeat.py
@subnet/api/main.py
@subnet/api/routers/v1/nmaps.py
@subnet/utils/db/database.py

<interfaces>
<!-- Key types and contracts from the existing codebase -->

From subnet/utils/pubsub/heartbeat.py:
```python
HEARTBEAT_TOPIC = "heartbeat"

class HeartbeatData(BaseModel):
    epoch: int
    subnet_id: int
    subnet_node_id: int
    version: int = 1
    peer_id: str | None = None
    models: list[str] | None = None
    gpu: str | None = None
    gpu_uuid: str | None = None
    gpu_attested: bool = False
    tee_score: float = 0.0
    vram_total_gb: int | None = None
    vram_used_gb: int | None = None
    requests_in_flight: int = 0
    latency_p95_ms: float = 0.0
    nim_version: str | None = None
```

From subnet/tee/quote.py:
```python
TEE_QUOTE_TOPIC = "tee_quote"
RATLS_CERT_TOPIC = "ratls_cert"
```

From subnet/node/mock.py:
```python
_WORK_TOPIC = "mock_work"
```

From subnet/frontier/messages.py:
```python
# Topics: "node_join", "node_leave"
```

From subnet/utils/db/database.py:
```python
class RocksDB:
    def nmap_get(self, nmap: str, key: str, default=None) -> Any
    def nmap_set(self, nmap: str, key: str, value: Any) -> None
    def nmap_get_all(self, nmap: str) -> dict[str, Any]
```

GossipSub nmap key format: `{epoch}:{peer_id}` for all topics.

Docker Compose tee-dev services: bootnode (38960), validator (38961), miner-1 (38962), miner-2 (38963), overwatch (38964). Each node has health endpoint at :8080/health.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend WebSocket bridge + REST endpoints</name>
  <files>
    subnet/dashboard/__init__.py,
    subnet/dashboard/ws_bridge.py,
    subnet/dashboard/rest_api.py,
    subnet/dashboard/cli.py
  </files>
  <action>
Create `subnet/dashboard/` package with a FastAPI app that serves as the WebSocket event bridge between subnet nodes and dashboard clients.

**subnet/dashboard/__init__.py** — empty init.

**subnet/dashboard/ws_bridge.py** — WebSocket bridge:
- FastAPI app factory `create_dashboard_app()` returning a FastAPI instance
- CORS middleware allowing all origins (dev mode)
- WebSocket endpoint at `/ws` that:
  - Accepts connection, adds to a `connected_clients: set[WebSocket]` set
  - On disconnect, removes from set
  - Sends JSON messages of shape: `{"type": "heartbeat"|"tee_quote"|"work_record"|"overwatch"|"node_join"|"node_leave", "data": {...}, "timestamp": "ISO8601"}`
- Background polling loop (asyncio task started on app startup) that:
  - Every 2 seconds, reads RocksDB nmaps for all topics: `heartbeat`, `tee_quote`, `mock_work`
  - Tracks `last_seen_keys: dict[str, set[str]]` per topic to detect NEW entries only
  - When new entries appear, broadcasts them to all connected WebSocket clients
  - On each poll, also reads all heartbeat entries to build a `nodes` dict keyed by peer_id with latest heartbeat data
  - For TEE quotes, extracts `backend`, `tee_type`, `nonce` (epoch), `peer_id` from the stored TeeQuote
  - For work records, extracts `epoch`, `peer_id`, result from the stored OutputEnvelope
- Use `asyncio` (not trio) since FastAPI/uvicorn runs on asyncio. The RocksDB reads are synchronous and fast (in-process), so call them directly (no thread pool needed for the small nmap scans).
- Environment variables:
  - `DASHBOARD_DB_PATH` (default: `/tmp/bootstrap`) — path to RocksDB (same as node's DB, mounted read-only)
  - `DASHBOARD_HOST` (default: `0.0.0.0`)
  - `DASHBOARD_PORT` (default: `8100`)
  - `DASHBOARD_AUTH_TOKEN` (default: `None`) — optional bearer token for admin endpoints

**subnet/dashboard/rest_api.py** — REST endpoints mounted on the same FastAPI app:
- `GET /api/nodes` — returns list of all nodes derived from latest heartbeat data per unique peer_id. Each node object: `{peer_id, subnet_node_id, epoch, tee_score, gpu, gpu_uuid, gpu_attested, models, status: "online"|"offline", last_seen}`. A node is "online" if its latest heartbeat epoch is within 2 of the current max epoch.
- `GET /api/nodes/{peer_id}` — returns detailed node info: latest heartbeat + latest TEE quote metadata + latest work record metadata for that peer.
- `GET /api/events?topic=heartbeat&limit=50` — returns recent events from a given topic nmap, newest first. Parse the `{epoch}:{peer_id}` keys and sort by epoch descending.
- `GET /api/topology` — returns `{nodes: [{peer_id, subnet_node_id, status}], edges: [{from, to}]}`. Edges derived from: all nodes that share the same epoch in heartbeat topic are connected (they are in the same GossipSub mesh if they both published heartbeats in the same epoch). This is an approximation suitable for visualization.
- `GET /api/overwatch` — returns overwatch-related data. Read from RocksDB nmap `mock_work` and flag entries where the work record contains `tampered: true` or parity mismatch indicators.
- Admin endpoints (require `Authorization: Bearer {DASHBOARD_AUTH_TOKEN}` header when token is set):
  - `GET /api/admin/db-stats` — returns nmap names and entry counts
  - Same data as public endpoints but unfiltered

**subnet/dashboard/cli.py** — CLI entry point:
- `def cli()` function that creates the app via `create_dashboard_app()`, opens RocksDB in read-only mode using `RocksDB(path, read_only=True)`, attaches it to app state, and runs with uvicorn.
- Add `[project.scripts]` entry `run_dashboard = "subnet.dashboard.cli:cli"` to pyproject.toml.

Important: The RocksDB instance is opened in READ-ONLY mode — the dashboard never writes to the node's database. It mounts the same volume as one of the nodes (e.g., validator's DB).
  </action>
  <verify>
    <automated>cd /home/aphex5/work/subnet-template && python -c "from subnet.dashboard.ws_bridge import create_dashboard_app; app = create_dashboard_app(); print('OK:', [r.path for r in app.routes])"</automated>
  </verify>
  <done>
    - FastAPI app imports and creates without error
    - Routes registered: /ws, /api/nodes, /api/nodes/{peer_id}, /api/events, /api/topology, /api/overwatch, /api/admin/db-stats
    - WebSocket bridge has broadcast mechanism for connected clients
    - CLI entry point registered in pyproject.toml
  </done>
</task>

<task type="auto">
  <name>Task 2: Vue.js 3 dashboard frontend with Tailwind CSS</name>
  <files>
    dashboard/package.json,
    dashboard/vite.config.ts,
    dashboard/tsconfig.json,
    dashboard/tsconfig.node.json,
    dashboard/index.html,
    dashboard/tailwind.config.js,
    dashboard/postcss.config.js,
    dashboard/.gitignore,
    dashboard/src/main.ts,
    dashboard/src/App.vue,
    dashboard/src/style.css,
    dashboard/src/router/index.ts,
    dashboard/src/stores/network.ts,
    dashboard/src/stores/auth.ts,
    dashboard/src/types/index.ts,
    dashboard/src/composables/useWebSocket.ts,
    dashboard/src/views/ExplorerView.vue,
    dashboard/src/views/AdminView.vue,
    dashboard/src/views/LoginView.vue,
    dashboard/src/views/NodeDetailView.vue,
    dashboard/src/components/NodeCard.vue,
    dashboard/src/components/EventFeed.vue,
    dashboard/src/components/NetworkTopology.vue,
    dashboard/src/components/OverwatchFeed.vue,
    dashboard/src/components/StatusBadge.vue,
    dashboard/src/components/AppHeader.vue,
    dashboard/Dockerfile
  </files>
  <action>
Scaffold a complete Vue.js 3 + TypeScript + Tailwind CSS + Vite dashboard in `dashboard/`.

**Project setup (package.json):**
- Dependencies: `vue@^3.5`, `vue-router@^4`, `pinia@^2`, `@vueuse/core` (for WebSocket composable utilities)
- Dev dependencies: `vite@^6`, `@vitejs/plugin-vue`, `typescript@^5.7`, `tailwindcss@^3`, `postcss`, `autoprefixer`, `vue-tsc`
- Scripts: `dev`, `build`, `preview`

**vite.config.ts:**
- Vue plugin
- Dev server proxy: `/api` -> `http://dashboard-api:8100/api`, `/ws` -> `ws://dashboard-api:8100/ws` (WebSocket proxy)
- Build output to `dist/`

**Tailwind config (per DASH-07 — white and light green theme):**
- Extend colors with: `green: { 50: '#f0fdf4', 100: '#dcfce7', 200: '#bbf7d0', 300: '#86efac', 400: '#4ade80', 500: '#22c55e', 600: '#16a34a' }`
- Background: white (`bg-white`), accent: light green (`bg-green-50`, `bg-green-100`)
- Card borders: `border-green-200`, status indicators: green shades
- Font: system font stack

**TypeScript types (src/types/index.ts):**
```typescript
export interface SubnetNode {
  peer_id: string
  subnet_node_id: number
  epoch: number
  tee_score: number
  gpu: string | null
  gpu_uuid: string | null
  gpu_attested: boolean
  models: string[] | null
  status: 'online' | 'offline'
  last_seen: string
}

export interface DHTEvent {
  type: 'heartbeat' | 'tee_quote' | 'work_record' | 'overwatch' | 'node_join' | 'node_leave'
  data: Record<string, unknown>
  timestamp: string
}

export interface TopologyData {
  nodes: { peer_id: string; subnet_node_id: number; status: string }[]
  edges: { from: string; to: string }[]
}

export interface OverwatchEvent {
  epoch: number
  peer_id: string
  result: 'pass' | 'fail' | 'tampered'
  details: string
}
```

**WebSocket composable (src/composables/useWebSocket.ts):**
- Connect to `ws://${location.host}/ws` (proxied by Vite in dev, nginx in prod)
- Auto-reconnect with exponential backoff (1s, 2s, 4s, max 30s)
- Parse incoming JSON messages as `DHTEvent`
- Expose reactive `connected: Ref<boolean>`, `lastEvent: Ref<DHTEvent | null>`
- Emit events to Pinia store via `useNetworkStore().handleEvent(event)`

**Pinia stores:**

`src/stores/network.ts`:
- State: `nodes: Map<string, SubnetNode>`, `events: DHTEvent[]` (capped at 200), `topology: TopologyData`, `overwatchEvents: OverwatchEvent[]` (capped at 100)
- Actions: `fetchNodes()` (GET /api/nodes), `fetchNodeDetail(peerId)` (GET /api/nodes/{peerId}), `fetchTopology()` (GET /api/topology), `fetchOverwatch()` (GET /api/overwatch), `handleEvent(event: DHTEvent)` (processes WebSocket events — updates node state for heartbeats, appends to events array)
- On startup: fetch initial state via REST, then WebSocket keeps it live

`src/stores/auth.ts`:
- State: `token: string | null`, `isAuthenticated: boolean`
- Actions: `login(token: string)` (stores in localStorage + state), `logout()` (clears both)
- Used by admin view to attach `Authorization: Bearer {token}` header

**Router (src/router/index.ts):**
- `/` — ExplorerView (public, no auth required)
- `/node/:peerId` — NodeDetailView (public)
- `/admin` — AdminView (requires auth, redirect to /login if not authenticated)
- `/login` — LoginView
- Navigation guard: `/admin` checks `auth.isAuthenticated`, redirects to `/login` if false

**Views:**

`ExplorerView.vue` (public — DASH-01, DASH-02, DASH-05):
- Top: connection status indicator (green dot = WebSocket connected, red = disconnected)
- Stats bar: total nodes, online nodes, current epoch, avg TEE score
- Left panel (2/3 width on lg): Grid of NodeCards (responsive: 1 col mobile, 2 col md, 3 col lg)
- Right panel (1/3 width on lg): EventFeed component showing live DHT events
- Bottom: NetworkTopology component (simple visualization)

`NodeDetailView.vue` (public — DASH-03):
- Header: peer_id (truncated with copy button), subnet_node_id, status badge
- TEE section: tee_score bar (0-1.0, green gradient), backend type, last quote epoch
- Hardware section: GPU name, GPU UUID, GPU attested badge, VRAM usage
- Models section: list of assigned models (if any)
- Recent activity: last 20 events for this peer from the event feed
- Back button to explorer

`AdminView.vue` (authenticated — DASH-06):
- Everything in ExplorerView plus:
- DB stats panel (nmap names, entry counts)
- OverwatchFeed component showing audit results and slash events (DASH-04)
- Raw event inspector (expandable JSON for any event)

`LoginView.vue` (DASH-06):
- Simple centered card with token input field and "Login" button
- Stores token via auth store
- Redirects to /admin on success
- Note: This is a simple bearer token auth (the operator sets DASHBOARD_AUTH_TOKEN env var and enters the same token here). No user/password database.

**Components:**

`AppHeader.vue`:
- Logo/title: "TEE Subnet Monitor" on the left
- Navigation: Explorer | Admin (if authenticated)
- Connection status dot (green/red) on the right
- White background with bottom border in green-200

`NodeCard.vue` (props: `node: SubnetNode`):
- White card with green-100 left border (4px) when online, gray-200 when offline
- Top: subnet_node_id badge + status badge (StatusBadge component)
- Middle: peer_id (first 8 + last 4 chars), tee_score as progress bar (green gradient)
- Bottom: GPU info if present, epoch number
- Click navigates to /node/{peer_id}
- Hover: subtle green-50 background

`StatusBadge.vue` (props: `status: 'online' | 'offline'`):
- Online: green-500 bg, white text, pulsing green dot
- Offline: gray-400 bg, white text

`EventFeed.vue` (props: `events: DHTEvent[]`, `maxItems: number = 50`):
- Scrollable list, newest at top
- Each event: colored left border by type (green=heartbeat, blue=tee_quote, purple=work_record, red=overwatch, yellow=node_join/leave)
- Shows: timestamp (relative, e.g. "3s ago"), type badge, peer_id (truncated), epoch
- New events animate in with a brief green flash
- Auto-scrolls to top when new events arrive (unless user has scrolled down)

`NetworkTopology.vue` (props: `topology: TopologyData`):
- Simple force-directed graph using pure SVG (no D3 dependency — keep it lightweight)
- Nodes as circles: green-400 fill when online, gray-300 when offline
- Edges as lines between connected nodes
- Node labels: subnet_node_id
- Tooltip on hover: peer_id, tee_score
- Auto-layout: arrange nodes in a circle if <10 nodes (which is the dev setup)
- Falls back to a simple grid if SVG is too complex — this is v1, not a production graph viz

`OverwatchFeed.vue` (props: `events: OverwatchEvent[]`):
- Similar to EventFeed but for overwatch-specific data
- Color coding: green=pass, red=fail/tampered
- Shows: epoch, peer_id (truncated), result, details

**Dockerfile (multi-stage):**
- Stage 1: `node:20-alpine`, install deps, build
- Stage 2: `nginx:alpine`, copy dist to /usr/share/nginx/html
- nginx.conf: proxy `/api` and `/ws` to `dashboard-api:8100`, serve SPA with try_files for client-side routing

**Global styles (src/style.css):**
- `@tailwind base; @tailwind components; @tailwind utilities;`
- Body: `bg-white text-gray-800`
- Scrollbar styling: thin, green-200 track
  </action>
  <verify>
    <automated>cd /home/aphex5/work/subnet-template/dashboard && npm install && npm run build 2>&1 | tail -5</automated>
  </verify>
  <done>
    - `npm run build` succeeds with no errors
    - dist/ directory contains index.html and JS/CSS bundles
    - All views render: Explorer (public), Admin (auth-gated), Login, NodeDetail
    - White and light green theme applied consistently (per DASH-07)
    - WebSocket composable connects and processes events
    - Network topology SVG renders
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>
Full dashboard stack: Python WebSocket bridge backend reading from GossipSub/RocksDB + Vue.js 3 frontend with real-time event feed, node cards, network topology, and overwatch monitoring. Added `dashboard` and `dashboard-api` services to docker-compose.tee-dev.yml.

The docker-compose.tee-dev.yml should be updated to add:

```yaml
  dashboard-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: tee-dashboard-api
    ports:
      - "8100:8100"
    volumes:
      - tee-validator-db:/app/db:ro
      - mock-chain:/app/mock_chain:ro
    environment:
      DASHBOARD_DB_PATH: "/app/db"
      DASHBOARD_PORT: "8100"
      DASHBOARD_AUTH_TOKEN: "dev-admin-token"
      MOCK_CHAIN_DB_PATH: "/app/mock_chain/mock_hypertensor.db"
    command: >
      subnet.dashboard.cli
    depends_on:
      - validator
    restart: unless-stopped

  dashboard:
    build:
      context: ./dashboard
      dockerfile: Dockerfile
    container_name: tee-dashboard
    ports:
      - "3000:80"
    environment:
      DASHBOARD_API_URL: "http://dashboard-api:8100"
    depends_on:
      - dashboard-api
    restart: unless-stopped
```
  </what-built>
  <how-to-verify>
    1. Run: `docker compose -f docker-compose.tee-dev.yml up --build -d`
    2. Wait 30-60 seconds for nodes to start publishing heartbeats
    3. Open http://localhost:3000 in browser — should see Explorer view
    4. Verify: Node cards appear for validator, miner-1, miner-2, overwatch (4 nodes)
    5. Verify: Event feed on the right shows live heartbeat and TEE quote events streaming in
    6. Verify: White background with light green accents (cards, borders, status badges)
    7. Click a node card — should navigate to detail view showing TEE score, hardware info
    8. Verify: Network topology shows connected nodes
    9. Go to http://localhost:3000/login — enter "dev-admin-token" — should redirect to /admin
    10. Verify: Admin view shows overwatch feed and DB stats
    11. Open browser DevTools Network tab — confirm WebSocket connection is active at /ws
  </how-to-verify>
  <resume-signal>Type "approved" if dashboard displays nodes and live events correctly, or describe issues</resume-signal>
</task>

</tasks>

<verification>
- `python -c "from subnet.dashboard.ws_bridge import create_dashboard_app; print('backend OK')"` succeeds
- `cd dashboard && npm run build` succeeds
- `docker compose -f docker-compose.tee-dev.yml config` validates without errors
- WebSocket at ws://localhost:8100/ws accepts connections
- GET http://localhost:8100/api/nodes returns JSON array of nodes
- Dashboard at http://localhost:3000 renders with node cards and event feed
</verification>

<success_criteria>
- DASH-01: Explorer view shows all 4 nodes with status badges (online/offline)
- DASH-02: Event feed shows live heartbeats, TEE quotes, work records updating in real-time via WebSocket
- DASH-03: Node detail view shows TEE attestation status, tee_score, GPU info, hardware_id
- DASH-04: Admin view shows overwatch activity feed with audit results
- DASH-05: Network topology SVG shows connected nodes with edges
- DASH-06: Explorer is public (no auth), Admin requires bearer token authentication
- DASH-07: White and light green color theme applied throughout
</success_criteria>

<output>
After completion, create `.planning/quick/dashboard/SUMMARY.md`
</output>
