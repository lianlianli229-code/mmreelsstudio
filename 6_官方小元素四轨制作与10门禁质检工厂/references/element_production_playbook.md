# 透明通道动画小元素 4 轨快速生产手册 (`element_production_playbook.md`)

---

## 一、生产前第一原则：能程序化直出，就不赌视频生成！

制作每一批新元素前，先按视觉动作复杂度分流到以下四条最快、最稳的轨道：

1. **Track A — 程序化 2× 超采样 72 帧精确循环 (`build-procedural --supersample 2`)**
   - **适用对象**：圣光呼吸、珠光星芒、花瓣/粒子/金粉升腾、圣焰火舌飘动、羽毛/丝带轻柔摆动、巴洛克金匾 / `AMEN` 徽章扫光闪烁。
   - **核心优势**：24fps × 72 帧 = `3.00s`；在 `1024×1024`（`2×` 超采样）渲染周期动画再 Lanczos 降采到 `512×512`，**天然满足第 0 帧完整在场、`F0 ≡ F72` 零接缝、绝无 AI 降质糊感、绝对无越界**，单条 20~30 秒极速生成。
2. **Track A+ — AE/Skia 包装动效与真 3D 金属自转直出 (`build-packaging --mode l1_vfx|l2_packaging|l3_spin360`)**
   - **底层引擎**：由 Node `@napi-rs/canvas` (`ae_element_studio.mjs`) 执行 `2×` 超采样直接流式喂入 FFmpeg VP9 `yuva420p` 管道（`<8秒/条`，无 Chrome 启动开销）。全部粒子/Curl-Noise/金属扫光采用 `u = frame / N` 严格 `2π` 1-周期数学公式，**100% 保证 `F(0) ≡ F(N)` 且零暗边（禁止 `'transparent'` 或黑色渐变停止色）**。
   - **三大制作层**：
     - **`l1_vfx`（`540×960` 30fps 90f 全屏特效 & 订阅条）**：`golden_galaxy_vortex`、`sacred_bokeh_rays`、`blessing_hearts_stream`、`holy_sparks_rain`、`frosted_subscribe_bar`，彻底替代 AI 模糊粒子流并留空中部口播人物清晰区。
     - **`l2_packaging`（`512×512` 24fps 72f 原画级包装静物）**：`bell_spring_ring`（顶枢阻尼双响摆动+声波弧）、`wreath_shimmer_petals`（微呼吸浮动+3D花瓣绕飞）、`emblem_royal_gleam`（8 折对称圣光射线+`source-atop` 45° 金属扫光）、`candle_fluid_flame`。直接吃 `.jpg`/`.png`/`.webm`（自动首帧抠像并清洗碎渣），保留 100% 原画珠宝锐度。
     - **`l3_spin360`（`512×512` 24fps 72f 24K 金边挤出真 360° 旋转）**：`gold_bevel_360` 通过 `20` 层 Z-sorted 纯金浮雕侧壁 + `ctx.scale(signedC, 1)` 单次仿射与 24K 金拉丝背面雕刻实现单向 360° 真自转，天然通过 `G10_SPIN360_PHYSICS`（双波谷 + 单向光流）且无撕裂锯齿。
   - **选型原则**：凡粒子全屏流、UI 订阅条、硬质铃铛/花环/徽章摆动闪光、以及单徽章 360° 自转，**一律优先 Track A+ 取代抽卡生视频**；只有生物自由骨骼大动作（如白鸽真实扇翅悬停、祈祷手臂动作）才走 Track B/C/D 视频生成。
3. **Track B — 真实 3D 形变 / 展翅 / 复杂物理运动（废除 `1080×1920 + >=21%` 模糊套，改走三大高清方案）**
   - **旧方案为什么糊？** 把方形主体硬放进 `1080×1920` 竖屏并四周留 `>=21%` 绿边，主体只占宽约 `626px`；若再按 `res: 1` 跑视频，主体实际有效采样严重不足，细节糊成一团！
   - **新方案 1（主推 · 原生比例 + 紧致 `8%~12%` 留白 + Colab H3 `res: 2`）**：
     1. 用 `fast_element_factory.py prep-still --aspect auto` 按主体长宽比直接铺进 **`1:1` (`1024×1024`) / `3:4` (`960×1280`) / `4:3` (`1280×960`)**，左右底仅留 **`8%~10%`**、向上展翅/火焰顶部留 **`12%~13%`**（主体撑满画幅 `78%~84%` 宽）。
     2. 投递 **Colab H3 `multi`（`aspect` 与画布一致，`res: 2`, `opt: true`）**，再由 `build-from-video` **全分辨率解码**做全帧包围盒裁剪并单步 Lanczos 降采样进 `[46, 466]`，清晰度提升 `3×~6×`！
   - **新方案 2（Flow 720p 备选）**：仅当需走 Flow 时，禁 `>=21%` 大留白，紧缩至 `10%~12%` 留白 + `footage: "帧"` 首尾锁图 (`images: [img, img]`) + `720p`。
   - **新方案 3（动静分层高清混合 · Hybrid）**：若珠宝/浮雕底座要求极致锐度，保留 1024px 原画静图层底座，仅将 `H3 1:1 res: 2` 局部动态区（如展翅/火舌）羽化合成。
   - 提示词模板见 [../templates/element_prompt_templates.json](../templates/element_prompt_templates.json)。
4. **Track C — 纯黑虚空底 (`#000000`) 发光元素**
   - **适用对象**：烈焰圣心、五旬节火舌、黄金螺旋星尘、圣灵羽翼带焰光晕。
   - **禁止放绿幕**：`#00FF00` 经 `4:2:0` 视频压缩会直接把半透明火苗和金羽边染成黄绿色脏框！必须用 `#000000` 纯黑底生成，后期走 `black_ai_luma` / `black_fire`（`rembg isnet-general-use` + 亮度焰芒融合 + 反预乘提亮）。
5. **Track D — 纯绿底 (`#00FF00` / `#00B140`) 实体与花环**
   - **适用对象**：雪白鸽子、宝石金十字、玫瑰/百合花环、念珠、祈祷闭眼天使。
   - **抠像选择**：
     - `green_dove`：保护中性雪白羽翼、深色眼睛与粉红喙/玫瑰，剔除鸽头周围黄绿发光残影，并对半透明羽尖反预乘提纯为雪白。
     - `green_wreath`：保护暖金万寿菊/麦穗/粉玫瑰不被绿幕阈值误伤，清除内部小镂空孔绿点并对洗绿花瓣还原金橙色调。
     - `green_solid`：常规金属/宝石/金匾 Vlahos 去绿溢，外缘羽化消黑。

---

## 二、后期封装五大标准工序（`build-from-video` 已内置自动化）

1. **全分辨率解码 + 全帧并集包围盒 (`All-Frame Union BBox`)**：严禁预先 `scale` 缩小原片（会丢失 H3 `res: 2` 清晰度），直接全分辨率解码并遍历全部帧合并前景外框，加 `~2%` 安全外扩后单步 Lanczos 放缩居中放进 `512 × 512` 内部的 **`420 × 420` 安全盒 `[46, 466]`**（`SAFE_MIN=46, SAFE_MAX=466`）。
2. **连通域去悬浮噪点 (`remove_small_components`)**：`alpha > 0.06` 二值图执行 8 连通域分析，清除 `< 40px` 孤立灰黑渣点（同时避免误删较大的亮色花瓣/火花）。
3. **反预乘亮底提纯 (`unpremul_and_bright_lift`)**：
   - 半透明边缘 (`0.02 < alpha < 0.96`) 执行直通道反预乘 `rgb / max(alpha, 0.30)`；
   - 白羽启用 `lift_white=True` 将偏灰半透羽尖顺滑提纯为暖雪白；
   - 火焰启用 `lift_warm_fire=True` 将暗红/暗褐半透焰缘提纯为纯亮橙金（强制 `G <= 0.62*R` 防止过绿）。
4. **4px RGB 边缘扩散 (`dilate_rgb_4px`)**：
   - 借助 `cv2.distanceTransformWithLabels` 将所有 `alpha <= 5` 且距离前景 `<= 4.2px` 的全透明像素 RGB 填为最近前景像素色（`alpha` 依然保持 `0`）。
   - **目的**：根除 `VP9 yuva420p` 编码器在进行 `2×2` YUV 色度次采样时把周围 `(0,0,0)` 纯黑混进透明羽翼边缘而产生的“亮底黑灰边”。
5. **WebM VP9 Alpha 编码与真循环防伪反假循环铁律**：
   - **严禁盲目 Crossfade（`premul_crossfade`）或直接对称 Pingpong 倒放**：跨姿态强行淡入淡出必然在衔接窗出现“四只翅膀/双影鬼影”，直接像素镜面拼合会出现僵硬倒放折返感。
   - **真循环标准工序 (`--loop auto_cycle`)**：
     1. 若走 Flow 且允许首尾锁图，优先用 **`footage: "帧"`** 直接把同一张 `prep-still` 图作为首尾锁定；
     2. AI 视频由 `find_best_loop_cycle_and_morph()` 在全视频内搜索 **姿态+速度方向均匹配的自然周期 `[i_best, j_best]`**（默认 `48~120` 帧）；若找不到真实接近周期（`poseMAE > 4.5` 或 `alphaMAE > 3.5`），直接报错退回重生成，绝不强行叠化造假！
     3. 仅在剩余微小误差（`0.6 < poseMAE <= 4.5`）时，对末尾 **4 帧 (`--morph-frames 4`)** 做 **DIS 双向光流形变微衔接 (`cv2.DISOpticalFlow`)**，对齐羽翼/火焰坐标后再融合，彻底消除双影鬼影。
   ```bash
   ffmpeg -y -f rawvideo -pix_fmt rgba -s 512x512 -r 24 -i - `
     -c:v libvpx-vp9 -pix_fmt yuva420p -crf 22 -b:v 0 -auto-alt-ref 0 -deadline good -cpu-used 4 `
     output.webm
   ```
   - 产物落盘后同时生成 `stage-photo.jpg` 合成封面图与 `vn-alpha-element/1.0` JSON 元数据；
   - 本地同步时将 `output.webm` 覆盖至 `01_透明通道WebM成片\<ID>_<标题>.webm` 并断言 `SHA256` 100% 一致；
   - **编码完毕立刻自动运行 `fast_element_qa.py`**（含 `G03_CROSSFADE_GHOST` / `G03_INTERNAL_CUT` / `G03_PINGPONG_REVERSE` 与 `SEAM fXXX` 自动聚焦拼图）并肉眼核验。

---

## 三、元素 JSON 元数据标准 (`vn-alpha-element/1.0`)

```json
{
  "schema": "vn-alpha-element/1.0",
  "id": "E-061",
  "title": "黑底烈焰红宝石圣心白翼金十字(零绿边)",
  "kind": "element",
  "format": "webm_vp9_yuva420p",
  "width": 512,
  "height": 512,
  "fps": 24,
  "duration_sec": 3.0,
  "loop": true,
  "seamless_loop": true,
  "spin_360": false,
  "key_mode": "proc_halo_sparkles",
  "stage_bg": "photo",
  "webm_url": "/r2/webm/E-061.webm",
  "poster_url": "/r2/posters/E-061.jpg"
}
```
