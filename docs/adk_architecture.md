# ADK 設計書 — キャンペーン収集パイプライン

## システム概要図

```mermaid
graph TB
    subgraph Entry["エントリーポイント"]
        CLI["main.py<br/>CLI (argparse)"]
    end

    subgraph ADK["Google ADK Framework"]
        Runner["ADK Runner<br/>(google.adk.runners.Runner)"]
        Session["InMemorySessionService<br/>(google.adk.sessions)"]
    end

    subgraph RootAgent["CampaignPipelineAgent (BaseAgent)"]
        direction TB
        Orchestrator["_run_async_impl()<br/>メインオーケストレーション"]

        subgraph Tools["Tools Layer (同期/非同期ユーティリティ)"]
            SeedCollector["seed_collector<br/>シードURL収集"]
            FetchExtract["fetch_extract<br/>ページ取得 & 特徴抽出"]
            RuleClassifier["rule_classifier<br/>ルールベース分類"]
            BrowserTool["browser<br/>Playwright管理"]
        end

        subgraph Agents["Sub-Agent Layer (LLM連携)"]
            LLMClassifier["llm_page_classifier<br/>LLMページ分類"]
            DetailNorm["detail_normalization<br/>LLM詳細正規化"]
            DetailValidator["detail_validator<br/>正規化結果検証"]
            Persistence["persistence<br/>DB永続化"]
        end
    end

    subgraph External["外部サービス"]
        Gemini["Gemini API<br/>(gemini-2.5-flash)"]
        TargetSites["対象Webサイト<br/>(PayPay, d払い 等)"]
    end

    subgraph Storage["データストア"]
        MySQL["MySQL 8.0<br/>(Docker)"]
        JSON["campaigns_json/<br/>JSONエクスポート"]
    end

    CLI --> Runner
    Runner --> Session
    Runner --> Orchestrator

    Orchestrator --> SeedCollector
    Orchestrator --> FetchExtract
    Orchestrator --> RuleClassifier
    Orchestrator --> LLMClassifier
    Orchestrator --> DetailNorm
    Orchestrator --> DetailValidator
    Orchestrator --> Persistence

    SeedCollector --> TargetSites
    SeedCollector -.->|フォールバック| BrowserTool
    FetchExtract --> TargetSites
    FetchExtract -.->|フォールバック| BrowserTool
    BrowserTool --> TargetSites

    LLMClassifier --> Gemini
    DetailNorm --> Gemini
    DetailValidator --> Gemini

    Persistence --> MySQL
    Orchestrator --> MySQL
    Orchestrator --> JSON
```

## コンポーネント詳細

### 1. エントリーポイント (`main.py`)

```mermaid
graph LR
    A["argparse<br/>--service NAME"] --> B["asyncio.run()"]
    B --> C["ADK Runner 生成"]
    C --> D["Session 生成"]
    D --> E["runner.run_async()"]
    E --> F["イベントストリーム受信"]
    F --> G["ログ出力 & 終了"]
```

| 項目 | 内容 |
|------|------|
| フレームワーク | Google ADK (`google.adk`) |
| セッション管理 | `InMemorySessionService`（揮発性、実行単位） |
| 引数 | `--service` で対象サービス絞り込み（省略時: 全サービス） |

### 2. ルートエージェント (`CampaignPipelineAgent`)

```mermaid
graph TD
    subgraph CampaignPipelineAgent
        A["_run_async_impl()"] --> B{payment_methods?}
        B -->|空| Z1["Event: No payment methods"]
        B -->|あり| C["loop: 各サービス"]

        C --> D0["get_existing_campaign_urls()"]
        D0 --> D["create_execution_run()"]
        D --> E["collect_seed_urls_async()"]
        E --> F{seed 取得成功?}
        F -->|失敗| G["update: status=failed → 次へ"]
        F -->|成功| H["asyncio.gather + Semaphore(5)"]

        H --> I["_process_url() × N 並行"]
        I --> I2["seen_urls にキャンペーン詳細URLを記録"]
        I2 --> I3["hide_unseen_campaigns()"]
        I3 --> J["update_execution_run(completed)"]
        J --> C

        C --> K["close_browser()"]
        K --> L["_export_campaigns_json()"]
        L --> M["Event: summary JSON"]
    end
```

| 項目 | 内容 |
|------|------|
| 基底クラス | `google.adk.agents.BaseAgent` |
| 並行度 | `asyncio.Semaphore(5)` — URL 処理を最大5並行 |
| LLM 呼び出し | `google.genai.Client` で Gemini API を直接呼び出し |
| 出力形式 | `response_mime_type="application/json"` で JSON を強制 |
| 検証モデル | `VALIDATOR_MODEL_ID` 環境変数で独立設定（デフォルト: gemini-2.5-flash-lite） |

### 3. URL 処理パイプライン (`_process_url`)

```mermaid
flowchart TD
    Start(["URL入力"]) --> Step1

    subgraph Step1["Step 1: ページ取得"]
        F1["requests.get()"] --> C1{main_text >= 200文字?}
        C1 -->|Yes| OK1["features 確定"]
        C1 -->|No| F2["Playwright fallback"]
        F2 --> C2{成功?}
        C2 -->|Yes| OK1
        C2 -->|No| ERR1["error 記録"]
    end

    ERR1 --> LogErr["crawl_log 保存<br/>(fetch_error)"]
    LogErr --> End1(["スキップ"])

    OK1 --> Step2

    subgraph Step2["Step 2: ルールベース分類"]
        S1["score_detail()"] --> S4
        S2["score_list()"] --> S4
        S3["score_not_campaign()"] --> S4
        S4["スコア比較 + is_detail_saveable()"]
        S4 --> R1{結果}
    end

    R1 -->|campaign_detail / campaign_list / not_campaign| Step4
    R1 -->|uncertain| Step3

    subgraph Step3["Step 3: LLM 分類"]
        L1["Gemini API 呼び出し"]
        L1 --> LC{成功?}
        LC -->|Yes| L2["LLM判定ラベル採用"]
        LC -->|No| L3["not_campaign (安全側)"]
    end

    Step3 --> Step4

    subgraph Step4["Step 4: 詳細正規化 & 検証 & 保存"]
        C4{label == campaign_detail?}
        C4 -->|No| Skip4["保存スキップ"]
        C4 -->|Yes| N1["Gemini: 正規化"]
        N1 --> NC{成功?}
        NC -->|Yes| N2["normalized data"]
        NC -->|No| N3["title のみ抽出"]
        N2 --> RR{reward_rate_text?}
        N3 --> RR
        RR -->|null| Skip4
        RR -->|あり| V1["検証LLM: 正規化結果を検証<br/>(VALIDATOR_MODEL_ID)"]
        V1 --> VC{検証結果}
        VC -->|is_valid=true| VT["is_validated=TRUE"]
        VC -->|is_valid=false| VF["is_validated=FALSE"]
        VC -->|エラー| VN["is_validated=NULL"]
        VT --> Save["upsert_campaign()"]
        VF --> Save
        VN --> Save
        Save --> SC{content_hash 変化?}
        SC -->|変化なし| Skip5["更新スキップ (is_show=TRUEに復帰)"]
        SC -->|変化あり| Upsert["INSERT or UPDATE (is_show=TRUE)"]
    end

    Step4 --> Step5

    subgraph Step5["Step 5: ログ保存"]
        CL["insert_crawl_log()"]
    end

    Step5 --> End2(["完了"])

    style ERR1 fill:#f66,color:#fff
    style L3 fill:#f96,color:#fff
    style N3 fill:#f96,color:#fff
    style Skip4 fill:#999,color:#fff
    style Skip5 fill:#999,color:#fff
```

### 4. データモデル (MySQL)

```mermaid
erDiagram
    points ||--o{ payment_methods : "1:N"
    points ||--o{ campaigns : "1:N"
    campaigns ||--o{ crawl_logs : "0:N"
    execution_runs ||--o{ crawl_logs : "1:N"

    points {
        BIGINT id PK
        VARCHAR point_name UK
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    payment_methods {
        BIGINT id PK
        ENUM type "card / qrCode"
        VARCHAR name UK
        BIGINT point_id FK
        VARCHAR campaign_list_url
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    campaigns {
        BIGINT id PK
        BIGINT point_id FK
        VARCHAR title
        VARCHAR period_text
        VARCHAR reward_rate_text
        BOOLEAN entry_required
        VARCHAR target_stores "対象店舗 (NULL可)"
        VARCHAR detail_url UK
        VARCHAR source_list_url
        BOOLEAN is_show "表示フラグ (DEFAULT TRUE)"
        BOOLEAN is_validated "検証フラグ (NULL/TRUE/FALSE)"
        VARCHAR content_hash "重複検知用SHA256"
        TIMESTAMP created_at
        TIMESTAMP updated_at
    }

    crawl_logs {
        BIGINT id PK
        VARCHAR execution_id FK
        VARCHAR url
        ENUM label "campaign_detail/list/not_campaign/uncertain"
        INT detail_score
        INT list_score
        INT not_campaign_score
        BOOLEAN is_detail_saveable
        BOOLEAN used_llm
        VARCHAR confidence_type
        TEXT reason
        BIGINT campaign_id FK
        TEXT error_message
        TIMESTAMP created_at
    }

    execution_runs {
        VARCHAR id PK "UUID"
        VARCHAR service_name
        JSON seed_urls
        ENUM status "running/completed/failed"
        INT total_urls
        INT processed_urls
        INT saved_campaigns
        INT errors
        TIMESTAMP started_at
        TIMESTAMP finished_at
    }
```

## エラーハンドリング設計

```mermaid
flowchart TD
    subgraph ErrorStrategy["エラーハンドリング戦略"]
        direction TB

        E1["Webページ取得失敗"]
        E1 --> E1A["1. 静的取得 → Playwright フォールバック"]
        E1A --> E1B["2. 両方失敗 → crawl_log に fetch_error 記録"]
        E1B --> E1C["3. 該当URL スキップ、他URL は継続"]

        E2["LLM API 呼び出し失敗"]
        E2 --> E2A["分類: not_campaign (安全側) で続行"]
        E2 --> E2B["正規化: title/h1 のみ抽出、他は null"]
        E2 --> E2D["検証: is_validated=NULL で保存続行"]
        E2A --> E2C["confidence_type='llm_error' でログ記録"]

        E3["DB 保存失敗"]
        E3 --> E3A["upsert_campaign: error を result に記録"]
        E3A --> E3B["エラーカウント加算、他URL は継続"]

        E4["Seed URL 収集失敗"]
        E4 --> E4A["execution_run を failed に更新"]
        E4A --> E4B["該当サービスをスキップ、次のサービスへ"]

        E5["URL 処理中の未捕捉例外"]
        E5 --> E5A["Semaphore 内 try/except で捕捉"]
        E5A --> E5B["{error: str(e)} を返却"]
        E5B --> E5C["他 URL の並行処理には影響しない"]

        E5D["hide_unseen_campaigns 失敗"]
        E5D --> E5E["エラーをログに記録して続行"]
        E5E --> E5F["キャンペーンは is_show=TRUE のまま残る（安全側）"]

        E6["パイプライン全体の致命的エラー"]
        E6 --> E6A["finally で close_browser() を実行"]
        E6A --> E6B["main.py の try/except でログ出力"]
        E6B --> E6C["sys.exit(1) で異常終了"]
    end

    style E1 fill:#e74c3c,color:#fff
    style E2 fill:#e67e22,color:#fff
    style E3 fill:#f39c12,color:#fff
    style E4 fill:#e74c3c,color:#fff
    style E5 fill:#e67e22,color:#fff
    style E6 fill:#c0392b,color:#fff
```

### エラー分類と復旧方針

| レベル | 発生箇所 | 影響範囲 | 復旧方針 |
|--------|----------|----------|----------|
| **Low** | 個別URL取得失敗 | 1 URL | フォールバック → スキップ。他URLに影響なし |
| **Low** | LLM API エラー (分類/正規化) | 1 URL | 安全側デフォルト値で続行 |
| **Low** | 検証LLM エラー | 1 URL | is_validated=NULL で保存続行（検証不能） |
| **Low** | 検証失敗 (is_valid=false) | 1 キャンペーン | is_validated=FALSE で保存し人手レビュー可能に |
| **Medium** | DB保存失敗 | 1 キャンペーン | エラー記録して続行。次回実行で再取得可能 |
| **Medium** | Seed URL 収集失敗 | 1 サービス全体 | サービスをスキップ。他サービスは継続 |
| **Low** | 非表示処理失敗 | 1 サービス | エラーログ記録して続行。is_show=TRUE のまま（安全側） |
| **High** | 未捕捉例外 | パイプライン全体 | ブラウザを安全に閉じて終了 |

### リトライ方針

- **即時リトライは行わない** — 同一実行内でのリトライは実装していない
- **フォールバック戦略** — 静的取得 → Playwright の2段構え
- **冪等性** — `content_hash` による重複検知で、再実行しても安全に差分更新
- **再実行** — パイプラインを再度実行すれば `ON DUPLICATE KEY UPDATE` で最新化される
- **更新フロー** — 再実行時、発見されたキャンペーンは `is_show=TRUE`、見つからなかったものは `is_show=FALSE` に更新
