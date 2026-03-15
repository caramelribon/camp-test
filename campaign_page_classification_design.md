# キャンペーンページ判定設計書

## 1. 目的

本設計書は、キャンペーン関連ページを次の4分類に判定するための設計を定義する。

- `campaign_detail`
- `campaign_list`
- `not_campaign`
- `uncertain`

本判定器の目的は、単に「キャンペーンっぽいか」を判定することではなく、以下を区別することである。

- このページは **1キャンペーンとして保存可能な詳細ページ** か
- このページは **詳細ページを発見するための一覧ページ** か
- それ以外のページか
- ルールベースでは断定困難であり、LLM に判定を委ねるべきページか

---

## 2. 分類定義

### 2.1 `campaign_detail`

このページ単体から、1つのキャンペーンレコードを保存できるページ。

#### 判定基準
- 1つのキャンペーンを主題としている
- タイトルまたは見出しからキャンペーン名らしさがある
- 特典内容がある
- 実施期間がある
- 条件または対象がある
- 1施策についてまとまった説明がある

#### 役割
- 保存対象
- 後続の「キャンペーン種類判定・正規化」処理へ渡す

---

### 2.2 `campaign_list`

複数のキャンペーン詳細ページへの導線として使えるページ。

#### 判定基準
- 一覧、特集、開催中などの表現がある
- 複数のキャンペーンらしいリンクが並んでいる
- 個別詳細情報は薄く、発見用ページとして機能している

#### 役割
- 保存対象ではない
- 詳細ページ候補 URL の発見に利用する

---

### 2.3 `not_campaign`

`campaign_detail` と `campaign_list` のいずれにも該当しないページ。

#### 代表例
- 規約
- FAQ
- 会社情報
- プライバシーポリシー
- 問い合わせ
- サービス説明
- 店舗一覧のみのページ
- エントリーフォーム専用ページ

#### 役割
- 保存対象ではない
- 後続処理を行わない

---

### 2.4 `uncertain`

ルールベースでは断定困難であり、LLM に判定を委ねるべきページ。

#### 該当ケース
- `campaign_detail` と `campaign_list` の境界が曖昧
- キャンペーン語はあるが保存可能性が不足
- ニュース形式だが詳細ページの可能性がある
- `not_campaign` とも言い切れない
- 本文抽出が不足している

#### 役割
- LLM へ最終判定を依頼するための一時状態

---

## 3. 全体フロー

```text
URL
 ↓
HTML取得
 ↓
特徴抽出
 ↓
ルールベース判定
 ├─ confident → detail/list/not_campaign
 └─ ambiguous → uncertain
                  ↓
                LLM判定
                  ↓
          detail/list/not_campaign
```

重要な方針は、**最初から LLM に投げず、ルールベースを主軸にすること** である。

---

## 4. 入力データ設計

判定器は HTML 生文を直接扱うのではなく、前段で抽出されたページ特徴を入力とする。

### 4.1 入力項目

- `url`
- `title`
- `meta_description`
- `h1`
- `headings`
- `main_text`
- `button_texts`
- `anchor_texts`
- `detected_features`

### 4.2 入力データ例

```json
{
  "url": "https://example.com/campaign/spring-2026",
  "title": "春のポイント還元キャンペーン",
  "meta_description": "対象店舗で最大10%還元",
  "h1": "春のポイント還元キャンペーン",
  "headings": ["概要", "実施期間", "対象条件", "注意事項"],
  "main_text": "2026年3月1日から3月31日まで、対象店舗で決済すると最大10%還元...",
  "button_texts": ["エントリーする", "対象店舗を見る"],
  "anchor_texts": ["応募規約", "詳細はこちら"],
  "detected_features": {
    "dates": ["2026年3月1日", "2026年3月31日"],
    "percentages": ["10%"],
    "point_mentions": ["500ポイント"],
    "campaign_keywords": ["キャンペーン", "還元", "エントリー", "対象店舗"]
  }
}
```

---

## 5. 特徴量設計

判定器に必要な特徴量は、大きく次の3群に分かれる。

### 5.1 `campaign_detail` 判定に効く特徴
- 特典の存在
- 実施期間の存在
- 条件または対象の存在
- 1施策を説明している構造
- タイトルや H1 が個別施策名らしいこと

### 5.2 `campaign_list` 判定に効く特徴
- 一覧、特集、開催中などの語
- 複数のキャンペーンらしいリンク
- 本文よりリンク列挙が中心
- 個別情報が薄いこと

### 5.3 `not_campaign` 判定に効く特徴
- FAQ、規約、会社情報、問い合わせ、プライバシーなど
- サービス説明のみ
- キャンペーン関連の特典・期間・条件が弱いこと

---

## 6. 判定ロジックの基本方針

判定は if 文のみで決定せず、各ラベルごとにスコアを持つ。

### 6.1 保持するスコア
- `detail_score`
- `list_score`
- `not_campaign_score`

### 6.2 `uncertain` の扱い
上記3ラベルのいずれにも十分寄らない場合に `uncertain` とする。

---

## 7. `campaign_detail` 判定設計

`campaign_detail` は本設計において最重要であり、**保存可能性で定義する**。

### 7.1 定義
このページだけで、1キャンペーン分の主レコードを作れるページ。

### 7.2 強い判定材料
- キャンペーン名らしいタイトルまたは H1 がある
- 特典内容がある
- 実施期間がある
- 条件または対象がある
- 1つの施策がまとまって説明されている

### 7.3 スコアリング例
- title または h1 に `キャンペーン`, `還元`, `進呈`, `特典`, `応援` などがある: `+2`
- 本文に `%`, `ポイント`, `円相当`, `キャッシュバック`, `抽選` などがある: `+2`
- 日付・期間表現がある: `+2`
- `対象`, `条件`, `要エントリー`, `上限`, `注意事項` がある: `+1`
- 見出しに `概要`, `期間`, `条件`, `対象`, `注意事項` がある: `+1`
- ボタンに `エントリー`, `応募`, `詳細` がある: `+1`

### 7.4 保存可能性の追加チェック
点数が高くても、保存に必要な情報が不足している場合は `campaign_detail` にしない。

#### 追加チェック項目
- `has_campaign_name_like`
- `has_benefit`
- `has_period`
- `has_conditions_or_targets`

上記4項目のうち **3つ以上が true** の場合、保存可能とみなす。

---

## 8. `campaign_list` 判定設計

`campaign_list` は保存対象ではなく、発見用ページとして扱う。

### 8.1 定義
複数の個別キャンペーンへの導線ページ。

### 8.2 強い判定材料
- タイトルまたは H1 に `一覧`, `特集`, `開催中`, `おすすめキャンペーン`
- キャンペーンらしいリンクが複数並んでいる
- 個別施策の条件や期間は薄い
- カードやバナーの列挙が中心

### 8.3 スコアリング例
- title/h1 に `一覧`, `キャンペーン一覧`, `特集`, `実施中`: `+3`
- アンカーテキストにキャンペーン語が複数ある: `+2`
- 同一ドメインのキャンペーン候補 URL が複数ある: `+2`
- 本文よりリンク列挙が中心: `+1`

---

## 9. `not_campaign` 判定設計

`campaign_detail` と `campaign_list` に該当しないページを `not_campaign` とする。

### 9.1 代表例
- 規約
- FAQ
- 会社情報
- プライバシーポリシー
- 問い合わせ
- サービス説明
- 店舗一覧だけのページ
- エントリーフォームだけのページ

### 9.2 スコアリング例
- title/h1 に `利用規約`, `FAQ`, `会社概要`, `お問い合わせ`, `プライバシー`: `+3`
- 特典、期間、条件がほぼない: `+2`
- キャンペーン語が弱い: `+1`
- CTA がログインや会員登録のみ: `+1`

---

## 10. `uncertain` 判定設計

`uncertain` は分類ラベルというより、LLM に渡すための保留状態である。

### 10.1 `uncertain` にする条件
- `detail_score` と `list_score` が近い
- キャンペーン語はあるが保存可能性が不足
- ニュース形式で `campaign_detail` の可能性がある
- スコアは高くないが `not_campaign` とも言い切れない
- 本文抽出が足りない

### 10.2 ルール例
- 最大スコアが一定未満
- 1位と2位の差が小さい
- `campaign_detail` の保存可能性チェックに落ちた

---

## 11. 判定アルゴリズム

### 11.1 基本手順
1. 各ラベルのスコアを計算する
2. 上位2ラベルを確認する
3. 条件を満たせばルールベースで確定する
4. 条件を満たさなければ `uncertain` にする

### 11.2 確定条件
- 最大スコア `>= 6`
- 2位との差 `>= 2`

### 11.3 追加条件
- top が `campaign_detail` の場合は保存可能性チェックを通すこと

---

## 12. 擬似コード

```python
def classify_page(features):
    detail_score = score_detail(features)
    list_score = score_list(features)
    not_campaign_score = score_not_campaign(features)

    scores = {
        "campaign_detail": detail_score,
        "campaign_list": list_score,
        "not_campaign": not_campaign_score,
    }

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_label, top_score = ranked[0]
    second_label, second_score = ranked[1]

    if top_label == "campaign_detail":
        if not is_detail_saveable(features):
            return {
                "label": "uncertain",
                "scores": scores,
                "reason": "detail score is high but saveability is insufficient"
            }

    if top_score >= 6 and (top_score - second_score) >= 2:
        return {
            "label": top_label,
            "scores": scores,
            "reason": "rule-based confident classification"
        }

    return {
        "label": "uncertain",
        "scores": scores,
        "reason": "ambiguous boundary"
    }
```

---

## 13. `is_detail_saveable()` の設計

`campaign_detail` の誤判定を減らすため、保存可能性を別条件で確認する。

```python
def is_detail_saveable(features):
    has_campaign_name = features["has_campaign_name_like"]
    has_benefit = features["has_benefit"]
    has_period = features["has_period"]
    has_conditions = features["has_conditions"] or features["has_target_scope"]

    signals = [has_campaign_name, has_benefit, has_period, has_conditions]
    return sum(signals) >= 3
```

---

## 14. LLM 判定設計

LLM には `uncertain` のみ渡す。

### 14.1 LLM への入力
- URL
- title
- h1
- headings
- main_text
- button_texts
- detected_features
- rule scores
- `uncertain` になった理由

### 14.2 LLM の出力
- `campaign_detail` / `campaign_list` / `not_campaign`
- 判定理由
- confidence
- `campaign_detail` の場合は保存可能な根拠

---

## 15. 判定器の出力形式

後続処理で使いやすいように、出力形式は統一する。

### 15.1 ルールベース確定例

```json
{
  "url": "https://example.com/campaign/abc",
  "label": "campaign_detail",
  "scores": {
    "campaign_detail": 8,
    "campaign_list": 2,
    "not_campaign": 1
  },
  "is_detail_saveable": true,
  "used_llm": false,
  "confidence_type": "rule_high",
  "reason": "title, benefit, period, and conditions are clearly present"
}
```

### 15.2 LLM 解決例

```json
{
  "url": "https://example.com/news/abc",
  "label": "campaign_detail",
  "scores": {
    "campaign_detail": 5,
    "campaign_list": 3,
    "not_campaign": 2
  },
  "is_detail_saveable": true,
  "used_llm": true,
  "confidence_type": "llm_resolved",
  "reason": "news-style page but contains sufficient campaign detail for saving"
}
```

---

## 16. 判定器の責務範囲

本判定器は **ページ種別判定器** である。  
そのため、以下は責務に含めない。

- キャンペーンの種類分類
- DB スキーマへの正規化
- 詳細な数値抽出の最終決定

これらは後段の別エージェントに分離する。

---

## 17. ADK 上での責務分担

Google ADK 構成に落とす場合、本判定部分は次のように責務分担する。

### 17.1 `RuleClassifierTool`
- スコア計算
- 保存可能性判定
- `uncertain` 判定

### 17.2 `UncertainPageJudgeLLMAgent`
- `uncertain` のみ最終判定

### 17.3 Root / Workflow
- 判定結果に応じて `campaign_detail` / `campaign_list` / `not_campaign` の後続処理へ分岐

つまり、判定の中心はルールであり、意味の曖昧さ解消だけを LLM が担当する。

---

## 18. 運用後の改善ポイント

運用開始後は、次の観点で誤判定ログを確認し、改善を行う。

- `campaign_detail` と判定したが保存に必要情報が不足していたケース
- `campaign_list` と判定したが実は `campaign_detail` だったケース
- ニュースページの誤分類
- 規約や対象店舗一覧の誤分類
- キャンペーン語はあるが恒常特典ページだったケース

改善対象は以下である。

- キーワード辞書
- スコア重み
- 保存可能性条件
- LLM に回す閾値

---

## 19. 設計上の重要ポイント

本設計の肝は次の2点である。

### 19.1 `campaign_detail` を保存可能性で定義すること
単に「キャンペーンらしいか」ではなく、「このページ単体で保存できるか」を基準にする。

### 19.2 `uncertain` を許容し、そこだけ LLM に渡すこと
無理にルールで断定せず、曖昧なものだけを意味判定に回すことで、精度とコストのバランスを取る。

---

## 20. 最終まとめ

本判定器は、以下の方針で設計する。

- `campaign_detail` は保存可能性で定義する
- `campaign_list` は詳細発見用ページとして扱う
- それ以外は `not_campaign`
- ルールで断定できないものだけ `uncertain` とし、LLM に委譲する

この設計により、判定処理は次の特性を持つ。

- 保存要件とページ分類要件が一致する
- ルールベースを主軸にして安定運用できる
- LLM 利用箇所を限定できる
- 後続の正規化・保存処理に素直につなげられる
