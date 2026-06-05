#!/usr/bin/env python3
"""独立的日报生成 Worker 进程

用于在隔离的子进程中执行图表生成和 PDF 导出，
彻底避免 matplotlib / reportlab 等 C 扩展库的段错误
拖垮主 FastAPI 进程。

用法:
    python3 workers/report_worker.py <report_date> <output_dir>

参数:
    report_date: 报表日期，格式 YYYY-MM-DD
    output_dir:  输出目录绝对路径

环境变量:
    DB_ENGINE, DATABASE_URL, POSTGRES_* 等数据库配置
"""

import sys
import os
import json
import traceback
from pathlib import Path
from datetime import datetime, date

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ["WORKER_MODE"] = "1"

from loguru import logger
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger.add(
    f"{LOG_DIR}/worker_{{time:YYYY-MM-DD}}.log",
    rotation="00:00",
    retention="14 days",
    compression="zip",
    level="DEBUG",
    encoding="utf-8",
)


def main() -> int:
    if len(sys.argv) < 3:
        print(json.dumps({
            "success": False,
            "error": "参数不足: python3 report_worker.py <report_date> <output_dir>"
        }, ensure_ascii=False))
        return 1

    report_date_str = sys.argv[1]
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        report_date = datetime.strptime(report_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(json.dumps({
            "success": False,
            "error": f"日期格式错误: {report_date_str}, 需要 YYYY-MM-DD"
        }, ensure_ascii=False))
        return 1

    result = {
        "success": False,
        "date": report_date_str,
        "output_dir": str(output_dir),
        "files": {},
        "errors": [],
    }

    try:
        from app import engine, Base, SessionLocal
        from app.models import (
            LiveSession, Order, Product, Anchor, RealtimeDataPoint,
        )
        from sqlalchemy import func
        import csv
        from datetime import timedelta

        db = SessionLocal()
        try:
            start_dt = datetime.combine(report_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            sessions = db.query(LiveSession).filter(
                LiveSession.start_time >= start_dt,
                LiveSession.start_time < end_dt,
            ).all()
            session_ids = [s.id for s in sessions]
            session_str_ids = [s.session_id for s in sessions]

            session_gmv_map = {}
            session_viewer_map = {}
            session_order_map = {}

            if session_str_ids:
                try:
                    order_stats = db.query(
                        Order.session_id,
                        func.count(Order.id).label("cnt"),
                        func.coalesce(func.sum(Order.paid_amount), 0).label("gmv"),
                    ).filter(
                        Order.session_id.in_(session_str_ids)
                    ).group_by(Order.session_id).all()
                    for sid, cnt, gmv in order_stats:
                        session_gmv_map[sid] = float(gmv or 0)
                        session_order_map[sid] = int(cnt or 0)
                except Exception as e:
                    result["errors"].append(f"订单聚合查询异常: {str(e)[:200]}")

                try:
                    viewer_stats = db.query(
                        RealtimeDataPoint.session_id,
                        func.coalesce(func.max(RealtimeDataPoint.viewer_count), 0).label("peak_viewers"),
                        func.coalesce(func.sum(RealtimeDataPoint.new_viewers), 0).label("total_new"),
                    ).filter(
                        RealtimeDataPoint.session_id.in_(session_str_ids)
                    ).group_by(RealtimeDataPoint.session_id).all()
                    for sid, peak, total_new in viewer_stats:
                        session_viewer_map[sid] = int(max(peak or 0, total_new or 0))
                except Exception as e:
                    result["errors"].append(f"实时数据聚合查询异常: {str(e)[:200]}")

            def _session_gmv(s: LiveSession) -> float:
                if s.total_gmv and s.total_gmv > 0:
                    return float(s.total_gmv)
                order_gmv = session_gmv_map.get(s.session_id, 0.0)
                if order_gmv > 0:
                    return order_gmv
                if s.estimated_gmv and s.estimated_gmv > 0:
                    return float(s.estimated_gmv)
                return 0.0

            def _session_viewers(s: LiveSession) -> int:
                if s.total_viewers and s.total_viewers > 0:
                    return int(s.total_viewers)
                rt = session_viewer_map.get(s.session_id, 0)
                if rt > 0:
                    return rt
                if s.estimated_traffic and s.estimated_traffic > 0:
                    return int(s.estimated_traffic)
                return 0

            def _session_orders(s: LiveSession) -> int:
                if s.total_orders and s.total_orders > 0:
                    return int(s.total_orders)
                return session_order_map.get(s.session_id, 0)

            total_gmv = sum(_session_gmv(s) for s in sessions)
            total_viewers = sum(_session_viewers(s) for s in sessions)
            total_orders = sum(_session_orders(s) for s in sessions)

            platform_stats = {}
            for s in sessions:
                if s.platform not in platform_stats:
                    platform_stats[s.platform] = {"gmv": 0, "sessions": 0}
                platform_stats[s.platform]["gmv"] += _session_gmv(s)
                platform_stats[s.platform]["sessions"] += 1

            anchor_stats = {}
            for s in sessions:
                anchor_name = s.anchor.name if s.anchor else "未知"
                key = (s.anchor_id, anchor_name)
                if key not in anchor_stats:
                    anchor_stats[key] = {"gmv": 0, "sessions": 0}
                anchor_stats[key]["gmv"] += _session_gmv(s)
                anchor_stats[key]["sessions"] += 1

            anchor_ranking = sorted(
                [{"name": k[1], "gmv": v["gmv"], "sessions": v["sessions"]}
                 for k, v in anchor_stats.items()],
                key=lambda x: x["gmv"], reverse=True
            )[:10]

            product_stats = {}
            if session_ids:
                session_str_ids = [s.session_id for s in sessions]
                products = db.query(
                    Order.product_sku, Product.name,
                    func.sum(Order.quantity).label("qty"),
                    func.sum(Order.paid_amount).label("amt")
                ).join(Product, Order.product_sku == Product.sku).filter(
                    Order.session_id.in_(session_str_ids)
                ).group_by(Order.product_sku, Product.name).all()
                for sku, pname, qty, amt in products:
                    product_stats[sku] = {"name": pname, "quantity": qty or 0, "amount": amt or 0}

            top_products = sorted(
                list(product_stats.values()), key=lambda x: x["amount"], reverse=True
            )[:10]

            summary = {
                "report_date": report_date_str,
                "total_sessions": len(sessions),
                "total_gmv": float(total_gmv),
                "total_viewers": int(total_viewers),
                "total_orders": int(total_orders),
                "avg_gmv_per_session": float(total_gmv) / len(sessions) if sessions else 0,
                "platform_stats": platform_stats,
                "anchor_ranking": anchor_ranking,
                "top_products": top_products,
            }

            summary_path = output_dir / f"daily_summary_{report_date_str}.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
            result["files"]["summary"] = str(summary_path)

            csv_path = output_dir / f"daily_report_{report_date_str}.csv"
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["指标", "数值"])
                writer.writerow(["直播场次", summary["total_sessions"]])
                writer.writerow(["总GMV", f"{summary['total_gmv']:.2f}"])
                writer.writerow(["总观看人数", summary["total_viewers"]])
                writer.writerow(["总订单数", summary["total_orders"]])
                writer.writerow(["场均GMV", f"{summary['avg_gmv_per_session']:.2f}"])
                writer.writerow([])
                writer.writerow(["平台名称", "GMV", "场次"])
                for p, st in platform_stats.items():
                    writer.writerow([p, f"{st['gmv']:.2f}", st["sessions"]])
                writer.writerow([])
                writer.writerow(["主播排名", "主播名称", "GMV", "场次"])
                for i, a in enumerate(anchor_ranking, 1):
                    writer.writerow([i, a["name"], f"{a['gmv']:.2f}", a["sessions"]])
                writer.writerow([])
                writer.writerow(["商品排名", "商品名称", "销量", "销售额"])
                for i, p in enumerate(top_products, 1):
                    writer.writerow([i, p["name"], p["quantity"], f"{p['amount']:.2f}"])
            result["files"]["csv"] = str(csv_path)

            generated_charts = []
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                from matplotlib import font_manager
                import numpy as np

                font_candidates = [
                    "/System/Library/Fonts/PingFang.ttc",
                    "/System/Library/Fonts/STHeiti Medium.ttc",
                    "/Library/Fonts/Arial Unicode.ttf",
                    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                    "C:/Windows/Fonts/msyh.ttc",
                ]
                font_path = None
                for fp in font_candidates:
                    if os.path.exists(fp):
                        font_path = fp
                        break
                if font_path:
                    font_prop = font_manager.FontProperties(fname=font_path)
                    plt.rcParams["font.family"] = font_prop.get_name()
                plt.rcParams["axes.unicode_minus"] = False

                if platform_stats:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    platforms = list(platform_stats.keys())
                    gmvs = [v["gmv"] for v in platform_stats.values()]
                    colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7"]
                    ax.pie(gmvs, labels=platforms, autopct="%1.1f%%",
                           startangle=90, colors=colors[:len(platforms)])
                    ax.set_title(f"各平台GMV占比 ({report_date_str})",
                                 fontproperties=font_prop if font_path else None)
                    pie_path = output_dir / f"platform_gmv_pie_{report_date_str}.png"
                    fig.savefig(pie_path, dpi=150, bbox_inches="tight")
                    plt.close(fig)
                    generated_charts.append(("platform_pie", str(pie_path)))

                if anchor_ranking:
                    fig, ax = plt.subplots(figsize=(12, 6))
                    names = [a["name"] for a in anchor_ranking]
                    gmvs = [a["gmv"] for a in anchor_ranking]
                    bars = ax.bar(range(len(names)), gmvs, color="#4ECDC4")
                    ax.set_xticks(range(len(names)))
                    ax.set_xticklabels(names, rotation=45, ha="right",
                                       fontproperties=font_prop if font_path else None)
                    ax.set_ylabel("GMV (元)", fontproperties=font_prop if font_path else None)
                    ax.set_title(f"主播GMV排行 Top10 ({report_date_str})",
                                 fontproperties=font_prop if font_path else None)
                    for bar, val in zip(bars, gmvs):
                        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                                f"{val/10000:.1f}万", ha="center", va="bottom", fontsize=9)
                    rank_path = output_dir / f"anchor_rank_{report_date_str}.png"
                    fig.tight_layout()
                    fig.savefig(rank_path, dpi=150)
                    plt.close(fig)
                    generated_charts.append(("anchor_rank", str(rank_path)))

                for key, path in generated_charts:
                    result["files"][key] = path

            except ImportError as e:
                result["errors"].append(f"matplotlib 未安装或加载失败，跳过图表生成: {e}")
            except Exception as e:
                result["errors"].append(f"图表生成异常 (非致命): {str(e)[:200]}")

            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.lib import colors
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
                )
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont

                pdf_path = output_dir / f"daily_report_{report_date_str}.pdf"
                doc = SimpleDocTemplate(
                    str(pdf_path), pagesize=A4,
                    rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
                )

                story = []
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle("CnTitle", parent=styles["Title"], fontSize=20)
                h2_style = ParagraphStyle("CnH2", parent=styles["Heading2"], fontSize=14)
                normal_style = ParagraphStyle("CnNormal", parent=styles["Normal"], fontSize=10)

                font_names = []
                font_candidates_pdf = [
                    ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
                    ("/System/Library/Fonts/STHeiti Medium.ttc", "STHeiti"),
                    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYi"),
                ]
                for fp, fn in font_candidates_pdf:
                    if os.path.exists(fp):
                        try:
                            pdfmetrics.registerFont(TTFont(fn, fp))
                            font_names.append(fn)
                        except Exception:
                            pass
                if font_names:
                    title_style.fontName = font_names[0]
                    h2_style.fontName = font_names[0]
                    normal_style.fontName = font_names[0]

                story.append(Paragraph(f"直播运营日报 - {report_date_str}", title_style))
                story.append(Spacer(1, 20))

                summary_data = [
                    ["关键指标", "数值"],
                    ["直播场次", str(summary["total_sessions"])],
                    ["总GMV", f"¥ {summary['total_gmv']:,.2f}"],
                    ["总观看人数", f"{summary['total_viewers']:,}"],
                    ["总订单数", str(summary["total_orders"])],
                    ["场均GMV", f"¥ {summary['avg_gmv_per_session']:,.2f}"],
                ]
                summary_tbl = Table(summary_data, colWidths=[180, 200])
                summary_tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4ECDC4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, -1), font_names[0] if font_names else "Helvetica"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ]))
                story.append(summary_tbl)
                story.append(Spacer(1, 20))

                if platform_stats:
                    story.append(Paragraph("各平台GMV分布", h2_style))
                    story.append(Spacer(1, 10))
                    plat_data = [["平台", "GMV", "场次"]]
                    for p, st in platform_stats.items():
                        plat_data.append([p, f"¥ {st['gmv']:,.2f}", str(st["sessions"])])
                    plat_tbl = Table(plat_data, colWidths=[140, 140, 100])
                    plat_tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#45B7D1")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                        ("FONTNAME", (0, 0), (-1, -1), font_names[0] if font_names else "Helvetica"),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ]))
                    story.append(plat_tbl)
                    story.append(Spacer(1, 15))

                if generated_charts:
                    for key, chart_path in generated_charts:
                        if os.path.exists(chart_path):
                            try:
                                img = Image(chart_path, width=480, height=280)
                                story.append(img)
                                story.append(Spacer(1, 10))
                            except Exception:
                                pass

                doc.build(story)
                result["files"]["pdf"] = str(pdf_path)

            except ImportError as e:
                result["errors"].append(f"reportlab 未安装或加载失败，跳过PDF生成: {e}")
            except Exception as e:
                result["errors"].append(f"PDF生成异常 (非致命): {str(e)[:200]}")

            db.close()

            result["success"] = True

        except Exception as inner_e:
            result["errors"].append(f"数据库查询异常: {str(inner_e)[:300]}")
            result["errors"].append(traceback.format_exc()[:500])
            try:
                db.close()
            except Exception:
                pass

    except Exception as outer_e:
        result["errors"].append(f"Worker顶层异常: {str(outer_e)[:300]}")
        result["errors"].append(traceback.format_exc()[:800])

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
