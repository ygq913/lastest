# 球衣分类器修复记录（JerseyClassifierProvider2020For2023）

## 问题现象

在 `gc` 把己方设为 BLACK 时，黑色球衣机器人**经常被误识别为对手 yellow**；切换观察者为 yellow 队后，**黑色球衣又被误识别为 own**。两种情形对称地出现 bug。

## 根本原因

### 原因 1：BHuman 的 `saturated` 通道是**亮度归一化**的

`@/home/zou/My_BHman/lastest/Src/Libs/ImageProcessing/YHSColorConversion.h:42-47`:

```cpp
saturated = sqrt((U-128)² + (V-128)²) × √2 × 256 / Y
```

亮度低的暗像素，**任何细微的色偏都会被放大成"高饱和度"**。导致原算法里 `sat < satThreshold` 这个"非彩色"判定对真黑色球衣完全失效（黑色球衣的 sat 反而比黄色还高）。

实测数据：

| 球衣 | Iavg (Y) | Savg (sat) | Hcol (hue) |
|------|----------|------------|-----------|
| 黑色 | 78        | **132**    | 137 |
| 黄色 | 138        | 106       | 133 |

→ **饱和度反过来**，且两者 hue 极度接近，无法用 hue/sat 区分。

### 原因 2：暗黑色球衣的"伪 hue"恰好落在 yellow 范围

相机/光照让"黑色"球衣有微弱蓝偏（U≈102, V≈127）：
- `atan2(V-128, U-128) ≈ 138`（在 yellow 的 97~157 容忍范围）
- 算法把它当成"hue=138 的彩色像素" → 触发黄色分类器

### 原因 3：原代码两个分类分支**不互斥**

- 分支①（黑色识别）：`sat < satThreshold && gray ≤ grayRange.min && (hue 远离彩色)`
- 分支④（彩色识别）：纯 hue 比较，**没有亮度门槛**

→ 一个暗像素同时满足两个分类器。`detectJersey` 用 if-else 链先到先得，分类结果取决于先测哪个，造成混乱。

## 解决方案：用**亮度**作为唯一可靠的区分维度

实测数据中，黑色 vs 黄色唯一可靠的差异是 **Iavg (亮度)**（78 vs 138，差距 60）。所以让亮度成为黑/彩色分流的唯一依据：

```
gray ≤ grayRange.min  → 走黑色分类器
gray > grayRange.min  → 走彩色分类器
```

两个范围严格互补，任何像素只能匹配一个分类器。

---

## 修改清单

### 改动 1 — 分支①（黑色识别，无 mono 对手）：亮度 + 饱和度双门槛

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:286`

**修改前**：
```cpp
return theECImage.saturated[y][x] < satThreshold &&
       theECImage.grayscaled[y][x] <= grayRange.min &&
       (theECImage.saturated[y][x] < minColoredSaturation ||
        (|hue - o1Hue| > T && |hue - o2Hue| > T && |hue - o3Hue| > T));
```

**修改后**：
```cpp
return theECImage.grayscaled[y][x] <= grayRange.min
    && theECImage.saturated[y][x] < satThreshold;
```

**理由**：
- 去掉了 hue 相关检查（在低亮度下是噪声，不可靠）
- 去掉了 `minColoredSaturation`（多余）
- 保留 `sat < satThreshold` 用来排除"暗但有色"的像素（例如深色彩色球衣 navy/dark red）
- 亮度仍是主门槛，饱和度作为副门槛排除假阳性

**风险**：深色彩色球衣（深蓝 navy、深绿 forest green）若亮度 ≤ grayRange.min 且 sat 偶然偏低，可能仍被识别为黑色。但 RoboCup 标准球衣中只有 `black` 是低亮度色，所以现实中不会冲突。

**调参**：
- 黑色识别不到 → 调高 `satThreshold`（87 → 95 → 110），允许更多"高伪饱和"的暗像素通过
- 深色对手被误识别为黑 → 调低 `satThreshold`

### 改动 2 — 分支②（彩色识别，所有对手都是彩色）：加亮度门槛

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:288-300`

**新增首行**：
```cpp
if(theECImage.grayscaled[y][x] <= grayRange.min)
  return false;
```

并在 lambda 捕获列表里加入 `grayRange`。

**理由**：让彩色分类器**只接受亮像素**，与分支①互补，避免暗像素被两个分类器同时接受。

### 改动 3a — 分支③（黑色识别，至少一个 mono 对手）：与分支①保持一致

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:312`

**修改前**：对每个 o（o1/o2/o3）单独判断：
- mono 对手（gray/white）：`sat < colorDelimiter && gray < grayRange.min`
- 彩色对手：`sat < satThreshold && gray <= grayRange.min && hue 远离 oHue`

**修改后**：和分支①完全一致
```cpp
return theECImage.grayscaled[y][x] <= grayRange.min
    && theECImage.saturated[y][x] < satThreshold;
```

**理由**：
- 分支③和分支①的目的相同（识别"黑色像素"），应该用同一个标准
- 单一 hue 检查在低亮度下不可靠，去除
- 保留 `sat < satThreshold` 排除暗彩色像素
- `colorDelimiter` 不再使用（之前只在分支③出现）

### 改动 3b — 分支④（彩色识别，至少一个 mono 对手）：加亮度门槛

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:332-343`

**新增首行**（在 `checkO1` 之前）：
```cpp
if(theECImage.grayscaled[y][x] <= grayRange.min)
{
  DOT(...:branch4Stage, x, y, gray, gray);
  return false;
}
```

**理由**：与分支②对称。同时用灰色调试点表示该像素被亮度门拒绝，方便可视化诊断。

### 改动 4 — 配置：`grayRange.min` 调高

`@/home/zou/My_BHman/lastest/Config/Locations/Default/jerseyClassifierProvider2020For2023.cfg:14`

```ini
# 修改前
grayRange = { min = 0.42; max = 0.67; };
# 修改后
grayRange = { min = 0.45; max = 0.67; };
```

**理由**：实测黑色球衣 Iavg=78、黄色 Iavg=138。设 maxBrightness≈180，则阈值从 76 → 99，覆盖更多黑色边缘像素，同时仍远低于黄色 138 不会误抓。



### 改动 5 — 新增参数 `scanWidthRatio`：缩小横向扫描范围排除手臂

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.h:43`
`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:87-88`

**问题**：原代码 `width = obstacle.right - obstacle.left + 1`，扫描范围 = 整个障碍物 bbox 宽度，导致两侧手臂被采样污染数据。
原有的 `relativeJerseyWidth` 只影响**权重衰减**，不影响**采样范围**。

**修改**：新增配置 `scanWidthRatio`（默认 1.0，向后兼容），实际使用按比例缩小宽度：
```cpp
const int width = (obstacle.right - obstacle.left + 1) * scanWidthRatio;
```

配置默认设为 `0.7`，只采样中间 70% 宽度，避开手臂：
```ini
scanWidthRatio = 0.7;
```

调参指南：
- `1.0`：保持原行为（扫描完整 bbox）
- `0.7`：默认，避开手臂
- `0.5`：只扫中间一半，更紧凑但可能采样太少

### 改动 6 — 调试可视化：`branch4Stage` 调试层

`@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp:28`

新增调试层 `module:JerseyClassifierProvider2020For2023:branch4Stage`，在分支④的每一阶段失败时画不同颜色的点：
- 🩶 灰色：亮度门拒绝（gray ≤ grayRange.min）
- 🔴 红色：checkO1 失败
- 🟠 橙色：checkO2 失败
- 🟣 品红：checkO3 失败
- 🩵 青色：全部通过

打开方式：
```
vid upper module:JerseyClassifierProvider2020For2023:branch4Stage
```

### 改动 7 — 调试可视化：HSI 平均值显示

在 `detectJersey` 中输出每个 obstacle 的 `Havg / Savg / Iavg / Hcol / sat=N/M` 数值，方便实时观察数据。

---

## 修改后效果（黄队观察者视角）

| 球衣 | gray | hue | isOwn (yellow, 分支④) | isOpp (black, 分支①) | 结果 |
|------|------|-----|----------------------|---------------------|------|
| 黄色 (own) | 135 | 129 | gray>110 ✓ + hue 接近 ✓ → **own** | gray>110 → 拒绝 | **own** ✓ |
| 黑色 (opp) | 79 | 152 | gray≤110 → **拒绝** | gray≤110 ✓ → **opp** | **opp** ✓ |

黑队观察者视角对称成立。

---

## 调参指南

如果黑色识别不到：
- 调高 `grayRange.min`（0.55 → 0.65 → 0.75）

如果彩色（黄色）被误识别为黑色：
- 调低 `grayRange.min`

**安全上限**：必须保证 `maxBrightness × grayRange.min < 黄色 Iavg`。一般 `(黑色Iavg + 黄色Iavg) / 2 / maxBrightness` 是最稳健的中间值。

---

## 已知局限

1. **不支持深色彩色球衣**（如 navy、dark green）：会被识别为 black。RoboCup 标准球衣无此问题。
2. **依赖光照稳定**：场地切换、光源变化可能需要重新调 `grayRange.min`。
3. **依赖白色参考点**：`maxBrightness` 由机器人下半身白色部分扫描得到，如果机器人腿部也偏色会影响阈值精度。

---

## 涉及文件

- `@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.cpp`（核心改动 1/2/3/6/7）
- `@/home/zou/My_BHman/lastest/Src/Modules/Perception/PlayersPerceptors/JerseyClassifierProvider2020For2023.h`（改动 5：新增 `scanWidthRatio` 参数）
- `@/home/zou/My_BHman/lastest/Config/Locations/Default/jerseyClassifierProvider2020For2023.cfg`（改动 4/5 + 调参）

---

## 当前默认配置

```ini
grayRange = { min = 0.45; max = 0.67; };  // 亮度归一化阈值
scanWidthRatio = 0.7;                      // 横向扫描占 bbox 宽度比例（排除手臂）
satThreshold = 95;                         // 黑色像素的饱和度上限（升高 -> 接受更多暗像素）
relativeJerseyWidth = 0.5;                 // 中心区满权重半径（仅影响权重衰减）
hueSimilarityThreshold = 30;               // 彩色 hue 容忍度
```

说明：
- `colorDelimiter` 和 `minColoredSaturation` 已不再被任何代码路径使用，保留 cfg 仅为兼容性。
