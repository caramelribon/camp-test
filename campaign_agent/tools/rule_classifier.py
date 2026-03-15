import re
import logging

logger = logging.getLogger(__name__)

# --- Detail scoring keywords ---
DETAIL_TITLE_KEYWORDS = [
    "キャンペーン", "還元", "進呈", "特典", "応援", "プレゼント",
    "キャッシュバック", "抽選", "もれなく", "おトク", "お得",
]

DETAIL_BODY_KEYWORDS = [
    "%", "％", "ポイント", "円相当", "キャッシュバック", "抽選",
    "進呈", "還元", "プレゼント", "クーポン", "割引", "増量",
]

DETAIL_CONDITION_KEYWORDS = [
    "対象", "条件", "要エントリー", "エントリー", "上限", "注意事項",
    "適用条件", "付与条件", "対象外",
]

DETAIL_HEADING_KEYWORDS = [
    "概要", "期間", "条件", "対象", "注意事項", "特典内容",
    "キャンペーン内容", "実施期間", "付与条件", "対象店舗",
]

DETAIL_BUTTON_KEYWORDS = [
    "エントリー", "応募", "詳細", "参加", "登録",
]

# --- List scoring keywords ---
LIST_TITLE_KEYWORDS = [
    "一覧", "キャンペーン一覧", "特集", "実施中", "開催中",
    "おすすめキャンペーン", "おすすめ",
]

# --- Not-campaign scoring keywords ---
NOT_CAMPAIGN_TITLE_KEYWORDS = [
    "利用規約", "規約", "FAQ", "よくある質問", "会社概要", "お問い合わせ",
    "問い合わせ", "プライバシー", "プライバシーポリシー", "特定商取引",
    "ヘルプ", "サポート", "採用", "IR", "会社情報",
]

NOT_CAMPAIGN_CTA_KEYWORDS = [
    "ログイン", "会員登録", "新規登録", "サインイン",
]


def _text_contains_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _count_campaign_links(anchor_texts: list[str]) -> int:
    campaign_words = ["キャンペーン", "還元", "ポイント", "特典", "割引", "クーポン"]
    count = 0
    for text in anchor_texts:
        if any(w in text for w in campaign_words):
            count += 1
    return count


def score_detail(features: dict) -> int:
    score = 0
    title = features.get("title", "")
    h1 = features.get("h1", "")
    main_text = features.get("main_text", "")
    headings = features.get("headings", [])
    button_texts = features.get("button_texts", [])
    detected = features.get("detected_features", {})

    title_h1 = f"{title} {h1}"

    # Title/H1 contains campaign keywords: +2
    if _text_contains_any(title_h1, DETAIL_TITLE_KEYWORDS):
        score += 2

    # Body contains benefit keywords: +2
    if _text_contains_any(main_text, DETAIL_BODY_KEYWORDS):
        score += 2

    # Date/period expressions exist: +2
    if detected.get("dates"):
        score += 2

    # Condition/target keywords: +1
    if _text_contains_any(main_text, DETAIL_CONDITION_KEYWORDS):
        score += 1

    # Headings contain structure keywords: +1
    headings_text = " ".join(headings)
    if _text_contains_any(headings_text, DETAIL_HEADING_KEYWORDS):
        score += 1

    # Button keywords: +1
    buttons_text = " ".join(button_texts)
    if _text_contains_any(buttons_text, DETAIL_BUTTON_KEYWORDS):
        score += 1

    return score


def score_list(features: dict) -> int:
    score = 0
    title = features.get("title", "")
    h1 = features.get("h1", "")
    anchor_texts = features.get("anchor_texts", [])
    main_text = features.get("main_text", "")

    title_h1 = f"{title} {h1}"

    # Title/H1 contains list keywords: +3
    if _text_contains_any(title_h1, LIST_TITLE_KEYWORDS):
        score += 3

    # Multiple campaign-like anchor texts: +2
    campaign_link_count = _count_campaign_links(anchor_texts)
    if campaign_link_count >= 3:
        score += 2

    # Many same-domain campaign links: +2
    if campaign_link_count >= 5:
        score += 2

    # More links than content (heuristic: short main text relative to links)
    if anchor_texts and len(main_text) < len(anchor_texts) * 100:
        score += 1

    return score


def score_not_campaign(features: dict) -> int:
    score = 0
    title = features.get("title", "")
    h1 = features.get("h1", "")
    main_text = features.get("main_text", "")
    button_texts = features.get("button_texts", [])
    detected = features.get("detected_features", {})

    title_h1 = f"{title} {h1}"

    # Title/H1 contains non-campaign keywords: +3
    if _text_contains_any(title_h1, NOT_CAMPAIGN_TITLE_KEYWORDS):
        score += 3

    # No benefit/period/condition signals: +2
    has_benefit = bool(
        detected.get("percentages") or detected.get("point_mentions")
    )
    has_period = bool(detected.get("dates"))
    has_campaign_kw = bool(detected.get("campaign_keywords"))
    if not has_benefit and not has_period and not has_campaign_kw:
        score += 2

    # Weak campaign keywords: +1
    if not has_campaign_kw:
        score += 1

    # CTA is only login/signup: +1
    buttons_text = " ".join(button_texts)
    if _text_contains_any(buttons_text, NOT_CAMPAIGN_CTA_KEYWORDS) and not _text_contains_any(
        buttons_text, DETAIL_BUTTON_KEYWORDS
    ):
        score += 1

    return score


def is_detail_saveable(features: dict) -> bool:
    """Check if the page has enough information to save as a campaign record."""
    title = features.get("title", "")
    h1 = features.get("h1", "")
    main_text = features.get("main_text", "")
    detected = features.get("detected_features", {})
    headings = features.get("headings", [])

    title_h1 = f"{title} {h1}"
    all_text = f"{title_h1} {main_text} {' '.join(headings)}"

    # 1. Has campaign name-like title/h1
    has_campaign_name = _text_contains_any(title_h1, DETAIL_TITLE_KEYWORDS)

    # 2. Has benefit info
    has_benefit = bool(
        detected.get("percentages")
        or detected.get("point_mentions")
        or _text_contains_any(main_text, ["進呈", "還元", "キャッシュバック", "プレゼント", "割引"])
    )

    # 3. Has period info
    has_period = bool(detected.get("dates"))

    # 4. Has conditions/target
    has_conditions = _text_contains_any(all_text, DETAIL_CONDITION_KEYWORDS)

    signals = [has_campaign_name, has_benefit, has_period, has_conditions]
    return sum(signals) >= 3


def classify_page(features: dict) -> dict:
    """Rule-based page classification.

    Returns:
        dict with 'label', 'scores', 'is_detail_saveable', 'used_llm',
        'confidence_type', 'reason'.
    """
    detail = score_detail(features)
    lst = score_list(features)
    not_campaign = score_not_campaign(features)

    scores = {
        "campaign_detail": detail,
        "campaign_list": lst,
        "not_campaign": not_campaign,
    }

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_label, top_score = ranked[0]
    _second_label, second_score = ranked[1]

    # If top is detail, check saveability
    if top_label == "campaign_detail":
        saveable = is_detail_saveable(features)
        if not saveable:
            return {
                "label": "uncertain",
                "scores": scores,
                "is_detail_saveable": False,
                "used_llm": False,
                "confidence_type": "rule_uncertain",
                "reason": "detail score is high but saveability is insufficient",
            }
    else:
        saveable = False

    # Confident if top_score >= 4 and margin >= 2
    if top_score >= 4 and (top_score - second_score) >= 2:
        return {
            "label": top_label,
            "scores": scores,
            "is_detail_saveable": saveable if top_label == "campaign_detail" else False,
            "used_llm": False,
            "confidence_type": "rule_high",
            "reason": "rule-based confident classification",
        }

    # Otherwise uncertain
    return {
        "label": "uncertain",
        "scores": scores,
        "is_detail_saveable": saveable if top_label == "campaign_detail" else False,
        "used_llm": False,
        "confidence_type": "rule_uncertain",
        "reason": "ambiguous boundary",
    }
