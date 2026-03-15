"""DetailValidationAgent - Validate normalized campaign data against original page content."""

DETAIL_VALIDATION_INSTRUCTION = """\
あなたはキャンペーン情報の検証専門家です。
LLMが抽出・正規化したキャンペーン情報が、元のページ内容と**明らかに矛盾していないか**を検証してください。

## 重要な原則

**検証の目的は「捏造されたデータ」を検出することです。**
ページに実際に記載されている情報を正しく抽出できているなら、is_valid=true としてください。
曖昧なケースや解釈の余地があるケースは valid として扱ってください。

## 検証対象フィールド

- title: キャンペーン名がページのタイトル・H1・見出し・本文のいずれかに含まれているか
- period_text: 実施期間がページの本文に記載されている日付と矛盾しないか
- reward_rate_text: 還元率・ポイント情報がページ本文の記載と矛盾しないか
- entry_required: エントリー要否がページ内容と明らかに矛盾しないか
- target_stores: 対象店舗がページに記載されているか

## 判定基準（厳守）

1. **null/None のフィールドは必ず valid=true（検証スキップ）**とする。nullであること自体を理由に invalid にしてはいけない
2. **完全一致は不要** — 部分一致、要約、言い換えでも意味的に同等ならば valid とする
3. **is_valid=false にするのは、title または reward_rate_text がページ内容と明確に矛盾する場合のみ**
4. period_text, entry_required, target_stores は多少の不一致があっても is_valid 全体には影響しない（個別フィールドのvalid=falseは可）
5. **迷った場合は valid=true** とする（寛容に判定する）

## is_valid の最終判定ルール

- title が valid かつ reward_rate_text が valid → **is_valid=true**
- title が invalid または reward_rate_text が invalid → **is_valid=false**
- null フィールドは常に valid 扱い

## 出力形式

以下のJSON形式で回答してください:
```json
{
  "is_valid": true,
  "field_results": {
    "title": {"valid": true, "reason": "ページのH1と一致"},
    "period_text": {"valid": true, "reason": "本文中の日付と一致"},
    "reward_rate_text": {"valid": true, "reason": "還元率の記載と一致"},
    "entry_required": {"valid": true, "reason": "エントリーボタンの存在と一致"},
    "target_stores": {"valid": true, "reason": "対象店舗の記載と一致"}
  },
  "summary": "全フィールドがページ内容と一致しています"
}
```
"""


def build_detail_validation_prompt(features: dict, normalized_data: dict) -> str:
    """Build the user prompt for validating normalized data against original page."""
    # Format normalized data for display
    normalized_fields = []
    for key in ("title", "period_text", "reward_rate_text", "entry_required", "target_stores"):
        value = normalized_data.get(key)
        normalized_fields.append(f"  - {key}: {value}")
    normalized_text = "\n".join(normalized_fields)

    return f"""\
以下の正規化されたキャンペーン情報が、元ページの内容と矛盾しないか検証してください。

## 元ページの情報
- URL: {features.get('url', '')}
- タイトル: {features.get('title', '')}
- H1: {features.get('h1', '')}
- 見出し: {', '.join(features.get('headings', [])[:15])}

## 本文
{features.get('main_text', '')[:3000]}

## 正規化された結果（検証対象）
{normalized_text}

## 検証指示
- 各項目が元ページの本文に裏付けがあるかチェックしてください
- 完全一致でなくても、意味的に同等であればvalidとしてください
- null/Noneのフィールドは必ずvalid=trueとしてください（スキップ扱い）
- is_validをfalseにするのは、titleまたはreward_rate_textが本文と明確に矛盾する場合のみです
- 迷った場合はvalid=trueとしてください
"""
