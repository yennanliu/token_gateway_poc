# Token Gateway 使用說明（繁體中文）

> 本文件說明本系統的運作原理、安裝設定與啟動方式。
> 英文版請見 [`README.md`](../README.md)。

---

## 一、這是什麼

**Token Gateway** 是一個「多供應商 LLM API 閘道（Gateway）」，把 **OpenAI、Anthropic、
Google Gemini** 三家模型服務整合在同一個入口後面。

核心理念：**你不需要改程式、不需要包裝函式庫**，只要把原本使用的 SDK 的
**base URL（服務網址）** 與 **API 金鑰** 換掉，就能透過本閘道呼叫三家的模型，
並共用同一份「點數（credits）」餘額。

一把 `gw-…` 金鑰 → 一份點數餘額 → 存取三家模型。

### 運作流程（每一次請求）

```
1. 用戶端 SDK 打到閘道（例如 /v1/chat/completions）
2. 驗證：從 Authorization / x-api-key / x-goog-api-key / ?key= 取出金鑰
        → 以 SHA-256 雜湊比對 → 找到對應的 專案(project) 與 工作區(workspace)
        → 找不到或已停用 → 401
3. 額度檢查：餘額 <= 0 → 402；超過每月預算 → 402(budget_exceeded)
4. 流量限制：超過該金鑰的每分鐘上限 → 429
5. 白名單：該專案是否允許此模型 → 否則 403
6. 轉送：拿掉用戶端金鑰、換上「真正的」供應商金鑰、改寫網址後轉送上游
7. 計量與扣款：讀取上游回傳的 token 用量 → 換算成本 → 在同一交易內
   寫入用量紀錄、扣款、記帳
8. 回傳：以該 SDK 期待的格式回覆用戶端
```

### 資源階層

```
組織 Organization → 工作區 Workspace（存放點數）→ 專案 Project（模型白名單）→ API 金鑰
```

- **點數：** 1 點 = 0.01 美元；內部以整數「micro-credits」儲存（1,000,000 micros = 1 點），避免浮點誤差。
- **金鑰：** 只儲存雜湊值與前綴（如 `gw-AbCdEfGh`），原始金鑰只顯示一次。

---

## 二、技術架構

Python 3.12 · uv · FastAPI · httpx · SQLAlchemy 2（async）· SQLite（預設）/ Postgres ·
Vue 3（CDN）。採用測試驅動開發（TDD），以 pytest + respx 撰寫測試。

> **資料庫說明：** 預設使用本機 SQLite 檔案，因此不需要任何外部服務即可執行。
> 正式環境請將 `DATABASE_URL` 設為 `postgresql+asyncpg://…` 連線字串。

---

## 三、安裝設定（Setup）

### 1. 前置需求
- [uv](https://github.com/astral-sh/uv)（Python 套件與虛擬環境管理工具）
- uv 會自動安裝 Python 3.12，不需另外安裝

### 2. 安裝相依套件

```bash
uv sync --extra dev
```

### 3. 設定環境變數

```bash
cp .env.example .env
```

接著編輯 `.env`，重點欄位：

| 變數 | 說明 |
|------|------|
| `DATABASE_URL` | 資料庫連線；預設為本機 SQLite，正式環境改為 Postgres |
| `OPENAI_API_KEY` | 你在 OpenAI 的「真實」金鑰（閘道會替用戶端注入） |
| `ANTHROPIC_API_KEY` | Anthropic 的真實金鑰 |
| `GEMINI_API_KEY` | Google Gemini 的真實金鑰 |
| `ADMIN_TOKEN` | 管理主控台 / `/admin` API 的權杖 |
| `REDIS_URL` | （選填）設定後改用 Redis 做跨機流量限制，留空則用記憶體 |
| `ENABLE_TRANSLATION` | （選填）讓 OpenAI 格式的請求呼叫 claude-* 模型 |
| `STRIPE_SECRET_KEY` | （選填）留空則儲值採用 mock 模式，立即入帳 |

---

## 四、啟動與使用（Run）

### 1. 建立第一把金鑰

```bash
uv run python scripts/create_key.py \
  --workspace "Acme" --project "prod" \
  --models gpt-5.4 claude-sonnet-4-6 gemini-2.5-pro \
  --credits 100
# 會印出一把 gw-… 金鑰，以及 Workspace / Project ID（請保存）
```

### 2. 啟動服務

```bash
uv run uvicorn gateway.main:app --reload
```

### 3. 開啟管理主控台

瀏覽器開啟 <http://localhost:8000/>，輸入 `ADMIN_TOKEN` 即可查看
點數餘額、金鑰清單、用量分析與請求紀錄。

### 4. 用各家 SDK 呼叫（只換 base URL 與金鑰）

```python
# OpenAI Python SDK
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="gw-...")
client.chat.completions.create(
    model="gpt-5.4", messages=[{"role": "user", "content": "hi"}]
)
```

```bash
# curl
curl http://localhost:8000/v1/models -H "Authorization: Bearer gw-..."
```

---

## 五、API 端點一覽

| 端點 | 相容於 |
|------|--------|
| `GET /v1/models` | OpenAI（依專案白名單） |
| `POST /v1/chat/completions` | OpenAI（支援串流、可轉譯至 Anthropic） |
| `POST /v1/messages` | Anthropic（支援串流） |
| `POST /v1/models/{model}:generateContent` | Gemini |
| `GET/POST /admin/*` | 主控台 API（需 `X-Admin-Token`） |
| `GET/POST/PUT/DELETE /manage/*` | 控制平面 + 權限（RBAC） |
| `GET /metrics` | Prometheus 監控指標 |
| `GET /` | Vue 管理主控台 |

錯誤格式會依照各家 SDK 的形狀回傳：`400/401/402/403/429/502`。

---

## 六、資料庫遷移與 Docker

```bash
uv run alembic upgrade head          # 套用資料表結構（正式環境用；開發會自動建立）
docker compose up --build            # 一次啟動 閘道 + Postgres + Redis
```

---

## 七、執行測試

```bash
uv run pytest -q                     # 全部 91 個測試
uv run pytest -q -m unit             # 41 個單元測試（純邏輯，不含 app/DB）
uv run pytest -q -m integration      # 50 個整合測試（完整流程）
```

CI 由 GitHub Actions 執行：在 SQLite 上跑單元 + 整合測試，並在真實的
Postgres 服務上套用 Alembic 遷移。

---

## 八、功能階段（Phase）對照

- **Phase 1** — 代理轉送、`gw-…` 金鑰、點數帳本與計量、模型白名單、串流、錯誤格式、簡易主控台。
- **Phase 2** — 組織/使用者/成員與角色、每金鑰流量限制、儲值（mock + Stripe 準備）、請求紀錄與分析、Vue 主控台。
- **Phase 3** — 控制平面（`/manage/*`）CRUD、權限 RBAC（owner/admin/member）、使用者 session、活動紀錄、Alembic 遷移。
- **Phase 4** — 每月花費預算、上游重試（退避）、跨供應商轉譯（OpenAI→Anthropic）、Prometheus `/metrics`、Docker/compose/Makefile。
- **Phase 5** — Redis 流量限制（可退回記憶體）、真實 Stripe Checkout + 簽章 webhook（可退回 mock）。

詳細設計請見 [`design-and-implementation.md`](./design-and-implementation.md)。
