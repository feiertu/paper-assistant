import pymupdf
import re
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import config

def merge_spans_by_line(blocks: Dict) -> List[Dict]:
    lines = []
    
    for block in blocks.get("blocks", []):
        if block["type"] != 0:  
            continue
            
        for line in block.get("lines", []):
            full_text = "".join(span["text"] for span in line.get("spans", []))
            
            first_span = line["spans"][0] if line.get("spans") else None
            if not first_span:
                continue
                
            lines.append({
                "text": full_text,
                "size": first_span["size"],
                "bbox": line.get("bbox"), 
            })
    
    return lines


SPECIAL_SECTIONS = {
    'references', 'abstract', 'acknowledgements', 'acknowledgments',
    'conclusion', 'conclusions', 'supplementary material',
    'contents', 'introduction', 'related work', 'related works',
    'background', 'method', 'methods', 'methodology',
    'experiments', 'experiment', 'results', 'discussion',
    'limitations', 'appendix', 'appendices',
}

_PURE_NUM_RE = re.compile(r'^\d+(\.\d+)?\.?\s*$')
_YEAR_RE = re.compile(r'^(19|20)\d{2}[a-z]?\.?$')
_CITATION_PAGE_RE = re.compile(r'\.{3,}|\bpp?\.\s*\d|\bvol\.?\s*\d|^\s*\d+\s*$')

MAX_TITLE_LEN = 120


def _looks_like_title(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > MAX_TITLE_LEN:
        return False
    if _PURE_NUM_RE.match(t):
        return False
    # 拒绝以"年份."或"年份"开头的条目（参考文献常见）
    first_token = t.split()[0] if t.split() else ''
    if _YEAR_RE.match(first_token.rstrip('.')):
        return False
    # 目录条目（含...点引导符 + 页码）通常很长
    if _CITATION_PAGE_RE.search(t) and len(t) > 50:
        return False
    return True


def is_special_section(text: str) -> bool:
    return text.strip().lower() in SPECIAL_SECTIONS


def is_section_title(text: str, size: float) -> bool:
    t = text.strip()
    if not _looks_like_title(t):
        return False
    section_pattern = re.compile(r'^(\d+\.|[A-Z]\.)\s*\S')
    is_special = is_special_section(t) and size >= 10.0
    return bool(section_pattern.match(t)) or is_special


def is_subsection_title(text: str, size: float) -> bool:
    t = text.strip()
    if not _looks_like_title(t):
        return False
    subsection_pattern = re.compile(r'^(\d+\.\d+\.|[A-Z]\.\d+\.)\s*\S')
    return bool(subsection_pattern.match(t))


def parse_pdf_structure(pdf_path: str, min_body_size: float = 6.5) -> Dict[str, Any]:
    
    doc = pymupdf.open(pdf_path)
    metadata = doc.metadata
    
    result = {
        "metadata": {
            "title": metadata.get("title"),
            "author": metadata.get("author"),
            "creationDate": metadata.get("creationDate"),
        },
        "sections": []
    }
    
    current_section: Optional[Dict] = None
    current_subsection: Optional[Dict] = None
    pre_section_buffer: List[str] = []
    pre_section_page: Optional[int] = None
    
    def save_current_subsection():
        nonlocal current_section, current_subsection
        if current_subsection and current_subsection["content"].strip():
            if "subsections" not in current_section:
                current_section["subsections"] = []
            current_section["subsections"].append(current_subsection)
        current_subsection = None
    
    def save_current_section():
        nonlocal current_section
        if current_section and current_section["content"].strip():
            result["sections"].append(current_section)
        current_section = None
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("dict")
        
        lines = merge_spans_by_line(blocks)
        
        for line in lines:
            text = line["text"].strip()
            size = line["size"]
            
            if not text:
                continue
            
            if is_section_title(text, size):
                if current_section:
                    save_current_subsection()
                    save_current_section()
                
                current_section = {
                    "title": text,
                    "page": page_num + 1,
                    "size": size,
                    "content": ""
                }
                current_subsection = None
                
            elif is_subsection_title(text, size):
                if current_section:
                    save_current_subsection()
                else:
                    pre_section_buffer.append(text)
                    pre_section_page = page_num + 1
                    continue
                
                current_subsection = {
                    "title": text,
                    "page": page_num + 1,
                    "size": size,
                    "content": ""
                }
                
            else:
                if size < min_body_size:
                    continue
                
                if current_subsection:
                    current_subsection["content"] += " " + text
                elif current_section:
                    current_section["content"] += " " + text
                else:
                    pre_section_buffer.append(text)
                    pre_section_page = pre_section_page or (page_num + 1)

    if pre_section_buffer:
        first_section = {
            "title": "Abstract" if result["metadata"].get("title") else "Preamble",
            "page": pre_section_page or 1,
            "size": 0.0,
            "content": " ".join(pre_section_buffer)
        }
        result["sections"].insert(0, first_section)

    if current_section:
        save_current_subsection()
        save_current_section()
    
    doc.close()
    return result


def print_structure(result: Dict[str, Any], filename: str):
    metadata = result["metadata"]
    print(f"📄 [{filename}] {metadata.get('title', 'N/A')}")
    print(f"   📊 共识别到 {len(result['sections'])} 个章节")
    for section in result["sections"]:
        print(f"   📖 [{section['page']}] {section['title']}")
        if "subsections" in section:
            for subsection in section["subsections"]:
                print(f"      └─ [{subsection['page']}] {subsection['title']}")
    print()


def batch_process(input_dir: Optional[str] = None, output_dir: Optional[str] = None, min_body_size: float = 6.5):
    """
    批量处理目录下的所有 PDF 文件

    Args:
        input_dir: 输入目录（包含 PDF 文件）。None 则用 config.RAW_PDF_DIR。
        output_dir: 输出目录（保存 JSON 结果）。None 则用 config.PARSED_DIR。
        min_body_size: 正文最小字号阈值
    """
    input_path = Path(input_dir) if input_dir else config.RAW_PDF_DIR
    output_path = Path(output_dir) if output_dir else config.PARSED_DIR
    
    if not input_path.exists():
        print(f"❌ 输入目录不存在: {input_dir}")
        return
    
    # 创建输出目录
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 查找所有 PDF 文件（包括子目录）
    pdf_files = list(input_path.rglob("*.pdf"))
    
    if not pdf_files:
        print(f"⚠️  在 {input_dir} 中未找到 PDF 文件")
        return
    
    print(f"🚀 开始批量处理，共找到 {len(pdf_files)} 个 PDF 文件\n")
    
    success_count = 0
    fail_count = 0
    
    for pdf_file in pdf_files:
        try:
            print(f"📝 处理中: {pdf_file.relative_to(input_path)}")
            result = parse_pdf_structure(str(pdf_file), min_body_size)
            
            # 保存到输出目录，保持子目录结构
            relative_path = pdf_file.relative_to(input_path).with_suffix(".json")
            save_path = output_path / relative_path
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            print_structure(result, pdf_file.name)
            success_count += 1
            
        except Exception as e:
            print(f"❌ 处理失败: {pdf_file.name} | 错误: {e}\n")
            fail_count += 1
    
    # 打印汇总
    print("=" * 50)
    print(f"✅ 处理完成！成功: {success_count} | 失败: {fail_count}")
    print(f"📁 结果已保存至: {output_path.resolve()}")


def main():
    # 配置输入输出目录：走 config.py，避免历史版本里"../data/parsed"导致输出落到 src/data/parsed 的 bug
    INPUT_DIR = str(config.RAW_PDF_DIR)
    OUTPUT_DIR = str(config.PARSED_DIR)

    print(f"📂 INPUT  = {INPUT_DIR}")
    print(f"📂 OUTPUT = {OUTPUT_DIR}")
    batch_process(INPUT_DIR, OUTPUT_DIR, min_body_size=config.PDF_MIN_BODY_SIZE)


if __name__ == "__main__":
    main()