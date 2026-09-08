import React, { useState, useRef } from 'react';
import { Upload, FileText, Image as ImageIcon, FileCode, CheckCircle2, ArrowRight, Loader2, Sparkles } from 'lucide-react';
import { UploadInfo } from '../types';

interface FileUploaderProps {
  onStartTranslate: (uploadInfo: UploadInfo) => void;
  isTranslating: boolean;
  selectedModel: string;
  translateMode: 'courseware' | 'academic';
}

// 现代化文件拖拽上传组件
export const FileUploader: React.FC<FileUploaderProps> = ({
  onStartTranslate,
  isTranslating,
  selectedModel,
  translateMode,
}) => {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragOver(true);
    } else if (e.type === 'dragleave') {
      setDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const processFile = (file: File) => {
    const ext = file.name.split('.').pop()?.toLowerCase();
    const validExts = ['pdf', 'docx', 'md', 'png', 'jpg', 'jpeg', 'webp'];
    if (!ext || !validExts.includes(ext)) {
      setUploadError('不支持该格式，请上传 PDF、Word (.docx)、Markdown (.md) 或图片。');
      setSelectedFile(null);
      return;
    }
    setUploadError('');
    setSelectedFile(file);
  };

  // 触发文件上传并准备翻译任务
  const handleUploadAndTranslate = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setUploadError('');

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const resp = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });

      if (!resp.ok) {
        const errData = await resp.json();
        throw new Error(errData.detail || '上传文件失败');
      }

      const uploadInfo: UploadInfo = await resp.json();
      onStartTranslate(uploadInfo);
    } catch (err: any) {
      setUploadError(err.message || '上传异常，请检查后端运行状态');
    } finally {
      setUploading(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  };

  return (
    <div className="max-w-4xl mx-auto my-6 px-4">
      <div
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        onClick={() => !selectedFile && fileInputRef.current?.click()}
        className={`relative border-2 border-dashed rounded-3xl p-8 lg:p-12 text-center transition-all duration-300 ${
          dragOver
            ? 'border-blue-500 bg-blue-50/60 scale-[1.01]'
            : selectedFile
            ? 'border-emerald-300 bg-emerald-50/30'
            : 'border-slate-300 hover:border-blue-400 bg-white hover:bg-slate-50/50 shadow-sm'
        } ${!selectedFile ? 'cursor-pointer' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.md,.png,.jpg,.jpeg,.webp"
          onChange={handleChange}
          className="hidden"
        />

        {!selectedFile ? (
          <div className="flex flex-col items-center justify-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center shadow-inner group-hover:scale-110 transition-transform">
              <Upload className="w-8 h-8" />
            </div>
            
            <div className="space-y-1">
              <h2 className="text-lg font-bold text-slate-800">
                拖拽文件至此处，或 <span className="text-blue-600 hover:underline">点击浏览上传</span>
              </h2>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                支持英文课件 PDF、学术论文 PDF、Word 讲义、Markdown 课件笔记及图表截图
              </p>
            </div>

            {/* 支持格式微标签 */}
            <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-50 text-rose-700 border border-rose-200">
                <FileText className="w-3.5 h-3.5" /> PDF 课件/论文
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200">
                <FileText className="w-3.5 h-3.5" /> Word (.docx)
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-200">
                <FileCode className="w-3.5 h-3.5" /> Markdown (.md)
              </span>
              <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200">
                <ImageIcon className="w-3.5 h-3.5" /> 图片/截图
              </span>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center space-y-5">
            <div className="w-14 h-14 rounded-2xl bg-emerald-100 text-emerald-600 flex items-center justify-center shadow-sm">
              <CheckCircle2 className="w-8 h-8" />
            </div>

            <div>
              <h3 className="text-base font-bold text-slate-900">{selectedFile.name}</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                文件大小: {formatFileSize(selectedFile.size)} · 准备使用{' '}
                <span className="font-semibold text-blue-600">{selectedModel}</span> 执行{' '}
                <span className="font-semibold text-indigo-600">
                  {translateMode === 'courseware' ? '课件模式' : '学术论文模式'}
                </span>{' '}
                翻译
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedFile(null);
                  if (fileInputRef.current) fileInputRef.current.value = '';
                }}
                disabled={uploading || isTranslating}
                className="px-4 py-2 text-xs font-medium text-slate-600 hover:text-slate-900 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-colors"
              >
                更换文件
              </button>

              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleUploadAndTranslate();
                }}
                disabled={uploading || isTranslating}
                className="flex items-center gap-2 px-6 py-2.5 text-xs font-semibold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 rounded-xl shadow-lg shadow-blue-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50"
              >
                {uploading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    正在上传文件...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    开始生成左右对照 PDF
                    <ArrowRight className="w-3.5 h-3.5" />
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>

      {uploadError && (
        <div className="mt-3 p-3 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-700 text-center">
          {uploadError}
        </div>
      )}
    </div>
  );
};
