import fitz  # PyMuPDF
import os
import re
from pathlib import Path
from datetime import datetime
import argparse

def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def pdf_to_markdown(pdf_path, output_dir=None, img_dir="attachments", text_only=False):
    """
    将PDF文件转换为Markdown格式，提取文本并保存图片到附件目录
    
    参数:
        pdf_path (str): PDF文件路径
        output_dir (str): 输出目录(默认为PDF所在目录)
        img_dir (str): 图片保存目录(相对于Markdown文件的路径)
        text_only (bool): 是否只提取文本(忽略图片)
    """
    # 创建输出目录
    if output_dir is None:
        output_dir = os.path.dirname(pdf_path)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 创建图片目录(绝对路径)
    img_abs_dir = os.path.join(output_dir, img_dir)
    Path(img_abs_dir).mkdir(parents=True, exist_ok=True)
    
    # 生成Markdown文件名
    pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
    sanitized_name = sanitize_filename(pdf_name)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    md_filename = f"{sanitized_name}_{timestamp}.md"
    md_path = os.path.join(output_dir, md_filename)
    
    # 打开PDF文件
    doc = fitz.open(pdf_path)
    md_content = f"# {sanitized_name}\n\n"  # 添加标题
    md_content += f"> 转换自: {os.path.basename(pdf_path)}\n"
    md_content += f"> 转换时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    # 遍历每一页
    for page_num, page in enumerate(doc, start=1):
        md_content += f"## 第 {page_num} 页\n\n"
        
        # 提取文本内容
        text = page.get_text()
        if text.strip():
            # 基本文本格式化
            formatted_text = re.sub(r'\n{3,}', '\n\n', text)  # 减少多余空行
            md_content += formatted_text + "\n\n"
        
        # 提取图片(如果不需要文本可忽略)
        if not text_only:
            img_list = page.get_images(full=True)
            for img_index, img_info in enumerate(img_list):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                img_bytes = base_image["image"]
                img_ext = base_image["ext"]
                
                # 保存图片
                img_name = f"page_{page_num}_img_{img_index}.{img_ext}"
                img_path = os.path.join(img_abs_dir, img_name)
                with open(img_path, "wb") as img_file:
                    img_file.write(img_bytes)
                
                # 添加Markdown图片引用
                relative_img_path = os.path.join(img_dir, img_name)
                md_content += f"![图{page_num}-{img_index}]({relative_img_path})\n\n"
    
    # 写入Markdown文件
    with open(md_path, "w", encoding="utf-8") as md_file:
        md_file.write(md_content)
    
    print(f"转换完成! Markdown文件已保存至: {md_path}")
    if not text_only:
        print(f"图片已保存至: {img_abs_dir}")
    
    return md_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF转Markdown工具")
    parser.add_argument("pdf_path", help="PDF文件路径")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("-i", "--imgdir", default="attachments", help="图片保存目录")
    parser.add_argument("-t", "--textonly", action="store_true", help="仅提取文本(忽略图片)")
    
    args = parser.parse_args()
    
    pdf_to_markdown(
        pdf_path=args.pdf_path,
        output_dir=args.output,
        img_dir=args.imgdir,
        text_only=args.textonly
    )
