import argparse
import pandas as pd
from openai import OpenAI
from pydantic import BaseModel

# config.py에서 환경 설정 로드
from config import OPENAI_API_KEY, OPENAI_LLM_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)
MODEL_NAME = OPENAI_LLM_MODEL or "gpt-4o-mini"

# ==================== 설정 플래그 ====================
# 상세 로그 출력 On/Off 플래그 (False로 변경하거나 아래 출력 블록 주석 처리 가능)
DEBUG_PRINT_EACH = True

# ==================== Pydantic Schema ====================
class RefinedGroundTruth(BaseModel):
    refined_ground_truth: str

# ==================== Ground Truth 정제 함수 ====================
def refine_ground_truth(question: str, raw_gt: str) -> str:
    prompt = f"""
    당신은 창조과학 및 기원 논쟁(성경적 창조론 vs 진화론) 분야의 RAG 평가용 Ground Truth(모범 답안)를 정제하는 전문가입니다.
    주어진 질문에 정확히 대응되도록, 원본 답변을 RAGAS의 Answer Correctness 평가에 최적화된 핵심 모범 답안으로 정교하게 압축 및 재구성해주세요.

    [정제 규칙]
    1. [직접 대응]: 첫 문장은 반드시 [질문]에 대한 직접적인 결론(예: "사실이 아닙니다.", "핵심 쟁점은 ~입니다.")으로 시작하세요.
    2. [핵심 논거 압축]: 원본 답변의 부연 설명, 감정적 수식어, 교훈적 맺음말을 제거하고 핵심 논거 1~2개만 남겨 공백 포함 100~200자 내외로 요약하세요.
    3. [용어 보존]: 창조과학 논쟁의 핵심 개념어(자연주의적 세계관, 유물론, 돌연변이, 자연선택, 기원 등)는 유지하세요.
    4. [팩트 왜곡 금지]: 원본 답변의 주장 및 논거와 어긋나는 새로운 사실을 추가하지 마세요.

    - [질문]: {question}
    - [원본 답변]: {raw_gt}
    """

    response = client.beta.chat.completions.parse(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        response_format=RefinedGroundTruth,
    )
    return response.choices[0].message.parsed.refined_ground_truth

# ==================== Main ====================
def main():
    parser = argparse.ArgumentParser(description="Refine Ground Truth only from dataset.")
    parser.add_argument("--start", type=int, default=0, help="시작 인덱스 (기본값: 0)")
    parser.add_argument("--end", type=int, default=5, help="종료 인덱스 (기본값: 5)")
    parser.add_argument("--file", type=str, default="eval_data.xlsx", help="엑셀 파일 경로")
    args = parser.parse_args()

    df = pd.read_excel(args.file)
    target_df = df.iloc[args.start:args.end].copy()
    total_count = len(target_df)

    print(f"총 {total_count}건 정제 시작 (인덱스 {args.start} ~ {args.end - 1})...\n")

    # 질문 정제 생략 및 20개 단위 진행상황 로그 추가
    refined_ground_truths = []

    for i, (idx, row) in enumerate(target_df.iterrows(), start=1):
        q = str(row["question"])
        raw_gt = str(row["ground_truth"])

        # Ground Truth 정제 실행
        ref_gt = refine_ground_truth(q, raw_gt)
        refined_ground_truths.append(ref_gt)

        # ----------------------------------------------------
        # [2-1 & 2-2] 개별 데이터 전체 출력 (DEBUG_PRINT_EACH 변수로 제어 또는 블록 주석 처리 가능)
        # ----------------------------------------------------
        if DEBUG_PRINT_EACH:
            print("=" * 60)
            print(f"[Index {idx}] ({i}/{total_count})")
            print(f"Q        : {q}")
            print(f"GT (원본): {raw_gt}")
            print(f"GT (정제): {ref_gt}")
            print("=" * 60 + "\n")

        # ----------------------------------------------------
        # [2-3] 20개 단위 진행상황 로그
        # ----------------------------------------------------
        if i % 20 == 0 or i == total_count:
            progress = (i / total_count) * 100
            print(f"[진행 현황] {i}/{total_count}건 처리 완료 ({progress:.1f}%)")

    target_df["refined_ground_truth"] = refined_ground_truths

    output_filename = f"eval_gt_refined_{args.start}_{args.end}.xlsx"
    target_df.to_excel(output_filename, index=False)
    print(f"\n정제 완료: '{output_filename}' 파일로 저장되었습니다.")

if __name__ == "__main__":
    main()