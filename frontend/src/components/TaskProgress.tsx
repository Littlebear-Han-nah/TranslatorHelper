import React from 'react';
import { Loader2, CheckCircle2, Sparkles, Layers, FileCheck } from 'lucide-react';
import { TaskStatus } from '../types';

interface TaskProgressProps {
  status: TaskStatus;
}

// 翻译任务进度与流水线状态组件
export const TaskProgress: React.FC<TaskProgressProps> = ({ status }) => {
  const isCompleted = status.stage === 'completed';
  const isFailed = status.stage === 'failed';

  const steps = [
    { key: 'starting', label: '1. 结构解析与排版提取' },
    { key: 'translating', label: '2. 通义千问学术精翻' },
    { key: 'stitching', label: '3. 左右无损拼接对照 PDF' },
    { key: 'completed', label: '4. 完成生成' },
  ];

  return (
    <div className="max-w-4xl mx-auto my-6 px-4">
      <div className="bg-white rounded-3xl p-6 lg:p-8 shadow-sm border border-slate-200">
        
        {/* 顶部标题与动态状态指示 */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            {!isCompleted && !isFailed ? (
              <div className="w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center">
                <Loader2 className="w-5 h-5 animate-spin" />
              </div>
            ) : isCompleted ? (
              <div className="w-8 h-8 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                <CheckCircle2 className="w-5 h-5" />
              </div>
            ) : (
              <div className="w-8 h-8 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center">
                !
              </div>
            )}
            <div>
              <h3 className="text-sm font-bold text-slate-900">
                {isCompleted
                  ? '翻译与对照生成完毕！'
                  : isFailed
                  ? '处理中断或出错'
                  : '正在生成双语对照文档...'}
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">{status.message}</p>
            </div>
          </div>

          <div className="text-right">
            <span className="text-xl font-black text-blue-600 tracking-tight">
              {status.percent}%
            </span>
            {status.total_pages > 0 && status.stage === 'translating' && (
              <p className="text-[11px] text-slate-400">
                第 {status.current_page} / {status.total_pages} 页
              </p>
            )}
          </div>
        </div>

        {/* 进度条动画 */}
        <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden mb-6">
          <div
            className={`h-2.5 rounded-full transition-all duration-500 ease-out ${
              isCompleted
                ? 'bg-emerald-500'
                : isFailed
                ? 'bg-rose-500'
                : 'bg-gradient-to-r from-blue-500 to-indigo-600'
            }`}
            style={{ width: `${Math.max(status.percent, 4)}%` }}
          />
        </div>

        {/* 流水线阶段步骤条 */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-slate-100 text-xs">
          {steps.map((step, idx) => {
            const stepOrder = ['starting', 'translating', 'stitching', 'completed'];
            const currentIdx = stepOrder.indexOf(status.stage);
            const thisIdx = stepOrder.indexOf(step.key);
            const isDone = isCompleted || (currentIdx > thisIdx);
            const isCurrent = currentIdx === thisIdx && !isCompleted;

            return (
              <div
                key={step.key}
                className={`flex items-center gap-2 p-2 rounded-xl transition-colors ${
                  isDone
                    ? 'text-emerald-700 bg-emerald-50/50'
                    : isCurrent
                    ? 'text-blue-700 bg-blue-50/80 font-semibold'
                    : 'text-slate-400'
                }`}
              >
                {isDone ? (
                  <CheckCircle2 className="w-3.5 h-3.5 shrink-0 text-emerald-600" />
                ) : isCurrent ? (
                  <Loader2 className="w-3.5 h-3.5 shrink-0 text-blue-600 animate-spin" />
                ) : (
                  <span className="w-3.5 h-3.5 rounded-full border border-slate-300 flex items-center justify-center text-[9px]">
                    {idx + 1}
                  </span>
                )}
                <span className="truncate">{step.label}</span>
              </div>
            );
          })}
        </div>

      </div>
    </div>
  );
};
