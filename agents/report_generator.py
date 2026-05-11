"""
agents/report_generator.py
--------------------------
Report Generator — creates PDF, HTML, and JSON screening reports.
Uses ReportLab for PDF and Jinja2-like HTML templating.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from schemas.pydantic_models import CandidateScore, JDRequirements

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# JSON Report
# ──────────────────────────────────────────────

def generate_json_report(
    ranked: List[Tuple[int, CandidateScore, Dict]],
    jd: JDRequirements,
    llm_summary: Optional[Dict] = None,
) -> Path:
    """Generate a JSON report and return its path."""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "job_title": jd.role_title,
        "total_candidates": len(ranked),
        "executive_summary": llm_summary.get("executive_summary", "") if llm_summary else "",
        "hiring_notes": llm_summary.get("hiring_notes", "") if llm_summary else "",
        "next_steps": llm_summary.get("next_steps", []) if llm_summary else [],
        "candidates": [],
    }

    for rank, score, override in ranked:
        eff_score = override.get("new_score", score.total_weighted_score)
        entry = {
            "rank": rank,
            "name": score.candidate_name,
            "effective_score": eff_score,
            "llm_score": score.total_weighted_score,
            "recommendation": score.recommendation,
            "strengths": score.strengths,
            "weaknesses": score.weaknesses,
            "semantic_similarity": score.semantic_similarity,
            "has_override": bool(override),
            "override_reason": override.get("reason", ""),
            "dimension_scores": {
                d.dimension: d.raw_score
                for d in score.dimension_scores
            },
        }
        report["candidates"].append(entry)

    out_path = REPORTS_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info(f"[Report] JSON report saved: {out_path}")
    return out_path


# ──────────────────────────────────────────────
# HTML Report
# ──────────────────────────────────────────────

def generate_html_report(
    ranked: List[Tuple[int, CandidateScore, Dict]],
    jd: JDRequirements,
    llm_summary: Optional[Dict] = None,
) -> Path:
    """Generate a styled HTML report."""
    rows = ""
    for rank, score, override in ranked:
        eff_score = override.get("new_score", score.total_weighted_score)
        rec = score.recommendation
        color_map = {"Strong Yes": "#16a34a", "Yes": "#2563eb", "Maybe": "#d97706", "No": "#dc2626"}
        badge_color = color_map.get(rec, "#6b7280")
        override_badge = (
            f'<span style="background:#7c3aed;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;margin-left:6px;">Overridden</span>'
            if override else ""
        )
        strengths_html = "".join(f"<li>✅ {s}</li>" for s in score.strengths[:3])
        weaknesses_html = "".join(f"<li>⚠️ {w}</li>" for w in score.weaknesses[:3])

        dim_html = ""
        for d in score.dimension_scores:
            pct = d.raw_score / 10 * 100
            dim_html += f"""
            <div style="margin-bottom:4px;">
              <span style="font-size:12px;color:#6b7280;width:160px;display:inline-block;">{d.dimension.replace("_"," ").title()}</span>
              <div style="display:inline-block;background:#e5e7eb;border-radius:4px;width:140px;height:8px;vertical-align:middle;">
                <div style="background:#3b82f6;width:{pct:.0f}%;height:8px;border-radius:4px;"></div>
              </div>
              <span style="font-size:12px;margin-left:6px;">{d.raw_score:.1f}/10</span>
            </div>"""

        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
          <td style="padding:16px;font-weight:700;color:#1e40af;">#{rank}</td>
          <td style="padding:16px;">
            <div style="font-weight:600;font-size:15px;">{score.candidate_name}{override_badge}</div>
            <div style="margin-top:8px;">{dim_html}</div>
          </td>
          <td style="padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:800;color:#1e3a8a;">{eff_score:.1f}</div>
            <div style="font-size:11px;color:#6b7280;">/ 10</div>
          </td>
          <td style="padding:16px;">
            <span style="background:{badge_color};color:#fff;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;">{rec}</span>
          </td>
          <td style="padding:16px;">
            <ul style="margin:0;padding-left:16px;font-size:13px;">{strengths_html}</ul>
          </td>
          <td style="padding:16px;">
            <ul style="margin:0;padding-left:16px;font-size:13px;">{weaknesses_html}</ul>
          </td>
        </tr>"""

    summary_html = ""
    if llm_summary:
        summary_html = f"""
        <div style="background:#eff6ff;border-left:4px solid #3b82f6;padding:16px;margin-bottom:24px;border-radius:0 8px 8px 0;">
          <h3 style="margin:0 0 8px;color:#1e40af;">Executive Summary</h3>
          <p style="margin:0;color:#374151;">{llm_summary.get("executive_summary","")}</p>
        </div>
        <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:16px;margin-bottom:24px;border-radius:0 8px 8px 0;">
          <h3 style="margin:0 0 8px;color:#166534;">Hiring Notes</h3>
          <p style="margin:0;color:#374151;">{llm_summary.get("hiring_notes","")}</p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>HR Resume Screening Report — {jd.role_title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#f9fafb; color:#111827; margin:0; padding:32px; }}
    .container {{ max-width:1100px; margin:0 auto; background:#fff; border-radius:12px; box-shadow:0 4px 24px rgba(0,0,0,0.08); overflow:hidden; }}
    .header {{ background:linear-gradient(135deg,#1e3a8a,#3b82f6); color:#fff; padding:32px; }}
    .header h1 {{ margin:0 0 8px; font-size:28px; }}
    .header p {{ margin:0; opacity:0.85; font-size:14px; }}
    .body {{ padding:32px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th {{ background:#f3f4f6; padding:12px 16px; text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:0.05em; color:#6b7280; }}
  </style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📋 Resume Screening Report</h1>
    <p>Role: <strong>{jd.role_title}</strong> &nbsp;|&nbsp; Candidates: <strong>{len(ranked)}</strong> &nbsp;|&nbsp; Generated: {datetime.utcnow().strftime("%B %d, %Y %H:%M UTC")}</p>
  </div>
  <div class="body">
    {summary_html}
    <table>
      <thead>
        <tr>
          <th>Rank</th><th>Candidate</th><th>Score</th><th>Decision</th><th>Strengths</th><th>Weaknesses</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
</div>
</body>
</html>"""

    out_path = REPORTS_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"[Report] HTML report saved: {out_path}")
    return out_path


# ──────────────────────────────────────────────
# PDF Report via ReportLab
# ──────────────────────────────────────────────

def generate_pdf_report(
    ranked: List[Tuple[int, CandidateScore, Dict]],
    jd: JDRequirements,
    llm_summary: Optional[Dict] = None,
) -> Optional[Path]:
    """Generate a PDF report using ReportLab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )

        out_path = REPORTS_DIR / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
        doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle("Title", parent=styles["Heading1"],
                                     textColor=colors.HexColor("#1e3a8a"), fontSize=20, spaceAfter=6)
        story.append(Paragraph(f"Resume Screening Report", title_style))
        story.append(Paragraph(f"Role: {jd.role_title} | {datetime.utcnow().strftime('%B %d, %Y')}", styles["Normal"]))
        story.append(Spacer(1, 8*mm))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#3b82f6")))
        story.append(Spacer(1, 6*mm))

        # Summary
        if llm_summary and llm_summary.get("executive_summary"):
            story.append(Paragraph("Executive Summary", styles["Heading2"]))
            story.append(Paragraph(llm_summary["executive_summary"], styles["Normal"]))
            story.append(Spacer(1, 4*mm))

        # Candidate table
        story.append(Paragraph("Candidate Rankings", styles["Heading2"]))
        story.append(Spacer(1, 2*mm))

        table_data = [["#", "Name", "Score", "Decision", "Key Strength", "Key Weakness"]]
        for rank, score, override in ranked:
            eff_score = override.get("new_score", score.total_weighted_score)
            strength = score.strengths[0] if score.strengths else "—"
            weakness = score.weaknesses[0] if score.weaknesses else "—"
            name = score.candidate_name
            if override:
                name += " ★"
            table_data.append([
                str(rank), name, f"{eff_score:.1f}/10",
                score.recommendation, strength[:40], weakness[:40]
            ])

        col_widths = [15*mm, 45*mm, 20*mm, 22*mm, 45*mm, 45*mm]
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        story.append(Spacer(1, 6*mm))

        # Individual detail sections
        for rank, score, override in ranked[:5]:  # Top 5 detailed
            eff_score = override.get("new_score", score.total_weighted_score)
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb")))
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph(f"#{rank} — {score.candidate_name} ({eff_score:.1f}/10)", styles["Heading3"]))

            dim_lines = " | ".join(
                f"{d.dimension.replace('_',' ').title()}: {d.raw_score:.1f}"
                for d in score.dimension_scores
            )
            story.append(Paragraph(dim_lines, styles["Normal"]))

            strengths_text = "Strengths: " + "; ".join(score.strengths[:3])
            weaknesses_text = "Weaknesses: " + "; ".join(score.weaknesses[:3])
            story.append(Paragraph(strengths_text, styles["Normal"]))
            story.append(Paragraph(weaknesses_text, styles["Normal"]))
            if override:
                story.append(Paragraph(
                    f"⚠ Score overridden by HR: {override.get('reason','')}",
                    ParagraphStyle("override", parent=styles["Normal"], textColor=colors.HexColor("#7c3aed"))
                ))
            story.append(Spacer(1, 3*mm))

        doc.build(story)
        logger.info(f"[Report] PDF report saved: {out_path}")
        return out_path

    except Exception as e:
        logger.error(f"[Report] PDF generation failed: {e}")
        return None
