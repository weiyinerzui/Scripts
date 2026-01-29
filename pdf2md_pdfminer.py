#!/usr/bin/env python3
import os, re, sys, json
from pathlib import Path
import fitz   # PyMuPDF
from pdfminer.high_level import extract_text
from tqdm import tqdm

def sanitize(name: str) -> str:
    return re.sub(r'[^-_0-9A-Za-z\u4e00-\u9fff]', '_', name)

def pdf_to_markdown(pdf_path: Path, out_dir: Path):
    pdf_path = Path(pdf_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 文字
    text = extract_text(str(pdf_path))
    md_lines = [line.rstrip() for line in text.splitlines() if line.strip()]

    # 2. 图片
    attach_dir = out_dir / "attachments"
    attach_dir.mkdir(exist_ok=True)
    doc = fitz.open(pdf_path)

    img_refs = []
    for page_idx in range(len(doc)):
        for img_idx, img in enumerate(doc.get_page_images(page_idx)):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha < 4:           # GRAY or RGB
                pix.save(attach_dir / f"{page_idx+1}_{img_idx+1}.png")
            else:                               # CMYK → RGB
                pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(attach_dir / f"{page_idx+1}_{img_idx+1}.png")
            img_refs.append(
                f"\n![图 {page_idx+1}-{img_idx+1}](attachments/{page_idx+1}_{img_idx+1}.png)\n"
            )

    # 3. 合并
    md_file = out_dir / f"{sanitize(pdf_path.stem)}.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("\n\n".join(md_lines))
        f.write("\n")
        f.writelines(img_refs)

    print(f"完成：{md_file}  共提取 {len(img_refs)} 张图片")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python pdf2md.py xxx.pdf [输出目录]")
        sys.exit(1)
    pdf_file = sys.argv[1]
    out_folder = sys.argv[2] if len(sys.argv) > 2 else Path(pdf_file).stem
    pdf_to_markdown(pdf_file, out_folder)