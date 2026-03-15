from google.adk.agents import LlmAgent
from campaign_agent.config import MODEL_ID
from campaign_agent.tools.seed_collector import collect_seed_urls


seed_collector_agent = LlmAgent(
    name="seed_collector",
    model=MODEL_ID,
    instruction="""あなたはキャンペーンURL収集エージェントです。

与えられたseed URLにアクセスし、キャンペーン候補URLを収集してください。

collect_seed_urls ツールを使って、seed URLからリンクを抽出してください。
seed URLは state の 'current_seed_url' に格納されています。

ツールの結果をそのまま返してください。""",
    tools=[collect_seed_urls],
    output_key="seed_result",
)
