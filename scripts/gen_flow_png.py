#!/usr/bin/env python3
"""生成 README 框架流程图 PNG（docs/flow.png）。

逻辑坐标画一遍，再 2x 渲染保清晰。可反复运行迭代。
"""
from __future__ import annotations

from PIL import Image, ImageDraw

FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
S = 2                       # 渲染倍率
W, H = 1840, 552

# 逻辑坐标
CX = [104, 288, 472, 656, 840, 1024, 1208, 1392, 1576, 1760]
CY = 118
BOX_W, BOX_H = 158, 60

# 角色 → (fill, border, text)
ROLE = {
    "agent": ((238, 242, 255), (74, 111, 165), (30, 41, 59)),
    "gate": ((255, 247, 214), (204, 154, 6), (30, 41, 59)),
    "term": ((253, 226, 226), (168, 50, 50), (30, 41, 59)),
    "store": ((220, 245, 231), (30, 122, 70), (30, 41, 59)),
    "tier": ((244, 246, 248), (154, 165, 177), (75, 85, 99)),
}
ARROW = (71, 85, 105)
LABEL = (100, 116, 139)


def sc(*p):
    return tuple(v * S for v in p)


def main() -> None:
    img = Image.new("RGB", (W * S, H * S), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def f(size: int):
        from PIL import ImageFont
        return ImageFont.truetype(FONT_PATH, int(size * S))

    F_TITLE, F_SUB, F_E, F_BAND, F_CAP = f(16), f(12.5), f(13), f(16), f(12.5)

    def box(cx, cy, w, h, role, title, sub=""):
        fill, border, txt = ROLE[role]
        x0, y0 = cx - w / 2, cy - h / 2
        d.rounded_rectangle(sc(x0, y0, x0 + w, y0 + h), radius=10 * S, fill=fill, outline=border, width=2 * S)
        tw = d.textlength(title, font=F_TITLE)
        d.text(sc(cx - tw / 2, cy - 20 + (0 if sub else 6)), title, font=F_TITLE, fill=txt)
        if sub:
            sw = d.textlength(sub, font=F_SUB)
            d.text(sc(cx - sw / 2, cy + 6), sub, font=F_SUB, fill=txt)

    def diamond(cx, cy, hw, hh, role, title, sub=""):
        fill, border, txt = ROLE[role]
        pts = [(cx, cy - hh), (cx + hw, cy), (cx, cy + hh), (cx - hw, cy)]
        d.polygon([sc(*p) for p in pts], fill=fill, outline=border, width=2 * S)
        tw = d.textlength(title, font=F_SUB)
        d.text(sc(cx - tw / 2, cy - 13), title, font=F_SUB, fill=txt)
        if sub:
            sw = d.textlength(sub, font=f(10.5))
            d.text(sc(cx - sw / 2, cy + 3), sub, font=f(10.5), fill=txt)

    def arrow(x1, y1, x2, y2, color=ARROW, dash=False, head=8):
        if dash:
            import math
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy) or 1
            ux, uy = dx / length, dy / length
            seg, gap = 9, 6
            trav = 0.0
            while trav < length - head:
                a = trav
                b = min(trav + seg, length - head)
                d.line(sc(x1 + ux * a, y1 + uy * a, x1 + ux * b, y1 + uy * b), fill=color, width=2 * S)
                trav += seg + gap
        else:
            d.line(sc(x1, y1, x2, y2), fill=color, width=2 * S)
        # 箭头头
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        for s in (1, -1):
            ax = x2 - head * math.cos(ang - s * 0.5)
            ay = y2 - head * math.sin(ang - s * 0.5)
            d.line(sc(x2, y2, ax, ay), fill=color, width=2 * S)

    def elabel(x, y, text, font=F_E, color=LABEL):
        tw = d.textlength(text, font=font)
        d.text(sc(x - tw / 2, y), text, font=font, fill=color)

    # ---- 三层带 ----
    d.rounded_rectangle(sc(60, 40, 1780, 170), radius=14 * S, fill=(250, 251, 253), outline=(210, 218, 230), width=1 * S)
    d.text(sc(74, 47), "智能体编排层（LangGraph 状态机：重试 / 人工门 / 终态 / 检查点）", font=F_BAND, fill=ROLE["tier"][2])

    d.rounded_rectangle(sc(60, 256, 1780, 338), radius=14 * S, fill=ROLE["tier"][0], outline=ROLE["tier"][1], width=1 * S)
    d.text(sc(74, 263), "控制面 · VPS 常驻唯一入口", font=F_BAND, fill=ROLE["tier"][2])

    d.rounded_rectangle(sc(60, 362, 1780, 444), radius=14 * S, fill=ROLE["tier"][0], outline=ROLE["tier"][1], width=1 * S)
    d.text(sc(74, 369), "硬件网关 · Windows 实验室（按需上线）", font=F_BAND, fill=ROLE["tier"][2])

    # ---- 主链路节点 ----
    nodes = [
        ("Jira", "缺陷单", "agent"),
        ("ReproPlanner", "规划复现", "agent"),
        ("执行复现", "flash·capture·inject", "agent"),
        ("符号化", "backtrace→函数", "agent"),
        ("Diagnostician", "根因诊断", "agent"),
        ("Fixer", "产 patch·开 PR", "agent"),
    ]
    for i, (t, s, r) in enumerate(nodes):
        box(CX[i], CY, BOX_W, BOX_H, r, t, s)
    # 7 人工门（菱形）
    diamond(CX[6], CY, 56, 34, "gate", "人工门", "飞书审批·PR合并")
    # 8 9 10
    box(CX[7], CY, BOX_W, BOX_H, "agent", "复测", "rebuild·flash")
    box(CX[8], CY, BOX_W, BOX_H, "agent", "Summarizer", "总结")
    box(CX[9], CY, BOX_W, BOX_H, "store", "知识库", "RAG 召回·沉淀")

    # ---- 主链路箭头 + 数据流标签 ----
    edges = [
        (0, 1, "缺陷单"), (1, 2, "复现计划"), (2, 3, "串口 log"),
        (3, 4, "符号化 log"), (4, 5, "诊断"), (5, 6, "patch / PR"),
        (7, 8, "verdict=pass"), (8, 9, "case"),
    ]
    for a, b, lab in edges:
        x1 = CX[a] + BOX_W / 2
        x2 = (CX[b] - 56) if b == 6 else (CX[b] - BOX_W / 2)
        if a == 6:
            x1 = CX[6] + 56
        arrow(x1, CY, x2, CY)
        elabel((x1 + x2) / 2, CY - 30, lab)
    # gate -> 复测（7 -> 7th node index 7）通过
    arrow(CX[6] + 56, CY, CX[7] - BOX_W / 2, CY)
    elabel((CX[6] + CX[7]) / 2, CY - 30, "通过")

    # ---- 拒绝分支（gate 上方）----
    box(CX[6], 70, 176, 44, "term", "❌ rejected 终态", "")
    arrow(CX[6], 92, CX[6], CY - 34)
    elabel(CX[6] + 78, 86, "拒绝/超时")

    # ---- 失败重试回退（spine 下方）----
    arrow(CX[7], CY + BOX_H / 2, CX[7], 196)
    d.line(sc(CX[7], 196, CX[5], 196), fill=ARROW, width=2 * S)
    arrow(CX[5], 196, CX[5], CY + BOX_H / 2)
    elabel((CX[5] + CX[7]) / 2, 184, "复测失败·回退重试(≤max)")

    # ---- 知识库召回（虚线，回到 Diagnostician）----
    arrow(CX[9], CY + BOX_H / 2, CX[9], 224, dash=True)
    d.line(sc(CX[9], 224, CX[4], 224), fill=ARROW, width=2 * S)
    # dashed horizontal
    import math
    _dash_h(d, CX[4], CX[9], 224)
    arrow(CX[4], 224, CX[4], CY + BOX_H / 2, dash=True)
    elabel((CX[4] + CX[9]) / 2, 212, "知识库召回相似案例")

    # ---- 层间数据流 ----
    arrow(CX[2], CY + BOX_H / 2, CX[2], 256)            # 执行复现 -> 控制面
    elabel(CX[2] + 96, 200, "硬件请求(MCP)")
    arrow(980, 338, 980, 362)                            # 控制面 -> 硬件网关
    elabel(980 + 70, 344, "路由/排队")

    # ---- 控制面内部 ----
    box(520, 300, 230, 44, "store", "Registry", "注册·心跳·TTL·按板找网关")
    box(980, 300, 230, 44, "store", "离线队列", "网关离线入队·上线续跑")
    box(1440, 300, 250, 44, "store", "Dispatcher", "路由到在线网关")

    # ---- 硬件网关内部 ----
    box(620, 406, 300, 50, "agent", "M0 MCP server", "build·flash·serial·symbolize·relay")
    box(1180, 406, 240, 50, "agent", "ESP32-S3 + 继电器", "被测设备·物理动作")
    arrow(620 + 150, 406, 1180 - 120, 406)
    elabel((620 + 1180) / 2, 392, "USB / 串口")

    # ---- 图例 ----
    legend = [("智能体", "agent"), ("人工门", "gate"), ("终态", "term"), ("存储/服务", "store")]
    lx = 80
    for name, role in legend:
        fill, border, _ = ROLE[role]
        d.rounded_rectangle(sc(lx, 478, lx + 26, 502), radius=4 * S, fill=fill, outline=border, width=2 * S)
        d.text(sc(lx + 34, 480), name, font=F_CAP, fill=(71, 85, 105))
        lx += 150

    img.save("docs/flow.png")
    print("saved docs/flow.png", img.size)


def _dash_h(d, x1, x2, y):
    x = x1
    while x < x2:
        d.line(sc(x, y, min(x + 9, x2), y), fill=ARROW, width=2 * S)
        x += 15


if __name__ == "__main__":
    main()
