"""智能体：ReproPlanner（复现规划）、Diagnostician（log 诊断）。

只负责理解+决策+生成（结构化输出），绝不直接执行；执行由 pipeline 经 MCP client 完成。
"""
