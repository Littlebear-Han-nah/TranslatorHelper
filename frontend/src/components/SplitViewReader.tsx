import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Maximize2, Copy, Check, Eye, Columns } from 'lucide-react';
import { PageResult } from '../types';

interface SplitViewReaderProps {
  pages: PageResult[];
}

// 核心组件：双栏左右对照交互式阅读器（左侧原版 · 右侧中文）
export const SplitViewReader: React.FC<SplitViewReaderProps> = ({ pages }) => {
  const [currentPageIndex, setCurrentPageIndex] = useState(0);
  const [zoomLevel, setZoomLevel] = useState(100);
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<'visual' | 'text'>('visual');

  if (!pages || pages.length === 0) return null;

  const totalPages = pages.length;
  const currentPage = pages[currentPageIndex];

  const handlePrev = () => {
    if (currentPageIndex > 0) setCurrentPageIndex(currentPageIndex - 1);
  };

  const handleNext = () => {
    if (currentPageIndex < totalPages - 1) setCurrentPageIndex(currentPageIndex + 1);
  };

  const handleZoomIn = () => {
    if (zoomLevel < 180) setZoomLevel(zoomLevel + 15);
  };

  const handleZoomOut = () => {
    if (zoomLevel > 70) setZoomLevel(zoomLevel - 15);
  };

  const handleCopyTranslation = () => {
    if (currentPage.trans_text) {
      navigator.clipboard.writeText(currentPage.trans_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="max-w-7xl mx-auto my-6 px-4">
      <div className="bg-white rounded-3xl shadow-lg border border-slate-200 overflow-hidden flex flex-col">
        
        {/* 阅读器工具栏：翻页控制、缩放调节、视图模式切换 */}
        <div className="bg-slate-50/80 border-b border-slate-200 px-5 py-3 flex flex-wrap items-center justify-between gap-3">
          
          {/* 翻页控制器 */}
          <div className="flex items-center gap-2">
            <button
              onClick={handlePrev}
              disabled={currentPageIndex === 0}
              className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-white text-slate-700 transition-colors"
              title="上一页"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs font-semibold text-slate-700 px-2">
              第 {currentPageIndex + 1} / {totalPages} 页
            </span>
            <button
              onClick={handleNext}
              disabled={currentPageIndex === totalPages - 1}
              className="p-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-white text-slate-700 transition-colors"
              title="下一页"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          {/* 视图模式切换：高保真排版图 vs 纯文本精读 */}
          <div className="flex items-center bg-slate-200/70 p-0.5 rounded-lg text-xs font-medium">
            <button
              onClick={() => setViewMode('visual')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-md transition-all ${
                viewMode === 'visual'
                  ? 'bg-white text-blue-600 shadow-sm font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Columns className="w-3.5 h-3.5" />
              高保真排版对照
            </button>
            <button
              onClick={() => setViewMode('text')}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-md transition-all ${
                viewMode === 'text'
                  ? 'bg-white text-blue-600 shadow-sm font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Eye className="w-3.5 h-3.5" />
              双语文本精读
            </button>
          </div>

          {/* 缩放与复制操作 */}
          <div className="flex items-center gap-2">
            <div className="flex items-center bg-white border border-slate-200 rounded-lg px-1.5 py-0.5 text-xs text-slate-600">
              <button
                onClick={handleZoomOut}
                className="p-1 hover:text-blue-600 transition-colors"
                title="缩小"
              >
                <ZoomOut className="w-3.5 h-3.5" />
              </button>
              <span className="px-1.5 font-medium">{zoomLevel}%</span>
              <button
                onClick={handleZoomIn}
                className="p-1 hover:text-blue-600 transition-colors"
                title="放大"
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </button>
            </div>

            <button
              onClick={handleCopyTranslation}
              className="flex items-center gap-1 px-2.5 py-1.5 bg-white border border-slate-200 hover:bg-slate-100 rounded-lg text-xs font-medium text-slate-700 transition-colors"
              title="复制当前页中文翻译文本"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                  <span className="text-emerald-600">已复制</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>复制中文</span>
                </>
              )}
            </button>
          </div>

        </div>

        {/* 核心双栏阅读区：左侧原版 · 右侧中文对照 */}
        {viewMode === 'visual' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-200 bg-slate-100/60 p-4 lg:p-6 overflow-auto max-h-[75vh]">
            
            {/* 左侧：原版页面 */}
            <div className="flex flex-col items-center p-2">
              <div className="flex items-center gap-1.5 mb-2.5 self-start">
                <span className="w-2.5 h-2.5 rounded-full bg-slate-400"></span>
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                  原版 (Original) · 第 {currentPage.page} 页
                </span>
              </div>
              <div
                className="bg-white rounded-xl shadow-md border border-slate-200/80 overflow-hidden transition-transform origin-top"
                style={{ width: `${zoomLevel}%` }}
              >
                <img
                  src={currentPage.orig_img}
                  alt={`原版第 ${currentPage.page} 页`}
                  className="w-full h-auto object-contain select-none"
                  loading="lazy"
                />
              </div>
            </div>

            {/* 右侧：中文翻译对照 */}
            <div className="flex flex-col items-center p-2">
              <div className="flex items-center gap-1.5 mb-2.5 self-start">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-600"></span>
                <span className="text-xs font-bold text-blue-700 uppercase tracking-wider">
                  中文对照 (Translation) · 第 {currentPage.page} 页
                </span>
              </div>
              <div
                className="bg-white rounded-xl shadow-md border border-slate-200/80 overflow-hidden transition-transform origin-top"
                style={{ width: `${zoomLevel}%` }}
              >
                <img
                  src={currentPage.trans_img}
                  alt={`中文翻译第 ${currentPage.page} 页`}
                  className="w-full h-auto object-contain select-none"
                  loading="lazy"
                />
              </div>
            </div>

          </div>
        ) : (
          /* 文本精读模式：直接对比双语文字 */
          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-slate-200 p-6 overflow-auto max-h-[75vh] bg-white">
            
            {/* 左侧英文原文 */}
            <div className="p-4 space-y-3">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="w-2 h-2 rounded-full bg-slate-400"></span>
                <h4 className="text-xs font-bold text-slate-700">英文原文提取</h4>
              </div>
              <div className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap font-serif bg-slate-50 p-4 rounded-xl border border-slate-100 min-h-[300px]">
                {currentPage.orig_text || '（本页无可选纯文本，可能为纯图表或截图）'}
              </div>
            </div>

            {/* 右侧中文翻译 */}
            <div className="p-4 space-y-3">
              <div className="flex items-center gap-1.5 mb-2">
                <span className="w-2 h-2 rounded-full bg-blue-600"></span>
                <h4 className="text-xs font-bold text-blue-700">通义千问中文翻译</h4>
              </div>
              <div className="text-sm text-slate-800 leading-relaxed whitespace-pre-wrap font-sans bg-blue-50/40 p-4 rounded-xl border border-blue-100 min-h-[300px]">
                {currentPage.trans_text || '（暂无翻译文本）'}
              </div>
            </div>

          </div>
        )}

      </div>
    </div>
  );
};
