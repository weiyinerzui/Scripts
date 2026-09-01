import pandas as pd
from pathlib import Path

# 原始 Excel 文件路径
input_file = r'20260512王振伟移交.xlsx'   # TODO: 换成你的文件名
sheet_name = "Sheet1"              # 或写具体表名，如 'Sheet1'
col_name = '接收客户经理'            # 按照这一列拆分

# 自定义列数据类型：{'列名': 类型}
dtype_dict = {
    '客户号': str,      # 姓名保持字符串
    '借据号': str,       # 手机号保持字符串
    '金额': float,      # 成绩转整数（避免如 100.0）
    '余额': float,  # 示例：如需其他列加在这里
}

date_cols = ['起始日', '到期日']  # TODO: 确认确切列名，解析为日期

# 自定义后缀，如 '_v1' 或 '_20260307'
suffix = '_移交'   # TODO: 修改这里

# 读取原始表
df = pd.read_excel(
    input_file, 
    sheet_name=sheet_name, 
    dtype=dtype_dict, 
    parse_dates=date_cols  # 自动识别日期格式
)

# 输出目录：与原文件同目录下的 output 子目录
in_path = Path(input_file)
out_dir = in_path.parent / 'output'
out_dir.mkdir(exist_ok=True)

# 按姓名分组并分别写入新的工作簿
for name, group in df.groupby(col_name):
    # 每个 name 一个新的 Excel 文件，如 张三.xlsx、李四.xlsx
    # index=False 不输出行索引
    out_file = out_dir / f'{name}{suffix}.xlsx'
    group.to_excel(out_file, index=False)
    print(f'已生成: {out_file}')
