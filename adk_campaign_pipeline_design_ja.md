# ADKキャンペーン処理フロー設計書

## 1. 目的

本設計書は、Google ADK を用いてキャンペーンページの収集・判定・正規化・保存を行うための処理フローを定義するものである。

対象フローは、以下のエージェント構成を前提とする。

```text
[Root CustomAgent]
  ↓
[SequentialAgent]
  1. SeedCollectorAgent
  2. ParallelAgent(URLごと)
     2-1. FetchExtractAgent
     2-2. RuleClassifierTool
     2-3. If uncertain → LLMPageClassifierAgent
     2-4. If campaign_detail → DetailNormalizationAgent
     2-5. CampaignTypeStructuringAgent
     2-6. PersistenceAgent
```

本フローの目的は、キャンペーン候補ページを安定的に処理し、最終的に保存可能なキャンペーンデータとしてデータベースへ反映することである。

---

## 2. 全体方針

本設計では、処理を大きく次の2層に分ける。

### 2.1 全体制御層
- `Root CustomAgent`
- `SequentialAgent`

この層では、処理順序の制御、各エージェントの呼び出し、分岐制御、最終結果の集約を行う。

### 2.2 URL単位処理層
- `ParallelAgent(URLごと)` 以下の各処理

この層では、1つの URL を入力として、取得・特徴抽出・ページ分類・詳細正規化・種類判定・保存までを行う。

このように分離することで、全体の流れは順序制御しつつ、URLごとの処理は並列に実行できる構成とする。

---

## 3. エージェント構成概要

## 3.1 Root CustomAgent

### 役割
全体オーケストレーションを担う最上位エージェント。

### 主な責務
- 実行開始
- seed URL 群の受け取り
- `SequentialAgent` の起動
- 実行結果の集約
- エラー時の制御
- 実行ログやメトリクスの取りまとめ

### 採用理由
本フローでは固定順序処理に加え、条件分岐や例外制御が必要であるため、柔軟な制御が可能な `CustomAgent` をルートに採用する。

---

## 3.2 SequentialAgent

### 役割
全体処理を定義済みの順序で実行するワークフローエージェント。

### 実行順序
1. `SeedCollectorAgent`
2. `ParallelAgent(URLごと)`

### 主な責務
- 発見処理を先に行う
- 取得した URL 群を URL 単位処理へ渡す
- 後段の並列処理結果を受け取る

### 採用理由
本フローは「発見 → URL単位処理」という明確な順序を持つため、逐次実行に適した `SequentialAgent` を採用する。

---

## 4. URL発見フェーズ

## 4.1 SeedCollectorAgent

### 役割
seed URL を起点として、処理対象となる候補 URL を収集する。

### 入力
- サービス名
- seed URL 一覧
- 収集ルール

### 出力
- 候補 URL 一覧

### 主な処理
- seed URL へアクセス
- `<a>` タグから URL を抽出
- 相対 URL を絶対 URL に変換
- 同一ドメイン制限を適用
- 重複 URL を除去
- 明らかに不要な URL を除外

### 位置づけ
このエージェントは、後続処理の入力データとなる URL 群を作る「発見担当」である。

---

## 5. URL単位並列処理フェーズ

## 5.1 ParallelAgent(URLごと)

### 役割
収集された候補 URL ごとに同一処理フローを並列実行する。

### 入力
- 1件の候補 URL
- サービス名
- seed URL 情報

### 出力
- URL単位の処理結果
- ページ判定結果
- 保存結果
- エラー情報

### 採用理由
候補 URL は独立して処理可能であるため、URLごとに並列実行することで全体処理時間を短縮できる。

---

## 6. URL単位処理の詳細

## 6.1 FetchExtractAgent

### 役割
対象 URL の HTML を取得し、後続判定に必要な特徴を抽出する。

### 入力
- URL

### 出力
- `url`
- `title`
- `meta_description`
- `h1`
- `headings`
- `main_text`
- `button_texts`
- `anchor_texts`
- `detected_features`

### 主な処理
- HTML 取得
- 不要要素除去
- 本文抽出
- タイトル、見出し、ボタン文言抽出
- 日付、還元率、ポイント、キーワード等の特徴抽出

### 位置づけ
ページ内容を「分類可能な構造化情報」に変換するための前処理担当である。

---

## 6.2 RuleClassifierTool

### 役割
抽出済み特徴をもとに、ページ種別をルールベースで判定する。

### 入力
- `FetchExtractAgent` の出力

### 出力
- `campaign_detail`
- `campaign_list`
- `not_campaign`
- `uncertain`
- スコア情報
- 判定理由

### 主な処理
- `detail_score` の算出
- `list_score` の算出
- `not_campaign_score` の算出
- 保存可能性チェック
- 高信頼判定なら即確定
- 曖昧な場合は `uncertain`

### 判定方針
- `campaign_detail` は保存可能性で定義する
- `campaign_list` は発見用ページとして扱う
- detail/list/not_campaign に明確に寄らないものは `uncertain`

### 位置づけ
ページ判定の第一段階であり、全件に対して必ず実行する deterministic な判定担当である。

---

## 6.3 LLMPageClassifierAgent

### 実行条件
`RuleClassifierTool` の結果が `uncertain` の場合のみ実行する。

### 役割
ルールベースでは断定困難なページに対して、意味理解を用いた最終ページ判定を行う。

### 入力
- URL
- title
- h1
- headings
- main_text
- button_texts
- detected_features
- ルールベーススコア
- `uncertain` 判定理由

### 出力
- `campaign_detail`
- `campaign_list`
- `not_campaign`
- confidence
- 判定理由

### 主な処理
- ニュース形式ページの意味判定
- detail と list の境界判断
- not_campaign との最終切り分け

### 位置づけ
ルールベース判定の補完担当であり、全件ではなく曖昧ケースのみに限定して使用する。

---

## 6.4 DetailNormalizationAgent

### 実行条件
ページ判定結果が `campaign_detail` の場合に実行する。

### 役割
詳細ページから、保存前の生キャンペーンデータを作成する。

### 入力
- `campaign_detail` と判定されたページ特徴
- URL
- seed URL 情報

### 出力
- `service_name`
- `detail_url`
- `source_list_url`
- `title`
- `reward_text`
- `period_text`
- `condition_text`
- `raw_text`

### 主な処理
- キャンペーン名抽出
- 特典文言抽出
- 実施期間抽出
- 条件・対象文言抽出
- 生本文保持

### 位置づけ
ページを「保存前のキャンペーンオブジェクト」に変換する担当である。

---

## 6.5 CampaignTypeStructuringAgent

### 実行条件
`DetailNormalizationAgent` の後に実行する。

### 役割
生キャンペーンデータを読み取り、キャンペーン種類の判定と保存用スキーマへの正規化を行う。

### 入力
- 正規化前キャンペーンデータ
- 前段で抽出済みの特徴量

### 出力
- `campaign_type_primary`
- `campaign_type_secondary`
- `condition_tags`
- `normalized_campaign`
- `detail_json`
- `confidence`
- `needs_review`
- `reasons`

### 主な処理
- 主分類判定
- 条件タグ抽出
- 報酬情報の構造化
- 共通DBスキーマへのマッピング
- 種類別詳細 JSON の生成
- review 要否判定

### 位置づけ
「ページとしての detail」を「DB保存可能なキャンペーン構造」に変換する中核担当である。

---

## 6.6 PersistenceAgent

### 役割
最終的なキャンペーンデータおよび処理ログを保存する。

### 入力
- `normalized_campaign`
- URL単位判定結果
- 実行メタデータ

### 出力
- 保存成功／失敗結果
- upsert 結果
- ログ保存結果

### 主な処理
- キャンペーンデータの upsert
- crawl log の保存
- 実行履歴の記録
- 重複防止制御
- review 対象データの保留登録

### 位置づけ
最終保存担当であり、AI判断結果を永続化する役割を担う。

---

## 7. URL単位処理の条件分岐

URLごとの処理では、以下のような分岐を行う。

### 7.1 `campaign_detail` の場合
1. `DetailNormalizationAgent` 実行
2. `CampaignTypeStructuringAgent` 実行
3. `PersistenceAgent` 実行

### 7.2 `campaign_list` の場合
- 保存対象ではない
- crawl log のみ保存する
- 必要に応じて発見元として利用する

### 7.3 `not_campaign` の場合
- 保存対象ではない
- crawl log のみ保存する

### 7.4 `uncertain` の場合
1. `LLMPageClassifierAgent` 実行
2. LLM結果が `campaign_detail` なら後続正規化・保存へ進む
3. `campaign_list` または `not_campaign` なら保存対象外としてログのみ保存する

---

## 8. 処理責務の整理

各コンポーネントの責務は以下のように整理する。

### Root CustomAgent
- 全体制御
- 実行管理
- 条件分岐
- 結果集約

### SequentialAgent
- 固定順序のワークフロー実行

### SeedCollectorAgent
- URL 発見

### FetchExtractAgent
- HTML取得と特徴抽出

### RuleClassifierTool
- ルールベースページ判定

### LLMPageClassifierAgent
- 曖昧ページの意味判定

### DetailNormalizationAgent
- 詳細ページをキャンペーン生データへ変換

### CampaignTypeStructuringAgent
- キャンペーン種類判定
- 正規化
- 構造化

### PersistenceAgent
- DB保存
- ログ保存

---

## 9. 設計意図

本設計は、1本の巨大なAIエージェントにすべてを任せるのではなく、各段階の責務を分離して安定性を高めることを目的とする。

### 9.1 ルールベース優先
ページ判定はまず `RuleClassifierTool` で行い、LLM は `uncertain` のみ担当する。

### 9.2 deterministic 処理の分離
- HTML取得
- 特徴抽出
- スコア計算
- DB保存

などは deterministic に処理し、AI に任せない。

### 9.3 意味理解が必要な箇所だけ LLM を使う
- 曖昧なページ判定
- キャンペーン種類の解釈
- 条件タグ付け
- 保存用スキーマへの意味的正規化

### 9.4 URL単位処理の並列化
URL単位で独立処理とすることで、サイト数・URL数が増えても拡張しやすい構成とする。

---

## 10. 最終まとめ

本フローは、次の考え方で設計する。

- ルートでは `Root CustomAgent` が全体制御を担う
- 主ワークフローは `SequentialAgent` により順序制御する
- URLごとの処理は `ParallelAgent` により並列実行する
- ページ分類は `RuleClassifierTool` を主軸とし、`uncertain` のみ `LLMPageClassifierAgent` に委譲する
- `campaign_detail` に確定したページのみ正規化・種類判定・保存へ進める
- 最終保存は `PersistenceAgent` が担当する

この構成により、以下を実現できる。

- 安定した順序制御
- URL単位の並列処理
- LLM利用箇所の限定
- 保存可能なキャンペーンデータへの整形
- 将来的な拡張や運用改善のしやすさ
