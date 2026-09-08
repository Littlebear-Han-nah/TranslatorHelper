import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { ApiKeyModal } from './components/ApiKeyModal';
import { FileUploader } from './components/FileUploader';
import { TaskProgress } from './components/TaskProgress';
import { SplitViewReader } from './components/SplitViewReader';
import { ExportBar } from './components/ExportBar';
import { ModelInfo, UploadInfo, TaskStatus, TranslationResult } from './types';
import { Sparkles, Layers, BookOpen, Download, ShieldCheck, Zap } from 'lucide-react';

export const App: React.FC = () => {
  // 模型与配置状态
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('qwen3.8-flash');
  const [translateMode, setTranslateMode] = useState<'courseware' | 'academic'>('courseware');
  const [apiKey, setApiKey] = useState<string>(() => localStorage.getItem('DASHSCOPE_API_KEY') || '');
  const [isKeyModalOpen, setIsKeyModalOpen] = useState(false);
  const [hasDefaultKey, setHasDefaultKey] = useState(true);

  // 任务与结果状态
  const [currentUpload, setCurrentUpload] = useState<UploadInfo | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [result, setResult] = useState<TranslationResult | null>(null);
  const [isTranslating, setIsTranslating] = useState(false);

  // 初始化加载后端配置与模型列表
  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((data) => {
        if (data.models && data.models.length > 0) {
          setModels(data.models);
          setSelectedModel(data.default_model || data.models[0].id);
        }
        setHasDefaultKey(data.has_default_key);
      })
      .catch((err) => console.error('加载系统配置失败:', err));
  }, []);

  // 保存 API Key 到本地存储
  const handleSaveKey = (key: string) => {
    setApiKey(key);
    if (key) {
      localStorage.setItem('DASHSCOPE_API_KEY', key);
    } else {
      localStorage.removeItem('DASHSCOPE_API_KEY');
    }
  };

  // 触发翻译任务并开启 SSE 实时流监听
  const handleStartTranslate = async (uploadInfo: UploadInfo) => {
    setCurrentUpload(uploadInfo);
    setIsTranslating(true);
    setResult(null);
    setTaskStatus({
      task_id: '',
      stage: 'starting',
      percent: 5,
      message: '正在初始化翻译流水线...',
      current_page: 0,
      total_pages: 1,
    });

    try {
      const formData = new FormData();
      formData.append('file_id', uploadInfo.file_id);
      formData.append('saved_path', uploadInfo.saved_path);
      formData.append('extension', uploadInfo.extension);
      formData.append('model', selectedModel);
      formData.append('mode', translateMode);
      if (apiKey) {
        formData.append('api_key', apiKey);
      }

      const resp = await fetch('/api/translate', {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        throw new Error('启动翻译任务失败');
      }

      const { task_id } = await resp.json();

      // 建立 Server-Sent Events (SSE) 实时获取翻译进度
      const eventSource = new EventSource(`/api/tasks/${task_id}/events`);

      eventSource.onmessage = (event) => {
        const data: TaskStatus = JSON.parse(event.data);
        setTaskStatus(data);

        if (data.stage === 'completed' && data.result) {
          setResult(data.result);
          setIsTranslating(false);
          eventSource.close();
        } else if (data.stage === 'failed') {
          setIsTranslating(false);
          eventSource.close();
        }
      };

      eventSource.onerror = (err) => {
        console.warn('SSE 接收中断，自动回退到轮询模式...', err);
        eventSource.close();
        startPolling(task_id);
      };
    } catch (err: any) {
      setIsTranslating(false);
      setTaskStatus({
        task_id: '',
        stage: 'failed',
        percent: 0,
        message: err.message || '翻译启动失败',
        current_page: 0,
        total_pages: 0,
      });
    }
  };

  // SSE 异常时的轮询兜底机制
  const startPolling = (taskId: string) => {
    const timer = setInterval(async () => {
      try {
        const resp = await fetch(`/api/tasks/${taskId}/status`);
        const data: TaskStatus = await resp.json();
        setTaskStatus(data);

        if (data.stage === 'completed') {
          clearInterval(timer);
          setIsTranslating(false);
          if (data.result) setResult(data.result);
        } else if (data.stage === 'failed') {
          clearInterval(timer);
          setIsTranslating(false);
        }
      } catch (err) {
        clearInterval(timer);
        setIsTranslating(false);
      }
    }, 1500);
  };

  return (
    <div className="min-h-screen flex flex-col bg-gradient-to-b from-slate-50 to-slate-100/70 text-slate-900">
      
      {/* 顶部导航栏 */}
      <Header
        models={models}
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
        translateMode={translateMode}
        onChangeMode={setTranslateMode}
        onOpenKeyModal={() => setIsKeyModalOpen(true)}
        isKeySet={Boolean(apiKey || hasDefaultKey)}
      />

      {/* API Key 配置模态窗 */}
      <ApiKeyModal
        isOpen={isKeyModalOpen}
        onClose={() => setIsKeyModalOpen(false)}
        apiKey={apiKey}
        onSaveKey={handleSaveKey}
        models={models}
        currentModel={selectedModel}
      />

      {/* 主体内容区 */}
      <main className="flex-1 py-8">
        
        {/* 标题与特性说明 */}
        <div className="max-w-4xl mx-auto text-center px-4 mb-8">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 border border-blue-200 text-blue-700 text-xs font-semibold mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            全新支持课件与学术论文左右对照无损并排排版
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 tracking-tight">
            课件与论文 <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">左右双语对照翻译</span>
          </h2>
          <p className="text-sm text-slate-600 mt-2.5 max-w-2xl mx-auto leading-relaxed">
            上传您的英文课件或学术论文（PDF / Word / Markdown / 图片），通义千问 AI 自动解析版面，输出<strong className="text-slate-800">左侧原版、右侧中文</strong>的高清双语对照 PDF 与交互式精读视图。
          </p>

          {/* 3大特色保障 */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-6 text-left">
            <div className="bg-white/80 p-3.5 rounded-2xl border border-slate-200 shadow-sm flex items-start gap-3">
              <div className="p-2 rounded-xl bg-blue-50 text-blue-600 shrink-0">
                <Layers className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-slate-800">原版无损左右并排</h4>
                <p className="text-[11px] text-slate-500 mt-0.5">左页原图文，右页中文精准排版，一目了然。</p>
              </div>
            </div>

            <div className="bg-white/80 p-3.5 rounded-2xl border border-slate-200 shadow-sm flex items-start gap-3">
              <div className="p-2 rounded-xl bg-indigo-50 text-indigo-600 shrink-0">
                <BookOpen className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-slate-800">公式与学术术语保留</h4>
                <p className="text-[11px] text-slate-500 mt-0.5">保留 LaTeX 公式、代码块与专业文献引用。</p>
              </div>
            </div>

            <div className="bg-white/80 p-3.5 rounded-2xl border border-slate-200 shadow-sm flex items-start gap-3">
              <div className="p-2 rounded-xl bg-emerald-50 text-emerald-600 shrink-0">
                <Download className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-slate-800">多格式文件一键下载</h4>
                <p className="text-[11px] text-slate-500 mt-0.5">一键导出并排对照 PDF、纯中文版与双语文档。</p>
              </div>
            </div>
          </div>
        </div>

        {/* 拖拽上传区 */}
        <FileUploader
          onStartTranslate={handleStartTranslate}
          isTranslating={isTranslating}
          selectedModel={selectedModel}
          translateMode={translateMode}
        />

        {/* 翻译进行中进度展示 */}
        {taskStatus && <TaskProgress status={taskStatus} />}

        {/* 完成后的导出与下载栏 */}
        {result && <ExportBar result={result} />}

        {/* 双栏左右对照交互式阅读器 */}
        {result && result.pages && result.pages.length > 0 && (
          <SplitViewReader pages={result.pages} />
        )}

      </main>

      {/* 页脚 */}
      <footer className="border-t border-slate-200 bg-white/50 py-6 text-center text-xs text-slate-500">
        <p>课件/论文智能对照翻译系统 · 基于通义千问 DashScope API 驱动 · 左右双栏无损对照排版</p>
      </footer>

    </div>
  );
};

export default App;
