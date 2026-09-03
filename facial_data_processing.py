import pandas as pd
import numpy as np

# ========== 1. 读取文件 ==========
file_path = r"C:\Users\WilliamLi\Desktop\SURF\Output_Final Final.xlsx"
df = pd.read_excel(file_path, engine="openpyxl")
print(f"共 {len(df)} 行原始数据")

# ========== 2. 解析时间戳 ==========
df["datetime"] = pd.to_datetime(
    df["日期"].astype(str) + " " + df["时间"].astype(str),
    format="%Y%m%d %H:%M:%S.%f",
    errors="coerce"
)
df = df.dropna(subset=["datetime"])
df = df.set_index("datetime").sort_index()

# ========== 3. 映射情绪分类 ==========
face_rules = {
    "FACE_A": {
        "高兴": "positive", "悲伤": "negative", "愤怒": "negative",
        "厌恶": "negative", "惊讶": "neutral", "自然": "neutral"
    },
    "FACE_B": {
        "高兴": "positive", "悲伤": "negative", "愤怒": "negative",
        "厌恶": "exclude", "惊讶": "neutral", "自然": "neutral"
    }
}
df["label_A"] = df["面部情绪"].map(face_rules["FACE_A"])
df["label_B"] = df["面部情绪"].map(face_rules["FACE_B"])

# ========== 4. 按分钟聚合（新公式 + 保留原筛选逻辑） ==========
df["minute"] = df.index.floor("min")
groups = df.groupby("minute")

processed_rows = 0
last_report = 0
result_list = []

for minute, group in groups:
    # ===== FACE-A 计算 =====
    pos_a = (group["label_A"] == "positive").sum()
    neg_a = (group["label_A"] == "negative").sum()
    neu_a = (group["label_A"] == "neutral").sum()
    
    # 无任何正负情绪 → 设为空值，后续删除
    if pos_a + neg_a == 0:
        score_a = np.nan
    else:
        # 分母 = 积极 + 负面 + 中性，得分更平滑
        score_a = (pos_a - neg_a) / (pos_a + neg_a + neu_a)
    
    # ===== FACE-B 计算 =====
    pos_b = (group["label_B"] == "positive").sum()
    neg_b = (group["label_B"] == "negative").sum()
    neu_b = (group["label_B"] == "neutral").sum()
    
    if pos_b + neg_b == 0:
        score_b = np.nan
    else:
        score_b = (pos_b - neg_b) / (pos_b + neg_b + neu_b)
    
    result_list.append({
        "minute": minute,
        "face_a": score_a,
        "face_b": score_b
    })
    
    # 进度提示
    processed_rows += len(group)
    if processed_rows - last_report >= 2000:
        print(f"  ⏳ 已处理 {processed_rows} 行 / 共 {len(df)} 行")
        last_report = processed_rows

# 转成 DataFrame，删除全空分钟（无有效正负情绪的分钟）
minute_df = pd.DataFrame(result_list).set_index("minute")
minute_df = minute_df.dropna(how="all")
print(f"聚合完成，共 {len(minute_df)} 个有有效得分的分钟")

# ========== 5. 标准化 + 输出 ==========
minute_df["z_face_a"] = (minute_df["face_a"] - minute_df["face_a"].mean()) / minute_df["face_a"].std()
minute_df["z_face_b"] = (minute_df["face_b"] - minute_df["face_b"].mean()) / minute_df["face_b"].std()

print("\n===== 前5行结果 =====")
print(minute_df.head())
print("\n===== 描述性统计 =====")
print(minute_df.describe())

minute_df.to_excel("minute_face_scores.xlsx", engine="openpyxl")
print("\n结果已保存为 minute_face_scores.xlsx")
