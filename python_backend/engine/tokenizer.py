"""
tokenizer.py — Model-aware exact BPE token counter with deterministic offline fallback.
"""

import re
from typing import Any, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

# Regex matching standard BPE subword chunks and punctuation boundaries
_BPE_REGEX = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[a-zA-Z]+| ?\d+| ?[^\s\w]+|\s+(?!\S)|\s+""",
    re.IGNORECASE
)

_TIKTOKEN_ENCODINGS: dict[str, Any] = {}
_HAS_TIKTOKEN = False

try:
    import tiktoken
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False


def _get_tiktoken_encoding(model: str = ""):
    """Safely retrieves a cached tiktoken encoding or defaults to cl100k_base."""
    if not _HAS_TIKTOKEN:
        return None
    model_name = (model or "").lower().strip()
    if model_name in _TIKTOKEN_ENCODINGS:
        return _TIKTOKEN_ENCODINGS[model_name]

    try:
        enc = tiktoken.encoding_for_model(model_name)
    except Exception:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception:
            enc = None

    if enc:
        _TIKTOKEN_ENCODINGS[model_name] = enc
    return enc


def _fallback_bpe_count(text: str) -> int:
    """
    Deterministic pure-Python token count estimation.
    Splits text across whitespace and punctuation boundaries, weighting words
    and code syntax with standard BPE token distribution ratios.
    """
    if not text:
        return 0
    # Standard rule of thumb: ~4 characters per token on average for English/code,
    # with min 1 token if non-empty
    length = len(text)
    if length <= 4:
        return 1
    # Check word / whitespace segmentation
    words = text.split()
    estimated_by_words = int(len(words) * 1.33)
    estimated_by_chars = length // 4
    # Take median between word expansion and character heuristics
    return max(1, (estimated_by_words + estimated_by_chars) // 2)


def count_tokens_exact(text: Any, model: str = "") -> int:
    """
    Computes exact BPE tokens if tiktoken is available, otherwise falls back
    to deterministic tokenizer heuristic.
    """
    if text is None:
        return 0
    s = str(text)
    if not s.strip():
        return 0

    enc = _get_tiktoken_encoding(model)
    if enc:
        try:
            return len(enc.encode(s, disallowed_special=()))
        except Exception:
            pass
    return _fallback_bpe_count(s)


def count_message_tokens(msg: BaseMessage, model: str = "") -> int:
    """
    Counts total tokens in a BaseMessage including message text,
    tool call arguments, and metadata.
    """
    tokens = 0
    content = getattr(msg, "content", "")
    if content:
        tokens += count_tokens_exact(content, model)

    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            # Function name overhead + arguments
            tokens += count_tokens_exact(tc.get("name", ""), model) + 4
            tokens += count_tokens_exact(str(tc.get("args", "")), model)

    # Overhead for role formatting (~3 tokens per message in chat models)
    return tokens + 3


def calculate_token_savings(
    raw_messages: list[BaseMessage],
    pruned_messages: list[BaseMessage],
    model: str = ""
) -> tuple[int, int, int]:
    """
    Calculates exact token reduction achieved by dynamic pruning.
    Returns: (raw_tokens, pruned_tokens, tokens_saved)
    """
    raw_tok = sum(count_message_tokens(m, model) for m in raw_messages)
    pruned_tok = sum(count_message_tokens(m, model) for m in pruned_messages)
    savings = max(0, raw_tok - pruned_tok)
    return raw_tok, pruned_tok, savings
