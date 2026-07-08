from dataclasses import dataclass

from app.core.config import settings


@dataclass
class SDKRunResult:
    used_sdk: bool
    output: str
    error: str | None = None


class OpenAIAgentsRuntime:
    async def run_research_summary(self, question: str, evidence: str) -> SDKRunResult:
        if settings.agent_runtime == "local":
            return SDKRunResult(used_sdk=False, output="")
        if not settings.openai_api_key:
            return SDKRunResult(used_sdk=False, output="", error="OPENAI_API_KEY is not configured.")

        try:
            from agents import Agent, Runner, function_tool
        except Exception as exc:
            return SDKRunResult(used_sdk=False, output="", error=f"Agents SDK unavailable: {exc}")

        @function_tool
        def get_grounding_evidence() -> str:
            """Return retrieved evidence that must ground the answer."""
            return evidence

        agent = Agent(
            name="ResearchOps Research Agent",
            instructions=(
                "Answer only from get_grounding_evidence. "
                "If evidence is insufficient, say that directly. "
                "Keep the answer concise and cite source labels from the evidence."
            ),
            model=settings.openai_agent_model,
            tools=[get_grounding_evidence],
        )

        try:
            result = await Runner.run(agent, question)
        except Exception as exc:
            return SDKRunResult(used_sdk=False, output="", error=f"Agents SDK run failed: {exc}")
        return SDKRunResult(used_sdk=True, output=str(result.final_output))


openai_agents_runtime = OpenAIAgentsRuntime()
