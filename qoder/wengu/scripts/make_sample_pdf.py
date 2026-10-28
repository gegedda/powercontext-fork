"""生成示例论文笔记 PDF（只用于准备样例语料，运行时不需要 reportlab）。

用法（Linux / openEuler）::

    pip install reportlab
    python scripts/make_sample_pdf.py sample_library/oceanbase-tpcc-notes.pdf

正文是公开论文《OceanBase: A 707 Million tpmC Distributed Relational Database System》
的阅读笔记，用来演示 PDF 解析与混合检索；不是论文原文。
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

TITLE = "OceanBase 论文精读笔记：707 万 tpmC 的分布式关系数据库"

SECTIONS: list[tuple[str, list[str]]] = [
    (
        "论文信息",
        [
            "论文：OceanBase: A 707 Million tpmC Distributed Relational Database System，PVLDB 2022。",
            "作者来自蚂蚁集团 OceanBase 团队。TPC-C 是 OLTP 基准，衡量每分钟新订单事务数（tpmC）。",
            "该论文报告在 TPC-C 上达到 7.07 亿 tpmC，所有业务数据存放在同一套分布式数据库中。",
            "关键结论：单机数据库的扩展上限可以通过「共享存储无关的多副本 Paxos 组 + 分区」突破。",
        ],
    ),
    (
        "架构要点",
        [
            "OceanBase 采用 shared-nothing 架构，每个分区（partition）是一个 Paxos 组，通常三副本。",
            "副本之间用 Paxos 协议同步 redo 日志，多数派持久化即可对外提供服务，保证 RPO=0。",
            "多副本中的 Leader 处理读写，Follower 参与投票与日志持久化；Leader 故障时自动重新选主。",
            "存储层使用 LSM-Tree 风格的基线数据 + 增量 memtable，合并（major freeze）把增量转成 SSTable。",
        ],
    ),
    (
        "事务与一致性",
        [
            "分布式事务使用两阶段提交（2PC）加全局时间戳服务（GTS），保证快照读的一致性。",
            "GTS 为每个事务分配提交版本号，读操作按照版本号获取一致性快照，实现多版本并发控制（MVCC）。",
            "跨机房的强一致通过 Paxos 多数派实现；同城三机房部署时，任一机房故障不丢数据。",
            "租户（tenant）是资源隔离单位，多个租户共享一套集群，CPU 与内存按租户配额调度。",
        ],
    ),
    (
        "对学习的启发",
        [
            "把「共识协议 + 日志复制 + 多版本」串起来看，才能理解分布式数据库为什么能同时做到高可用与强一致。",
            "benchmark 数字的解读要看前提：tpmC、响应时间约束、数据量与硬件配置必须一起报告。",
            "复习时优先掌握三个因果链：Paxos 多数派 -> 不丢数据；GTS 版本号 -> 快照隔离；LSM 合并 -> 写放大。",
        ],
    ),
]


def build(path: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    title_style = ParagraphStyle("title", fontName="STSong-Light", fontSize=17, leading=24, spaceAfter=10)
    heading_style = ParagraphStyle("heading", fontName="STSong-Light", fontSize=13, leading=20, spaceBefore=8, spaceAfter=4)
    body_style = ParagraphStyle("body", fontName="STSong-Light", fontSize=10.5, leading=17)

    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=TITLE,
    )
    story = [Paragraph(TITLE, title_style), Spacer(1, 6)]
    for heading, paragraphs in SECTIONS:
        story.append(Paragraph(heading, heading_style))
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph, body_style))
            story.append(Spacer(1, 3))
        story.append(Spacer(1, 6))
    document.build(story)


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "oceanbase-tpcc-notes.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    build(target)
    print(f"wrote {target} ({target.stat().st_size} bytes)")
