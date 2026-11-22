"""data/articles.jsonl → 임베딩 → Chroma. collect.py 다음에 실행."""
from retriever import build_index

if __name__ == "__main__":
    n = build_index()
    print(f"인덱스 완료: 조문 덩어리 {n}개")
