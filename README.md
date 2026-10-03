# gfont-variants

一个可复用的轨迹字体变体生成工具。用户指定**输入字体文件、变形选项、参数和输出目录**，
即可生成多套字体，供奎享雕刻等上位机的多字体随机选字功能使用。

输入文件可以位于任意用户目录，无需放进仓库或修改代码。仓库不捆绑字体，
启动时不会自动寻找或处理当前目录的字体。命令行和 Python 接口共用同一生成流程。

**当前支持 xiongzai v6 `.gfont` 的已验证格式布局。** 同格式字体的名称、作者、
字形内容、字符集合与字数均从输入文件读取。扩展名相同不代表格式相同，
暂不支持其他 `.gfont` 方言以及 TTF/OTF；不兼容的文件会明确报错。

生成器只有两项可叠加的变形，**默认都关闭**：

- **笔画延长/缩短**：沿原轨迹裁剪笔端，或沿笔端切线延伸；保护交接区域。
- **缩放**：整字等比例缩放，或围绕某个中心、随距离衰减的局部缩放。

生成器不包含随机旋转、独立平移、剪切、噪声或其他随机变形。
原字体文件只读。每批输出保留完整字符集合和原始落笔顺序、落笔段数，
内部字体名称各不相同，预览字形与字形库一起更新。

## 运行

Python 3.10 或更新版本；生成器和测试均只使用标准库，无需安装依赖：

```bash
python -m gfont_variants inspect '/path/to/input.gfont'
python -m gfont_variants generate --help
```

可选安装为命令：`python -m pip install -e .`，随后用 `gfont-variants` 代替
`python -m gfont_variants`。安装后可在任意工作目录运行。
下面的 `/path/to/input.gfont` 均替换为用户自己的文件路径。

### 仅调整长短

```bash
python -m gfont_variants generate '/path/to/input.gfont' \
  --output output/length-only \
  --count 16 --seed 42 \
  --length --length-min 0.95 --length-max 1.05
```

`0.95` 表示目标长度为原来的 95%（缩短 5%），`1.05` 表示延长 5%。
只要缩短可用 `0.90～0.98`，只要延长可用 `1.02～1.10`。
上下限相等时使用固定倍数。

### 仅局部缩放

```bash
python -m gfont_variants generate '/path/to/input.gfont' \
  --output output/scale-only \
  --count 16 --seed 42 \
  --scale --scale-mode local \
  --scale-min 0.95 --scale-max 1.05 --scale-radius 0.35
```

整字缩放改为 `--scale-mode global`，并去掉只用于局部缩放的参数。

### 叠加长短与缩放

```bash
python -m gfont_variants generate '/path/to/input.gfont' \
  --output output/combined \
  --count 16 --seed 42 \
  --length --length-min 0.95 --length-max 1.05 \
  --scale --scale-mode local \
  --scale-min 0.95 --scale-max 1.05 --scale-radius 0.35
```

顺序固定为**先长短、后缩放**。两项有独立随机流，因此增加另一项不会改变
已经抽取的随机参数；缩放的作用范围基于长短调整后的字形框。
相同输入、参数、种子和工具版本可重复生成相同字形；压缩文件的字节复现还取决于
Python/zlib 环境。不同变体、不同字符分别抽取参数。

## Python 接口

其他程序可以直接调用，无需构造命令行参数：

```python
from gfont_variants import Options, generate_variants

output = generate_variants(
    input_font='/path/to/input.gfont',
    output_dir='/path/to/new-output',
    count=16,
    seed=42,
    options=Options(
        length=True,
        length_min=0.95,
        length_max=1.05,
        scale=True,
        scale_mode='local',
        scale_min=0.95,
        scale_max=1.05,
        scale_radius=0.35,
    ),
)
print(output)  # 已生成的输出目录（pathlib.Path）
```

只需要一种变形时，只开启对应的 `length` 或 `scale`。其余字段与下表参数对应，
Python 字段名使用下划线。接口默认不打印日志；可传 `progress=print` 接收进度。
`preview_chars=None` 从输入字体选择预览字符，`preview_count` 控制展示多少个变体。
无效参数或不支持的格式抛出 `ValueError`（包括其子类 `FontError`），文件错误抛出 `OSError`。

## 参数

倍数都使用小数而非百分数。所有幅度均为可调的工程参数，没有经过实机效果标定。

| 参数 | 默认 | 含义 |
|---|---|---|
| `--length` | 关闭 | 开启笔端长短调整 |
| `--length-min` / `--length-max` | `0.95` / `1.05` | 每条路径抽取的目标长度倍数范围 |
| `--length-ends` | `both` | 允许修改 `start`、`end` 或 `both`；交接保护仍然生效 |
| `--junction-tolerance` | `0.002` | 交接保护距离，除以原字形最大边长后的比例；0 仍保护精确相交 |
| `--scale` | 关闭 | 开启缩放 |
| `--scale-mode` | `local` | `local` 局部缩放或 `global` 整字缩放 |
| `--scale-min` / `--scale-max` | `0.95` / `1.05` | 每个字抽取一个等比例缩放倍数 |
| `--scale-center` | `random` | `random` 为字形框内随机点，`center` 为框中心 |
| `--scale-radius` | `0.35` | 局部影响半径 / 字形最大边长；只用于 local |
| `--scale-step` | `0.01` | 局部变形前折线采样最大间隔 / 字形最大边长；同时不超过半径的 1/8 |
| `--count` | `16` | 生成几套字体 |
| `--seed` | 随机生成 | 可重复生成用的整数种子，实际值写入记录 |
| `--preview-chars` | 自动选择 | 从输入字体字符集合选择最多 8 个；可显式指定，不限制导出字符集合 |
| `--preview-count` | `4` | 对比图展示前几个变体；0 只展示原字 |
| `--output` | 必填 | 新输出目录；已存在则报错，不覆盖 |

必须显式启用至少一项。只设置 `--scale-min` 等参数而未启用 `--scale` 会报错，
避免参数悄悄失效。范围必须有序且倍数大于 0，不接受 NaN 或无穷大。

## 变形的具体含义

### 长短

当前的“笔画”指文件中的**几何落笔轨迹段**，不是自动识别后的标准汉字笔画。
若字体把一条竖拆成上下两段，算法会保护交接处，向各自自由笔端调整。

长度按折线弧长计算。两端都可以调整时，把总变化量平分给两端；只有一端可以
调整时，由这一端承担。缩短时沿原路径裁剪；延长时沿终端切线增加一段直线。
原有内部曲线与拐点保持不变（被缩短裁掉的末端除外）。

与其他路径接近、接触或相交的部分属于保护区域。缩短不能越过保护区域；延长
会受到原有轨迹及本次已延长轨迹的阻挡限制。闭合路径、零长度路径、没有自由笔端的路径保持不变。
因此，**输入倍数是目标值，保护约束可能使实际变化更小或不变**。
每套字体的记录包含延长、缩短、未变化、受限制的路径数量。

### 缩放

整字缩放为 `p' = c + s * (p - c)`。随机中心带来的位置变化是该缩放公式的一部分，
没有额外加入独立随机平移。

局部缩放为：

```text
p' = p + (s - 1) * exp(-||p - c||² / (2r²)) * (p - c)
```

同一个字的所有路径使用同一中心、倍数和影响半径。`s` 是中心附近的缩放倍数，
远处影响衰减到 0，因此局部模式并不意味着整个字的宽高都乘以 `s`。
较小的半径使变化更集中，较大的半径使变化更接近整字缩放。

局部缩放会先在原线段上增加采样点，再转换坐标，以表达弯曲后的轨迹；
这不是额外的平滑或随机扰动。倍数为 1 时跳过采样，保持原坐标字节。
增加采样会增大文件及发送给写字机的路径数据量；可以调大 `--scale-step` 减少采样量，
但需比较曲线与交接区域的近似误差。整字缩放不增加采样点。
局部倍数上限限制在约 3.2408 以下，以避免这个连续径向映射折叠。
离散折线近似、float32 精度和机械运动仍可能影响非常细小的交接，需实机核对。

## 输出与奎享雕刻

```text
output/combined/
  variant_001.gfont
  variant_002.gfont
  ...
  manifest.json
  preview.svg
```

把需要的一组 `.gfont` 导入奎享雕刻，在多字体选择中选中这些变体即可。
`preview.svg` 使用实际导出后重新读取的坐标，每行采用相同的坐标与比例。
`manifest.json` 保存源文件哈希、全部参数、种子、每个字体的哈希与变化统计。
预览字符默认来自实际输入文件，中文、英文或数字字库均不依赖预设字符。
手动指定输入字体没有的预览字符时会报错，可省略该参数使用自动选择。

生成器会读回每份输出，核对 ZIP 校验、字形和预览一致性、字符集合、落笔段数
以及 float32 坐标。当前没有在奎享客户端或物理写字机上测试；名称是已确认的
可修改字段，其余作者/标识元数据保留，客户端是否另有去重规则仍需导入验证。
默认不做字形大小归一化、裁边或重定位；放大或延长可能扩大字框，需在上位机
预览中检查字距与相邻字。连续随机选字仍可能抽到同一版本。

## 开发与验证

```bash
python -m unittest discover -s tests -v
```

测试动态构造合成字体，不需要提供真实字体文件。覆盖不同名称、字数、字符集合、
坐标尺度与预览数量，以及二进制往返、预览同步、分段连接保护、笔端长短、
整字/局部缩放公式、叠加次序、随机复现、参数校验及不覆盖已有输出。

```text
gfont_variants/
  cli.py          命令行入口
  pipeline.py     公共文件处理流程 / Python 接口
  font.py         已支持格式的读写
  transforms.py   可选变形与参数
  geometry.py     路径几何计算
  preview.py      根据输入字符集合生成预览
tests/            不依赖真实字体的测试
```

字体文件、生成结果以及本地调研材料不纳入 Git，也不是安装或运行的依赖。
格式扩展应放在读写层，变形层只操作通用的字形与轨迹数据。
已支持的格式元数据为明文，ZIP 条目以字符命名，字形没有尾随优先级字段。
