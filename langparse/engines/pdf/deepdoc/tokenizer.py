"""
Lightweight stand-in for RAGFlow's rag_tokenizer (which itself wraps a
tokenizer bundled inside the infinity-sdk vector-DB client). deepdoc's live
call sites only need coarse signals -- "is this char CJK", "how many
word-tokens is this text", "is this single token a person name" -- for
table-cell type classification, not text reconstruction, so a real
segmenter (jieba) is enough; we don't need infinity-sdk's tokenizer.
"""

from __future__ import annotations

import jieba
import jieba.posseg as jieba_posseg

_CJK_RANGE = ("一", "鿿")


def is_chinese(text: str) -> bool:
    return bool(text) and any(_CJK_RANGE[0] <= ch <= _CJK_RANGE[1] for ch in text)


def tokenize(text: str) -> str:
    return " ".join(jieba.cut(text))


def tag(token: str) -> str:
    if not token:
        return ""
    words = list(jieba_posseg.cut(token))
    return words[0].flag if words else ""
