# キャンペーン情報取得パイプライン シーケンス図

## 全体フロー概要

```
1. 起動・初期化
2. 決済手段の取得
3. サービスごとのループ
   3-1. シードURL収集
   3-2. URLごとの並行処理
       3-2-1. ページ取得 & 特徴抽出
       3-2-2. ルールベース分類
       3-2-3. LLM分類 (不確定時)
       3-2-4. キャンペーン詳細抽出 & 正規化
       3-2-5. 検証 (バリデーション)
       3-2-6. DB保存
       3-2-7. クロールログ保存
   3-3. 未発見キャンペーンの非表示処理
4. 後処理 & 結果返却
```

> **リトライポリシー**: 全ての外部通信 (HTTP / Playwright / LLM API / DB) は **最大3回リトライ**（指数バックオフ: 1秒 → 2秒 → 4秒）

---

## 1. 起動・初期化

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Main as メイン処理
    participant Runner as ADK Runner
    participant Agent as パイプライン<br/>エージェント

    User->>Main: パイプライン実行<br/>(対象サービス指定 / 全件)
    Main->>Runner: エージェントとセッションを生成
    Main->>Runner: パイプラインを非同期実行
    Runner->>Agent: メイン処理を開始
```

---

## 2. 決済手段の取得

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant DB as MySQL

    Agent->>DB: 対象の決済手段を取得
    DB-->>Agent: 決済手段一覧

    alt 決済手段が見つからない
        Note over Agent: 「対象なし」を返却して終了
    end
```

---

## 3-1. シードURL収集

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant DB as MySQL
    participant Seed as シードURL<br/>収集
    participant Browser as ブラウザ<br/>(Playwright)

    Note over Agent: === サービスごとのループ開始 ===

    Agent->>DB: 該当サービスの既存キャンペーンURL一覧を取得
    DB-->>Agent: 既存URL一覧

    Agent->>DB: 実行ログを作成 (実行ID発行)

    Agent->>Seed: シードURLからキャンペーン候補URLを収集

    rect rgb(255, 248, 220)
        Note over Seed: 静的HTML取得 (リトライ: 最大3回)
        Seed->>Seed: HTTP GET → リンク抽出
    end

    alt 十分なURL数が取得できた (3件以上)
        Seed-->>Agent: 候補URL一覧
    else URL数が不足 または 静的取得が3回リトライ後も失敗
        rect rgb(255, 248, 220)
            Note over Browser: Playwright取得 (リトライ: 最大3回)
            Seed->>Browser: JSレンダリングでページを取得
        end
        alt ブラウザ取得成功
            Browser-->>Seed: レンダリング済みHTML
            Seed-->>Agent: 候補URL一覧
        else ブラウザ取得が3回リトライ後も失敗
            Browser-->>Seed: エラー
            Note over Seed: 静的取得の部分結果があればそれを返す
            Seed-->>Agent: 候補URL一覧 (部分的) + エラー情報
        end
    end

    alt シードURL収集に失敗 (候補URLが空)
        Agent->>DB: 実行ステータスを「失敗」に更新
        Note over Agent: このサービスをスキップして次へ
    end

    Agent->>DB: 処理対象URL数を記録
```

---

## 3-2-1. ページ取得 & 特徴抽出

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant Fetch as ページ取得<br/>特徴抽出
    participant Browser as ブラウザ<br/>(Playwright)
    participant Persist as 永続化

    Note over Agent: === URLごとの並行処理 (最大5件同時) ===

    Agent->>Fetch: ページを取得して特徴を抽出

    rect rgb(255, 248, 220)
        Note over Fetch: 静的HTML取得 (リトライ: 最大3回)
        Fetch->>Fetch: HTTP GET → HTML解析 → 特徴抽出
    end

    alt 十分なコンテンツが取得できた (200文字以上)
        Fetch-->>Agent: ページ特徴情報
    else コンテンツが不足 または 静的取得が3回リトライ後も失敗
        rect rgb(255, 248, 220)
            Note over Browser: Playwright取得 (リトライ: 最大3回)
            Fetch->>Browser: JSレンダリングでページを取得
        end
        alt ブラウザ取得成功
            Browser-->>Fetch: レンダリング済みHTML
            Fetch-->>Agent: ページ特徴情報
        else ブラウザ取得が3回リトライ後も失敗
            Browser-->>Fetch: エラー
            alt 静的取得の結果が残っている
                Fetch-->>Agent: ページ特徴情報 (部分的)
            else 完全に取得失敗
                Fetch-->>Agent: エラー情報
            end
        end
    end

    alt ページ取得エラー
        Agent->>Persist: クロールログを保存 (取得失敗として記録)
        Note over Agent: このURLをスキップ → 次のURLへ
    end
```

---

## 3-2-2〜3. ルールベース分類 & LLM分類

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant Rule as ルールベース<br/>分類
    participant LLM as Gemini LLM

    Agent->>Rule: ページ種別をルールで判定
    Rule->>Rule: 詳細/一覧/非キャンペーンの各スコアを算出
    Rule-->>Agent: 分類結果 (ラベル・スコア・信頼度)

    alt 分類結果が「不確定」
        rect rgb(255, 248, 220)
            Note over LLM: LLM分類 (リトライ: 最大3回)
            Agent->>LLM: ページ種別をLLMで判定
            LLM-->>Agent: 判定ラベルと理由
        end
        alt LLM呼び出しが3回リトライ後も失敗
            Note over Agent: 「非キャンペーン」として安全側に倒して続行
        end
    end
```

---

## 3-2-4〜5. キャンペーン詳細抽出 & 検証

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant LLM as Gemini LLM<br/>(正規化)
    participant Validator as Gemini LLM<br/>(検証)

    alt 「キャンペーン詳細」と判定された場合

        rect rgb(255, 248, 220)
            Note over LLM: LLM正規化 (リトライ: 最大3回)
            Agent->>LLM: キャンペーン情報を抽出・正規化
            Note over LLM: タイトル・期間・還元率<br/>エントリー要否・対象店舗を抽出
            LLM-->>Agent: 正規化されたキャンペーン情報
        end

        alt LLM正規化が3回リトライ後も失敗
            Note over Agent: ページタイトルのみ採用<br/>他項目はnullで続行
        end

        alt 還元率情報がない
            Note over Agent: DB保存をスキップ (還元率なし)
        else 還元率情報がある
            rect rgb(255, 248, 220)
                Note over Validator: 検証LLM (リトライ: 最大3回)
                Agent->>Validator: 正規化結果を検証
                Note over Validator: 各フィールドが元ページに<br/>裏付けがあるか判定
                Validator-->>Agent: 検証結果 (is_valid / field_results)
            end

            alt 検証成功 (is_valid=true)
                Note over Agent: is_validated=TRUE で保存
            else 検証失敗 (is_valid=false)
                Note over Agent: is_validated=FALSE で保存 (要レビュー)
            else 検証LLMが3回リトライ後もエラー
                Note over Agent: is_validated=NULL で保存 (検証不能)
            end
        end
    end
```

---

## 3-2-6〜7. DB保存 & クロールログ

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant Persist as 永続化<br/>エージェント
    participant DB as MySQL

    alt キャンペーン詳細 かつ 還元率あり
        rect rgb(255, 248, 220)
            Note over Persist: DB保存 (リトライ: 最大3回)
            Agent->>Persist: キャンペーン情報をDBに保存 (is_validated付き)
            Persist->>DB: コンテンツハッシュで既存レコードを確認
        end

        alt 内容に変更なし
            DB-->>Persist: 既存ID (is_show=TRUEに復帰)
        else 新規 または 内容に変更あり
            Persist->>DB: キャンペーンを登録/更新 (is_show=TRUE)
            DB-->>Persist: キャンペーンID
        end
        Persist-->>Agent: 保存結果

        alt DB保存が3回リトライ後も失敗
            Persist-->>Agent: エラー情報
            Note over Agent: エラーを記録して続行
        end
    end

    rect rgb(255, 248, 220)
        Note over Persist: クロールログ保存 (リトライ: 最大3回)
        Agent->>Persist: クロールログをDBに保存
        Persist->>DB: クロールログ挿入
    end
```

---

## 3-3. 未発見キャンペーンの非表示処理

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant DB as MySQL

    Agent->>DB: 実行結果を更新 (処理数・保存数・エラー数)

    Agent->>DB: 今回発見されなかったキャンペーンを is_show=FALSE に更新
    DB-->>Agent: 非表示にした件数
    Note over Agent: 非表示件数をログに記録

    Note over Agent: === 次のサービスへ (ループ継続) ===
```

---

## 4. 後処理 & 結果返却

```mermaid
sequenceDiagram
    participant Agent as パイプライン<br/>エージェント
    participant Browser as ブラウザ<br/>(Playwright)
    participant DB as MySQL
    participant Runner as ADK Runner
    participant Main as メイン処理
    participant User as ユーザー

    Agent->>Browser: ブラウザを終了
    Browser-->>Agent: 終了完了

    Agent->>DB: 保存済みキャンペーン一覧を取得
    DB-->>Agent: キャンペーン一覧
    Agent->>Agent: JSONファイルとしてエクスポート

    Agent-->>Runner: 実行サマリーを返却
    Runner-->>Main: 最終イベント
    Main-->>User: パイプライン完了
```

---

## リトライポリシー

| 設定項目 | デフォルト値 | 環境変数 |
|---|---|---|
| 最大リトライ回数 | 3 | `MAX_RETRIES` |
| バックオフ基準秒数 | 1.0秒 | `RETRY_BACKOFF_BASE` |
| バックオフ計算式 | `base × 2^(attempt-1)` | — |

**リトライ間隔の例 (デフォルト):**

| 試行 | 待機時間 | 累積待機時間 |
|---|---|---|
| 1回目 | 即時実行 | 0秒 |
| 2回目 (リトライ1) | 1秒 | 1秒 |
| 3回目 (リトライ2) | 2秒 | 3秒 |
| (打ち切り) | — | 最大約7秒 |

---

## エラー時の対応一覧

| # | エラー発生箇所 | リトライ | 対応 |
|---|---|---|---|
| 1 | **シードURL収集 (静的取得)** | 最大3回 | 3回失敗 → Playwright にフォールバック |
| 2 | **シードURL収集 (Playwright)** | 最大3回 | 3回失敗 → 静的取得の部分結果があればそれを返却。なければ空URLリスト + エラー |
| 3 | **シードURL収集結果** | — | エラーあり / URLが空 → 実行ログを「失敗」に更新し、このサービスをスキップして次へ |
| 4 | **ページ取得 (静的取得)** | 最大3回 | 3回失敗 → Playwright にフォールバック |
| 5 | **ページ取得 (Playwright)** | 最大3回 | 3回失敗 → 静的取得HTMLが残っていれば特徴抽出。完全失敗ならエラー返却 |
| 6 | **ページ取得結果** | — | エラーあり → クロールログに「取得失敗」として記録し、このURLをスキップ |
| 7 | **LLMページ分類** | 最大3回 | 3回失敗 → 「非キャンペーン」として安全側に倒して続行 |
| 8 | **LLM詳細正規化** | 最大3回 | 3回失敗 → ページタイトルのみ採用し、他フィールドはnullで続行 |
| 9 | **還元率未検出** | — | 正規化結果に還元率なし → DB保存をスキップ（ログのみ記録） |
| 10 | **検証LLM呼び出し** | 最大3回 | 3回失敗 → is_validated=NULL で保存続行（検証不能として扱う） |
| 11 | **検証結果** | — | 検証失敗 (is_valid=false) → is_validated=FALSE で保存し、後から人手レビュー可能にする |
| 12 | **DB保存 (キャンペーン)** | 最大3回 | 3回失敗 → エラー情報を返却、エラーカウントに加算して続行 |
| 13 | **DB保存 (クロールログ)** | 最大3回 | 3回失敗 → エラーをログに記録して続行 |
| 14 | **URL処理全体** | — | 並行処理内で捕捉しエラー情報を返却、他URLの処理は継続 |
| 15 | **非表示処理** | — | DB更新失敗 → エラーをログに記録して続行 (is_show=TRUE のまま残る＝安全側) |
| 16 | **パイプライン全体** | — | finally でブラウザを確実に終了。メイン処理で異常終了コードを返す |
