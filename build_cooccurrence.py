# -*- coding: utf-8 -*-
"""从 MMKG CSV 统计元素 co-occurrence 矩阵"""
import pandas as pd
import json
from collections import defaultdict
from pathlib import Path

# 读取 MMKG CSV
csv_path = Path("d:/SD/MMKG/data_csv/mmkg_final_v53_optimized.csv")
df = pd.read_csv(csv_path)

print(f"CSV 行数: {len(df)}")
print(f"列: {df.columns.tolist()}")
print(f"\n前 5 行:")
print(df.head())

# 统计元素共现
# 假设 head 是元素，tail 是属性/意义
# 我们要找的是：哪些元素经常一起出现在同一个意图/主题下

# 先看看数据结构
print(f"\nhead_type 值: {df['head_type'].unique()}")
print(f"relation 值: {df['relation'].unique()}")
print(f"tail_type 值: {df['tail_type'].unique()}")

# 统计每个元素出现的次数
element_counts = df[df['head_type'] == 'Element']['head'].value_counts()
print(f"\n元素出现频率 Top 20:")
print(element_counts.head(20))

# 构建 co-occurrence 矩阵
# 策略：如果两个元素都指向同一个 Meaning，则认为它们共现
cooccurrence = defaultdict(lambda: defaultdict(int))
meaning_to_elements = defaultdict(list)

for _, row in df.iterrows():
    if row['head_type'] == 'Element' and row['tail_type'] == 'Meaning':
        element = row['head']
        meaning = row['tail']
        meaning_to_elements[meaning].append(element)

# 统计共现
for meaning, elements in meaning_to_elements.items():
    elements = list(set(elements))  # 去重
    for i, elem1 in enumerate(elements):
        for elem2 in elements[i+1:]:
            cooccurrence[elem1][elem2] += 1
            cooccurrence[elem2][elem1] += 1

# 转换为可序列化的格式
cooccurrence_dict = {}
for elem, co_dict in cooccurrence.items():
    # 只保留共现次数 >= 2 的
    top_cooccurrences = sorted(co_dict.items(), key=lambda x: x[1], reverse=True)[:10]
    if top_cooccurrences:
        cooccurrence_dict[elem] = {
            "cooccurs_with": [item[0] for item in top_cooccurrences],
            "frequencies": [item[1] for item in top_cooccurrences],
        }

# 保存
output_path = Path("d:/SD/cooccurrence_rules.json")
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(cooccurrence_dict, f, ensure_ascii=False, indent=2)

print(f"\n共现规则已保存到 {output_path}")
print(f"包含 {len(cooccurrence_dict)} 个元素的共现数据")

# 打印前 10 个元素的共现关系
print("\n前 10 个元素的共现关系:")
for i, (elem, data) in enumerate(list(cooccurrence_dict.items())[:10]):
    print(f"{elem}: {data['cooccurs_with'][:5]}")
