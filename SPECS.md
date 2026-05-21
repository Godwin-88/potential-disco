# Lex Kenya — Full Product Specification

**Version:** 1.0  
**Target deploy:** Today (remote, production-ready)  
**Stack:** React 18 + React Router v6 · FastAPI backend (existing) · Tailwind CSS · Vite

---

## 1. Product Vision

> a proprietary knowledge graph of the Kenyan legal system — constitution, corporate acts, and case law from superior courts. Every module is powered by GraphRAG: graph traversal combined with semantic retrieval, so answers are always traceable to specific legal sources. This is a premier AI legal intelligence tool purpose-built for Kenyan corporate law.

Target users: corporate lawyers, in-house counsel, compliance officers, legal researchers, and law students operating in the Kenyan jurisdiction.

---

## 2. Application Architecture

### Page Map

```
/                       Landing page (public)
/login                  Login (public)
/signup                 Signup (public)
/app                    Protected shell (requires auth)
  /app/qa               Q&A Assistant
  /app/compliance       Compliance Checker
  /app/predictor        Ruling Predictor
  /app/graph            Knowledge Graph Admin
    /app/graph/scraper  Scraper sub-tab
    /app/graph/stats    Graph Stats sub-tab
```

### Project Structure

```
frontend/
├── public/
│   └── favicon.svg
├── src/
│   ├── main.jsx
│   ├── App.jsx                   # Router root, auth provider
│   ├── api/
│   │   ├── client.js             # axios instance, base URL, auth header
│   │   ├── qa.js
│   │   ├── compliance.js
│   │   ├── predictor.js
│   │   └── scraper.js
│   ├── auth/
│   │   ├── AuthContext.jsx       # JWT context + localStorage persistence
│   │   ├── ProtectedRoute.jsx
│   │   └── useAuth.js
│   ├── pages/
│   │   ├── Landing.jsx
│   │   ├── Login.jsx
│   │   ├── Signup.jsx
│   │   └── app/
│   │       ├── Shell.jsx         # Sidebar + topbar layout wrapper
│   │       ├── QA.jsx
│   │       ├── Compliance.jsx
│   │       ├── Predictor.jsx
│   │       └── Graph.jsx
│   ├── components/
│   │   ├── CitationChip.jsx
│   │   ├── SourceCard.jsx
│   │   ├── SlideOver.jsx
│   │   ├── CitationGraph.jsx     # D3 force graph
│   │   ├── RiskBadge.jsx
│   │   ├── OutcomeBar.jsx
│   │   ├── Toast.jsx
│   │   └── LiveLog.jsx
│   └── styles/
│       └── index.css             # Tailwind base + custom tokens
├── index.html
├── vite.config.js
├── tailwind.config.js
└── package.json
```

---

## 3. Landing Page (`/`)

### Purpose
Convert anonymous visitors into registered users by communicating the product's unique value clearly and credibly before any sign-in friction.

### Sections

#### 3.1 Hero
Full-viewport section. Dark background (#0B1120). Centred content.

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   [Lex Kenya wordmark]                    [Login] [Sign up →]│
│                                                              │
│                                                              │
│         The first AI legal intelligence platform             │
│         purpose-built for Kenyan corporate law.              │
│                                                              │
│   Our proprietary knowledge graph maps the Constitution,     │
│   19 corporate Acts, and case law from five courts.          │
│   Every answer traces back to a specific legal source.       │
│                                                              │
│         [Get started free →]   [See how it works ↓]         │
│                                                              │
│                                                              │
│   ─────── Trusted legal sources ───────                      │
│   [Supreme Court] [Court of Appeal] [High Court]             │
│   [Environment & Land] [Employment & Labour]                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Typography:** "The first AI legal intelligence platform" — 52px, font-weight 700, white.  
Sub-copy — 18px, color #94A3B8.  
CTAs — primary button (emerald #059669), ghost button (white border).  
Court logos / names rendered as small pill badges beneath the sub-copy.

#### 3.2 Problem → Solution Strip
Three-column cards, light background (#F8FAFC).

| Problem | → | Lex Kenya |
|---|---|---|
| Legal research in Kenya is slow — manually searching through Acts, judgments, and regulations takes hours. | | Ask a question in plain English. Get a cited answer in seconds, traced to the exact section or judgment. |
| Compliance risk is invisible until a dispute. Directors rarely know which sections impose personal liability. | | The Compliance Checker maps any corporate action to applicable sections, risk level, and specific obligations. |
| Junior advocates assess precedent manually — reading dozens of judgments to find analogous fact patterns. | | The Ruling Predictor surfaces structurally similar cases from the graph and shows historical outcome distribution. |

#### 3.3 How It Works (GraphRAG explained simply)

Three-step horizontal flow with connecting arrows:

```
[1. You ask a question]  →  [2. Graph + semantic search]  →  [3. Cited answer]
 "Can a director vote       Traverses 5,500+ nodes           "Under § 142 of
  on a related-party        across Acts, cases,              the Companies Act
  transaction?"             and constitutional               2015, the director
                            articles.                        must declare their
                                                             interest and may
                                                             not vote. [§ 142]"
```

Below: small stat bar — **5,500+ legal nodes · 19 Acts · 997+ judgments · 5 courts**

#### 3.4 Module Showcase
Three tabbed panels previewing each module. Tabs: "Q&A Assistant" / "Compliance Checker" / "Ruling Predictor". Each tab shows a static screenshot or the existing HTML prototype panel (iframe or inline). No live API calls on landing page.

#### 3.5 Knowledge Graph Credential
Dark section, centred. Establishes the data differentiation.

> **Built on a proprietary legal knowledge graph**  
> Unlike general-purpose AI tools that hallucinate statute references, Lex Kenya answers are generated against a structured graph of verified Kenyan legal sources. Every citation is a real node — cross-linked with CITES, PART_OF, INTERPRETS, and DERIVES_AUTHORITY_FROM relationships.

Graphic: simplified node-edge diagram showing a Case node citing a Section node citing an Act node.

#### 3.6 Signup CTA Strip
Full-width emerald band.

> **Start your free legal research today.**  
> No credit card. No setup. Instant access to the knowledge graph.  
> [Create free account →]

#### 3.7 Footer
Four columns: Product (Q&A, Compliance, Predictor, Graph), Legal Sources (Constitution 2010, Companies Act, Capital Markets Act, Employment Act), Company (About, Pricing, Contact), Disclaimer.  
Bottom bar: "© 2026 Lex Kenya. AI-assisted legal research — not legal advice."

---

## 4. Authentication Pages

### 4.1 Login (`/login`)

```
┌──────────────────────────────┐
│  [← Back to Lex Kenya]       │
│                              │
│  Welcome back                │
│  Log in to your account      │
│                              │
│  Email                       │
│  [________________________]  │
│                              │
│  Password                    │
│  [________________________]  │
│                              │
│  [Log in →]                  │
│                              │
│  Don't have an account?      │
│  [Create one →]              │
└──────────────────────────────┘
```

Centred card on dark-ish background (#0F172A). Card: white, 400px wide, rounded-xl, shadow-xl.

**Auth flow (v1 — JWT, backend-managed):**  
`POST /api/auth/login` → `{access_token, token_type}` → store in `localStorage` → redirect to `/app/qa`.  
On 401: inline error "Invalid email or password."

### 4.2 Signup (`/signup`)

Same card layout as Login. Fields: Full name · Email · Password · Confirm password.  
`POST /api/auth/register` → auto-login → redirect to `/app/qa`.  
Password validation: min 8 chars, shown inline under field.

### 4.3 Auth Backend Additions Required

Add to FastAPI `main.py`:

```
POST /api/auth/register    { name, email, password } → { access_token }
POST /api/auth/login       { email, password }       → { access_token }
GET  /api/auth/me          (Bearer token)            → { id, name, email }
```

JWT secret via `AUTH_JWT_SECRET` env var. User store: simple JSON file or Neo4j `:User` node — whichever is faster to ship. Protected routes add `Depends(get_current_user)` to all `/api/qa`, `/api/compliance`, `/api/predictor`, `/api/scraper` endpoints.

**Frontend:** `AuthContext` stores token, exposes `user`, `login()`, `logout()`. `ProtectedRoute` wraps all `/app/*` routes — redirects to `/login` if no valid token.

---

## 5. App Shell (`/app/*`)

### Layout

```
┌────────────────────────────────────────────────────────────┐
│ SIDEBAR 240px (fixed)      │ TOPBAR (full width, 56px)     │
│                            │────────────────────────────── │
│  ╔══════════════════╗      │  Q&A Assistant                │
│  ║  Lex Kenya       ║      │                    [user ▾]   │
│  ║  Legal Intel.    ║      │──────────────────────────────│
│  ╚══════════════════╝      │                              │
│                            │                              │
│  ── Research ──            │       ACTIVE PAGE            │
│  ○ Q&A Assistant           │                              │
│  ○ Compliance Checker      │                              │
│  ○ Ruling Predictor        │                              │
│                            │                              │
│  ── System ──              │                              │
│  ○ Knowledge Graph         │                              │
│                            │                              │
│  ─────────────────         │                              │
│  ● KG Online               │                              │
│    5,543 nodes             │                              │
│    [user name]  [logout]   │                              │
└────────────────────────────┴──────────────────────────────┘
```

Sidebar: fixed 240px, `bg-slate-900`, white text. Active item: `bg-emerald-900/40 text-emerald-400`. Hover: `bg-slate-800`.  
Topbar: `bg-white border-b border-slate-200`, breadcrumb left, user avatar menu right.  
Content area: `bg-slate-50`, scrollable.

On mobile (<768px): sidebar collapses to hamburger menu overlay.

---

## 6. Q&A Page (`/app/qa`)

### Layout: Two-Column

```
┌────────────────────────────────────────────────────────────┐
│ LEFT: Chat (60%)              │ RIGHT: Source Panel (40%) │
│                               │                           │
│ [conversation history]        │ (empty until answer)      │
│                               │                           │
│  [LK] Hello. I can answer…    │ ─── Sources (3) ───       │
│                               │                           │
│  [U]  What are the            │ [§] Companies Act §11     │
│       requirements to…        │     Authority  ████  0.82 │
│                               │     Relevance  ███   0.91 │
│  [LK] Under Companies Act…    │                           │
│       [§ 11(1)] …must file…   │ [§] Companies Act §24     │
│       [§ 24] …name must not…  │     Authority  ████  0.78 │
│       [§ 56(2)]               │     Relevance  ████  0.87 │
│                               │                           │
│       ┌─────────────────────┐ │ [⚖] Mwangi v Kariuki     │
│       │ Consensus: High ✓   │ │     2019 · Court of App   │
│       │ [View graph ⎋]      │ │     Outcome: Claimant ✓  │
│       └─────────────────────┘ │                           │
│                               │ ─── Follow-ups ───        │
│  ─────────────────────────── │ ▸ What is a co. secretary? │
│  [Ask about Kenyan law…] [▶] │ ▸ Can one director run a  │
│  Citations: [8 ▾]             │   private company?        │
└───────────────────────────────┴───────────────────────────┘
```

### Chat Behaviour

- Message history stored in component state (session-only in v1, no persistence).
- `POST /api/qa/ask` called on submit.
- Loading: animated "LK" avatar with three-dot pulse while awaiting response.
- Answer rendered with inline citation chips. Parser: split answer on `[§ X]` or `[Art. X]` or `[⚖ Name Year]` patterns to wrap in `<CitationChip>` components.
- Source panel auto-populates from `sources[]` on response.
- `GET /api/qa/suggest?q={question}` called in parallel; follow-up pills render in right panel below sources.
- "View graph" button opens `<SlideOver>` with D3 citation graph from `GET /api/qa/trace/{answer_id}`.

### Retrieval Debug Accordion
Below the answer bubble, collapsed by default. Label: "Retrieval details". Expands to show `retrieval_stats`, `consensus_level` badge, `disputed_points` list if non-empty.

### CitationChip Component

```jsx
// Variants: section | article | case
<CitationChip type="section" label="§ 11(1)" onClick={openSourceCard} />
<CitationChip type="case"    label="⚖ Mwangi 2019" overruled={false} />
```

- Section/Clause: `bg-emerald-50 text-emerald-800 border-emerald-200`
- Article (Constitution): `bg-blue-50 text-blue-800 border-blue-200`
- Case: `bg-violet-50 text-violet-800 border-violet-200`
- Overruled case: amber border + "⚠ overruled" tooltip

### Citation Graph (SlideOver)

D3 force-directed. Nodes: circles, radius proportional to `authority_score`, coloured by `label` (Section=green, Case=violet, Article=blue, Act=slate). Edges: directional arrows labelled with relationship type (CITES, INTERPRETS, PART_OF). Click node → show metadata card within the slide-over.

---

## 7. Compliance Checker Page (`/app/compliance`)

### Layout: Split Form + Result

```
┌───────────────────────────────────────────────────────────┐
│ FORM (left 42%)               │ RESULT (right 58%)        │
│                               │                           │
│ What are you assessing?       │ [shown after run]         │
│ [Action type dropdown ▾]      │                           │
│                               │ ┌───────────────────────┐ │
│ Describe the specific action  │ │ ● HIGH COMPLIANCE RISK│ │
│ [textarea]                    │ └───────────────────────┘ │
│                               │                           │
│ Entity context (optional)     │ This action likely        │
│ [Company type ▾]              │ constitutes a related     │
│                               │ party transaction…        │
│ [▶ Run compliance check]      │                           │
│                               │ Obligations               │
│ ─── Recent checks ───         │ ☐ Board approval required │
│ · Director conflict  High     │ ☐ Declare interest at     │
│ · ESOP setup         Low      │   board meeting           │
│                               │ ☐ Shareholder disclosure  │
│                               │                           │
│                               │ Exposure                  │
│                               │ § 149 personal liability  │
│                               │ § 142–144 breach          │
│                               │                           │
│                               │ Sources                   │
│                               │ [§ §142] [§ §149] [⚖ …] │
│                               │                           │
│                               │ [↗ Ask Q&A about this]   │
└───────────────────────────────┴───────────────────────────┘
```

### Action Types
- Director conflict of interest / related-party transaction
- Share buyback by private company
- Foreign investor acquiring stake (>25%)
- Employee share option scheme (ESOP)
- Dividend declaration without distributable profits
- Director removal or resignation
- Cross-border capital transfer
- Change of company name or objects
- Voluntary winding up

### Risk Badge
`RiskBadge` component: prop `level: "low" | "medium" | "high"`.
- Low: `bg-emerald-50 text-emerald-800 border-emerald-300` · "✓ Low compliance risk"
- Medium: `bg-amber-50 text-amber-800 border-amber-300` · "⚠ Medium compliance risk"
- High: `bg-red-50 text-red-800 border-red-300` · "● High compliance risk"

### Recent Checks
Stored in `localStorage` keyed by user email (5 most recent). Shows action type + risk level as quick recall. Click to re-populate the form.

### "Ask Q&A" Button
Pre-populates Q&A input: `"What are the legal obligations when [action_type]: [description]?"` and navigates to `/app/qa`.

---

## 8. Ruling Predictor Page (`/app/predictor`)

### Layout: Form Top, Results Bottom

```
┌───────────────────────────────────────────────────────────┐
│ CASE PROFILE                                              │
│                                                           │
│ [Court ▾]            [Dispute type ▾]                     │
│ [Claimant type ▾]    [Remedy sought ▾]                    │
│                                                           │
│ Additional facts (optional)                               │
│ [textarea — describe the key facts of the dispute]        │
│                                                           │
│ [▶ Predict likely outcome]                                │
├───────────────────────────────────────────────────────────┤
│ OUTCOME DISTRIBUTION                                      │
│                                                           │
│ Claimant succeeds    ████████████░░░░  68%                │
│ Partial remedy       ███░░░░░░░░░░░░░  22%                │
│ Dismissed            █░░░░░░░░░░░░░░░  10%                │
│                                                           │
│ Based on 14 comparable precedents in the knowledge graph. │
│ [Analysis paragraph from LLM]                             │
├───────────────────────────────────────────────────────────┤
│ RELEVANT PRECEDENTS                                       │
│                                                           │
│  Case                        Court  Year  Outcome         │
│  ──────────────────────────────────────────────────────  │
│  Kamau v Savanna Holdings    CA     2020  Buyout ordered  │
│  Odhiambo v Equity Ventures  HC     2018  Partial relief  │
│  Re Pioneer Flowers Ltd      HC     2022  Damages only    │
│  [Show 11 more ▾]                                         │
└───────────────────────────────────────────────────────────┘
```

### Outcome Bars
`OutcomeBar` component. `width` = percentage, colour = outcome type. Animate width on mount (CSS transition 600ms ease-out).

### Precedent Table
Sortable by Court, Year, Outcome. Row click → `<SlideOver>` with full case detail: title, citation, headnote, cited sections list, outcome, court. "Ask Q&A about this case" button in slide-over footer.

### Form Dropdowns

**Courts:** Supreme Court · Court of Appeal · High Court (Commercial Division) · High Court (General) · Environment & Land Court · Employment & Labour Relations Court

**Dispute types:** Shareholder oppression · Director fiduciary breach · Wrongful dismissal · Unfair termination · Commercial contract breach · Land title dispute · Insolvency / winding up · Regulatory enforcement (CMA) · Constitutional petition · Defamation

**Claimant types:** Minority shareholder · Employee · Creditor · Regulator (CMA/CBK) · Landowner · Business partner · Consumer

**Remedies:** Damages · Injunction · Winding up · Share buyout order · Reinstatement · Declaration · Specific performance

---

## 9. Knowledge Graph Page (`/app/graph`)

Two sub-tabs: **Scraper** (default) and **Stats**.

### 9.1 Scraper Sub-tab

```
┌───────────────────────────────────────────────────────────┐
│ COURT COVERAGE  (from GET /api/scraper/courts)            │
│                                                           │
│ ┌──────────┐ ┌───────────────┐ ┌─────────────────┐       │
│ │ Supreme  │ │ Court of      │ │ High Court      │       │
│ │  Court   │ │   Appeal      │ │                 │       │
│ │ 12 cases │ │  284 cases    │ │  631 cases      │       │
│ └──────────┘ └───────────────┘ └─────────────────┘       │
│ ┌──────────────────────┐  ┌─────────────────────────┐    │
│ │ Environment & Land   │  │ Employment & Labour     │    │
│ │  47 cases            │  │  23 cases               │    │
│ └──────────────────────┘  └─────────────────────────┘    │
├───────────────────────────────────────────────────────────┤
│ RUN SCRAPER                                               │
│                                                           │
│ Court:     [All courts ▾]                                 │
│ Max cases: [200]   Max pages: [10]                        │
│                                                           │
│ [▶ Start scrape]            Last run: 2 days ago ✓        │
├───────────────────────────────────────────────────────────┤
│ LIVE LOG  (polls GET /api/scraper/status every 3 s)       │
│                                                           │
│  ● Running — Court of Appeal  (47 / 200)                  │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│  [14:03:12] Fetching page 1 of keca…                      │
│  [14:03:14] Scraped: Kamau v Safaricom Ltd 2024           │
│  [14:03:16] Already exists — skipping                     │
│                                                           │
│  [■ Stop]                                                 │
├───────────────────────────────────────────────────────────┤
│ HISTORY  (from GET /api/scraper/history)                  │
│                                                           │
│  Date        Cases added  Duration  Status                │
│  2026-05-13  47           4m 12s    ✓ Complete            │
│  2026-05-10  12           1m 03s    ✓ Complete            │
│  2026-05-07  0            41s       ⚠ No new cases        │
└───────────────────────────────────────────────────────────┘
```

**Polling logic:** `setInterval(3000)` starts on "Start scrape" click. Clears when `status !== "running"`. Court coverage cards refresh on completion.

### 9.2 Stats Sub-tab

```
┌───────────────────────────────────────────────────────────┐
│ NODE COUNTS                                               │
│                                                           │
│ [Section 1,903] [Case 997] [Clause 949] [Provision 1,031]│
│ [Article 264] [Penalty 327] [Schedule 25] [Right 26]     │
│ [LegalConcept 28] [Act 19]                                │
│                                                           │
│ Total: 5,569 nodes                                        │
├───────────────────────────────────────────────────────────┤
│ RELATIONSHIPS (top 20)                                    │
│                                                           │
│ PART_OF              ████████████████  8,241              │
│ CITES                ██████████        4,103              │
│ DECIDED_BY           ████              997                │
│ INTERPRETS           ██               412                 │
│ …                                                         │
├───────────────────────────────────────────────────────────┤
│ SYSTEM                                                    │
│                                                           │
│ Neo4j         ● Online     neo4j+s://4830d4c5.databases…  │
│ Embedding     local · BAAI/bge-m3 · 1024 dim              │
│ LLM           openai_compatible · qwen/qwen3-32b          │
│ Vector index  legal_embeddings · cosine · 1024 dim        │
└───────────────────────────────────────────────────────────┘
```

---

## 10. Shared Components

### CitationChip
```
Props: type ("section"|"article"|"case"), label, sourceData, overruled
```
Clicking opens `<SourceCard>` popover anchored to chip.

### SourceCard (popover)
Shows full metadata from `sources[]` entry:
- **Section:** Act title, section number, authority score bar, relevance score bar, section text excerpt
- **Case:** case title, citation, court, year, outcome, overruled_by warning (amber), headnote excerpt
- **Article:** Constitution of Kenya 2010, article number and heading, text excerpt

### SlideOver
Right-anchored drawer, 420px. Animated slide-in (300ms ease). Overlay backdrop. `Esc` closes. Used for: citation graph, case detail.

### RiskBadge
`level: "low"|"medium"|"high"` → coloured pill with icon.

### OutcomeBar
`label`, `percent`, `color`. Animates on mount. Accessible: `role="meter"` `aria-valuenow`.

### LiveLog
Scrollable `<pre>` box, `bg-slate-900 text-emerald-400`, monospace. Auto-scrolls to bottom on new entries. `log[]` array prop.

### Toast
Top-right stack. Auto-dismiss 5 s. `type: "success"|"warning"|"error"`. Rendered via React portal.

---

## 11. API Client (`src/api/client.js`)

```js
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const client = axios.create({ baseURL: API_BASE })

client.interceptors.request.use(cfg => {
  const token = localStorage.getItem('lex_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

client.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('lex_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default client
```

---

## 12. API → UI Field Mapping

| UI element | Source |
|---|---|
| Inline citation chips | Parse `answer` string for `[§ X]`, `[Art. N]`, `[⚖ Name Year]` patterns |
| Source panel cards | `sources[]` array |
| Risk badge colour | `risk_level` from compliance response |
| Consensus badge | `consensus_level` from `AskResponse` |
| Disputed points callout | `disputed_points[]` |
| Retrieval debug panel | `retrieval_stats{}` |
| Overruled case warning | `sources[].overruled_by` |
| Authority / relevance bars | `sources[].authority_score`, `.relevance_score` |
| Follow-up pills | `GET /api/qa/suggest` → `suggestions[]` |
| Citation graph edges | `GET /api/qa/trace` → `graph_edges[]`, `graph_nodes[]` |
| Outcome distribution bars | `predictor` response `outcome_distribution` |
| Precedents table | `predictor` response `precedents[]` |
| Scraper live log | `GET /api/scraper/status` → `log[]` |
| Court case counts | `GET /api/scraper/courts` |
| Node counts | `GET /graph/stats` → `nodes` |
| Relationship counts | `GET /graph/stats` → `relationships` |

---

## 13. Auth Backend Additions (FastAPI)

Add `core/auth.py`:

```python
# Endpoints to add to main.py
POST /api/auth/register   { name, email, password }  → { access_token, token_type }
POST /api/auth/login      { email, password }         → { access_token, token_type }
GET  /api/auth/me         Bearer token                → { id, name, email }
```

Storage v1: `:User` nodes in Neo4j (`MERGE (u:User {email: $email})`). Password hashed with `bcrypt`. JWT signed with `AUTH_JWT_SECRET` env var, 7-day expiry. Add `python-jose[cryptography] passlib[bcrypt]` to `requirements.txt`.

Apply `Depends(get_current_user)` to all protected routers once auth is wired.

---

## 14. Environment Variables

### Frontend (`frontend/.env`)
```
VITE_API_URL=https://your-api-domain.com
```

### Backend (add to `.env`)
```
AUTH_JWT_SECRET=your-secret-here-min-32-chars
AUTH_TOKEN_EXPIRE_DAYS=7
FRONTEND_ORIGIN=https://your-frontend-domain.com
```

Update CORS in `main.py`:
```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
    os.getenv("FRONTEND_ORIGIN", ""),
]
```

---

## 15. Deployment

### Backend (FastAPI)
Recommended: **Railway** or **Render** (both have free tier, support env vars, auto-deploy from GitHub).

```dockerfile
# Dockerfile (add to project root)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend (React/Vite)
Recommended: **Vercel** (zero-config Vite deploy).

```json
// vercel.json
{
  "rewrites": [{ "source": "/((?!api/).*)", "destination": "/index.html" }]
}
```

Set `VITE_API_URL` in Vercel environment variables to your Railway/Render backend URL.

### Deployment Checklist
- [ ] `AUTH_JWT_SECRET` set in backend env
- [ ] `FRONTEND_ORIGIN` set to Vercel URL in backend env
- [ ] `VITE_API_URL` set to backend URL in Vercel env
- [ ] Neo4j Aura credentials confirmed in backend env
- [ ] `Dockerfile` builds cleanly (`docker build -t lex-kenya .`)
- [ ] `POST /api/auth/register` and `POST /api/auth/login` endpoints live
- [ ] CORS updated to include production frontend origin
- [ ] `requirements.txt` includes `python-jose[cryptography] passlib[bcrypt]`

---

## 16. Build Commands

```bash
# Frontend
cd frontend
npm create vite@latest . -- --template react
npm install
npm install axios react-router-dom d3 @tailwindcss/forms
npx tailwindcss init -p
npm run dev        # http://localhost:5173
npm run build      # dist/ → deploy to Vercel

# Backend
pip install python-jose[cryptography] passlib[bcrypt]
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

*End of specification. All module layouts, component contracts, endpoint mappings, auth flow, and deployment steps are defined above. Implementation can begin directly from this document.*
