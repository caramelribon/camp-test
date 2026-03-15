# キャンペーン情報取得処理 シーケンス図

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant Main as メイン処理
    participant Runner as ADK Runner
    participant Agent as パイプライン<br/>エージェント
    participant DB as MySQL
    participant Seed as シードURL<br/>収集
    participant Fetch as ページ取得<br/>特徴抽出
    participant Browser as ブラウザ<br/>(Playwright)
    participant Rule as ルールベース<br/>分類
    participant LLM as Gemini LLM
    participant Persist as 永続化<br/>エージェント

    %% ===== 起動 =====
    User->>Main: パイプライン実行 (対象サービス指定 / 全件)
    Main->>Runner: エージェントとセッションを生成
    Main->>Runner: パイプラインを非同期実行
    Runner->>Agent: メイン処理を開始

    %% ===== 決済手段の取得 =====
    Agent->>DB: 対象の決済手段を取得
    DB-->>Agent: 決済手段一覧

    alt 決済手段が見つからない
        Agent-->>Runner: 「対象なし」イベントを返却
        Runner-->>Main: パイプライン終了
    end

    %% ===== サービスごとのループ =====
    loop 各決済サービスについて繰り返し
        Agent->>DB: 該当サービスの既存キャンペーンURL一覧を取得
        DB-->>Agent: 既存URL一覧

        Agent->>DB: 実行ログを作成 (実行ID発行)

        %% --- Seed URL 収集 ---
        Agent->>Seed: シードURLからキャンペーン候補URLを収集
        Seed->>Seed: 静的にHTMLを取得してリンクを抽出

        alt 十分なURL数が取得できた (3件以上)
            Seed-->>Agent: 候補URL一覧
        else URL数が不足 または 静的取得に失敗
            Seed->>Browser: JSレンダリングでページを取得
            alt ブラウザ取得成功
                Browser-->>Seed: レンダリング済みHTML
                Seed-->>Agent: 候補URL一覧
            else ブラウザ取得失敗
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

        %% ===== URL ごとの処理 (最大5件 並行) =====
        par 各URLを最大5件ずつ並行処理

            %% --- ページ取得 & 特徴抽出 ---
            Agent->>Fetch: ページを取得して特徴を抽出
            Fetch->>Fetch: 静的にHTMLを取得

            alt 十分なコンテンツが取得できた (200文字以上)
                Fetch-->>Agent: ページ特徴情報
            else コンテンツが不足 または 静的取得に失敗
                Fetch->>Browser: JSレンダリングでページを取得
                alt ブラウザ取得成功
                    Browser-->>Fetch: レンダリング済みHTML
                    Fetch-->>Agent: ページ特徴情報
                else ブラウザ取得失敗
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
                Persist->>DB: クロールログ挿入
                Note over Agent: このURLをスキップ
            end

            %% --- ルールベース分類 ---
            Agent->>Rule: ページ種別をルールで判定
            Rule->>Rule: 詳細/一覧/非キャンペーンの各スコアを算出
            Rule-->>Agent: 分類結果 (ラベル・スコア・信頼度)

            %% --- 判定が曖昧な場合 LLM で再分類 ---
            alt 分類結果が「不確定」
                Agent->>LLM: ページ種別をLLMで判定
                LLM-->>Agent: 判定ラベルと理由
                alt LLM呼び出し失敗
                    Note over Agent: 「非キャンペーン」として安全側に倒して続行
                end
            end

            %% --- キャンペーン詳細の場合: 情報抽出 & 保存 ---
            alt 「キャンペーン詳細」と判定された場合
                Agent->>LLM: キャンペーン情報を抽出・正規化
                Note over LLM: タイトル・期間・還元率<br/>エントリー要否・対象店舗を抽出
                LLM-->>Agent: 正規化されたキャンペーン情報

                alt LLM正規化失敗
                    Note over Agent: ページタイトルのみ採用、他項目はnullで続行
                end

                alt 還元率情報がない
                    Note over Agent: DB保存をスキップ (還元率なし)
                else 還元率情報がある
                    Agent->>LLM: 正規化結果を検証 (VALIDATOR_MODEL_ID)
                    Note over LLM: 各フィールドが元ページに<br/>裏付けがあるか判定
                    LLM-->>Agent: 検証結果 (is_valid / field_results)

                    alt 検証成功 (is_valid=true)
                        Note over Agent: is_validated=TRUE で保存
                    else 検証失敗 (is_valid=false)
                        Note over Agent: is_validated=FALSE で保存 (要レビュー)
                    else 検証LLMエラー
                        Note over Agent: is_validated=NULL で保存 (検証不能)
                    end

                    Agent->>Persist: キャンペーン情報をDBに保存 (is_validated付き)
                    Persist->>DB: コンテンツハッシュで既存レコードを確認
                    alt 内容に変更なし
                        DB-->>Persist: 既存ID (is_show=TRUEに復帰、更新スキップ)
                    else 新規 または 内容に変更あり
                        Persist->>DB: キャンペーンを登録/更新 (is_show=TRUE)
                        DB-->>Persist: キャンペーンID
                    end
                    Persist-->>Agent: 保存結果

                    alt DB保存失敗
                        Persist-->>Agent: エラー情報
                        Note over Agent: エラーを記録して続行
                    end
                end
            end

            %% --- クロールログ保存 ---
            Agent->>Persist: クロールログをDBに保存
            Persist->>DB: クロールログ挿入
        end

        Agent->>DB: 実行結果を更新 (処理数・保存数・エラー数)

        %% --- 未発見キャンペーンの非表示処理 ---
        Agent->>DB: 今回発見されなかったキャンペーンを is_show=FALSE に更新
        DB-->>Agent: 非表示にした件数
        Note over Agent: 非表示件数をログに記録
    end

    %% ===== 後処理 =====
    Agent->>Browser: ブラウザを終了
    Browser-->>Agent: 終了完了

    Agent->>DB: 保存済みキャンペーン一覧を取得
    DB-->>Agent: キャンペーン一覧
    Agent->>Agent: JSONファイルとしてエクスポート

    %% ===== 結果返却 =====
    Agent-->>Runner: 実行サマリーを返却
    Runner-->>Main: 最終イベント
    Main-->>User: パイプライン完了
```

## エラー時の対応一覧

| # | エラー発生箇所 | エラー内容 | 対応 |
|---|---|---|---|
| 1 | **シードURL収集 (静的取得)** | HTTP通信エラー | Playwright にフォールバック。Playwright も失敗した場合は静的取得の部分結果を使用。両方失敗ならエラーを返す |
| 2 | **シードURL収集 (Playwright)** | ブラウザ取得エラー | 静的取得の部分結果があればそれを返却。なければ空URLリスト + エラー |
| 3 | **シードURL収集結果** | エラーあり / URLが空 | 実行ログを「失敗」に更新し、このサービスをスキップして次のサービスへ |
| 4 | **ページ取得 (静的取得)** | HTTP通信エラー | Playwright にフォールバック |
| 5 | **ページ取得 (Playwright)** | ブラウザ取得エラー | 静的取得のHTMLが残っていればそこから特徴抽出。完全失敗ならエラーを返す |
| 6 | **ページ取得結果** | エラーあり | クロールログに「取得失敗」として記録し、このURLをスキップ |
| 7 | **LLMページ分類** | API呼び出し失敗 / JSONパース失敗 | 「非キャンペーン」として安全側に倒して続行 |
| 8 | **LLM詳細正規化** | API呼び出し失敗 / JSONパース失敗 | ページのタイトルのみ採用し、他フィールドはnullで続行 |
| 9 | **還元率未検出** | 正規化結果に還元率なし | DB保存をスキップ（ログのみ記録） |
| 9.5 | **検証LLM呼び出し** | API呼び出し失敗 / JSONパース失敗 | is_validated=NULL で保存続行（検証不能として扱う） |
| 9.6 | **検証結果** | 検証失敗 (is_valid=false) | is_validated=FALSE で保存し、後から人手レビュー可能にする |
| 10 | **DB保存** | データベースエラー | エラー情報を返却、エラーカウントに加算して続行 |
| 11 | **URL処理全体** | 未捕捉の例外 | 並行処理内で捕捉しエラー情報を返却、他URLの処理は継続 |
| 12 | **非表示処理** | DB更新失敗 | エラーをログに記録して続行。キャンペーンは is_show=TRUE のまま残る（安全側） |
| 13 | **パイプライン全体** | 致命的エラー | finally でブラウザを確実に終了。メイン処理で異常終了コードを返す |
