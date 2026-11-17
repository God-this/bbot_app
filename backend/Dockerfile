# syntax=docker/dockerfile:1

# [builder] : 패키지 설치, 모델 내려받는 작업공간
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY backend/requirements-lock.txt /tmp/
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements-lock.txt
COPY deploy/patch_langchain_protocol.sh /tmp/
RUN bash /tmp/patch_langchain_protocol.sh
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')"

# [runtime] : builder에서 필요한 결과물만 가져와 실제로 실행하는 이미지
FROM python:3.11-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    HF_HOME=/opt/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --create-home app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf /opt/hf
WORKDIR /app
COPY --chown=app:app backend/ /app/
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4).status==200 else 1)"
ENTRYPOINT ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["--workers", "1"]
