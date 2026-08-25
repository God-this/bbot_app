#!/bin/bash
# langchain-protocol의 TypedDict extra_items 문법이 Python 3.11에서 호환되지 않는 문제 패치
# 원인: langgraph-sdk가 langchain-protocol>=0.0.15를 요구하는데,
#      0.0.15는 Python 3.13+ 전용 extra_items 문법을 사용함
set -e
PROTOCOL_FILE=$(python -c "import langchain_protocol, os; print(os.path.dirname(langchain_protocol.__file__))")/protocol.py
sed -i 's/, extra_items=[^)]*//g' "$PROTOCOL_FILE"
echo "Patched: $PROTOCOL_FILE"
grep "extra_items" "$PROTOCOL_FILE" && echo "⚠️ 패치 실패 — extra_items가 여전히 존재" || echo "✅ 패치 성공"
