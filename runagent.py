"""Root launcher for the Agent CLI."""

from runpy import run_module


if __name__ == "__main__":
    run_module("agent.agent_runtime", run_name="__main__")
