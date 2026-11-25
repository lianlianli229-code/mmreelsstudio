-- ============================================================================
-- Reels 工作室 (Reels Studio v5.0) · 统一数据库迁移 Schema (Cloudflare D1 / SQLite)
-- 依据《vn-subtitle-cloud 架构评审》P1-5 与《节奏特效库 R-* 开发者沟通版》第 22 节定版：
--   1. 保留原版 4 张表 (items / meta_kv / custom_presets / publish_locks)，100% 兼容越/缅 858 套 S-*/O-*/E-* 资产
--   2. R-* / M-* / P-* 仅在数据库保存轻量注册索引、版本与运行记录；
--      导演规则 (Hidden Rhythm Skill)、参考案例与母版文件存放在 skills/ 目录下，不把节点数值塞入表字段。
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- [原版兼容核心表 1/4] items：统一承载 S-* (字幕)、O-* (覆层)、E-* (动画小元素)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'subtitle',          -- 'subtitle' | 'overlay' | 'element'
  lang TEXT NOT NULL DEFAULT 'my',                -- 'my' (缅甸语 858 套) | 'vi' (越南语 858 套)
  render_mode TEXT NOT NULL DEFAULT 'canvas',
  stage_bg TEXT NOT NULL DEFAULT 'photo',
  font_family TEXT NOT NULL DEFAULT 'Noto Sans Myanmar UI ExtraBold',
  font_keys_json TEXT NOT NULL DEFAULT '[]',
  webm_key TEXT NOT NULL DEFAULT '',
  poster_key TEXT NOT NULL DEFAULT '',
  ass_key TEXT NOT NULL,
  json_key TEXT NOT NULL,
  ass_text TEXT NOT NULL DEFAULT '',
  style_json TEXT NOT NULL,
  downloads_total INTEGER NOT NULL DEFAULT 0,
  sort_weight INTEGER NOT NULL DEFAULT 50,
  created_by TEXT NOT NULL DEFAULT 'backend_api',
  created_at TEXT NOT NULL,
  is_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_deleted, lang, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_rank ON items(is_deleted, lang, downloads_total DESC, sort_weight DESC, created_at DESC);

-- ----------------------------------------------------------------------------
-- [原版兼容核心表 2/4] meta_kv：目录版本号（修复 /track-use 不再高频刷版本号）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta_kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
INSERT OR IGNORE INTO meta_kv (k, v) VALUES ('catalog_version', '1');

-- ----------------------------------------------------------------------------
-- [原版兼容核心表 3/4] custom_presets：8位防碰撞短码 (C-XXXXXXXX) + canonical 校验
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS custom_presets (
  code TEXT PRIMARY KEY,
  base_id TEXT NOT NULL,
  canonical_sha256 TEXT NOT NULL DEFAULT '',
  overrides_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- ----------------------------------------------------------------------------
-- [原版兼容核心表 4/4] publish_locks：显式上新分布式租约互斥锁
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS publish_locks (
  lock_id TEXT PRIMARY KEY,
  lock_token TEXT NOT NULL,
  holder_agent TEXT NOT NULL,
  acquired_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER NOT NULL
);

-- ============================================================================
-- [新增库 1/3] R-* 节奏特效库 (Template Registry + Reference Cases + Runs)
-- 遵循《节奏特效库 R-* 架构建议》第 5、22 节：仅存索引与 Skill Key，绝不写死 116% 等节点参数
-- ============================================================================
CREATE TABLE IF NOT EXISTS rhythm_templates (
  id TEXT PRIMARY KEY,                            -- 如 'R-001', 'R-002'
  group_name TEXT NOT NULL DEFAULT '自媒体',       -- '自媒体' | '剧情' | '特殊'
  display_name TEXT NOT NULL,                     -- 如 '自媒体 · 卡点快节奏'
  short_desc TEXT NOT NULL,                       -- 如 '强重音、明显卡点、快速变化'
  feel_tags_json TEXT NOT NULL DEFAULT '[]',      -- 如 '["卡点","冲击","快速变化"]'
  preview_before TEXT NOT NULL DEFAULT '',
  preview_after TEXT NOT NULL DEFAULT '',
  skill_key TEXT NOT NULL,                        -- 指向隐藏导演规则，如 'social_fast_v1'
  version INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rhythm_reference_cases (
  case_id TEXT PRIMARY KEY,                       -- 如 'social-fast/case_001'
  template_id TEXT NOT NULL,                      -- 关联 R-001
  source_title TEXT NOT NULL,
  analysis_json TEXT NOT NULL,                    -- 拆解的内容结构/情绪/节奏/运镜/衔接/高潮/释放规律
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rhythm_runs (
  run_id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL,
  template_version INTEGER NOT NULL DEFAULT 1,
  video_meta_json TEXT NOT NULL DEFAULT '{}',
  rhythm_plan_json TEXT NOT NULL,                 -- Planner 输出的标准中间格式 rhythm_plan.json
  user_modified INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- [新增库 2/3] M-* 智能音乐库 (存干净原轨 + 音乐结构 Music Map，混音/避让在试听与导出时实时执行)
-- ============================================================================
CREATE TABLE IF NOT EXISTS music_catalog (
  id TEXT PRIMARY KEY,                            -- 如 'M-001' ~ 'M-008'
  title TEXT NOT NULL,
  emotion_camp TEXT NOT NULL,                     -- '悲悯忏悔' | '静谧圣洁' | '激昂布道' | '温暖祝福' | '民谣福音'
  emotion_tags_json TEXT NOT NULL DEFAULT '[]',
  trigger_keywords_json TEXT NOT NULL DEFAULT '[]',
  bpm INTEGER NOT NULL DEFAULT 68,
  duration_sec REAL NOT NULL DEFAULT 60.0,
  clean_audio_url TEXT NOT NULL DEFAULT '',       -- 干净未破坏原轨 URL
  music_map_json TEXT NOT NULL,                   -- 音乐结构：{ beats, bars, builds, drops, climax_sec, valley_sec }
  synth_preview_json TEXT NOT NULL DEFAULT '{}',  -- 零外部依赖 Web Audio 实时合成参数
  suno_style_prompt TEXT DEFAULT '',              -- 东南亚/缅甸民谣福音纯净版 Style Prompt
  enabled INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);

-- ============================================================================
-- [新增库 3/3] P-* 视频写词Skill库 (AI识图仅作建议 + 宗教与声学确定性红线硬锁定)
-- ============================================================================
CREATE TABLE IF NOT EXISTS prompt_templates (
  id TEXT PRIMARY KEY,                            -- 如 'P-001' ~ 'P-011'
  display_name TEXT NOT NULL,
  camp TEXT NOT NULL,                             -- '修女与信徒' | '新教牧师' | '儿童祝福' | '圣经电影'
  short_desc TEXT NOT NULL,
  skill_key TEXT NOT NULL,                        -- 指向 skills/prompts/ 下的确定性母版规则
  hard_redlines_json TEXT NOT NULL,               -- 不可被 AI 覆盖的宗教/声学/肤色确定性红线
  editable_slots_json TEXT NOT NULL,              -- 供人工确认的视觉槽位定义 (左右手/持麦/圣物/睁闭眼/机位)
  version INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);
