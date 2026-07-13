class LLMError(Exception):
    """Base error for recoverable LLM failures."""


class ProviderError(LLMError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


class EvidenceValidationError(LLMError):
    pass
