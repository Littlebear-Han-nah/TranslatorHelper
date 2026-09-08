import React from 'react';
import { BookOpen, Key, Sparkles, Layers, Sliders } from 'lucide-react';
import { ModelInfo } from '../types';

interface HeaderProps {
  models: ModelInfo[];
  selectedModel: string;
  onSelectModel: (model: string) => void;
  translateMode: 'courseware' | 'academic';
  onChangeMode: (mode: 'courseware' | 'academic') => void;
  onOpenKeyModal: () => void;
  isKeySet: boolean;
}

// 顶部导航栏组件：展示系统标题、模型选择、课件/论文模式切换与 API Key 快捷入口
export const Header: React.FC<HeaderProps> = ({
  models,
  selectedModel,
  onSelectModel,
  translateMode,
  onChangeMode,
  onOpenKeyModal,
  isKeySet,
}) => {
  return (
    <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-slate-200 px-4 lg:px-8 py-3.5 transition-all">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
        
        {/* 系统标题与 Logo */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center text-white shadow-md shadow-blue-500/20">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-slate-900 tracking-tight">课件/论文智能对照翻译</h1>
              <span className="px-2 py-0.5 text-xs font-semibold bg-blue-50 text-blue-700 rounded-full border border-blue-200/60">
                通义千问驱动
              </span>
            </div>
            <p className="text-xs text-slate-500">
              左侧原版 · 右侧中文 · 智能无损双语排版导出
            </p>
          </div>
        </div>

        {/* 顶部控制选项：翻译模式、模型选择、API Key 状态 */}
        <div className="flex items-center flex-wrap gap-2.5">
          
          {/* 模式选择：课件模式 vs 学术论文模式 */}
          <div className="flex items-center bg-slate-100 p-1 rounded-lg border border-slate-200/80 text-xs font-medium">
            <button
              onClick={() => onChangeMode('courseware')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all ${
                translateMode === 'courseware'
                  ? 'bg-white text-blue-600 shadow-sm font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              课件模式 (Slides)
            </button>
            <button
              onClick={() => onChangeMode('academic')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-all ${
                translateMode === 'academic'
                  ? 'bg-white text-blue-600 shadow-sm font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <BookOpen className="w-3.5 h-3.5" />
              学术论文 (Paper)
            </button>
          </div>

          {/* 模型切换下拉框 */}
          <div className="relative">
            <select
              value={selectedModel}
              onChange={(e) => onSelectModel(e.target.value)}
              className="appearance-none bg-white border border-slate-200 text-slate-800 text-xs font-medium rounded-lg px-3 py-1.5 pr-8 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 shadow-sm cursor-pointer hover:border-slate-300"
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            <Sparkles className="w-3.5 h-3.5 text-blue-500 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          </div>

          {/* API Key 按钮 */}
          <button
            onClick={onOpenKeyModal}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
              isKeySet
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            <span>{isKeySet ? 'API 密钥已配置' : '配置 API 密钥'}</span>
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isKeySet ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'
              }`}
            />
          </button>

        </div>
      </div>
    </header>
  );
};
