import React from 'react';
import { Download, FileDown, Sparkles, CheckCircle, ExternalLink } from 'lucide-react';
import { TranslationResult } from '../types';

interface ExportBarProps {
  result: TranslationResult;
}

// 导出与下载控制面板组件：提供左右并排对照 PDF、纯中文版及双语文档一键下载
export const ExportBar: React.FC<ExportBarProps> = ({ result }) => {
  return (
    <div className="max-w-7xl mx-auto my-6 px-4">
      <div className="bg-gradient-to-r from-blue-600 via-indigo-600 to-blue-700 rounded-3xl p-6 lg:p-8 text-white shadow-xl shadow-blue-500/20 flex flex-col md:flex-row items-center justify-between gap-6">
        
        {/* 左侧说明 */}
        <div className="space-y-1.5 text-center md:text-left">
          <div className="flex items-center justify-center md:justify-start gap-2">
            <span className="p-1 rounded-lg bg-white/20 backdrop-blur-md">
              <Sparkles className="w-4 h-4 text-amber-300" />
            </span>
            <h3 className="text-base font-bold tracking-tight">文档双语对照翻译已就绪</h3>
          </div>
          <p className="text-xs text-blue-100 max-w-xl">
            系统已完成逐页/段落精翻与无损合成。您可以直接下载“左原版、右中文”的双语对照文件或纯中文版本。
          </p>
        </div>

        {/* 右侧下载按钮组 */}
        <div className="flex flex-wrap items-center justify-center gap-3">
          
          {/* 核心重点：左右并排对照 PDF 下载 */}
          {result.side_by_side_pdf && (
            <a
              href={result.side_by_side_pdf}
              download
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 px-5 py-3 rounded-2xl bg-white text-blue-700 hover:bg-blue-50 font-bold text-xs shadow-lg shadow-black/10 transition-all transform hover:-translate-y-0.5 active:translate-y-0"
            >
              <Download className="w-4 h-4 text-blue-600" />
              下载左右并排对照 PDF
            </a>
          )}

          {/* 纯中文版 PDF 下载 */}
          {result.pure_trans_pdf && (
            <a
              href={result.pure_trans_pdf}
              download
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-white/10 hover:bg-white/20 border border-white/20 text-white font-semibold text-xs backdrop-blur-md transition-all"
            >
              <FileDown className="w-4 h-4" />
              下载纯中文 PDF
            </a>
          )}

          {/* Word 双语对照下载 */}
          {result.bilingual_docx && (
            <a
              href={result.bilingual_docx}
              download
              className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-white/10 hover:bg-white/20 border border-white/20 text-white font-semibold text-xs backdrop-blur-md transition-all"
            >
              <FileDown className="w-4 h-4" />
              下载双语 Word (.docx)
            </a>
          )}

          {/* Markdown 双语对照下载 */}
          {result.bilingual_md && (
            <a
              href={result.bilingual_md}
              download
              className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-white/10 hover:bg-white/20 border border-white/20 text-white font-semibold text-xs backdrop-blur-md transition-all"
            >
              <FileDown className="w-4 h-4" />
              下载双语 Markdown (.md)
            </a>
          )}

          {/* 拼接大图下载 */}
          {result.side_by_side_img && (
            <a
              href={result.side_by_side_img}
              download
              className="flex items-center gap-2 px-4 py-3 rounded-2xl bg-white/10 hover:bg-white/20 border border-white/20 text-white font-semibold text-xs backdrop-blur-md transition-all"
            >
              <FileDown className="w-4 h-4" />
              下载并排高清大图
            </a>
          )}

        </div>

      </div>
    </div>
  );
};
