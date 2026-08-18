import json
import glob
import platform
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ==================== 한글 폰트 설정 ====================
if platform.system() == "Darwin":
    plt.rcParams["font.family"] = "AppleGothic"
elif platform.system() == "Windows":
    plt.rcParams["font.family"] = "Malgun Gothic"
else:
    plt.rcParams["font.family"] = "NanumGothic"
plt.rcParams["axes.unicode_minus"] = False

# ==================== 비교할 두 모델의 결과 파일 ====================
# 경로가 다르면 여기만 수정하면 됨
MODEL_A_NAME = "gpt-5.5"
MODEL_A_GLOB = "./eval_logs/eval_202605192.jsonl"

MODEL_B_NAME = "gpt-5.6-luna"
MODEL_B_GLOB = "./eval_logs/eval_gpt-5.6-luna_*.jsonl"

METRICS = [
    "faithfulness", "answer_relevancy", "context_precision",
    "context_recall", "answer_correctness",
]


def load_jsonl(glob_pattern: str) -> pd.DataFrame:
    records = []
    paths = sorted(glob.glob(glob_pattern))
    if not paths:
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {glob_pattern}")
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    df = pd.DataFrame(records)
    for m in METRICS + ["duration"]:
        if m in df.columns:
            df[m] = pd.to_numeric(df[m], errors="coerce")
    return df


df_a = load_jsonl(MODEL_A_GLOB)
df_b = load_jsonl(MODEL_B_GLOB)

print(f"📋 {MODEL_A_NAME}: {len(df_a)}개")
print(f"📋 {MODEL_B_NAME}: {len(df_b)}개")

# ==================== 지표별 평균 비교 ====================
avg_a = {m: df_a[m].mean() if m in df_a.columns else np.nan for m in METRICS}
avg_b = {m: df_b[m].mean() if m in df_b.columns else np.nan for m in METRICS}

print("\n" + "=" * 70)
print(f"{'지표':<20}{MODEL_A_NAME:>15}{MODEL_B_NAME:>18}{'차이(B-A)':>15}")
print("=" * 70)
for m in METRICS:
    a, b = avg_a[m], avg_b[m]
    diff = b - a if not (np.isnan(a) or np.isnan(b)) else np.nan
    diff_str = f"{diff:+.4f}" if not np.isnan(diff) else "-"
    print(f"{m:<20}{a:>15.4f}{b:>18.4f}{diff_str:>15}")
print("=" * 70 + "\n")

# ==================== 그래프 1: 지표별 평균 막대 비교 ====================
fig, axes = plt.subplots(1, 2, figsize=(18, 7))

ax = axes[0]
x = np.arange(len(METRICS))
width = 0.35

bars_a = ax.bar(x - width/2, [avg_a[m] for m in METRICS], width,
                 label=MODEL_A_NAME, color="#3266ad", alpha=0.85)
bars_b = ax.bar(x + width/2, [avg_b[m] for m in METRICS], width,
                 label=MODEL_B_NAME, color="#e2734a", alpha=0.85)

for bars in (bars_a, bars_b):
    for bar in bars:
        h = bar.get_height()
        if not np.isnan(h):
            ax.text(bar.get_x() + bar.get_width()/2, h + 0.01, f"{h:.3f}",
                    ha="center", va="bottom", fontsize=9, fontweight="bold")

ax.set_xticks(x)
ax.set_xticklabels(METRICS, rotation=20, ha="right", fontsize=10)
ax.set_ylim(0, 1.15)
ax.set_title("지표별 평균 비교", fontsize=14, fontweight="bold")
ax.legend()
ax.grid(axis="y", alpha=0.3)

# ==================== 그래프 2: 소요 시간(duration) 비교 ====================
ax2 = axes[1]
dur_a = df_a["duration"].mean() if "duration" in df_a.columns else np.nan
dur_b = df_b["duration"].mean() if "duration" in df_b.columns else np.nan
bars = ax2.bar([MODEL_A_NAME, MODEL_B_NAME], [dur_a, dur_b],
               color=["#3266ad", "#e2734a"], alpha=0.85, width=0.4)
for bar, v in zip(bars, [dur_a, dur_b]):
    if not np.isnan(v):
        ax2.text(bar.get_x() + bar.get_width()/2, v + 0.1, f"{v:.2f}s",
                  ha="center", va="bottom", fontsize=11, fontweight="bold")
ax2.set_title("평균 응답 시간 비교", fontsize=14, fontweight="bold")
ax2.set_ylabel("seconds")
ax2.grid(axis="y", alpha=0.3)

plt.suptitle(f"RAGAS 평가 비교: {MODEL_A_NAME} vs {MODEL_B_NAME}", fontsize=16, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.95])
out_path = f"ragas_compare_{MODEL_A_NAME}_vs_{MODEL_B_NAME}.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
plt.show()
print(f"✅ {out_path} 저장 완료")

# ==================== 그래프 3: 문항별 지표 라인 비교 (faithfulness 예시) ====================
# q_num 기준으로 매칭 (없으면 순서대로 매칭)
def get_q_index(df):
    if "q_num" in df.columns:
        return df["q_num"]
    return pd.Series(range(1, len(df) + 1))

fig2, axes2 = plt.subplots(len(METRICS), 1, figsize=(16, 4 * len(METRICS)))
if len(METRICS) == 1:
    axes2 = [axes2]

for ax, m in zip(axes2, METRICS):
    if m not in df_a.columns or m not in df_b.columns:
        continue
    qa = get_q_index(df_a)
    qb = get_q_index(df_b)
    ax.plot(qa, df_a[m], marker="o", markersize=3, label=MODEL_A_NAME, color="#3266ad", alpha=0.8)
    ax.plot(qb, df_b[m], marker="o", markersize=3, label=MODEL_B_NAME, color="#e2734a", alpha=0.8)
    ax.set_title(m, fontsize=12, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

plt.tight_layout()
out_path2 = f"ragas_compare_by_question_{MODEL_A_NAME}_vs_{MODEL_B_NAME}.png"
plt.savefig(out_path2, dpi=150, bbox_inches="tight")
plt.show()
print(f"✅ {out_path2} 저장 완료")