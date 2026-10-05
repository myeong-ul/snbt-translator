"""CTranslate2 기반 로컬 NLLB 번역 서버."""
import argparse
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_NAME = os.getenv("SNBT_NLLB_MODEL", "facebook/nllb-200-distilled-600M")
APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = APP_ROOT / "models" / "nllb-200-distilled-600M"
CT2_MODEL_DIR = APP_ROOT / "models" / "nllb-200-distilled-600M-ct2"
LINE_DELIMITER = "\n[=]\n"
LANGUAGE_MAP = {
    "en": "eng_Latn", "ko": "kor_Hang", "ko_kr": "kor_Hang", "ja": "jpn_Jpan",
    "zh-cn": "zho_Hans", "zh_cn": "zho_Hans", "zh-tw": "zho_Hant", "zh_tw": "zho_Hant",
}

app = FastAPI(title="CTranslate2 NLLB Server", version="2.0")
_model = None
_tokenizer = None
_ctranslator = None
_load_lock = threading.Lock()
_inference_lock = threading.Lock()
_load_error: Optional[str] = None


class TranslationRequest(BaseModel):
    text: str
    src_lang: str = "en"
    tgt_lang: str = "ko"


class HealthResponse(BaseModel):
    status: str
    ready: bool
    model: str
    detail: Optional[str] = None


def _resolve_hf_model_dir() -> str:
    if DEFAULT_MODEL_DIR.is_dir() and any(DEFAULT_MODEL_DIR.iterdir()):
        return str(DEFAULT_MODEL_DIR)
    return MODEL_NAME


def _is_ct2_model(path: Path) -> bool:
    return path.is_dir() and (path / "model.bin").exists() and (path / "config.json").exists()


def _convert_model_if_needed(log=print) -> Path:
    if _is_ct2_model(CT2_MODEL_DIR):
        return CT2_MODEL_DIR

    converter = shutil.which("ct2-transformers-converter")
    if not converter:
        raise RuntimeError("ct2-transformers-converter를 찾을 수 없습니다. ctranslate2를 설치하세요.")

    source = _resolve_hf_model_dir()
    CT2_MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)

    # 변환기 자체가 output_dir을 생성하도록 한다. 기존 디렉터리를 미리 만들면
    # converter가 "already exists" 오류를 내므로, 고유한 임시 경로에 먼저 변환한다.
    staging_dir = Path(tempfile.mkdtemp(prefix=f"{CT2_MODEL_DIR.name}.building-", dir=CT2_MODEL_DIR.parent))
    # tempfile.mkdtemp()은 디렉터리를 생성하지만 converter는 output_dir이 없어야 한다.
    staging_dir.rmdir()
    try:
        log(f"[NLLB] CTranslate2 모델 변환을 시작합니다: {source}")
        command = [
            converter, "--model", source, "--output_dir", str(staging_dir),
            "--copy_files", "tokenizer.json",
            "--copy_files", "sentencepiece.bpe.model",
            "--copy_files", "sentencepiece.model",
            "--copy_files", "tokenizer_config.json",
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"CTranslate2 모델 변환 실패:\n{(result.stderr or result.stdout)[-4000:]}"
            )
        if not _is_ct2_model(staging_dir):
            raise RuntimeError("CTranslate2 모델 변환 결과가 올바르지 않습니다.")

        # 정상 변환이 끝난 뒤에만 최종 경로로 게시한다. 이전에 중단되어 남은
        # 불완전한 디렉터리는 새 결과로 교체한다.
        if CT2_MODEL_DIR.exists():
            shutil.rmtree(CT2_MODEL_DIR)
        try:
            staging_dir.replace(CT2_MODEL_DIR)
        except OSError:
            # 다른 서버 프로세스가 먼저 정상 모델을 게시했다면 그 모델을 사용한다.
            if _is_ct2_model(CT2_MODEL_DIR):
                shutil.rmtree(staging_dir, ignore_errors=True)
                return CT2_MODEL_DIR
            raise
        return CT2_MODEL_DIR
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def ensure_model_loaded():
    global _model, _tokenizer, _ctranslator, _load_error
    if _ctranslator is not None:
        return _ctranslator
    with _load_lock:
        if _ctranslator is not None:
            return _ctranslator
        try:
            import ctranslate2
            from transformers import AutoTokenizer

            model_dir = _convert_model_if_needed(print)
            # CT2 변환 출력에는 sentencepiece vocab/tokenizer 파일이 포함되지
            # 않을 수 있으므로 원본 NLLB tokenizer를 사용한다.
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            # CUDA 드라이버가 있어도 CUDA 12 런타임(cublas64_12.dll)이 없으면
            # 첫 추론 시 500 오류가 발생한다. 기본값은 CPU이며, CUDA를 쓸
            # 환경에서는 SNBT_NLLB_DEVICE=cuda로 명시적으로 활성화한다.
            requested_device = os.getenv("SNBT_NLLB_DEVICE", "cpu").lower()
            device = "cuda" if requested_device == "cuda" and ctranslate2.get_cuda_device_count() else "cpu"
            compute_type = os.getenv("SNBT_NLLB_COMPUTE_TYPE", "int8")
            _ctranslator = ctranslate2.Translator(
                str(model_dir), device=device, compute_type=compute_type,
                inter_threads=int(os.getenv("SNBT_NLLB_INTER_THREADS", "4")),
                intra_threads=int(os.getenv("SNBT_NLLB_INTRA_THREADS", "16")),
            )
            _model = model_dir
            _load_error = None
            print(f"[NLLB] CTranslate2 준비 완료: {model_dir}, device={device}, compute_type={compute_type}", flush=True)
            return _ctranslator
        except Exception as exc:
            _load_error = str(exc)
            print(f"[NLLB] CTranslate2 로딩 실패: {exc}", flush=True)
            raise


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok" if _ctranslator is not None else "loading",
                          ready=_ctranslator is not None, model=str(_model or MODEL_NAME), detail=_load_error)


@app.post("/translate")
def translate(payload: TranslationRequest):
    if not payload.text.strip():
        return {"translated_text": payload.text, "model": str(_model or MODEL_NAME)}

    source_code = LANGUAGE_MAP.get(payload.src_lang.lower(), payload.src_lang)
    target_code = LANGUAGE_MAP.get(payload.tgt_lang.lower(), payload.tgt_lang)
    ensure_model_loaded()
    uses_protocol = LINE_DELIMITER in payload.text
    lines = payload.text.split(LINE_DELIMITER) if uses_protocol else payload.text.splitlines() or [payload.text]
    tokenizer = _tokenizer
    tokenizer.src_lang = source_code
    source_id = tokenizer.convert_tokens_to_ids(source_code)
    target_id = tokenizer.convert_tokens_to_ids(target_code)
    if source_id is None or source_id == tokenizer.unk_token_id:
        raise ValueError(f"지원하지 않는 출발 언어 코드입니다: {source_code}")
    if target_id is None or target_id == tokenizer.unk_token_id:
        raise ValueError(f"지원하지 않는 대상 언어 코드입니다: {target_code}")

    # CTranslate2의 Python API는 토큰 문자열과 target_prefix 인자를 사용한다.
    # NLLB tokenizer의 특수 언어 토큰을 정수 ID로 직접 전달하지 않는다.
    tokenized = []
    line_indices = []
    max_input_tokens = 480
    for line_index, line in enumerate(lines):
        tokens = tokenizer.encode(line, add_special_tokens=True)
        if not tokens:
            continue
        token_texts = tokenizer.convert_ids_to_tokens(tokens)
        for offset in range(0, len(token_texts), max_input_tokens):
            tokenized.append(token_texts[offset:offset + max_input_tokens])
            line_indices.append(line_index)
    if not tokenized:
        return {"translated_text": LINE_DELIMITER.join([""] * len(lines)) if uses_protocol else "", "model": str(_model or MODEL_NAME)}

    batch_size = max(1, int(os.getenv("SNBT_NLLB_BATCH_SIZE", "32")))
    outputs = []
    target_prefix = [tokenizer.convert_ids_to_tokens(target_id)]
    with _inference_lock:
        started = time.perf_counter()
        for start in range(0, len(tokenized), batch_size):
            batch = tokenized[start:start + batch_size]
            outputs.extend(_ctranslator.translate_batch(
                batch,
                target_prefix=[target_prefix] * len(batch),
                beam_size=max(1, int(os.getenv("SNBT_NLLB_BEAM_SIZE", "1"))),
                max_batch_size=batch_size,
                max_decoding_length=int(os.getenv("SNBT_NLLB_MAX_DECODING_LENGTH", "256")),
            ))
        elapsed = time.perf_counter() - started
    parts = [[] for _ in lines]
    for index, result in zip(line_indices, outputs):
        hypothesis = result.hypotheses[0]
        output_tokens = list(hypothesis) if isinstance(hypothesis, (list, tuple)) else [hypothesis]
        if output_tokens and output_tokens[0] == target_prefix[0]:
            output_tokens = output_tokens[1:]
        decoded = tokenizer.convert_tokens_to_string([str(token) for token in output_tokens])
        parts[index].append(decoded)
    results = [" ".join(part for part in part_list if part).strip() for part_list in parts]
    translated = LINE_DELIMITER.join(results) if uses_protocol else "\n".join(results)
    print(f"[NLLB] translate_batch lines={len(tokenized)}, elapsed={elapsed:.2f}초", flush=True)
    return {"translated_text": translated, "model": str(_model or MODEL_NAME)}


def main():
    parser = argparse.ArgumentParser(description="CTranslate2 NLLB FastAPI server")
    parser.add_argument("--host", default=os.getenv("SNBT_NLLB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SNBT_NLLB_PORT", "8000")))
    args = parser.parse_args()
    ensure_model_loaded()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()