"""
Boundary token capture extension.

Captures token usage and cost from LLM responses and updates AgentRunner's ExecutionContext.
Runs after every chat_model_call via the chat_model_call_after hook.

Uses _15_ prefix to run early in the hook (before response modification extensions).
"""
import os
from helpers.extension import Extension
from helpers.print_style import PrintStyle


class BoundaryTokenCapture(Extension):
    """Capture token usage and cost from LLM responses. Updates AgentRunner's ExecutionContext."""

    async def execute(self, call_data=None, response="", reasoning="", **kwargs):
        """
        Capture token usage and cost from LLM call and update ExecutionContext.

        Args:
            call_data: Dict containing LLM call metadata (model, messages, etc.)
            response: String response from LLM
            reasoning: String reasoning from LLM
            **kwargs: Additional hook parameters

        Updates:
            - ExecutionContext.token_count (input + output tokens)
            - ExecutionContext.cost_usd (calculated cost)
            - BudgetTracker daily spend (if available)

        Gracefully handles:
            - Missing agent (no-op)
            - Missing call_data (no-op)
            - Missing runner (Phase 36 extensions not active)
            - Missing budget tracker (optional component)
            - Any errors (log and continue - never crash Agent Zero)
        """
        if not self.agent or not call_data:
            return

        try:
            # Get runner (may not exist if Phase 36 extensions not active)
            runner = self.agent.get_data("runner")
            if runner is None:
                return

            # Get model name from call_data
            model = call_data.get("model")
            if not model:
                return
            model_name = getattr(model, "model_name", "unknown")

            # Lazy-initialize token counter (once per agent lifecycle)
            token_counter = self.agent.get_data("boundary_token_counter")
            if token_counter is None:
                from core.boundary.token_counter import TokenCounter
                token_counter = TokenCounter()
                self.agent.set_data("boundary_token_counter", token_counter)

            # Lazy-initialize cost calculator (once per agent lifecycle)
            cost_calculator = self.agent.get_data("boundary_cost_calculator")
            if cost_calculator is None:
                from core.boundary.cost_calculator import CostCalculator

                # Resolve config path (Docker vs dev environment)
                # In Docker container, config is at /a0/config/
                # In dev, relative to VM107 root
                config_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    ))),
                    "config", "model_pricing.yaml"
                )
                if not os.path.exists(config_path):
                    # Fallback: try /a0/config/ (Docker container path)
                    config_path = "/a0/config/model_pricing.yaml"

                cost_calculator = CostCalculator(config_path)
                self.agent.set_data("boundary_cost_calculator", cost_calculator)

            # Count tokens using response text (Tier 2: tiktoken, Tier 3: word count)
            # Note: LiteLLM usage metadata is consumed inside unified_call() and not
            # passed through to the extension hook. We use tiktoken as primary here.
            full_text = (response or "") + (reasoning or "")
            total_tokens = token_counter.count_tokens(full_text)

            # Estimate input/output split:
            # We don't have access to exact input tokens from the hook.
            # Use the messages in call_data to estimate input tokens.
            messages = call_data.get("messages", [])
            input_text = str(messages) if messages else ""
            input_tokens = token_counter.count_tokens(input_text)
            output_tokens = total_tokens  # response + reasoning tokens

            # Calculate cost
            cost_usd = cost_calculator.calculate_cost(
                model_name=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )

            # Update ExecutionContext
            runner.execution_context.token_count += (input_tokens + output_tokens)
            runner.execution_context.cost_usd += cost_usd

            # Update daily budget tracker (if available)
            budget_tracker = self.agent.get_data("boundary_budget_tracker")
            if budget_tracker is not None:
                agent_name = getattr(self.agent, "agent_name", "unknown")
                budget_tracker.add_spend(agent_name, cost_usd)

        except Exception as e:
            # Graceful degradation: log error but don't crash Agent Zero
            PrintStyle.error(f"BoundaryTokenCapture error: {e}")
