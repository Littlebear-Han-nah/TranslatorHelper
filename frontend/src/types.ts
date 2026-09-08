// 模型定义接口
export interface ModelInfo {
  id: string;
  name: string;
  tag: string;
}

// 系统配置接口
export interface SystemConfig {
  models: ModelInfo[];
  default_model: string;
  has_default_key: boolean;
  default_base_url: string;
}

// 上传文件信息接口
export interface UploadInfo {
  file_id: string;
  filename: string;
  saved_path: string;
  extension: string;
  size: number;
}

// 单页翻译与预览结果
export interface PageResult {
  page: number;
  orig_text: string;
  trans_text: string;
  orig_img: string;
  trans_img: string;
}

// 任务完成结果
export interface TranslationResult {
  task_id: string;
  total_pages: number;
  side_by_side_pdf: string;
  pure_trans_pdf?: string;
  bilingual_docx?: string;
  bilingual_md?: string;
  side_by_side_img?: string;
  pages: PageResult[];
}

// 实时任务状态接口
export interface TaskStatus {
  task_id: string;
  stage: 'starting' | 'translating' | 'stitching' | 'rendering_pdf' | 'ocr' | 'completed' | 'failed';
  percent: number;
  message: string;
  current_page: number;
  total_pages: number;
  result?: TranslationResult;
  error?: string;
}
