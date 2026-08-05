"""
Ported from RAGFlow's deepdoc module (Apache-2.0):
https://github.com/infiniflow/ragflow/tree/main/deepdoc
Copyright 2025 The InfiniFlow Authors.

Ported near-verbatim: geometry, OCR, layout-recognition, and
table-structure-recognition logic is unchanged. Removed or replaced:
- All non-PDF format parsers, the resume parser, and the deepdoc_server
  FastAPI service (out of scope -- langparse has its own docx/excel/
  markdown parsers).
- VisionParser and PlainParser (VisionParser needs an LLM and RAGFlow's
  DB/service stack; PlainParser is a no-OCR pypdf fallback, redundant with
  langparse's own `simple` engine).
- Ascend NPU code paths and the remote DLA HTTP client branch (this port is
  CPU/ONNX-only).
- The XGBoost up/down line-merge classifier (updown_cnt_mdl /
  _updown_concat_features) -- confirmed dead code on the live call path in
  the source revision this was ported from: _concat_downward() returns
  immediately after its first two lines.
- rag_tokenizer (a thin wrapper around a tokenizer bundled in the
  infinity-sdk vector-DB client) -- replaced with tokenizer.py, a small
  jieba-backed shim covering the same call sites (is_chinese/tokenize/tag).
- common.*/rag.* cross-package imports -- replaced with local equivalents
  (see model_loader.py for model directory resolution).

operators.py and postprocess.py are themselves derived from PaddleOCR
(Apache-2.0) upstream in RAGFlow; that attribution carries through here too.
"""

from .layout_recognizer import LayoutRecognizer4YOLOv10 as LayoutRecognizer
from .ocr import OCR
from .pdf_parser import RAGFlowPdfParser
from .recognizer import Recognizer
from .table_structure_recognizer import TableStructureRecognizer

__all__ = ["OCR", "LayoutRecognizer", "Recognizer", "TableStructureRecognizer", "RAGFlowPdfParser"]
