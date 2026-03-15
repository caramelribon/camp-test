from google.adk.agents import LlmAgent
from campaign_agent.config import MODEL_ID
from campaign_agent.tools.fetch_extract import fetch_and_extract


fetch_extract_agent = LlmAgent(
    name="fetch_extract",
    model=MODEL_ID,
    instruction="""あなたはページ特徴抽出エージェントです。

与えられたURLのHTMLを取得し、ページの特徴を抽出してください。

fetch_and_extract ツールを使って、URLからページ特徴を抽出してください。
対象URLは state の 'current_url' に格納されています。

ツールの結果をそのまま返してください。""",
    tools=[fetch_and_extract],
    output_key="page_features",
)
