"""DetailNormalizationAgent - Extract campaign data from detail pages."""

DETAIL_NORMALIZATION_INSTRUCTION = """\
あなたはキャンペーン情報抽出の専門家です。
campaign_detail と判定されたページから、以下の4項目のみを抽出してください。

## 抽出項目

以下のJSON形式で回答してください:
```json
{
  "title": "キャンペーン名（タイトルやH1から抽出）",
  "period_text": "実施期間（開始日〜終了日）",
  "reward_rate_text": "還元率情報（例: '+5%', '10%還元', '500ポイント'）",
  "entry_required": true or false,
  "target_stores": "対象店舗・対象加盟店名（例: 'セブン-イレブン、ファミリーマート'）"
}
```

## 注意点

- 情報がない項目は null にしてください
- entry_required はエントリーが必要な場合は true、不要または不明な場合は false にしてください
- target_stores は対象店舗・対象加盟店が明記されている場合のみ記載し、なければ null にしてください
- 金額・ポイント数・還元率などの数値は原文のまま残してください
- 期間は原文の表記を保持してください
"""


def build_detail_normalization_prompt(features: dict, service_name: str, source_list_url: str) -> str:
    """Build the user prompt for detail normalization."""
    return f"""\
以下のキャンペーンページから情報を抽出してください。

## サービス情報
- サービス名: {service_name}
- 元の一覧URL: {source_list_url}

## ページ情報
- URL: {features.get('url', '')}
- タイトル: {features.get('title', '')}
- H1: {features.get('h1', '')}
- 見出し: {', '.join(features.get('headings', [])[:15])}
- ボタン: {', '.join(features.get('button_texts', [])[:5])}
- 検出特徴:
  - 日付: {', '.join(features.get('detected_features', {}).get('dates', [])[:10])}
  - 還元率: {', '.join(features.get('detected_features', {}).get('percentages', [])[:5])}
  - ポイント: {', '.join(features.get('detected_features', {}).get('point_mentions', [])[:5])}

## 本文
{features.get('main_text', '')[:3000]}
"""
