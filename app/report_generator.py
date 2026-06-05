import uuid
import random
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import pandas as pd
import numpy as np
from sqlalchemy import func, and_

from app import logger, get_db_session
from app.models import (
    DailyReport, LiveSession, Order, LiveProduct, Product,
    RestockAlert, QualityAlert, Promotion, Anchor
)
from app.analytics_engine import AnalyticsEngine
from config import settings, EXPORT_DIR, CHART_DIR

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "SimHei"]
    plt.rcParams["axes.unicode_minus"] = False
    MATPLOTLIB_AVAILABLE = True
except Exception as e:
    logger.warning(f"matplotlib不可用，图表生成将被跳过: {e}")
    MATPLOTLIB_AVAILABLE = False

try:
    import reportlab
    REPORTLAB_AVAILABLE = True
except Exception as e:
    logger.warning(f"reportlab不可用，PDF生成将被跳过: {e}")
    REPORTLAB_AVAILABLE = False


class ChartGenerator:
    def __init__(self, report_date: date):
        self.report_date = report_date
        self.chart_dir = CHART_DIR
        self.chart_dir.mkdir(parents=True, exist_ok=True)

    def _filename(self, name: str) -> str:
        return f"{self.report_date.strftime('%Y%m%d')}_{name}.png"

    def _safe_plot(self, plot_fn, *args, **kwargs):
        if not MATPLOTLIB_AVAILABLE:
            return ""
        try:
            return plot_fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"图表生成失败: {e}")
            return ""

    def generate_gmv_trend_chart(self, df_trend: pd.DataFrame) -> str:
        if df_trend.empty:
            return ""
        return self._safe_plot(self._gmv_trend_impl, df_trend)

    def _gmv_trend_impl(self, df_trend):
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(
            df_trend["date"].astype(str),
            df_trend["gmv"],
            marker="o",
            linewidth=2,
            color="#FF6B6B",
        )
        ax.fill_between(
            df_trend["date"].astype(str),
            df_trend["gmv"],
            alpha=0.3,
            color="#FF6B6B",
        )
        ax.set_title(f"GMV 近30天趋势 ({self.report_date})", fontsize=14, fontweight="bold")
        ax.set_xlabel("日期")
        ax.set_ylabel("GMV (元)")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(True, alpha=0.3)
        for i, v in enumerate(df_trend["gmv"]):
            if i % 3 == 0:
                ax.annotate(f"{int(v/10000)}万", (i, v), textcoords="offset points", xytext=(0, 8), ha="center")
        plt.tight_layout()
        path = self.chart_dir / self._filename("gmv_trend")
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def generate_platform_pie_chart(self, df_platform: pd.DataFrame) -> str:
        if df_platform.empty:
            return ""
        return self._safe_plot(self._platform_pie_impl, df_platform)

    def _platform_pie_impl(self, df_platform):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7"]
        ax1.pie(
            df_platform["gmv"],
            labels=df_platform["platform"],
            autopct="%1.1f%%",
            colors=colors[: len(df_platform)],
            startangle=90,
        )
        ax1.set_title("各平台 GMV 占比", fontsize=12, fontweight="bold")
        x_pos = range(len(df_platform))
        bars = ax2.bar(x_pos, df_platform["roi"].values, color=colors[: len(df_platform)], alpha=0.85)
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels(df_platform["platform"].values, rotation=45)
        ax2.set_title("各平台 ROI 对比", fontsize=12, fontweight="bold")
        ax2.set_ylabel("ROI")
        ax2.axhline(y=1.0, color="red", linestyle="--", alpha=0.5, label="ROI=1 盈亏线")
        ax2.legend()
        for bar in bars:
            height = bar.get_height()
            ax2.annotate(f"{height:.2f}", (bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points", ha="center")
        plt.tight_layout()
        path = self.chart_dir / self._filename("platform_pie")
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def generate_top_anchors_chart(self, df_anchors: pd.DataFrame) -> str:
        if df_anchors.empty:
            return ""
        return self._safe_plot(self._top_anchors_impl, df_anchors)

    def _top_anchors_impl(self, df_anchors):
        df = df_anchors.head(10).copy()
        fig, ax = plt.subplots(figsize=(12, 6))
        colors = plt.cm.RdYlGn(np.linspace(0.2, 0.8, len(df)))
        bars = ax.barh(range(len(df)), df["gmv"].values, color=colors)
        ax.set_yticks(range(len(df)))
        ax.set_yticklabels(df["anchor_name"].values)
        ax.invert_yaxis()
        ax.set_xlabel("GMV (元)")
        ax.set_title("TOP 10 主播 GMV 排行", fontsize=14, fontweight="bold")
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.annotate(f"¥{int(width):,}", (width, bar.get_y() + bar.get_height() / 2),
                       xytext=(5, 0), textcoords="offset points", va="center")
        plt.tight_layout()
        path = self.chart_dir / self._filename("top_anchors")
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return str(path)

    def generate_product_top10_chart(self, products: List[Dict]) -> str:
        if not products:
            return ""
        return self._safe_plot(self._product_top10_impl, products)

    def _product_top10_impl(self, products):
        names = [p["name"][:10] for p in products[:10]]
        amounts = [p["amount"] for p in products[:10]]
        rates = [p["sell_out_rate"] * 100 for p in products[:10]]
        fig, ax1 = plt.subplots(figsize=(12, 5))
        x = range(len(names))
        bars = ax1.bar(x, amounts, color="#4ECDC4", alpha=0.8, label="销售额")
        ax1.set_xlabel("商品")
        ax1.set_ylabel("销售额 (元)", color="#4ECDC4")
        ax1.tick_params(axis="y", labelcolor="#4ECDC4")
        ax1.set_xticks(x)
        ax1.set_xticklabels(names, rotation=45, ha="right")
        ax2 = ax1.twinx()
        ax2.plot(x, rates, marker="s", color="#FF6B6B", linewidth=2, label="售罄率")
        ax2.set_ylabel("售罄率 (%)", color="#FF6B6B")
        ax2.tick_params(axis="y", labelcolor="#FF6B6B")
        ax2.set_ylim(0, 100)
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        ax1.set_title("TOP 10 热销商品", fontsize=14, fontweight="bold")
        plt.tight_layout()
        path = self.chart_dir / self._filename("top_products")
        fig.savefig(path, dpi=100, bbox_inches="tight")
        plt.close(fig)
        return str(path)


class ExcelExporter:
    def __init__(self, report_date: date):
        self.report_date = report_date

    def export_report(self, report_data: Dict) -> str:
        path = EXPORT_DIR / f"运营日报_{self.report_date.strftime('%Y%m%d')}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary_df = pd.DataFrame([{
                "报告日期": self.report_date.strftime("%Y-%m-%d"),
                "总GMV(元)": report_data["total_gmv"],
                "总订单数": report_data["total_orders"],
                "总流量成本(元)": report_data["total_traffic_cost"],
                "总利润(元)": report_data["total_profit"],
                "退货金额(元)": report_data["total_return_amount"],
                "综合ROI": report_data["overall_roi"],
                "预警数量": report_data["alerts_count"],
                "进行中促销": report_data["promotions_active"],
            }])
            summary_df.to_excel(writer, sheet_name="概览", index=False)

            if report_data["platform_summary"]:
                pd.DataFrame(report_data["platform_summary"]).to_excel(
                    writer, sheet_name="平台汇总", index=False
                )

            if report_data["anchor_summary"]:
                pd.DataFrame(report_data["anchor_summary"]).to_excel(
                    writer, sheet_name="主播排行", index=False
                )

            if report_data["product_top10"]:
                pd.DataFrame(report_data["product_top10"]).to_excel(
                    writer, sheet_name="热销商品", index=False
                )

            if report_data["gmv_trend_30d"]:
                pd.DataFrame(report_data["gmv_trend_30d"]).to_excel(
                    writer, sheet_name="GMV趋势", index=False
                )

        return str(path)


class PDFExporter:
    _font_registered = False
    _font_name = "Helvetica"

    def __init__(self, report_date: date):
        self.report_date = report_date
        if REPORTLAB_AVAILABLE:
            self._ensure_font()

    @classmethod
    def _ensure_font(cls):
        if cls._font_registered:
            return
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            font_paths = [
                ("/System/Library/Fonts/PingFang.ttc", 0),
                ("/Library/Fonts/Arial Unicode.ttf", None),
                ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
            ]
            import os
            for path, subfont in font_paths:
                try:
                    if os.path.exists(path):
                        if subfont is not None:
                            pdfmetrics.registerFont(TTFont("Chinese", path, subfontIndex=subfont))
                        else:
                            pdfmetrics.registerFont(TTFont("Chinese", path))
                        cls._font_name = "Chinese"
                        break
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            cls._font_registered = True

    def export_report(self, report_data: Dict, charts: Dict[str, str]) -> str:
        if not REPORTLAB_AVAILABLE:
            return ""
        try:
            return self._export_impl(report_data, charts)
        except Exception as e:
            logger.warning(f"PDF导出失败: {e}")
            return ""

    def _export_impl(self, report_data: Dict, charts: Dict[str, str]) -> str:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
        )

        font_name = self._font_name

        path = EXPORT_DIR / f"运营日报_{self.report_date.strftime('%Y%m%d')}.pdf"

        doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm,
                                topMargin=15 * mm, bottomMargin=15 * mm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "title", parent=styles["Title"], fontName=font_name, fontSize=20, spaceAfter=12
        )
        h2_style = ParagraphStyle(
            "h2", parent=styles["Heading2"], fontName=font_name, fontSize=14, spaceAfter=8
        )
        normal_style = ParagraphStyle(
            "normal", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=16
        )

        story = []
        story.append(Paragraph(f"直播运营日报 - {self.report_date.strftime('%Y年%m月%d日')}", title_style))
        story.append(Paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", normal_style))
        story.append(Spacer(1, 10 * mm))

        story.append(Paragraph("一、核心指标概览", h2_style))
        summary_data = [
            ["指标", "数值"],
            ["总GMV", f"¥{report_data['total_gmv']:,.2f}"],
            ["总订单数", f"{report_data['total_orders']:,}"],
            ["总流量成本", f"¥{report_data['total_traffic_cost']:,.2f}"],
            ["总利润", f"¥{report_data['total_profit']:,.2f}"],
            ["退货金额", f"¥{report_data['total_return_amount']:,.2f}"],
            ["综合ROI", f"{report_data['overall_roi']:.4f}"],
            ["预警数量", str(report_data["alerts_count"])],
            ["进行中促销", str(report_data["promotions_active"])],
        ]
        t = Table(summary_data, colWidths=[80 * mm, 80 * mm])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4ECDC4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ]))
        story.append(t)
        story.append(Spacer(1, 8 * mm))

        for chart_key, chart_title in [
            ("gmv_trend", "二、GMV 近30天趋势"),
            ("platform", "三、各平台数据分析"),
            ("anchors", "四、TOP 10 主播排行"),
            ("products", "五、热销商品分析"),
        ]:
            chart_path = charts.get(chart_key)
            if chart_path and Path(chart_path).exists():
                story.append(Paragraph(chart_title, h2_style))
                try:
                    img = Image(chart_path, width=170 * mm, height=70 * mm)
                    story.append(img)
                except Exception:
                    pass
                story.append(Spacer(1, 5 * mm))

        if report_data["platform_summary"]:
            story.append(PageBreak())
            story.append(Paragraph("六、平台详细数据", h2_style))
            plat = report_data["platform_summary"]
            if isinstance(plat, dict):
                plat_list = [{**{"平台": k}, **v} for k, v in plat.items()]
            else:
                plat_list = plat
            if plat_list:
                headers = list(plat_list[0].keys())
                table_data = [headers] + [[str(row.get(h, "")) for h in headers] for row in plat_list]
                pt = Table(table_data, repeatRows=1)
                pt.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FF6B6B")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ]))
                story.append(pt)

        doc.build(story)
        return str(path)


class DailyReportGenerator:
    def generate(self, target_date: Optional[date] = None) -> Optional[Dict]:
        if not target_date:
            target_date = date.today()

        logger.info(f"开始生成 {target_date} 运营日报...")

        df_platform = AnalyticsEngine.get_platform_summary(target_date)
        df_anchors = AnalyticsEngine.get_anchor_ranking(target_date)
        df_trend_30d = AnalyticsEngine.get_gmv_trend(30)
        df_trend_7d = df_trend_30d.tail(7).copy()

        total_gmv = float(df_platform["gmv"].sum()) if not df_platform.empty else 0.0
        total_orders = int(df_platform["orders"].sum()) if not df_platform.empty else 0
        total_traffic_cost = float(df_platform["traffic_cost"].sum()) if not df_platform.empty else 0.0
        total_profit = float(df_platform["profit"].sum()) if not df_platform.empty else 0.0

        db = get_db_session()
        try:
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date, datetime.max.time())
            total_return_amount = (
                db.query(func.coalesce(func.sum(Order.paid_amount), 0.0))
                .filter(and_(Order.status == "returned", Order.order_time >= start, Order.order_time <= end))
                .scalar() or 0.0
            )

            alerts_count = (
                db.query(RestockAlert).filter(RestockAlert.created_at >= start, RestockAlert.created_at <= end).count()
                + db.query(QualityAlert).filter(QualityAlert.created_at >= start, QualityAlert.created_at <= end).count()
            )

            promotions_active = db.query(Promotion).filter(Promotion.status == "active").count()

            top_products = self._get_top_products(db, start, end)
        finally:
            db.close()

        overall_roi = round(total_profit / max(total_traffic_cost, 0.0001), 4)

        platform_summary = []
        if not df_platform.empty:
            platform_summary = df_platform.to_dict(orient="records")

        anchor_summary = []
        if not df_anchors.empty:
            anchor_summary = df_anchors.to_dict(orient="records")

        report_data = {
            "report_date": target_date,
            "total_gmv": round(total_gmv, 2),
            "total_orders": total_orders,
            "total_traffic_cost": round(total_traffic_cost, 2),
            "total_profit": round(total_profit, 2),
            "total_return_amount": round(float(total_return_amount), 2),
            "overall_roi": overall_roi,
            "platform_summary": platform_summary,
            "anchor_summary": anchor_summary,
            "product_top10": top_products,
            "gmv_trend_7d": df_trend_7d.to_dict(orient="records") if not df_trend_7d.empty else [],
            "gmv_trend_30d": df_trend_30d.to_dict(orient="records") if not df_trend_30d.empty else [],
            "alerts_count": alerts_count,
            "promotions_active": promotions_active,
        }

        charts = {"gmv_trend": "", "platform": "", "anchors": "", "products": ""}
        if MATPLOTLIB_AVAILABLE:
            try:
                chart_gen = ChartGenerator(target_date)
                charts["gmv_trend"] = chart_gen.generate_gmv_trend_chart(df_trend_30d)
                charts["platform"] = chart_gen.generate_platform_pie_chart(df_platform)
                charts["anchors"] = chart_gen.generate_top_anchors_chart(df_anchors)
                charts["products"] = chart_gen.generate_product_top10_chart(top_products)
            except Exception as e:
                logger.warning(f"图表生成已跳过: {e}")

        excel_exporter = ExcelExporter(target_date)
        excel_path = excel_exporter.export_report(report_data)

        pdf_path = ""
        if REPORTLAB_AVAILABLE:
            try:
                pdf_exporter = PDFExporter(target_date)
                pdf_path = pdf_exporter.export_report(report_data, charts)
            except Exception as e:
                logger.warning(f"PDF生成已跳过: {e}")

        db = get_db_session()
        try:
            existing = db.query(DailyReport).filter(DailyReport.report_date == target_date).first()
            if existing:
                db.delete(existing)
                db.flush()

            report = DailyReport(
                report_id=f"RPT_{uuid.uuid4().hex[:12]}",
                report_date=target_date,
                total_gmv=report_data["total_gmv"],
                total_orders=report_data["total_orders"],
                total_traffic_cost=report_data["total_traffic_cost"],
                total_profit=report_data["total_profit"],
                total_return_amount=report_data["total_return_amount"],
                overall_roi=report_data["overall_roi"],
                platform_summary=report_data["platform_summary"],
                anchor_summary=report_data["anchor_summary"],
                product_top10=report_data["product_top10"],
                gmv_trend_7d=report_data["gmv_trend_7d"],
                gmv_trend_30d=report_data["gmv_trend_30d"],
                alerts_count=report_data["alerts_count"],
                promotions_active=report_data["promotions_active"],
                pdf_path=pdf_path,
                excel_path=excel_path,
            )
            db.add(report)
            db.commit()
            logger.info(f"运营日报生成成功: PDF={pdf_path}, Excel={excel_path}")

            return {
                "report_id": report.report_id,
                "report_date": str(target_date),
                "pdf_path": pdf_path,
                "excel_path": excel_path,
                **report_data,
            }
        except Exception as e:
            logger.error(f"保存日报失败: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def _get_top_products(self, db, start: datetime, end: datetime) -> List[Dict]:
        results = (
            db.query(
                Order.product_sku,
                func.sum(Order.paid_amount).label("total_amount"),
                func.sum(Order.quantity).label("total_qty"),
            )
            .filter(
                and_(
                    Order.status.in_(["paid", "shipped", "completed"]),
                    Order.order_time >= start,
                    Order.order_time <= end,
                )
            )
            .group_by(Order.product_sku)
            .order_by(func.sum(Order.paid_amount).desc())
            .limit(10)
            .all()
        )
        products = []
        for sku, amount, qty in results:
            p = db.query(Product).filter(Product.sku == sku).first()
            if p:
                sell_out = (
                    1 - (p.current_stock / p.original_stock) if p.original_stock > 0 else 0
                )
                products.append({
                    "sku": sku,
                    "name": p.name,
                    "category": p.category,
                    "amount": float(amount or 0),
                    "quantity": int(qty or 0),
                    "sell_out_rate": round(sell_out, 4),
                })
        return products

    def get_report(self, target_date: date) -> Optional[Dict]:
        db = get_db_session()
        try:
            report = db.query(DailyReport).filter(DailyReport.report_date == target_date).first()
            if not report:
                return None
            return {
                "report_id": report.report_id,
                "report_date": str(report.report_date),
                "total_gmv": report.total_gmv,
                "total_orders": report.total_orders,
                "total_profit": report.total_profit,
                "overall_roi": report.overall_roi,
                "pdf_path": report.pdf_path,
                "excel_path": report.excel_path,
                "generated_at": report.generated_at,
            }
        finally:
            db.close()


daily_report_generator = DailyReportGenerator()
