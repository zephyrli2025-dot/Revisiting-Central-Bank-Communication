import pandas as pd
import numpy as np
import statsmodels.api as sm


# ============================================================
# 0. 文件接口
# ============================================================


EMOTION_FILE = "minute_face_scores.xlsx"
MARKET_FILE = "SH.000300.csv"

OUTPUT_DATA_FILE = "SURF_regression_data.xlsx"
OUTPUT_RESULT_FILE = "SURF_OLS_results.xlsx"


# ============================================================
# 1. 读取情绪数据
# ============================================================

emotion = pd.read_excel(
    EMOTION_FILE,
    engine="openpyxl"
)

# 将 minute 转换为真正的 datetime
emotion["minute"] = pd.to_datetime(
    emotion["minute"],
    errors="coerce"
)

# 删除无法解析时间的数据
emotion = emotion.dropna(
    subset=["minute"]
)

# 设置 timestamp 为索引
emotion = emotion.set_index(
    "minute"
).sort_index()


# ============================================================
# 2. 读取沪深300分钟 CSV
# ============================================================

market = pd.read_csv(
    MARKET_FILE
)

# 转换时间
market["时间"] = pd.to_datetime(
    market["时间"],
    errors="coerce"
)

# 删除无法解析时间的数据
market = market.dropna(
    subset=["时间"]
)


# ============================================================
# 3. 确保市场价格是数字
# ============================================================

for column in [
    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "成交量",
    "成交额"
]:

    if column in market.columns:

        market[column] = pd.to_numeric(
            market[column],
            errors="coerce"
        )


market = market.dropna(
    subset=["收盘价"]
)


# ============================================================
# 4. 找出所有交易日
# ============================================================
#
# 这里不使用交易所日历。
#
# 因为你的 CSV 是从淘宝获得的实际沪深300市场数据，
# 所以直接根据 CSV 中实际存在的日期判断交易日。
#
# 这样可以自动处理：
#
#     周末
#     春节
#     国庆
#     其他节假日
#
# ============================================================

market_dates_all = sorted(
    market["时间"]
    .dt.normalize()
    .unique()
)

trading_dates = set(
    market_dates_all
)


# ============================================================
# 5. 找到情绪数据涉及的日期
# ============================================================

emotion_dates = set(
    emotion.index
    .normalize()
    .unique()
)


# ============================================================
# 6. 为 overnight 保留“下一交易日”的市场数据
# ============================================================
#
# 例如：
#
# 情绪：
#
#     2020-01-15 16:30
#
# 那么我们需要：
#
#     2020-01-15 收盘价
#     2020-01-16 开盘价
#
# 如果：
#
#     2020-01-17 16:30
#
# 下一交易日可能是：
#
#     2020-01-20
#
# 因此不能简单地只筛选 emotion_dates。
#
# ============================================================

required_market_dates = set(
    emotion_dates
)


for emotion_date in emotion_dates:

    # 找到该日期之后的第一个交易日

    future_dates = [
        d
        for d in market_dates_all
        if d > emotion_date
    ]

    if len(future_dates) > 0:

        next_date = future_dates[0]

        required_market_dates.add(
            next_date
        )


# ============================================================
# 7. 筛选市场数据
# ============================================================

market = market[
    market["时间"]
    .dt.normalize()
    .isin(required_market_dates)
].copy()


print(
    f"筛选后市场数据量: {len(market)}"
)


# ============================================================
# 8. 设置市场数据时间索引
# ============================================================

market = market.set_index(
    "时间"
).sort_index()


# ============================================================
# 9. 定义中国 A 股正常交易时间
# ============================================================
#
# 上午：
#
#     09:30 – 11:30
#
# 下午：
#
#     13:00 – 15:00
#
# ============================================================

def is_trading_time(timestamp):

    time = timestamp.time()

    morning = (
        time >= pd.Timestamp(
            "09:30:00"
        ).time()
        and
        time <= pd.Timestamp(
            "11:30:00"
        ).time()
    )

    afternoon = (
        time >= pd.Timestamp(
            "13:00:00"
        ).time()
        and
        time <= pd.Timestamp(
            "15:00:00"
        ).time()
    )

    return (
        morning
        or
        afternoon
    )


# ============================================================
# 10. 找到下一交易日
# ============================================================

def get_next_trading_date(date):

    for trading_date in market_dates_all:

        if trading_date > date:

            return trading_date

    return None


# ============================================================
# 11. 判断情绪事件属于什么类型
# ============================================================
#
# INTRADAY：
#
#     交易日 + 交易时间
#
#     → t+5 / t+10 / t+20
#
#
# OVERNIGHT：
#
#     交易日 + 收盘以后
#
#     → 当天收盘 → 下一交易日开盘
#
#
# NON_TRADING_DAY：
#
#     周末 / 节假日
#
#     → 排除
#
# ============================================================

emotion_data = emotion.reset_index()

emotion_data["date"] = (
    emotion_data["minute"]
    .dt.normalize()
)


emotion_data["market_open"] = (
    emotion_data["date"]
    .isin(trading_dates)
)


emotion_data["within_trading_hours"] = (
    emotion_data["minute"]
    .apply(is_trading_time)
)


emotion_data["event_type"] = np.where(

    ~emotion_data["market_open"],

    "NON_TRADING_DAY",

    np.where(

        emotion_data[
            "within_trading_hours"
        ],

        "INTRADAY",

        "OVERNIGHT"
    )
)


# ============================================================
# 12. 输出事件类型统计
# ============================================================

print("\n")
print("=" * 60)
print("事件类型统计")
print("=" * 60)

print(
    emotion_data[
        "event_type"
    ].value_counts()
)


# ============================================================
# 13. 构造市场未来收益
# ============================================================
#
# 本研究按照原实验使用：
#
#     t+5
#     t+10
#     t+20
#
#
# 使用 log return：
#
#     R(t,t+h)
#       =
#     ln(P[t+h] / P[t])
#
#
# 例如：
#
#     return_t+5
#
#     =
#     ln(P[t+5] / P[t])
#
#
# 注意：
#
# 这里的 t+5 是“未来第5个分钟观测”，
# 而不是简单地 timestamp + 5 minutes。
#
# 这意味着午休不会被错误地计算成市场收益。
#
# ============================================================

price = market[
    "收盘价"
]


market[
    "return_t+5"
] = np.log(
    price.shift(-5)
    /
    price
)


market[
    "return_t+10"
] = np.log(
    price.shift(-10)
    /
    price
)


market[
    "return_t+20"
] = np.log(
    price.shift(-20)
    /
    price
)


# ============================================================
# 14. 处理交易时间内的事件
# ============================================================
#
# 对于 INTRADAY：
#
#     emotion timestamp
#             =
#     market timestamp
#
# 只有完全相同的 timestamp 才进行匹配。
#
# 不使用 nearest matching。
#
# ============================================================

intraday_emotion = emotion_data[
    emotion_data[
        "event_type"
    ]
    ==
    "INTRADAY"
].copy()


intraday_emotion = (
    intraday_emotion
    .set_index("minute")
)


market_columns = [

    "开盘价",
    "最高价",
    "最低价",
    "收盘价",
    "成交量",
    "成交额",

    "return_t+5",
    "return_t+10",
    "return_t+20"
]


intraday_data = (
    intraday_emotion
    .join(
        market[
            market_columns
        ],
        how="inner"
    )
)


# ============================================================
# 15. 处理 OVERNIGHT 事件
# ============================================================
#
# 对于：
#
#     交易日 + 收盘以后
#
# 定义：
#
#     R_overnight
#
#       =
#
#     ln(
#         Next Trading Day Open
#         /
#         Same Day Close
#     )
#
# ============================================================

overnight_emotion = emotion_data[
    emotion_data[
        "event_type"
    ]
    ==
    "OVERNIGHT"
].copy()


overnight_results = []


for _, row in overnight_emotion.iterrows():

    event_time = row[
        "minute"
    ]

    event_date = row[
        "date"
    ]


    # --------------------------------------------------------
    # 当天市场数据
    # --------------------------------------------------------

    same_day_market = market[
        market.index.normalize()
        ==
        event_date
    ]


    if len(same_day_market) == 0:

        continue


    # --------------------------------------------------------
    # 当天收盘价
    #
    # 使用当天最后一个市场观测值
    # --------------------------------------------------------

    same_day_close = (
        same_day_market[
            "收盘价"
        ].iloc[-1]
    )


    # --------------------------------------------------------
    # 下一交易日
    # --------------------------------------------------------

    next_trading_date = (
        get_next_trading_date(
            event_date
        )
    )


    if next_trading_date is None:

        continue


    # --------------------------------------------------------
    # 下一交易日市场数据
    # --------------------------------------------------------

    next_day_market = market[
        market.index.normalize()
        ==
        next_trading_date
    ]


    if len(next_day_market) == 0:

        continue


    # --------------------------------------------------------
    # 下一交易日开盘价
    # --------------------------------------------------------

    next_day_open = (
        next_day_market[
            "开盘价"
        ].iloc[0]
    )


    # --------------------------------------------------------
    # Overnight log return
    #
    #     R = ln(
    #         Next Open /
    #         Same Day Close
    #     )
    # --------------------------------------------------------

    overnight_return = np.log(
        next_day_open
        /
        same_day_close
    )


    result = row.to_dict()


    result[
        "开盘价"
    ] = next_day_open


    result[
        "收盘价"
    ] = same_day_close


    result[
        "return_overnight"
    ] = overnight_return


    result[
        "next_trading_date"
    ] = next_trading_date


    overnight_results.append(
        result
    )


overnight_data = pd.DataFrame(
    overnight_results
)


# ============================================================
# 16. 给 INTRADAY 数据补充 overnight 字段
# ============================================================

if len(intraday_data) > 0:

    intraday_data = (
        intraday_data
        .reset_index()
    )

    intraday_data[
        "return_overnight"
    ] = np.nan

    intraday_data[
        "next_trading_date"
    ] = pd.NaT


# ============================================================
# 17. 合并 INTRADAY + OVERNIGHT
# ============================================================

frames = []


if len(intraday_data) > 0:

    frames.append(
        intraday_data
    )


if len(overnight_data) > 0:

    frames.append(
        overnight_data
    )


if len(frames) > 0:

    data = pd.concat(
        frames,
        ignore_index=True,
        sort=False
    )

else:

    data = pd.DataFrame()


# 按时间排序

if len(data) > 0:

    data = data.sort_values(
        "minute"
    )


# ============================================================
# 18. 最终数据统计
# ============================================================

print("\n")
print("=" * 60)
print("最终数据统计")
print("=" * 60)

print(
    f"原始情绪观测数: "
    f"{len(emotion)}"
)


print(
    f"交易时间内成功匹配: "
    f"{len(intraday_data)}"
)


print(
    f"成功处理的隔夜事件: "
    f"{len(overnight_data)}"
)


print(
    f"最终进入分析的观测数: "
    f"{len(data)}"
)


if len(emotion) > 0:

    print(
        f"最终保留比例: "
        f"{len(data) / len(emotion):.2%}"
    )


print("\n最终数据前10行：")

print(
    data.head(10)
)


# ============================================================
# 19. 保存最终数据
# ============================================================
#
# 这个 Excel 用于人工审查。
#
# 建议重点检查：
#
#     minute
#     event_type
#     z_face_a
#     z_face_b
#     收盘价
#     return_t+5
#     return_t+10
#     return_t+20
#     return_overnight
#     next_trading_date
#
# ============================================================

data.to_excel(
    OUTPUT_DATA_FILE,
    index=False,
    engine="openpyxl"
)


print(
    f"\n匹配后的数据已经保存到："
    f"{OUTPUT_DATA_FILE}"
)


# ============================================================
# 20. OLS + Newey-West HAC
# ============================================================
#
# 基本模型：
#
#     R(t,t+h)
#
#       =
#
#     α + β * Emotion_t + ε_t
#
#
# 其中：
#
#     R(t,t+h)
#         = 未来 h 分钟累计 log return
#
#     Emotion_t
#         = 当前分钟的标准化情绪
#
#     α
#         = 截距
#
#     β
#         = 情绪与未来收益之间的线性关系
#
#
# OLS 估计：
#
#     α_hat
#     β_hat
#
#
# 但是由于 t+5/t+10/t+20 的收益存在 overlap，
# 相邻 observation 的误差项可能存在自相关：
#
#     Cov(ε_t, ε_(t-k)) != 0
#
#
# 因此普通 OLS standard errors 可能不可靠。
#
#
# Newey-West HAC：
#
#     Heteroskedasticity and
#     Autocorrelation Consistent
#
# 用来计算：
#
#     heteroskedasticity-robust
#     autocorrelation-robust
#
# 的标准误。
#
#
# 重要：
#
#     HAC 不改变 Beta。
#
#     它主要改变：
#
#         Standard Error
#         t-statistic
#         p-value
#
#
# 本研究最大 horizon = 20，
# 因此基准 HAC 设置：
#
#     maxlags = 20
#
# ============================================================


emotion_variables = [

    "z_face_a",

    "z_face_b"
]


return_variables = [

    "return_t+5",

    "return_t+10",

    "return_t+20",

    "return_overnight"
]


results = []


for emotion_variable in emotion_variables:

    for return_variable in return_variables:


        # ====================================================
        # 21. 根据收益类型选择样本
        # ====================================================

        if return_variable == "return_overnight":

            regression_data = data[
                data[
                    "event_type"
                ]
                ==
                "OVERNIGHT"
            ][
                [
                    emotion_variable,
                    return_variable
                ]
            ].dropna()

            event_type = (
                "OVERNIGHT"
            )

        else:

            regression_data = data[
                data[
                    "event_type"
                ]
                ==
                "INTRADAY"
            ][
                [
                    emotion_variable,
                    return_variable
                ]
            ].dropna()

            event_type = (
                "INTRADAY"
            )


        # ====================================================
        # 22. 检查样本数量
        # ====================================================

        if len(regression_data) < 5:

            print(
                f"跳过 "
                f"{emotion_variable} → "
                f"{return_variable}: "
                f"有效样本不足"
            )

            continue


        # ====================================================
        # 23. X = Emotion
        #
        # 模型：
        #
        #     R = α + βE + ε
        #
        # add_constant 增加截距项 α。
        # ====================================================

        X = regression_data[
            [emotion_variable]
        ]


        X = sm.add_constant(
            X
        )


        # ====================================================
        # 24. y = Future Return
        # ====================================================

        y = regression_data[
            return_variable
        ]


        # ====================================================
        # 25. OLS + Newey-West HAC
        # ====================================================
        #
        # maxlags = 20
        #
        # 允许误差项存在最多20阶的时间序列相关性。
        #
        # ====================================================

        model = sm.OLS(
            y,
            X
        ).fit(

            cov_type="HAC",

            cov_kwds={
                "maxlags": 20
            }
        )


        # ====================================================
        # 26. 保存统计结果
        # ====================================================

        results.append({

            "Emotion":
                emotion_variable,

            "Horizon":
                return_variable,

            "Event Type":
                event_type,

            "N":
                int(model.nobs),

            "Alpha":
                model.params[
                    "const"
                ],

            "Beta":
                model.params[
                    emotion_variable
                ],

            "Beta Std Error (HAC)":
                model.bse[
                    emotion_variable
                ],

            "t-statistic (HAC)":
                model.tvalues[
                    emotion_variable
                ],

            "p-value (HAC)":
                model.pvalues[
                    emotion_variable
                ],

            "R-squared":
                model.rsquared,

            "Adjusted R-squared":
                model.rsquared_adj
        })


# ============================================================
# 27. 整理回归结果
# ============================================================

results_df = pd.DataFrame(
    results
)


print("\n")
print("=" * 60)
print("OLS + Newey-West HAC Regression Results")
print("=" * 60)


if len(results_df) > 0:

    print(
        results_df.to_string(
            index=False
        )
    )


# ============================================================
# 28. 保存 OLS 结果
# ============================================================

results_df.to_excel(
    OUTPUT_RESULT_FILE,
    index=False,
    engine="openpyxl"
)


print(
    f"\nOLS + HAC结果已经保存到："
    f"{OUTPUT_RESULT_FILE}"
)


# ============================================================
# 29. 显著性检查
# ============================================================

print("\n")
print("=" * 60)
print("HAC 显著性检查")
print("=" * 60)


for _, row in results_df.iterrows():

    beta = row[
        "Beta"
    ]

    p = row[
        "p-value (HAC)"
    ]


    # --------------------------------------------------------
    # 显著性
    # --------------------------------------------------------

    if p < 0.01:

        significance = (
            "非常显著 (p < 0.01)"
        )

    elif p < 0.05:

        significance = (
            "显著 (p < 0.05)"
        )

    elif p < 0.10:

        significance = (
            "边际显著 (p < 0.10)"
        )

    else:

        significance = (
            "不显著"
        )


    # --------------------------------------------------------
    # 方向
    # --------------------------------------------------------

    if beta > 0:

        direction = "正相关"

    elif beta < 0:

        direction = "负相关"

    else:

        direction = "无方向"


    print(

        f"{row['Emotion']} → "
        f"{row['Horizon']}: "

        f"β={beta:.6f}, "

        f"HAC SE="
        f"{row['Beta Std Error (HAC)']:.6f}, "

        f"t="
        f"{row['t-statistic (HAC)']:.4f}, "

        f"p="
        f"{p:.4f}, "

        f"{direction}, "

        f"{significance}"

    )
