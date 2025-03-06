import os
import re
import uuid

import boto3
import dotenv
import streamlit as st
from mypy_boto3_bedrock_agent_runtime.client import AgentsforBedrockRuntimeClient
from mypy_boto3_bedrock_agent_runtime.type_defs import (
    InvokeAgentResponseTypeDef,
    OrchestrationTraceTypeDef,
    ResponseStreamTypeDef,
)
from streamlit.delta_generator import DeltaGenerator


def initialize_session() -> tuple[str, AgentsforBedrockRuntimeClient]:
    session_id = str(uuid.uuid4())
    client = boto3.client("bedrock-agent-runtime")
    return session_id, client


def display_title() -> None:
    st.title("もやナビ")
    st.text("頭の中のもやもやの原因を分析して、解決策を提示します！")


def display_user_input() -> str | None:
    prompt = st.chat_input(
        "何にもやもやしていますか？",
    )
    if prompt is not None:
        st.subheader("💭あなたのもやもや")
        st.write(prompt)
    return prompt


def create_column_container() -> tuple[DeltaGenerator, DeltaGenerator]:
    search_container, analysis_container = st.columns(2)

    search_container.subheader("🔎検索", divider="rainbow")
    analysis_container.subheader("📊分析", divider="rainbow")

    # 画面が下に伸びるのを防ぐため、1つの値のみを保持するコンテナに変換し、値をAIの出力値で上書きしていく
    search_container = search_container.empty()
    analysis_container = analysis_container.empty()

    return search_container, analysis_container


def invoke_bedrock_agent(
    client: AgentsforBedrockRuntimeClient,
    session_id: str,
    input_text: str,
    enable_trace: bool = True,
) -> InvokeAgentResponseTypeDef:
    dotenv.load_dotenv(override=True)

    agent_id = os.getenv("AGENT_ID")
    agent_alias_id = os.getenv("AGENT_ALIAS_ID")

    assert agent_id is not None
    assert agent_alias_id is not None

    response = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=input_text,
        enableTrace=enable_trace,
    )
    return response


def display_trace(title: str, content: str, container: DeltaGenerator):
    with container:
        st.text_area(title, content, key=str(uuid.uuid4()), height=200)


def extract_thinking_text(xml_str: str) -> str:
    match = re.search(r"<thinking>\s*(.*?)\s*</thinking>", xml_str, re.DOTALL)
    return match.group(1) if match else ""


def handle_trace(
    event: ResponseStreamTypeDef,
    search_container: DeltaGenerator,
    analysis_container: DeltaGenerator,
):
    # traceキーが含まれる場合にのみhandle_traceが呼ばれる
    assert "trace" in event
    assert "trace" in event["trace"]

    if "orchestrationTrace" not in event["trace"]["trace"]:
        return

    trace: OrchestrationTraceTypeDef = event["trace"]["trace"]["orchestrationTrace"]

    # 「モデル入力」トレース：思考内容＝プロンプトは見せない
    if "modelInvocationInput" in trace:
        display_trace("🤔 思考中…", "分析方針を考えています。", analysis_container)

    # 「モデル出力」トレース
    if "modelInvocationOutput" in trace:
        assert "rawResponse" in trace["modelInvocationOutput"]

        output = trace["modelInvocationOutput"]["rawResponse"].get(
            "content", "結果を表示する準備をしています。少々お待ちください。"
        )

        display_trace(
            "💡 思考がまとまりました", extract_thinking_text(output), analysis_container
        )

    # 「根拠」トレース
    if "rationale" in trace:
        display_trace(
            "✅ 次のアクションを決定しました",
            trace["rationale"].get(
                "text", "結果を表示する準備をしています。少々お待ちください。"
            ),
            analysis_container,
        )

    # 「ツール呼び出し」トレース
    if "invocationInput" in trace:
        invocation = trace["invocationInput"]
        invocation_type = invocation.get("invocationType", "")

        if invocation_type == "AGENT_COLLABORATOR":
            agent_name = invocation.get("agentCollaboratorInvocationInput", {}).get(
                "agentCollaboratorName", ""
            )

            input_text = (
                invocation.get("agentCollaboratorInvocationInput", {})
                .get("input", {})
                .get("text", "結果を表示する準備をしています。少々お待ちください。")
            )

            if agent_name:
                display_trace(
                    f"🤖 エージェント「{agent_name}」を呼び出し中…",
                    input_text,
                    search_container,
                )

    # 「観察」トレース
    if "observation" in trace:
        observation = trace["observation"]
        obs_type = observation.get("type", "")

        if obs_type == "AGENT_COLLABORATOR":
            agent_name = observation.get("agentCollaboratorInvocationOutput", {}).get(
                "agentCollaboratorName", ""
            )

            response_text = (
                observation.get("agentCollaboratorInvocationOutput", {})
                .get("output", {})
                .get("text", "結果を表示する準備をしています。少々お待ちください。")
            )

            if agent_name:
                display_trace(
                    f"🤖 エージェント「{agent_name}」が回答しました",
                    response_text,
                    search_container,
                )


def handle_response(
    response: InvokeAgentResponseTypeDef,
    search_container: DeltaGenerator,
    analysis_container: DeltaGenerator,
) -> None:
    for event in response["completion"]:
        if "trace" in event:
            handle_trace(event, search_container, analysis_container)

        if "chunk" in event:
            answer = event["chunk"].get("bytes", b"").decode()
            st.subheader("💡回答")
            st.write(answer)


def display_error_message(exception_str: str) -> None:
    """エラーポップアップを表示する"""
    if "throttlingException" in exception_str:
        error_message = "【エラー】AIモデルの負荷が高いようです。1分待ってから、ブラウザをリロードして再度お試しください🙏（改善しない場合は、モデルを変更するか[サービスクォータの引き上げ申請](https://aws.amazon.com/jp/blogs/news/generative-ai-amazon-bedrock-handling-quota-problems/)を実施ください）"
    else:
        error_message = "【エラー】想定外のエラーが発生しました。開発者に連絡してください。連絡先はxxxです。🙏"
    st.error(error_message)


def main():
    session_id, client = initialize_session()

    display_title()

    prompt = display_user_input()

    if prompt:
        search_container, analysis_container = create_column_container()
        response = invoke_bedrock_agent(client, session_id, prompt)

        try:
            handle_response(response, search_container, analysis_container)
        except Exception as e:
            if "throttlingException" in str(e):
                display_error_message(str(e))
            else:
                display_error_message(str(e))


if __name__ == "__main__":
    main()
