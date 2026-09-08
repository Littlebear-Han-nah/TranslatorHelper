import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 记录是否已成功初始化中文字体
_FONT_INITIALIZED = False
_CHINESE_FONT_NAME = "Helvetica"

def init_chinese_font():
    """
    初始化 ReportLab 的中文字体支持
    优先检查系统自带的中文字体（如 macOS 的 Arial Unicode / 华文黑体 / 冬青黑体），
    若无本地字体文件则回退到内置的 STSong-Light CID 字体。
    """
    global _FONT_INITIALIZED, _CHINESE_FONT_NAME
    if _FONT_INITIALIZED:
        return _CHINESE_FONT_NAME

    # 候选系统字体路径 (优先考虑 macOS 与 Linux 常见中文字体)
    font_candidates = [
        ("ArialUnicode", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ("STHeiti", "/System/Library/Fonts/STHeiti Light.ttc"),
        ("Hiragino", "/System/Library/Fonts/Hiragino Sans GB.ttc"),
        ("PingFang", "/System/Library/Fonts/PingFang.ttc"),
    ]

    for font_name, font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                # 注册 TrueType 字体
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                _CHINESE_FONT_NAME = font_name
                _FONT_INITIALIZED = True
                return _CHINESE_FONT_NAME
            except Exception:
                continue

    # 如果无法加载本地 TTF，尝试使用标准 CID 字体 STSong-Light
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _CHINESE_FONT_NAME = "STSong-Light"
        _FONT_INITIALIZED = True
        return _CHINESE_FONT_NAME
    except Exception:
        pass

    _FONT_INITIALIZED = True
    return _CHINESE_FONT_NAME

def get_chinese_font_name() -> str:
    """
    获取已注册的中文字体名称
    """
    return init_chinese_font()
