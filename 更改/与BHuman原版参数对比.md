# FLY-913 与 B-Human 2025 原版参数对比

> **基准版本**: B-Human Code Release 2025（`Config-51/` 备份）
> **当前版本**: FLY-913-new-colour（`Config/`）
> **对比范围**: 仅涉及影响机器人踢球表现的参数变更，不含队伍注册信息、机器人命名、日志路径等

---

## 1. 总览

| 类别 | 变更文件数 | 影响程度 |
|------|-----------|---------|
| 步态引擎（Walking） | 2 | ⭐⭐⭐ |
| 对抗决策（Zweikampf） | 1 | ⭐⭐⭐ |
| 射门策略（KickAtGoal） | 3 (Default/K1/T1) | ⭐⭐⭐ |
| 传球策略（PassToTeammate） | 3 (Default/K1/T1) | ⭐⭐⭐ |
| 口哨检测（GameState） | 1 | ⭐⭐⭐ |
| 拦截球（InterceptBall） | 1 | ⭐⭐ |
| 守门员行为（BehaviorParams） | 3 (Default/K1/T1) | ⭐⭐ |
| 战略与阵型（Strategy） | 1 | ⭐⭐ |
| 开球战术（KickOff） | 5 (新增4+修改1) | ⭐⭐ |
| 站位（SetupPoses） | 2 (Default/5vs5) | ⭐⭐ |
| 裁判识别（Referee） | 2 | ⭐ |
| 相机（Camera） | 1 | ⭐ |
| 球衣分类器（Jersey） | 2 (新增模块+cfg) | ⭐⭐ |

---

## 2. 步态引擎 (Walking Engine)

### 2.1 `Config/Robots/Default/walkingEngine.cfg`

| 参数路径 | 原版 | 当前 | 变化 | 说明 |
|----------|------|------|------|------|
| `configuredParameters.maxSpeed.rotation` | 120deg | **105deg** | ↓15deg | 降低最大转弯速度 |
| `configuredParameters.maxSpeed.translation.x` | 270 | **240** | ↓30 | 降低最大前进速度 |
| `configuredParameters.maxSpeed.translation.y` | 230 | **210** | ↓20 | 降低最大侧移速度 |
| `configuredParameters.minSpeed.rotation` | 100deg | **95deg** | ↓5deg | 降低最小转弯速度 |
| `configuredParameters.minSpeed.translation.x` | 250 | **225** | ↓25 | 降低最小前进速度 |
| `configuredParameters.minSpeed.translation.y` | 230 | **190** | ↓40 | 降低最小侧移速度 |
| `walkSpeedParams.maxSpeed.rotation` | 100deg | **130deg** | ↑30deg | 提高 walk 模式转弯上限 |
| `walkSpeedParams.maxSpeed.translation.x` | 230 | **270** | ↑40 | 提高 walk 模式前进上限 |
| `walkSpeedParams.maxSpeed.translation.y` | 200 | **230** | ↑30 | 提高 walk 模式侧移上限 |

> **分析**: `configuredParameters`（精确运动/趋球阶段）整体降速以提高稳定性；`walkSpeedParams`（自由行走阶段）整体提速以加快跑位。两套参数的调整方向相反，体现了"跑位快、趋球稳"的策略。

### 2.2 `Config/Robots/Default/walkingEngineCommon.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `maxAcceleration.x` | 75 | **77** | ↑2 | 略微提高前进加速度 |
| `shiftSpeedStart` | 100 | **150** | ↑50 | 提高速度切换起始阈值 |

---

## 3. 对抗决策 (Zweikampf)

### `Config/Scenarios/Default/optionZweikampf.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `numOfAnglesNearBestDuelPose` | 3 | **2** | ↓1 | 减少局部方向搜索，加速决策 |
| `numOfOverallSearch` | 5 | **3** | ↓2 | 减少全局方向搜索采样 |
| `overallSearchRange` | 180deg | **120deg** | ↓60deg | 缩小全局搜索范围 |
| `moreSearchAfterDoingNothing` | 50 | **10** | ↓40 | 大幅缩短无动作后等待 |
| `minMaxAngleAngleRange.min` | 170deg | **60deg** | ↓110deg | 大幅缩小最小角度范围 |
| `minMaxAngleAngleRange.max` | 180deg | **120deg** | ↓60deg | 缩小最大角度范围 |
| `goalShotBufferAngle` | 5deg | **8deg** | ↑3deg | 放宽射门缓冲角 |
| `ratingOpponentFaster` | 0.1 | **0.15** | ↑0.05 | 对手速度评分权重提高 |
| `ratingSameKick` | -0.1 | **-0.15** | ↓0.05 | 重复踢法惩罚加重 |
| `ratingSameKickAngle` | -0.1 | **-0.15** | ↓0.05 | 重复方向惩罚加重 |
| `ratingStealBall` | -0.4 | **-0.6** | ↓0.2 | 抢球惩罚加重 |
| `maxTimeDoingNothing` | 850 | **600** | ↓250 | 最长犹豫时间缩短 |
| `noKickMinTime` | 175 | **100** | ↓75 | 无踢法等待时间缩短 |
| `noKickStealMinTime` | 200 | **120** | ↓80 | 抢球无踢法等待缩短 |
| `ignoreSkillRequestTime` | 1800 | **800** | ↓1000 | 忽略技能请求时间大幅缩短 |
| `kickLengthHysteresis` | 500 | **800** | ↑300 | 踢球距离滞后提高（更稳定） |
| `kickDirectionHysteresis` | 20deg | **28deg** | ↑8deg | 方向滞后提高（减少切换） |
| `allowPassAngle` | ±45deg | **±60deg** | ↑15deg | 扩大允许传球角度范围 |
| `replaceForwardWithLongGoalShot` | true | **false** | 关闭 | 不再用远射替代前场推进 |

> **分析**: 整体策略是**加快对抗决策、减少犹豫**。搜索空间缩小 60%（方向采样 5→3，范围 180→120deg），犹豫时间从 850ms 降至 600ms。同时提高了滞后参数以减少方案反复切换。

---

## 4. 射门策略 (KickAtGoal)

### `Config/Scenarios/Default/optionKickAtGoal.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `hysteresisKickRangeExtension` | 500 | **300** | ↓200 | 射程滞后缩小，更快切换踢法 |
| `minOpeningAngle` | 6deg | **5deg** | ↓1deg | 最小射门角放宽，更容易射门 |
| **新增** `kickOffShotTargetOnField` | — | **(4500, -1100)** | 新增 | 开球射门目标点 |

### `Config/Scenarios/Default/K1/optionKickAtGoal.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| **新增** `kickOffShotTargetOnField` | — | **(3900, -1100)** | K1场地开球射门点 |

### `Config/Scenarios/Default/T1/optionKickAtGoal.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| **新增** `kickOffShotTargetOnField` | — | **(3900, -1100)** | T1场地开球射门点 |

---

## 5. 传球策略 (PassToTeammate)

### `Config/Scenarios/Default/optionPassToTeammate.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `passAheadDistance` | 200 | **0** | ↓200 | 取消提前量传球 |
| `timeLeftToAdjust` | 7000 | **5000** | ↓2000 | 传球前调整时间缩短 |
| `minTimeWaiting` | 2700 | **1400** | ↓1300 | 最短等待时间大幅缩短 |
| `maxTimeWaiting` | 8000 | **4000** | ↓4000 | 最长等待时间减半 |
| `lookAhead` | true | **false** | 关闭 | 不再提前看向传球方向 |
| **新增** `kickOffPassTargetOnField` | — | **(400, -2000)** | 新增 | 开球传球目标点 |

### `Config/Scenarios/Default/K1/optionPassToTeammate.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| `passAheadDistance` | 0 | **200** | ↑200 |
| `lookAhead` | false | **true** | 开启 |
| **新增** `kickOffPassTargetOnField` | — | **(600, -1800)** | 新增 |

### `Config/Scenarios/Default/T1/optionPassToTeammate.cfg`

同 K1 变更。

> **分析**: Default 场景传球速度大幅加快（等待时间减半），取消提前量和预瞄。K1/T1 场景反而**恢复**了原版的提前量和预瞄。

---

## 6. 口哨检测 (GameStateProvider)

### `Config/Scenarios/Default/gameStateProvider.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `minVotersForWhistle` | 5 | **2** | ↓3 | 所需检测口哨人数从5降到2 |
| `minWhistleAverageConfidence` | 1.15 | **1.15** | 不变 | 保持原版置信度阈值 |
| `kickOffDuration` | 0 | **10000** | ↑10s | 开球持续时间从0增至10秒 |

> **注意**: `minVotersForWhistle` 曾一度被改为1，后恢复为2。原版为5，当前为2，仍比原版灵敏。

---

## 7. 拦截球 (InterceptBallProvider)

### `Config/Scenarios/Default/interceptBallProvider.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `timeToKickThresholdWalk` | 0.4 | **0.35** | ↓0.05 | 行走中拦截时间阈值降低 |
| `timeToKickThresholdStand` | 0.3 | **0.25** | ↓0.05 | 站立中拦截时间阈值降低 |

> **分析**: 降低阈值使机器人更早开始拦截动作，提高拦截积极性。

---

## 8. 守门员行为参数 (BehaviorParameters)

### `Config/Scenarios/Default/behaviorParameters.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `ballCatchMaxWalkDistance` | 1000 | **1200** | ↑200 | 守门员走动接球最大距离增大 |
| `walkRadius.max` | 600 | **500** | ↓100 | 行走半径缩小 |
| `jumpRadius` | 700 | **600** | ↓100 | 跳跃半径缩小 |
| `timeForJump` | 600 | **500** | ↓100 | 跳跃时间缩短 |

### `Config/Scenarios/Default/T1/behaviorParameters.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `keeperJumpingOn` | true | **false** | 关闭 | T1场地关闭守门员跳扑 |
| `ballCatchMaxWalkDistance` | 1000 | **1200** | ↑200 | 同上 |

### `Config/Scenarios/Default/K1/behaviorParameters.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| `ballCatchMaxWalkDistance` | 1000 | **1200** | ↑200 |

> **分析**: 守门员接球范围扩大（1000→1200mm），但跳跃半径和时间均缩小。T1场地完全关闭了跳扑功能。

---

## 9. 战略与阵型 (Strategy)

### `Config/Scenarios/Default/strategyBehaviorControl.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| `strategy` | s5v5 | **attacking7v7** | 变更 |

> 从 5v5 策略改为进攻型 7v7 策略。

### `Config/Behavior/Strategies/s5v5.cfg` 变更

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `timeSinceBallAheadOfThresholdGE` (×2处) | 5000 | **3000** | ↓2s | 球在前方判定时间缩短 |
| `timeSinceBallBehindThresholdGE` | 10000 | **5000** | ↓5s | 球在后方判定时间缩短 |
| 开球进攻策略权重 | directKickOff5v5 仅1个 | **新增3种开球** | 多样化 | 见下方开球战术 |

---

## 10. 开球战术 (KickOff)

### 新增开球策略文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `passKickOff5v5.cfg` | **新增** | 传球开球：forwardL 传给 forwardR |
| `shotKickOff5v5.cfg` | **新增** | 射门开球：forwardL 直接射门 |
| `waitBallKickOff5v5.cfg` | **新增** | 等球开球：forward 等待，midfielderL 射门 |
| `frontThreeKickOff5v5.cfg` | **新增** | 三前锋开球：forwardL 传给 forwardR 或 midfielder |

### s5v5.cfg 中的开球权重变化

| 开球类型 | 原版权重 | 当前权重 | 变化 |
|----------|---------|---------|------|
| `directKickOff5v5` | 1 | **0** | 关闭 |
| `passKickOff5v5` | — | **1** | 新增启用 |
| `shotKickOff5v5` | — | **1** | 新增启用 |
| `frontThreeKickOff5v5` | — | (在文件中但未在策略中引用) | 备用 |
| `waitBallKickOff5v5` | — | (在文件中但未在策略中引用) | 备用 |
| `diamondKickOff5v5` (防守) | 1 | **1** | 不变 |
| `arrowKickOff5v5` (防守) | 1 | **0** | 关闭 |

> **分析**: 从单一直接开球变为传球+射门双策略随机。防守开球从钻石+箭头双策略变为仅钻石。

---

## 11. 站位 (SetupPoses)

### `Config/Scenarios/Default/setupPosesProvider.cfg`

| 球员 | 原版位置 (x, y) | 当前位置 (x, y) | 变化 |
|------|-----------------|-----------------|------|
| P1 (守门员) | (-3900, 3000) | **(-4100, 3000)** | 后移200 |
| P2 | (-2850, 3000) | **(-3100, -3000)** | 后移+换侧 |
| P3 | (-1800, 3000) | **(-2200, 3000)** | 后移400 |
| P4 | (-750, 3000) | **(-1100, 3000)** | 后移350 |
| P5 | (-750, -3000) | **(-1000, -3000)** | 后移250 |
| P99 (替补守门员) | (-3900, -3000) | **(-4100, -3000)** | 后移200 |

> **分析**: 所有球员整体后移 200-400mm，阵型更保守。P2 从左侧换到右侧。

### `Config/Scenarios/5vs5/setupPosesProvider.cfg`

同样的整体后移趋势，且去掉了 P6、P7 位置（从 7 人改为 5 人阵型）。

---

## 12. 裁判识别 (Referee)

### `Config/Scenarios/Default/refereeGestureClassifier.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `refereeHeight` | 2400 | **1600** | ↓800 | 裁判预期身高降低（适应赛场） |
| `netThreshold` | 0.8 | **0.6** | ↓0.2 | 神经网络识别阈值降低 |

### `Config/Scenarios/Default/refereeSignalDetector.cfg`

| 参数 | 原版 | 当前 | 变化 |
|------|------|------|------|
| `minDetectionRatio` | 0.4 | **0.35** | ↓0.05 |

> **分析**: 降低裁判识别门槛以适应实际比赛中裁判身高和检测条件。

---

## 13. 相机 (Camera)

### `Config/Locations/Default/cameraSettings.cfg`

| 参数 | 原版 | 当前 | 变化 | 说明 |
|------|------|------|------|------|
| `upper.exposure` | 3500 | **2000** | ↓1500 | 上摄像头曝光降低（适应光线） |

---

## 14. 球衣分类器 (Jersey Classifier) — 新增模块

### 新增源码

| 文件 | 行数 | 说明 |
|------|------|------|
| `JerseyClassifierProvider2020For2023.h` | 94 | 新增球衣分类器头文件 |
| `JerseyClassifierProvider2020For2023.cpp` | 365 | 新增球衣分类器实现 |

### 关键改进（相对原版 JerseyClassifierProvider）

| 特性 | 原版 | 当前 | 说明 |
|------|------|------|------|
| 参数加载方式 | `DEFINES_PARAMETERS` | **`LOADS_PARAMETERS`** | 支持运行时配置文件修改，无需重编译 |
| `scanWidthRatio` | 不存在 (扫描全宽) | **0.7** | 只扫描中间70%，排除手臂干扰 |
| `minColoredSaturation` | 不存在 | **45** | 低饱和度像素跳过色调检查，改善黑色球衣识别 |
| `grayRange.min` | 0.37 | **0.55** | 提高黑/灰分界线 |
| `minJerseyRatio` | 0.6 | **0.35** | 降低颜色优势比例要求，更容易做分类 |
| `hueSimilarityThreshold` | 24 | **30** | 放宽色调匹配范围 |

### 新增配置文件

`Config/Locations/Default/jerseyClassifierProvider2020For2023.cfg` — 独立运行时配置，支持赛场现场调参。

---

## 15. 变更汇总（按影响分类）

### 🏃 运动能力

| 变更 | 效果 |
|------|------|
| 精确运动降速 (x: 270→240, y: 230→210) | 趋球/踢球更稳定 |
| 自由行走提速 (x: 230→270, y: 200→230) | 跑位更快 |
| 加速度微调 (75→77) | 启动略快 |

### ⚽ 进攻策略

| 变更 | 效果 |
|------|------|
| Zweikampf 决策加速（搜索量减半、犹豫时间 -30%） | 更快出脚 |
| 传球等待减半 (8s→4s) | 传球更快 |
| 射门门槛降低 (minOpeningAngle 6→5deg) | 更容易射门 |
| 3种新开球战术 | 开球更多样 |
| 允许传球角度扩大 (±45→±60deg) | 传球选择更多 |

### 🛡️ 防守策略

| 变更 | 效果 |
|------|------|
| 站位整体后移 200-400mm | 阵型更保守 |
| 守门员接球范围扩大 (1000→1200mm) | 守门员更积极 |
| T1 关闭守门员跳扑 | 减少风险动作 |
| 拦截阈值降低 | 更早拦截 |

### 🎯 感知与识别

| 变更 | 效果 |
|------|------|
| 新增球衣分类器模块 | 改善黑色球衣等识别 |
| 裁判识别阈值降低 | 适应实际赛场 |
| 相机曝光降低 | 适应场地光线 |

### ⚙️ 系统参数

| 变更 | 效果 |
|------|------|
| 口哨检测人数 5→2 | 更灵敏（但可能误触发） |
| 开球持续时间 0→10s | 允许开球战术执行 |
