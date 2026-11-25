---
name: vn-subtitle-element-studio
description: "越南语字幕库（vn-subtitle-cloud）全套字幕(S-*)、覆层(O-*)与透明通道动画小元素(E-*)工业级快速生产与极速审片质检总控：覆盖 4 轨小元素制作（程序化 72 帧真循环 / Flow / Colab H3 / 亮底抠像+4pxRGB扩散）、10 门禁并发质检与亮底拼图（拦截首帧缺主体/非循环/隐蔽内部平切越界/暗边/绿边/假360摇摆）、9 门禁 AE 字幕防同质化防呆体检与 Skia 单双行速览拼图。凡制作、返修、重构、质检或审计字幕/覆层/动画小元素时强制激活。"
---

# 越南语字幕与动画小元素工业级制作与极速审片总控 (`vn-subtitle-element-studio` v1.0)

> **五大绝对红线（违者直接阻塞交付）**：
> 1. **严禁擅自自动上新 & 严禁主动催问上新**：除非用户在当次对话明确说出「上新 / 发布入库」，否则**严禁调用** `/api/v1/admin/seed-batch` 或 `/api/v1/publish/*`，也不得主动询问“要不要上新？”。
> 2. **零缺陷质检门禁（QA-Before-Delivery）**：任何小元素（`E-*`）与字幕/覆层（`S-*` / `O-*`）在汇报完成或同步交付前，**必须 100% 通过本技能 `<10秒` 并发自动化脚本门禁 + 亮底（`stage-photo.jpg`）抽帧审片拼图肉眼核验**。**严禁使用跨姿态透明叠化（crossfade）或直接对称倒放（pingpong）伪造假循环！**
> 3. **本地交付强制同步与双校验**：确认成片后同步写入 `C:\Users\Clara\Downloads\AI专用\2026-11-21\越南天主教土嗨小元素库\01_透明通道WebM成片\`（或用户指定交付路径），并校验 `SHA256` 与最新修改时间 100% 一致；云端 `R2`/`D1` 与本地必须同源字节一致。
> 4. **软件名称与队列红线**：本机多容器浏览器软件唯一正式名称为 **「火狐多账户管理」**；严禁取消/清空队列中他人任务、严禁擅自勾选未启用账号、严禁擅自推送「火狐多账户管理」云端更新。
> 5. **100% 原创 & 天主教喜庆亮暖红线**：严禁使用视频截图做素材；严禁主耶稣苦难相（Crucifix）、深黑十字架、圣婴/抱圣婴图；祈祷天使须穿白/金长袍且闭眼；神圣字幕严禁纯黑/近黑描边。

---

## 0. 资源导航（Progressive Disclosure）

- **全量用户需求与技术规格总纲**（宗教避雷 / 画幅 / 音色 / 网页与短码兼容）：[references/requirements_master.md](./references/requirements_master.md)
- **透明通道动画小元素 4 轨快速生产手册**（程序化 72 帧 / Flow / H3 / 抠像与 4px 扩散）：[references/element_production_playbook.md](./references/element_production_playbook.md)
- **字幕 / 覆层 / 8 款 AE 内核生产手册**（56 字体 R2 路径 / 防吞孔 / 去同质化 / 双行预览）：[references/subtitle_overlay_playbook.md](./references/subtitle_overlay_playbook.md)
- **历史翻车案例与门禁映射库**（含 `E-074` 隐蔽 `y=46` 平切 + F0 缺失复盘）：[references/failure_postmortem_catalog.md](./references/failure_postmortem_catalog.md)
- **核心自动化脚本（`scripts/`）**：
  - [fast_element_qa.py](./scripts/fast_element_qa.py) — 10 门禁并发 `.webm` 质检 + `stage-photo.jpg` 亮底 & 棋盘格 7+1 审片拼图
  - [fast_element_factory.py](./scripts/fast_element_factory.py) — `prep-still`（原生 `1:1`/`3:4`/`4:3` 紧致 `8%~12%` 留白对接 `H3 res:2`）/ `build-from-video`（全分辨率解码+全帧并集包围盒+亮底抠像+无缝循环+4px RGB 扩散）/ `build-procedural`（2×超采样 72 帧绝对循环直出）/ `build-packaging`（Track A+ AE/Skia `@napi-rs/canvas` 包装动效与真 3D 金属自转直出）
  - [ae_element_studio.mjs](./scripts/ae_element_studio.mjs) — Track A+ `@napi-rs/canvas` (Rust Skia) 包装渲染内核（`l1_vfx` 全屏粒子与磨砂订阅条 / `l2_packaging` 高清静图弹簧摇摆与金属扫光 / `l3_spin360` 24K 金边挤出真 360° 旋转）
  - [fast_subtitle_qa.py](./scripts/fast_subtitle_qa.py) — 9 门禁字幕/覆层体检 + 反水货同质化去重 + Skia 单双行速览拼图
  - [studio_self_test.py](./scripts/studio_self_test.py) — 真实库样本回归测试套（验证好坏样本与 Track A+ 产线 100% 精准识别）
- **提示词与样式模板（`templates/`）**：
  - [element_prompt_templates.json](./templates/element_prompt_templates.json)
  - [subtitle_ae_templates.json](./templates/subtitle_ae_templates.json)

---

## 1. 快速生产路由矩阵（Fast Production Routing）

### 1.1 动画小元素 (`E-*`) 四轨决策树（先选最快最稳的轨！）

| 轨道 | 适用素材类型 | 生成与加工路线 | 循环与画质保证 |
| :--- | :--- | :--- | :--- |
| **Track A：程序化 2× 超采样循环**<br>*(最快极清 · 20~30秒/条)* | **花瓣/金粉上升、圣焰摇曳呼吸、羽毛飘动、珠光闪烁、圣光呼吸、`AMEN` 徽章** | 高清静图母版 → `fast_element_factory.py build-procedural --supersample 2`（`1024×1024` 渲染再 Lanczos 降采样至 `512×512`） | **24fps 72 帧 (3.00s) 严格闭合 `F0 ≡ F72`**；2× 超采样锐利无锯齿、0 裁切、0 闪烁 |
| **Track A+：AE/Skia 包装动效与真 3D 金属自转**<br>*(零抽卡零糊 · `<8秒/条`)* | **全屏粒子流/圣光 Bokeh/磨砂订阅条 (`l1_vfx`)；铃铛声波摆动/花环微呼吸飘瓣/徽章金属扫光 (`l2_packaging`)；单徽章 24K 金边真 360° 旋转 (`l3_spin360`)** | `@napi-rs/canvas` (`ae_element_studio.mjs`) `2×` 超采样直出 → `fast_element_factory.py build-packaging --mode ... --preset ... --still ...` | 数学 `2π` **严格闭合 `F(0)≡F(N)`**，保留 100% 原画珠宝锐度，亮暖零黑边，`l3_spin360` 稳定过 `G10` 双波谷单向光流 |
| **Track B：真实 3D 生物动作 / 展翅** | **白鸽原地展翅悬停、天使翼动等需真实骨骼/物理形变的复杂运动** | 1. 用 `prep-still --aspect auto` 匹配 **`1:1` (`1024×1024`) / `3:4` (`960×1280`) / `4:3` (`1280×960`)**（**仅留 `8%~12%` 紧致留白**，严禁用 `1080×1920` + `>=21%` 大黑边稀释主体像素！）<br>2. 优先送 **Colab H3 `multi`（`res: 2, opt: true`, 同比例 `1:1`/`3:4`/`4:3`）**；若走 Flow 720p 则紧缩至 `10%~12%` 留白 + `footage:"帧"` 首尾锁图<br>3. 全分辨率解码全帧并集包围盒落入 `[46, 466]` 安全盒 → `fast_element_qa.py` | **第 0 帧即完整在场**；`H3 res:2 + 1:1` 让主体像素提升 **3×~6×**，缩至 `512×512` 丝毫毕现 |
| **Track C：纯发光 / 火焰 / 粒子 / 白翼带焰** | **烈焰圣心、五旬节火舌、圣光羽翼、星尘光束** | **强制 100% 纯黑 `#000000` 虚空底生成**（原生比例 + `H3 res:2`，严禁放绿幕上导致 `4:2:0` 染黄绿边） → `black_ai_luma` / `black_fire` | 亮底 `stage-photo.jpg` 零黑雾灰边、零脏颗粒 |
| **Track D：实心金属 / 宝石 / 白鸽 / 花环** | **金十字、念珠、玫瑰花环、圣爵、巴洛克金匾** | **纯平 `#00FF00` 或哑光 `#00B140` 绿幕**（原生比例 + `H3 res:2`，或硬质镶钻底座保高清静图层 + 仅局部翼动/焰动混合） → `green_dove` / `green_wreath` / `green_solid` | **编码前强制 `dilate_rgb_4px`**，彻底消灭 VP9 `yuva420p` 4:2:0 黑边 |

> **关键防呆**：无论 Track B 还是 Track C/D，FFmpeg 读取透明 `.webm` 时**必须把 `-c:v libvpx-vp9` 写在 `-i <file.webm>` 之前**！

### 1.2 动态字幕 (`S-*`) 与覆层 (`O-*`) 生产标准

1. **只走无损原生内核，永不降级 `.ass`**：所有样式由 `ReelsCanvasRenderer` + `ReelsAeTypography`（8 款 AE 引擎）+ `ReelsOverlay` 渲染直出；网页微调支持 `scale/dy/lh/ls/font/anim/stroke/box`，小元素支持 `scale (30%~200%)`、`dx (-45%~+45%)`、`dy (-45%~+45%)`。
2. **8 款实装 AE 特效引擎 ID**（已入库 `S-848 ~ S-855`，`worker.js` 白名单对齐）：
   - `particle_morph_gold`（金沙聚散）
   - `extruded_3d_gold`（12 层真 3D 金属挤出）
   - `saber_light_trace`（Saber 光束描边）
   - `liquid_molten_gold`（熔金流光）
   - `magnetic_wave_karaoke`（物理磁力避让波浪卡拉 OK）
   - `gold_foil_emboss_card`（暖米白 3D 金边浮雕牌匾）
   - `motion_blur_whip_slam`（5 层残影甩入重击）
   - `underline_brush_draw`（圣母天蓝金荧光划线 + 12 道圣光轮）
3. **绝对反“水货同质化”**：批量制作时，**禁止换个十六进制颜色就凑数**（会被 `S09_ANTI_HOMOGENIZATION_DEDUP` 直接拦截）；每款必须有明确的爆款对标意图、差异化排版/动效/质感搭配，且**必须通过单行 + 双行越语长短句试片预览**。
4. **D1 `font_keys_json` 路径铁律**：必须存 R2 路径数组（如 `["fonts/BeVietnamPro-Bold.ttf"]`），严禁存字体名字符串（如 `["Be Vietnam Pro"]`）。

---

## 2. 极速审核流程（2-Stage Fast QA Workflow）

### Stage 1：`<10秒` 并发自动化门禁（先机检，不瞎眼盲看）
- **小元素 (`E-*`) 真循环与视觉 13 项检测**（并发解码真实 VP9 Alpha 流）：
  - `G01` 格式与非空 Alpha (`VP9 yuva420p`)
  - `G02` **第 0 帧全主体在场**（拦截飞入、翅膀/火苗后冒出）
  - `G03_SEAMLESS_LOOP` **首尾帧无缝闭合**（`F0 vs F_last` 差值与帧间步长匹配）
  - `G03_CROSSFADE_GHOST` **严禁叠影假循环**（全序列检测半透明像素占比局部驼峰突变 ≥1.5×，专杀四翅叠影/鬼影衔接）
  - `G03_INTERNAL_CUT` **严禁内部/高动态硬切跳帧**（逐帧扫描 `i -> (i+1)%N` 突变峰值）
  - `G03_PINGPONG_REVERSE` **严禁原片直接镜面对称倒放假循环**（24 枢轴镜面对称扫查 + 全分辨率近枢轴 `mirror_mae < 0.75` 实锤拦截；程序化真循环除外）
  - `G04` **动态活力**（拦截假动效/死图）
  - `G05` **画布外沿零触边**（`3px` 安全边缘）
  - `G06` **隐蔽内部平切越界扫描**（检测任意帧 1px 极值边界 `>=30px` 锐利直线阶跃平切——专杀 `E-074` 缩进 46px 后的隐蔽 `y=46` 切翅膀！）
  - `G07` **锁机防漂移/畸变**
  - `G08` **亮底黑灰边与绿幕溢色扫描**
  - `G09` **连通域孤立黑灰噪点拦截**
  - `G10` **真 360° 单向光流旋转校验**（拦截左右摇摆假 360）
- **字幕 / 覆层 (`S-*` / `O-*`) 9 门禁**：
  - `S01` 56 款越语字体白名单 | `S02` `font_keys_json` 必须为 `fonts/*.ttf` 路径 | `S03` 神圣题材零黑边 | `S04` `box_connected:false` & 像素行距 `>=34` | `S05` 字号安全区与动态动画 `wrap<=80%` | `S06` 动效/AE 白名单同步 | `S07` NFC 与 `Giê-su`/`Ki-tô` 正字法 | `S08` 色彩对比度 | `S09` **反水货同质化去重**。

### Stage 2：亮底拼图强制肉眼核验
- 自动门禁通过后，**必须用 `read_file` 查看脚本生成的 `stage-photo.jpg` 亮底审片拼图**（小元素看 7 帧 + 棋盘格 + 青色 `[46..466]` 安全线；若命中 `G03_CROSSFADE_GHOST`/`G03_INTERNAL_CUT`，拼图第 2 格自动精准定位为 `SEAM fXXX` 衔接焦点帧以便直视鬼影/硬切！字幕看 **1 行短句 + 2 行带声调长句** 的 Skia 实景渲染拼图），确认无任何审美或物理瑕疵后方可交付。

---

## 3. 一键执行命令速查

```powershell
# 1) 静图按原生比例 (1:1/3:4/4:3) 紧致 8%~12% 安全留白送 Colab H3 (aspect=1:1, res=2)
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" prep-still `
  --input still.png --out prepped_1x1.png --aspect auto --bg green --margin-ratio 0.09 --margin-top 0.13

# 2) 无缝 72 帧 2x超采样程序化循环直出 (Track A, 自动跑 10 门禁 QA + 生成亮底拼图)
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" build-procedural `
  --eid E-999 --title "演示测试" --still prepped.png --preset halo_sparkles --supersample 2 --out-dir ./out --sheet ./out/qa.jpg

# 2b) Track A+ AE/Skia 包装动效与真 3D 360°旋转直出 (L1 全屏粒子 / L2 铃铛花环包装 / L3 24K金边360°自转)
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" build-packaging `
  --eid E-137 --title "金色星系粒子_L1" --mode l1_vfx --preset golden_galaxy_vortex --palette sacred_gold --out-dir ./out
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" build-packaging `
  --eid E-082 --title "大金铃铛_L2" --mode l2_packaging --preset bell_spring_ring --palette festive_red_gold --still still.jpg --out-dir ./out
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" build-packaging `
  --eid E-080 --title "皇冠金十字_L3" --mode l3_spin360 --preset gold_bevel_360 --palette heavenly_white_blue --still still.jpg --out-dir ./out

# 3) Flow/H3 成片自动全帧包围盒裁剪 + 亮底抠像 + 自然周期搜索与DIS光流微衔接 (--loop auto_cycle) + 4px扩散 + 门禁 QA
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_factory.py" build-from-video `
  --eid E-074 --title "白鸽悬停珍珠金环空十字(完整双翼)" --video raw_h3.mp4 --keyer green_dove --loop auto_cycle --out-dir ./out --sheet ./out/qa.jpg

# 4) 批量 10 门禁极速质检全量或指定小元素 (<10秒并发)
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_element_qa.py" `
  --input "C:\Users\Clara\Downloads\AI专用\2026-11-21\越南天主教土嗨小元素库\01_透明通道WebM成片" --glob "E-074*.webm" --sheet ./qa_e074.jpg

# 5) 字幕/覆层 9 门禁体检 + 反同质化去重 + Skia 单双行速览拼图
python "C:\Users\Clara\reels-studio\资源管理中心\6_官方小元素四轨制作与10门禁质检工厂\scripts\fast_subtitle_qa.py" `
  --file ./new_pack.json --preview-sheet ./qa_sub.jpg
```

---

## 4. 管理员显式下令「上新」后核验清单（平时严禁触发）
1. 本地交付目录 `01_透明通道WebM成片` 与 `vn-subtitle-cloud/public/r2/` 字节与 `SHA256` 100% 核对一致。
2. 字幕包 `font_keys_json` 为 `["fonts/..."]`、无 `S01~S09` 错误；小元素全数通过 `fast_element_qa.py`。
3. 仅推送到线上云端服务时调用 `/api/v1/admin/seed-batch`（`User-Agent: vn-sub-pack-manager/2.0`）并做 `HEAD` 与 `?preview=1` 接口复核，随后 `catalog_version` 确认递增；**严禁触碰「火狐多账户管理」云端更新**。

