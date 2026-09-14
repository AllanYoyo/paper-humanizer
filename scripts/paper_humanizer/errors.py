"""Exception hierarchy for paper-humanizer.

Exit-code contract (see docs/ARCHITECTURE.md B.4):
  0 = success, 1 = validation/repair failures (report produced), 2 = input or internal error.
"""


class PaperHumanizerError(Exception):
    """Base class for all paper-humanizer errors."""


class ConfigError(PaperHumanizerError):
    """Invalid or missing configuration (e.g. bundled assets not found)."""


class ProviderError(PaperHumanizerError):
    """LLM provider call failed or returned unusable output."""


class ProviderNotConfigured(ProviderError):
    """No LLM provider is configured for a step that requires one."""


class PromptError(PaperHumanizerError):
    """Prompt template missing, unfilled placeholders, or unparseable LLM JSON."""
