#!/usr/bin/env python3
"""Generate evidence-linked base-resume drafts from the reviewed master profile."""
from __future__ import annotations
import json
from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = json.loads((ROOT / "config" / "settings.local.json").read_text(encoding="utf-8")) if (ROOT / "config" / "settings.local.json").exists() else {}
OUT = ROOT / "resumes" / "base"

COMMON = {
 "education": SETTINGS.get("candidate", {}).get("education_line", "<UNIVERSITY> — <DEGREE>, <DATES>."),
 "header": "<NAME> | <LOCATION> | github.com/<you>",
}
RESUMES = {
 "example_agent": {"title":"Example AI Agent Base Resume", "summary":"Synthetic template resume showing the evidence-gated base-resume format. All bullets below are placeholders in the same shape as real, fact-linked bullets.", "skills":"Python, Git", "bullets":[("Example Agent Project", "Built a local agent workflow with tool wiring, written definitions of done and human review gates; every claim below links to a fact ID.", "project_example")]},
}

def write_md(key, data):
    lines=[f"# {COMMON['header']}", "", f"## {data['title']}", "", "## Summary", data['summary'], "", "## Education", COMMON['education'], "<!-- evidence: education_primary -->", "", "## Selected Evidence-Linked Projects"]
    provenance=[]
    for i,(heading, bullet, fact) in enumerate(data['bullets'],1):
        bullet_id=f"{key}-bullet-{i}"; lines += [f"### {heading}", f"- {bullet}", f"<!-- evidence: {fact}; bullet_id: {bullet_id} -->", ""]
        provenance.append({"bullet_id":bullet_id,"fact_id":fact,"text":bullet})
    lines += ["## Skills", data['skills'], "", "## Review notice", "This is a base-resume draft. It excludes unverified numbers, production claims and unresolved authorship details."]
    OUT.mkdir(parents=True,exist_ok=True); (OUT/f"{key}.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    (OUT/f"{key}.provenance.json").write_text(json.dumps({"resume":key,"bullets":provenance},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def style_run(run, size=None, bold=None, color=None):
    run.font.name="Calibri"; run._element.rPr.rFonts.set(qn("w:ascii"),"Calibri"); run._element.rPr.rFonts.set(qn("w:hAnsi"),"Calibri")
    if size: run.font.size=Pt(size)
    if bold is not None: run.bold=bold
    if color: run.font.color.rgb=RGBColor(*color)

def export_docx(key, data):
    doc=Document(); section=doc.sections[0]; section.top_margin=section.bottom_margin=section.left_margin=section.right_margin=Inches(1)
    normal=doc.styles['Normal']; normal.font.name='Calibri'; normal._element.rPr.rFonts.set(qn('w:ascii'),'Calibri'); normal.font.size=Pt(11); normal.paragraph_format.space_after=Pt(6); normal.paragraph_format.line_spacing=1.1
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run('<NAME>'); style_run(r,16,True,(46,116,181)); p.paragraph_format.space_after=Pt(2)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run('<LOCATION> | github.com/<you>'); style_run(r,9,False,(80,80,80)); p.paragraph_format.space_after=Pt(10)
    for title, body in [('PROFILE',data['summary']),('EDUCATION',COMMON['education'])]:
        h=doc.add_paragraph(); r=h.add_run(title); style_run(r,12,True,(46,116,181)); h.paragraph_format.space_before=Pt(8); h.paragraph_format.space_after=Pt(4)
        doc.add_paragraph(body)
    h=doc.add_paragraph(); r=h.add_run('SELECTED PROJECTS'); style_run(r,12,True,(46,116,181)); h.paragraph_format.space_before=Pt(8); h.paragraph_format.space_after=Pt(4)
    for heading,bullet,fact in data['bullets']:
        p=doc.add_paragraph(); r=p.add_run(heading); style_run(r,11,True); p.paragraph_format.space_after=Pt(2)
        p=doc.add_paragraph(style='List Bullet'); p.add_run(bullet); p.paragraph_format.space_after=Pt(4)
        p=doc.add_paragraph(); r=p.add_run(f'Evidence: {fact}'); style_run(r,8,False,(100,100,100)); p.paragraph_format.space_after=Pt(4)
    h=doc.add_paragraph(); r=h.add_run('SKILLS'); style_run(r,12,True,(46,116,181)); h.paragraph_format.space_before=Pt(8); h.paragraph_format.space_after=Pt(4); doc.add_paragraph(data['skills'])
    path=OUT/f'{key}.docx'; doc.save(path); print(path)

def main():
    for key,data in RESUMES.items(): write_md(key,data)
    export_docx('ai_agent',RESUMES['ai_agent'])
if __name__=='__main__': main()
