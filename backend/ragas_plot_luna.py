import json
import glob
import platform
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# ==================== 한글 폰트 설정 ====================
if platform.system() == "Darwin":       # macOS
    plt.rcParams["font.family"] = "AppleGothic"
elif platform.system() == "Windows":
    plt.rcParams["font.family"] = "Malgun Gothic"
else:
    plt.rcParams["font.family"] = "NanumGothic"
plt.rcParams["axes.unicode_minus"] = False

# ==================== 데이터 로드 ====================
# luna 평가 결과 폴더 (파일명 날짜는 실행일에 맞게 와일드카드로 전부 읽음)
JSONL_GLOB = "./eval_logs/eval_gpt-5.6-luna_*.jsonl"

records = []
for path in sorted(glob.glob(JSONL_GLOB)):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

if not records:
    raise FileNotFoundError(f"평가 결과 파일을 찾을 수 없습니다: {JSONL_GLOB}")

df = pd.DataFrame(records)
print(f"📋 로드된 평가 결과: {len(df)}개")

metrics = [
    "faithfulness", "answer_relevancy", "context_precision",
    "context_recall", "answer_correctness", "duration",
]
for m in metrics:
    if m in df.columns:
        df[m] = pd.to_numeric(df[m], errors="coerce")

df["q_label"] = [f"Q{i+1}" for i in range(len(df))]

# ==================== 통계 계산 함수 ====================
def get_stats(series, is_duration=False):
    s = series.dropna()
    n = len(s)
    if n == 0:
        return {}
    stats = {
        "min": s.min(), "max": s.max(), "avg": s.mean(),
        "nan": len(series) - n, "total": len(series),
    }
    if not is_duration:
        stats["above_75"]     = int((s >= 0.75).sum())
        stats["above_75_pct"] = (s >= 0.75).mean() * 100
        stats["above_95"]     = int((s >= 0.95).sum())
        stats["above_95_pct"] = (s >= 0.95).mean() * 100
    else:
        stats["above_5"]      = int((s >= 5).sum())
        stats["above_5_pct"]  = (s >= 5).mean() * 100
        stats["above_10"]     = int((s >= 10).sum())
        stats["above_10_pct"] = (s >= 10).mean() * 100
    return stats


def stat_text(stats, is_duration=False):
    if not stats:
        return "데이터 없음"
    unit = "s" if is_duration else ""
    nan_note = f"  (NaN: {stats['nan']}개)" if stats["nan"] > 0 else ""
    lines = [
        f"min {stats['min']:.3f}{unit}   max {stats['max']:.3f}{unit}   avg {stats['avg']:.3f}{unit}{nan_note}",
    ]
    if not is_duration:
        lines.append(
            f"≥0.75: {stats['above_75']}개 ({stats['above_75_pct']:.1f}%)   "
            f"≥0.95: {stats['above_95']}개 ({stats['above_95_pct']:.1f}%)"
        )
    else:
        lines.append(
            f"≥5s: {stats['above_5']}개 ({stats['above_5_pct']:.1f}%)   "
            f"≥10s: {stats['above_10']}개 ({stats['above_10_pct']:.1f}%)"
        )
    return "\n".join(lines)


# ==================== 콘솔 통계 출력 ====================
print("\n" + "=" * 65)
print(f"{'RAGAS 평가 통계 요약 (gpt-5.6-luna)':^65}")
print("=" * 65)
for m in metrics:
    if m in df.columns:
        is_dur = (m == "duration")
        s = get_stats(df[m], is_duration=is_dur)
        print(f"\n[{m}]")
        print(" " + stat_text(s, is_duration=is_dur).replace("\n", "\n "))
print("=" * 65 + "\n")

# ==================== 그래프 ====================
colors = {
    "faithfulness":       "#3266ad",
    "answer_relevancy":   "#e2734a",
    "context_precision":  "#5a9e6f",
    "context_recall":     "#9b6bbf",
    "answer_correctness": "#c9994f",
    "duration":           "#73726c",
}

plot_metrics = [
    ("faithfulness",       "Faithfulness",       False),
    ("answer_relevancy",   "Answer Relevancy",   False),
    ("context_precision",  "Context Precision",  False),
    ("context_recall",     "Context Recall",     False),
    ("answer_correctness", "Answer Correctness", False),
    ("duration",           "Duration (seconds)", True),
]
plot_metrics = [pm for pm in plot_metrics if pm[0] in df.columns]

x = np.arange(len(df))
step = max(1, len(df) // 20)

n_rows = len(plot_metrics) + 1  # 마지막 행은 지표 평균 요약
fig = plt.figure(figsize=(18, 5 * n_rows))
fig.suptitle("RAGAS Evaluation Results — gpt-5.6-luna", fontsize=17, fontweight="bold", y=0.995)

gs = gridspec.GridSpec(n_rows, 1, figure=fig, hspace=0.55)

for i, (col, title, is_dur) in enumerate(plot_metrics):
    ax = fig.add_subplot(gs[i, 0])
    values = df[col]
    ax.bar(x, values.fillna(0), color=colors.get(col, "#666666"), alpha=0.85, width=0.7)

    s = get_stats(values, is_duration=is_dur)
    if s:
        ax.axhline(s["avg"], color="red", linestyle="--", linewidth=1, alpha=0.8)

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_xticks(x[::step])
    ax.set_xticklabels(df["q_label"].iloc[::step], rotation=45, ha="right", fontsize=8)
    if not is_dur:
        ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)

    ax.text(
        0.5, -0.32, stat_text(s, is_duration=is_dur),
        transform=ax.transAxes, ha="center", va="top", fontsize=10,
        bbox=dict(boxstyle="round", facecolor="#f5f5f5", edgecolor="#cccccc"),
    )

# ---- 지표 평균 비교 (bar) ----
ax = fig.add_subplot(gs[n_rows - 1, 0])
score_metrics = [m for m, _, is_dur in plot_metrics if not is_dur]
avgs = [df[m].mean() for m in score_metrics]
bar_colors = [colors[m] for m in score_metrics]
bars = ax.bar(score_metrics, avgs, color=bar_colors, alpha=0.85, width=0.5)
for bar, v in zip(bars, avgs):
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02, f"{v:.3f}",
            ha="center", va="bottom", fontsize=10, fontweight="bold")
ax.set_title("Average Score Summary", fontsize=13, fontweight="bold")
ax.set_ylim(0, 1.15)
ax.set_xticklabels(score_metrics, rotation=15, fontsize=9)
ax.grid(axis="y", alpha=0.3)

plt.tight_layout(rect=[0, 0, 1, 0.98])
out_path = "ragas_eval_results_luna.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
plt.show()
print(f"✅ {out_path} 저장 완료")