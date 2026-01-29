Obsidian Canvas 设计准则 AI 精英学院™ by Axton

你将基于「⽂章全⽂」⽣成⼀份 Obsidian Canvas。⽬标是在画布中清晰、优雅地呈现⽂章脉

络，便于演示与复习。

任务步骤

1.  深⼊阅读：通读⽂章，抓取核⼼论点与关键事实。

2.  信息分层：按照「主题 → ⼦主题 → 关键要点」三级结构梳理内容。

3.  布局规划

坐标系：以画布中⼼ (0, 0) 为根节点位置；同层节点横向排列，层级向下/右递进。

间距基准：节点间⽔平 ≥ 320 px，垂直 ≥ 200 px，确保视觉留⽩。

节点尺⼨：

主主题 ≈ 320 × 140 px

⼦主题 ≈ 260 × 120 px

关键要点 ≈ 220 × 100 px

连线规则：

直接从⽗节点底边连到⼦节点顶边，使⽤直线；

复杂/跨级关系，⽤曲线并设置  toEnd:"arrow" 。

4.  颜⾊与⻛格

采⽤简洁商务配⾊：主主题 #4A90E2，⼦主题 #50E3C2，关键要点 #F5A623；

若需 Obsidian 预设⾊号，请⽤  "4" 、 "5" 、 "3"  分别对应绿、⻘、⻩；

群组背景可淡灰 #F7F7F7， backgroundStyle:"ratio"  以保持协调。

5.  节点内容

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 1 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

⽂本精炼：每节点 ≤ 2 ⾏、≤ 60 字；避免⻓段落。

重要数据或公式可放⼊  file  节点（图⽚、PDF 等），并在相邻⽂本节点中简要说

明。

6.  ID 与编码

所有  id  采⽤ 8~12 位随机⼗六进制；

JSON 中：中⽂双引号替换为 『』，中⽂单引号替换为 「」，英⽂双引号需转义。

7.  完整性检查

确认  nodes 、 edges 、 groups （如有）均已定义；

检查⽆坐标重叠、⽆孤⽴节点；

总体视觉居中、左右权重平衡。

8.  输出格式

完整符合下⽅《JSON Canvas Specification for Obsidian》的 Obsidian Canvas

⽂件；

不添加其他解释⽂字；结果可直接由 Obsidian 打开。

其他必须遵守的原则

styleAttributes（可选但建议写空对象）

节点与连线均允许带  "styleAttributes": {}  字段。

若暂时不⾃定义样式，务必输出空对象⽽不是省略，避免某些版本的 Obsidian 报

错。

group.label 必填

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 2 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

所有  type:"group"  节点请填写  label ，哪怕只是占位，如「分组 1」。

有助于后期在画布侧边栏快速定位分组。

节点与分组的层级顺序（z-index）

输出  nodes  数组时，先写最底层的背景/⼤分组，再写⼦分组，最后写最上层的普

通⽂本/链接节点。

这样导⼊后视觉层级正确，⽆需⼿动“置于底层”。

颜⾊写法

颜 ⾊ 可 ⽤ 预 设 数 字   "1" ～ "6"   或   HEX； 若 使 ⽤   HEX ， 推 荐 统 ⼀ ⼤ 写 ， 如

"#4A90E2" 。

请避免在同⼀ Canvas 混⽤数字与 HEX，以免主题切换时出现不可预期的对⽐度问

题。

连线缺省端点

fromEnd  和  toEnd  如果使⽤默认值，可省略；若需要箭头，⼀律写  "arrow" ，

不要写其他⼤⼩写形式。

避免导⼊后出现“⽆箭头”或箭头⽅向相反的情况。

⽂件与链接节点

type:"file"  节点：必须含  file  路径，若直指某段落可附  subpath:"#章节标

题" 。

type:"link"  节点：使⽤  url  字段指向完整的  https://… 。

JSON 基本格式

顶层仅包含  "nodes"  与  "edges" ，不要额外包裹在对象或数组⾥。

整个 JSON 不要换⾏注释；如需注释请在 Prompt 说明⽽⾮输出结果中写明。

中⽂引号替换规则再次提醒

中⽂双引号 → 『』，中⽂单引号 → 「」，英⽂双引号需要反斜杠转义  \" 。

这在实际导⼊测试中能完全避免 JSON 解析异常。

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 3 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

JSON CANVAS SPECIFICATION FOR

OBSIDIAN

JSON CANVAS SPEC

Version 1.0 — 2024-03-11

TOP LEVEL

The top level of JSON Canvas contains two arrays:

nodes  (optional, array of nodes)

edges  (optional, array of edges)

NODES

Nodes are objects within the canvas. Nodes may be text, files, links, or groups.

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 4 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

Nodes are placed in the array in ascending order by z-index. The first node in the array

should  be  displayed  below  all  other  nodes,  and  the  last  node  in  the  array  should  be

displayed on top of all other nodes.

Generic node

All nodes include the following attributes:

id  (required, string) is a unique ID for the node.

type  (required, string) is the node type.

text

file

link

group

x  (required, integer) is the  x  position of the node in pixels.

y  (required, integer) is the  y  position of the node in pixels.

width  (required, integer) is the width of the node in pixels.

height  (required, integer) is the height of the node in pixels.

color  (optional,  canvasColor ) is the color of the node, see the Color section.

Text type nodes

Text type nodes store text. Along with generic node attributes, text nodes include the

following attribute:

text  (required, string) in plain text with Markdown syntax.

File type nodes

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 5 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

File type nodes reference other files or attachments, such as images, videos, etc. Along

with generic node attributes, file nodes include the following attributes:

file  (required, string) is the path to the file within the system.

subpath   (optional,  string)  is  a  subpath  that  may  link  to  a  heading  or  a  block.

Always starts with a  # .

Link type nodes

Link type nodes reference a URL. Along with generic node attributes, link nodes include

the following attribute:

url  (required, string)

Group type nodes

Group type nodes are used as a visual container for nodes within it. Along with generic

node attributes, group nodes include the following attributes:

label  (optional, string) is a text label for the group.

background  (optional, string) is the path to the background image.

backgroundStyle   (optional,  string)  is  the  rendering  style  of  the  background

image. Valid values:

cover  fills the entire width and height of the node.

ratio  maintains the aspect ratio of the background image.

repeat  repeats the image as a pattern in both x/y directions.

EDGES

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 6 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

Edges are lines that connect one node to another.

id  (required, string) is a unique ID for the edge.

fromNode  (required, string) is the node  id  where the connection starts.

fromSide  (optional, string) is the side where this edge starts. Valid values:

top

right

bottom

left

fromEnd  (optional, string) is the shape of the endpoint at the edge start. Defaults

to  none  if not specified. Valid values:

none

arrow

toNode  (required, string) is the node  id  where the connection ends.

toSide  (optional, string) is the side where this edge ends. Valid values:

top

right

bottom

left

toEnd   (optional,  string)  is  the  shape  of  the  endpoint  at  the  edge  end.  Defaults

to  arrow  if not specified. Valid values:

none

arrow

color  (optional,  canvasColor ) is the color of the line, see the Color section.

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 7 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

label  (optional, string) is a text label for the edge.

COLOR

The  canvasColor   type  is  used  to  encode  color  data  for  nodes  and  edges.  Colors

attributes  expect  a  string.  Colors  can  be  specified  in  hex  format  e.g.  "#FF0000" ,  or

using one of the preset colors, e.g.  "1"  for red. Six preset colors exist, mapped to the

following numbers:

"1"  red

"2"  orange

"3"  yellow

"4"  green

"5"  cyan

"6"  purple

Specific  values  for  the  preset  colors  are  intentionally  not  defined  so  that  applications

can tailor the presets to their specific brand colors or color scheme.

你刚刚掌握了⼀个强⼤的「蓝图Prompt」。在「MAPS™ AI 系统化训练营」中，你将学习如何

为任何场景，系统化地设计、测试和迭代你⾃⼰的蓝图。欢迎加⼊我们，开启真正的系统构建之

旅：https://axtonliu.ai/aiagent

保持连接，共同成⻓

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 8 / 9 ⻚

Obsidian Canvas 设计准则 AI 精英学院™ by Axton

扫描上⽅⼆维码，或通过以下链接，与我建⽴更深度的连接。期待在我的内容和社群⾥，与你再

次相遇。

YouTube: youtube.com/@axtonliu

X (Twitter): x.com/axtonliu

个⼈⽹站: https://axtonliu.ai

© 2025 AI 精英学院™ & AXTONLIU™ All Rights Reserved. https://axtonliu.ai 第 9 / 9 ⻚

![图 9-1](attachments/9_1.png)
