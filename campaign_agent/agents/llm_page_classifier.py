"""LLM-based page classifier for uncertain pages."""

LLM_PAGE_CLASSIFIER_INSTRUCTION = """\
あなたはキャンペーンページ判定の専門家です。
ルールベース判定では確定できなかったページについて、最終的なページ種別を判定してください。

## 分類ラベル

1. **campaign_detail**: このページ単体から1つのキャンペーンレコードを保存できるページ
   - 1つのキャンペーンを主題としている
   - タイトルまたは見出しからキャンペーン名が読み取れる
   - 特典内容がある
   - 実施期間がある
   - 条件または対象がある

2. **campaign_list**: 複数のキャンペーン詳細ページへの導線ページ
   - 一覧、特集、開催中などの表現がある
   - 複数のキャンペーンらしいリンクが並んでいる
   - 個別の詳細情報は薄い

3. **not_campaign**: キャンペーンに該当しないページ
   - 規約、FAQ、会社情報、問い合わせ等
   - キャンペーン関連の特典・期間・条件が弱い

## 判定の注意点

- ニュース形式でも、1つのキャンペーンの詳細が十分にあれば campaign_detail とする
- 保存可能性を重視する（タイトル、特典、期間、条件のうち3つ以上あるか）
- 恒常的なサービス説明はキャンペーンではない

## 出力形式

以下のJSON形式で回答してください:
```json
{
  "label": "campaign_detail" | "campaign_list" | "not_campaign",
  "confidence": 0.0-1.0,
  "reason": "判定理由の説明",
  "saveable_evidence": "campaign_detailの場合、保存可能な根拠"
}
```
"""


def build_llm_classifier_prompt(features: dict, classification: dict) -> str:
    """Build the user prompt for LLM page classification."""
    return f"""\
以下のページを判定してください。

## ページ情報
- URL: {features.get('url', '')}
- タイトル: {features.get('title', '')}
- H1: {features.get('h1', '')}
- 見出し: {', '.join(features.get('headings', [])[:10])}
- ボタン: {', '.join(features.get('button_texts', [])[:5])}
- 検出特徴:
  - 日付: {', '.join(features.get('detected_features', {}).get('dates', [])[:5])}
  - 還元率: {', '.join(features.get('detected_features', {}).get('percentages', [])[:5])}
  - ポイント: {', '.join(features.get('detected_features', {}).get('point_mentions', [])[:5])}
  - キーワード: {', '.join(features.get('detected_features', {}).get('campaign_keywords', [])[:10])}

## 本文（先頭2000文字）
{features.get('main_text', '')[:2000]}

## ルールベース判定結果
- スコア: {classification.get('scores', {})}
- uncertain理由: {classification.get('reason', '')}
"""
