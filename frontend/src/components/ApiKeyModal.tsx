import React, { useState } from 'react';
import { Key, X, CheckCircle, AlertCircle, Loader2, Sparkles } from 'lucide-react';
import { ModelInfo } from '../types';

interface ApiKeyModalProps {
  isOpen: boolean;
  onClose: () => void;
  apiKey: string;
  onSaveKey: (key: string) => void;
  models: ModelInfo[];
  currentModel: string;
}

// API Key 配置与连通性测试模态弹窗组件
export const ApiKeyModal: React.FC<ApiKeyModalProps> = ({
  isOpen,
  onClose,
  apiKey,
  onSaveKey,
  models,
  currentModel,
}) => {
  const [inputKey, setInputKey] = useState(apiKey);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'failed'>('idle');
  const [testMessage, setTestMessage] = useState('');

  if (!isOpen) return null;

  // 测试通义千问 API 连通性
  const handleTest = async () => {
    setTestStatus('testing');
    setTestMessage('');
    try {
      const formData = new FormData();
      if (inputKey.trim()) {
        formData.append('api_key', inputKey.trim());
      }
      formData.append('model', currentModel);

      const resp = await fetch('/api/test-key', {
        method: 'POST',
        body: formData,
      });
      const data = await resp.json();
      if (data.success) {
        setTestStatus('success');
        setTestMessage(`连通成功！模型回复: "${data.reply}"`);
      } else {
        setTestStatus('failed');
        setTestMessage(`连接失败: ${data.error || '未知错误'}`);
      }
    } catch (err: any) {
      setTestStatus('failed');
      setTestMessage(`网络请求异常: ${err.message}`);
    }
  };

  const handleSave = () => {
    onSaveKey(inputKey.trim());
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-100 relative">
        
        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        {/* 弹窗头部 */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
            <Key className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900">通义千问 API 配置</h3>
            <p className="text-xs text-slate-500">配置阿里云百炼/DashScope API 密钥，保障极速学术翻译</p>
          </div>
        </div>

        {/* 表单输入区 */}
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5">
              DashScope API Key (兼容 OpenAI 规范)
            </label>
            <input
              type="password"
              value={inputKey}
              onChange={(e) => setInputKey(e.target.value)}
              placeholder="请输入 sk-..."
              className="w-full text-sm px-3.5 py-2.5 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono"
            />
            <p className="text-[11px] text-slate-400 mt-1">
              密钥将保存在您的本地浏览器中，绝不会被第三方存储。留空则使用系统预置密钥。
            </p>
          </div>

          {/* 连通性测试结果提示 */}
          {testStatus !== 'idle' && (
            <div
              className={`p-3 rounded-xl text-xs flex items-start gap-2.5 ${
                testStatus === 'testing'
                  ? 'bg-blue-50 text-blue-700 border border-blue-200'
                  : testStatus === 'success'
                  ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                  : 'bg-rose-50 text-rose-800 border border-rose-200'
              }`}
            >
              {testStatus === 'testing' && <Loader2 className="w-4 h-4 animate-spin shrink-0 text-blue-600" />}
              {testStatus === 'success' && <CheckCircle className="w-4 h-4 shrink-0 text-emerald-600" />}
              {testStatus === 'failed' && <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />}
              <span className="leading-relaxed">
                {testStatus === 'testing' ? `正在连接通义千问 (${currentModel}) 进行测试...` : testMessage}
              </span>
            </div>
          )}

          {/* 操作按钮组 */}
          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={handleTest}
              disabled={testStatus === 'testing'}
              className="px-4 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors disabled:opacity-50 flex items-center gap-1.5"
            >
              <Sparkles className="w-3.5 h-3.5 text-blue-500" />
              测试连通性
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-medium text-slate-600 hover:text-slate-800 rounded-xl transition-colors"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSave}
                className="px-5 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-xl shadow-md shadow-blue-500/20 transition-all"
              >
                保存设置
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
