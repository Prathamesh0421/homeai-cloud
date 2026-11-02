# 04 — Frontend (React SPA)

One single-page app in `web/`. **C4 owns the shell, routing, auth and the shared UI kit**; each member owns
their feature folder and pages. All pages follow the D2 GUI style: severity/status always icon + word
(never colour alone), WCAG 2.1 AA contrast, keyboard operable.

## 1. Stack and structure
- Vite + React 18 + TypeScript (strict), Tailwind CSS, React Router 6, TanStack Query 5,
  react-hook-form + zod, Recharts, lucide-react icons, Vitest + Testing Library, Playwright.
```
web/
├── src/
│   ├── main.tsx, App.tsx              # router + QueryClientProvider + AuthProvider (C4)
│   ├── api/
│   │   ├── http.ts                    # fetch wrapper: base '/api/v1', bearer token, error envelope -> ApiError
│   │   ├── types/                     # generated from each service's OpenAPI (openapi-typescript)
│   │   └── c1.ts c2.ts c3.ts c4.ts    # typed functions per component (owners write their own file)
│   ├── auth/                          # AuthProvider, useAuth(), RouteGuard, token storage (C4)
│   ├── shared/                        # UI kit (C4 owns; others may add via PR)
│   │   ├── AppShell.tsx Sidebar.tsx Breadcrumb.tsx Toasts.tsx ConfirmDialog.tsx
│   │   ├── DataTable.tsx FilterBar.tsx Pagination.tsx EmptyState.tsx ErrorState.tsx
│   │   ├── StatusChip.tsx SeverityBadge.tsx KpiTile.tsx ChartCard.tsx Timeline.tsx
│   │   ├── FormPanel.tsx ActionBar.tsx SaveBar.tsx SortableList.tsx ClipPlayer.tsx ConfidenceBars.tsx
│   │   └── tokens.ts                  # colors, severity/status -> {icon, label, classes}
│   └── features/
│       ├── c1-iot/      (Ekant)       # pages + components + hooks for C1
│       ├── c2-alerts/   (Prathamesh)
│       ├── c3-data/     (Renuka)
│       └── c4-dashboard/(Mohit)
├── e2e/                               # Playwright specs for demo scenarios
└── vite.config.ts                     # dev proxy: /api and /.well-known -> http://localhost:8080
```

## 2. Routes (role guard by C4; page by owner)
| Route | Roles | Page | Owner |
|---|---|---|---|
| `/login` | public | Login | C4 |
| `/alert-view/:token` | public, no shell | Signed Alert View | C2 |
| `/home/overview` | house_owner | Home Overview (KPIs, open alerts, feeds, activity) | C4 |
| `/home/settings` | house_owner, cloud_staff | Services and Settings + Emergency Contacts | C4 |
| `/home/feeds` | house_owner | My Feeds (read-only) | C1 |
| `/home/clips` | house_owner | Clip Library (own houses) | C1 |
| `/alerts` | house_owner, cloud_staff | Alerts list | C2 |
| `/alerts/:alertId` | house_owner, cloud_staff | Alert Detail | C2 |
| `/iot/feeds` | iot_staff, cloud_staff | Camera Feed Manager | C1 |
| `/iot/feeds/:feedId` | iot_staff, cloud_staff | Feed Detail (config versions, upload clip, recent clips) | C1 |
| `/iot/houses` | iot_staff, cloud_staff | Houses and Rooms | C1 |
| `/iot/clips` | iot_staff, cloud_staff | Clip Library | C1 |
| `/ops/dashboard` | cloud_staff | System Dashboard | C4 |
| `/ops/tenants` | cloud_staff | Tenants and Users | C4 |
| `/ops/alert-rules` | cloud_staff | Alert Rules | C2 |
| `/ops/models` | cloud_staff | Model Management | C3 |
| `/ops/models/:modelId` | cloud_staff | Model Detail (label map editor, metrics, activate) | C3 |
| `/ops/classify` | cloud_staff, iot_staff | Test Classify (upload a clip, see labels) | C3 |
| `/ops/records` | cloud_staff | Database Records | C3 |
| `/ops/dictionary` | cloud_staff | Data Dictionary | C3 |
| `/ops/integrity` | cloud_staff | Integrity Reports | C3 |
| `/ops/activity` | cloud_staff (owner sees it in Home Overview) | Activity Patterns | C3 |
Landing after login: house_owner → `/home/overview`, iot_staff → `/iot/feeds`, cloud_staff → `/ops/dashboard`.
Opening another role's route redirects to the user's landing page; any 401 clears the token and goes to `/login`.

## 3. Auth handling (C4)
- Token kept **in memory + sessionStorage** (cleared on tab close). Never in localStorage.
- `useAuth()` exposes `{user, role, tenantId, houseIds, login(), logout()}`; decodes claims client-side for UI only.
- `http.ts` adds `Authorization`, maps `{error}` bodies to `ApiError {status, code, message, details}`,
  emits a global event on 401 → logout.
- House picker in the header for owners with several houses; the selected house is kept in a React context
  and in the URL query (`?house=`) so pages share it.

## 4. Shared UI kit contracts (props)
| Component | Props (TypeScript) |
|---|---|
| `DataTable<T>` | `columns: {key, header, render?, sortable?}[]`, `rows: T[]`, `total`, `page`, `pageSize`, `onPageChange`, `onSort?`, `onRowClick?`, `loading`, `emptyText` |
| `FilterBar` | `filters: {name, label, type: 'select'|'date-range'|'text', options?}[]`, `value`, `onChange` |
| `StatusChip` | `kind: 'feed'|'clip'|'alert'|'notification'|'model'|'report'`, `value: string` |
| `SeverityBadge` | `severity: 'critical'|'high'|'medium'|'low'` (icon + word) |
| `KpiTile` | `label`, `value`, `delta?`, `to?` |
| `ChartCard` | `title`, `data: {key, count}[]`, `kind: 'bar'|'hbar'`, with a visually hidden table fallback |
| `Timeline` | `events: {label, at, actor?, note?}[]` |
| `FormPanel` | `title`, `onSubmit`, `fields` via children, `serverErrors?: {field, issue}[]` (maps 422 details to fields) |
| `ActionBar` | `actions: {label, onClick, variant, disabled?, tooltip?, confirm?}[]` |
| `ClipPlayer` | `getUrl: () => Promise<string>` (fetches a fresh playback URL on play) |
| `ConfidenceBars` | `labels: {label, confidence}[]`, `threshold?`, `matched?` |
| `ConfirmDialog`, `Toasts`, `SaveBar`, `SortableList` | as named; keyboard accessible |

## 5. Data fetching rules
- TanStack Query keys: `['c2','alerts',filters]` etc.; invalidate on mutation success.
- Alerts list / Home Overview poll every **15 s** (`refetchInterval`) — this is the in-app notification channel.
- Every page handles **loading, empty, error (shows `error.message` + request id), forbidden** states.
- Forms show 422 `details` next to fields; 409 shows a toast with the server message and reloads data.

## 6. Testing
- Vitest unit tests for shared components and each feature's hooks (mock `http.ts`).
- Playwright E2E specs per demo scenario (`e2e/c1-feed-setup.spec.ts`, `e2e/c2-alert-lifecycle.spec.ts`,
  `e2e/c3-model-activate.spec.ts`, `e2e/c4-login-settings.spec.ts`) against the local stack with seed data.
  These double as rehearsals for the demo videos (Playwright can record video: `use: { video: 'on' }`).

## 7. Build and deploy
`npm run build` → `web/dist`, copied into the Caddy image at `/srv/web`. Environment-free: the SPA always
calls relative `/api/v1`, so the same build works locally and on EC2.
