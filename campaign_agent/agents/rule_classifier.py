from google.adk.agents import LlmAgent
from campaign_agent.config import MODEL_ID
from campaign_agent.tools.rule_classifier import classify_page


rule_classifier_agent = LlmAgent(
    name="rule_classifier",
    model=MODEL_ID,
    instruction="""あなたはページ分類エージェントです。

抽出済みページ特徴をもとに、ルールベースでページ種別を判定してください。

classify_page ツールを使って判定を行ってください。
ページ特徴は state の 'page_features' に格納されています。

ツールの結果をそのまま返してください。""",
    tools=[classify_page],
    output_key="classification_result",
)
