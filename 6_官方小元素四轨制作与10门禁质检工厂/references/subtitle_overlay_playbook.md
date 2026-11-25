# 越南语字幕 / 覆层 / AE 引擎工业级生产手册 (`subtitle_overlay_playbook.md`)

---

## 一、核心原则：高可读 + 无损内核 + 零同质化

1. **绝不降级 `.ass`**：无论网页预览还是离线渲染，一律走原生 Skia/Canvas 内核（`ReelsCanvasRenderer` + `ReelsAeTypography` + `ReelsOverlay`）。
2. **禁止低质水数量**：严禁批量复制同一版式只改色号。每一组新样式必须具备清晰差异化的**字体气质 + 色彩方案 + 底框/笔刷/3D 质感 + 动效节奏**，并过 `S09_ANTI_HOMOGENIZATION_DEDUP` 查重门禁。
3. **56 款越语 134 字符实测字体 & `font_keys_json` 路径规范**：
   - 在 D1 数据库 `items.font_keys_json` 中**严禁存字体名**，必须存 R2 文件路径数组（例如 `["fonts/BeVietnamPro-Bold.ttf"]`）。
   - 常用爆款越语宽体字体推荐：
     - 口播大字首选：`Be Vietnam Pro`（`fonts/BeVietnamPro-Bold.ttf`）、`Montserrat`（`fonts/Montserrat-Bold.ttf`）、`TikTok Sans`（`fonts/TikTokSans-VariableFont-wght-Regular.ttf`）、`Rowdies`（`fonts/Rowdies-Bold.ttf`）、`Calistoga`（`fonts/Calistoga-Regular.ttf`）
     - 福音灵修衬线：`Lora`（`fonts/Lora-Bold.ttf`）、`Merriweather`（`fonts/Merriweather-VariableFont-wght-Regular.ttf`）、`Gelasio`（`fonts/Gelasio-VariableFont_wght.ttf`）、`Cormorant Garamond`（`fonts/CormorantGaramond-VariableFont-wght-Regular.ttf`）
   - 完整 56 款注册表可实时查询 `GET /api/v1/fonts`，脚本 `fast_subtitle_qa.py` 内置全量 56 款字体及精准 `.ttf` 路径映射表。

---

## 二、8 款已实装 AE 级字幕引擎速查 (`reels-ae-typography.js`)

| 引擎 ID (`anim_in_type`) | 视觉特效机制 | 推荐参数组合 & 红线 |
| :--- | :--- | :--- |
| **`particle_morph_gold`** | 离屏像素点云采样 + Curl 涡流金沙聚散成型 | `fontsize: 84~88`, `line_spacing: 40`, 先 stroke 后 fill, 亮暖色板 |
| **`extruded_3d_gold`** | 12 层真 3D 金属挤出 + 45° 扫光（可设 `extrude_3d_colors`） | `border_width: 8`, `extrude_3d_layers: 12`, 禁用纯黑挤出底色 |
| **`saber_light_trace`** | 多层发光能量光束沿越语轮廓描边燃烧 + 爆亮填充 | `stage_bg: "photo-dark"` 或高对比实景配枣红护盾 `#991124` |
| **`liquid_molten_gold`** | 动态流动熔金液态高光波纹 + 喜庆双层红金外廓 | `text_gradient_colors: "#FFF7B2,#FBBF24,#D97706"`, `#991124` 粗边 |
| **`magnetic_wave_karaoke`** | 朗读词弹簧放大 `1.20x` 上浮 + **两侧词物理斥力推开不碰撞** + 碎星环 | **强制 `wrap_width_percent <= 80`** 留出左右推开空间 |
| **`gold_foil_emboss_card`** | 暖米白 3D 金边浮雕承托牌匾 + 45° 扫光 + 红金胶囊词跳动 | `use_box: true`, `box_connected: false`, `dynamic_box: true` |
| **`motion_blur_whip_slam`** | 5 层递减透明度模糊残影高速甩入重击 + 果冻回弹 | 左右留足安全区（`wrap_width_percent <= 82`） |
| **`underline_brush_draw`** | 双色渐变手绘荧光下划线 + **神圣词自动爆射 12 道慢转金光轮** | 适合圣母天蓝金 `#1D4ED8` / 亮暖金去同质化 |

> 其余基础/扩展动效全集同样受 `reels-anim-engine.js` 支持（网页 UI「基础动效」页签展示精选 10 项，`worker.js` 支持白名单同步扩展）。

---

## 三、制作防呆 8 条硬指标（入库前 `fast_subtitle_qa.py` 100% 机检）

1. **双行底框分离**：凡 `use_box: true` 且 `box_adaptive_width: true`，除非刻意设计连体阶梯气泡，必须显式写 `"box_connected": false`；且 `line_spacing` 必须是 **`>= 34` 的像素值**（推荐 `38 ~ 42`），严禁写 `1.2` 之类小数倍数。
2. **越语声调留白 & 安全宽**：`fontsize` 常规 `78 ~ 92`（卡片型 `76 ~ 84`），`wrap_width_percent` 常规 `82 ~ 85`，放大/弹跳/磁力型 **`<= 80`**；`±32%` 上下留白防切 `Ấ / Ệ / Ộ / Ứ / Ẫ`。
3. **神圣题材零黑边**：凡含天主/耶稣/圣母/圣洁/灵修/福音/祈祷等风格，**`color_outline`、`stroke_color`、`color_shadow`、`extrude_3d_colors` 严禁出现纯黑或近黑 (`max RGB < 42`)**。
4. **先描边后填充**：内核已内置 `lineJoin='round'` 先描边再填充，制作 CSS/预览或自定义扩展时严禁把描边压在填充之上吞噬 `e/a/o` 字孔。
5. **正字法规范**：全部越语文本执行 `NFC` 归一化；圣名固定拼写 **`Giê-su`**、**`Ki-tô`**，严禁破坏性 `.upper()` 导致声调丢失或窄体变糊。
6. **覆层规范**：默认字号足够中老年手机端清晰看清（标题 `54~72`、正文 `48~64`），无需求不硬加多余顶标题；支持 `scroll` 与 `textcard` 的动效需在 `worker.js` 覆层白名单内。
7. **衬底匹配 (`stage_bg`)**：常规有描边/底框用 `photo`；无底框纯白/发光金字用 `photo-dark`；深色字/浅奶油手撕纸用 `photo-light`。
8. **单行 + 双行双样例必验**：调用 `fast_subtitle_qa.py --preview-sheet` 一次渲染 **1 行短句 (`Hãy giữ tâm bình an`) + 2 行带叠层重音长句 (`Đức Chúa Giê-su luôn nâng đỡ bạn`)** 实景拼图，确保两种长度都 0 裁切、0 粘连、高对比清晰！
