"""Prompt 模板集中地。

约定：
- 所有模板用 str.format 渲染，{placeholder} 必须出现在花括号里且不被转义。
- 中文 prompt 优先；英文 prompt 备一份给英文论文场景。
- 调用方负责传入真实变量，不要在这里写硬编码内容。
"""


# ---------- 单文档摘要（Day 3-7 的核心） ----------

SUMMARY_PROMPT_ZH = """你是学术论文摘要助手。请基于下面给出的论文片段，用中文写一份不超过 {max_words} 字的结构化摘要。

要求：
1. 用三段式：研究问题 / 方法 / 结论与意义。
2. 不要编造片段里没有的信息。
3. 保留关键术语的英文原词。

【论文片段】
{text}

【摘要】"""


SUMMARY_PROMPT_EN = """You are an academic paper summarization assistant.
Write a structured summary of the excerpt below in at most {max_words} words.
Use three sections: Problem / Method / Findings & Significance.
Do not fabricate information not present in the excerpt.

【Excerpt】
{text}

【Summary】"""


# ---------- 综述生成（Day 8-10 的核心，给多文档用） ----------

SURVEY_PROMPT_ZH = """你是学术综述助手。下面给出了多篇论文的摘要片段，请综合它们写一段不超过 {max_words} 字的中文综述。

要求：
1. 先用一句话点出这些论文共同关注的问题。
2. 列出主要方法/路线及代表论文（用片段前的 [编号] 引用）。
3. 总结结论异同，给出 1-2 个未来方向。
4. 严格基于片段，不要外推。

【论文片段】
{context}

【综述】"""


# ---------- RAG 问答 ----------

RAG_QA_SYSTEM = """你是一名严谨的学术论文问答助手。你的回答必须严格基于用户提供的参考资料。"""

RAG_QA_PROMPT_ZH = """请严格基于下面的【参考资料】回答【用户问题】。

规则：
1. 仅使用参考资料中明确出现的内容；不能外推或编造。
2. 引用处使用方括号编号，例如 [1]、[2]，并在回答末尾用「引用：[1][2]」列出。
3. 如果参考资料不足以回答，直接说"现有资料无法回答该问题"，不要猜测。
4. 回答用中文，简洁专业。如有需要，先简要分析问题再作答。

---
【少样本示例 1】

【参考资料】
[1] section=Introduction | page=1
SpatialClaw introduces a novel spatial action interface that enables VLMs to perform fine-grained robotic manipulation. Unlike prior works that rely on discretized action spaces, SpatialClaw uses continuous spatial representations grounded in the visual observation.

[2] section=Method | page=4
The core architecture consists of three components: (1) a spatial encoder that maps visual features to a continuous action manifold, (2) a grounding module that aligns language instructions with spatial coordinates, and (3) a trajectory decoder that outputs executable robot trajectories.

[3] section=Experiments | page=7
On the RLBench benchmark, SpatialClaw achieves 78.3% success rate across 18 tasks, outperforming PerAct (62.1%) and RVT (68.5%). The largest gains are observed on tasks requiring precise spatial reasoning, such as "open drawer" and "stack blocks".

【用户问题】
SpatialClaw 方法的核心创新是什么？效果如何？

【回答】
SpatialClaw 的核心创新在于用连续空间表示替代传统离散动作空间，让 VLM 能做精细的机器人操控 [1]。架构上包含三个关键组件：空间编码器（视觉特征→连续动作流形）、语言-空间坐标对齐模块、以及轨迹解码器 [2]。

效果方面，在 RLBench 的 18 个任务上达到 78.3% 成功率，显著超过 PerAct（62.1%）和 RVT（68.5%），在需要精确空间推理的任务（如开抽屉、堆方块）上提升最明显 [3]。

引用：[1][2][3]

---
【少样本示例 2】

【参考资料】
[1] section=Abstract | page=1
We propose a lightweight attention mechanism that reduces the quadratic complexity of standard self-attention to linear while maintaining comparable performance on NLP benchmarks.

[2] section=Results | page=5
On GLUE benchmark, our method scores 88.2 compared to 88.5 for standard attention, while reducing memory usage by 50%.

【用户问题】
这个方法在图像分类任务上的表现如何？

【回答】
现有资料无法回答该问题。参考资料仅涉及 NLP 任务（GLUE benchmark [2]），未提及任何图像分类实验结果。

---

【参考资料】
{context}

【用户问题】
{query}

【回答】"""


RAG_QA_PROMPT_EN = """Answer the user's question strictly based on the provided references.

Rules:
1. Use only information that is explicitly present in the references.
2. Cite sources inline with bracket numbers like [1], [2], and list them at the end.
3. If the references are insufficient, say so explicitly instead of guessing.
4. Keep the answer concise and professional. When helpful, briefly analyze the question before answering.

---
【Few-shot Example 1】

【References】
[1] section=Introduction | page=1
SpatialClaw introduces a novel spatial action interface that enables VLMs to perform fine-grained robotic manipulation. Unlike prior works that rely on discretized action spaces, SpatialClaw uses continuous spatial representations grounded in the visual observation.

[2] section=Method | page=4
The core architecture consists of three components: (1) a spatial encoder that maps visual features to a continuous action manifold, (2) a grounding module that aligns language instructions with spatial coordinates, and (3) a trajectory decoder that outputs executable robot trajectories.

[3] section=Experiments | page=7
On the RLBench benchmark, SpatialClaw achieves 78.3% success rate across 18 tasks, outperforming PerAct (62.1%) and RVT (68.5%).

【Question】
What is the main innovation of SpatialClaw and how well does it perform?

【Answer】
SpatialClaw's core innovation is using continuous spatial representations to replace traditional discretized action spaces, enabling VLMs to perform fine-grained robotic manipulation [1]. The architecture has three key components: a spatial encoder (visual features → continuous action manifold), a language-to-spatial-coordinate grounding module, and a trajectory decoder [2].

On RLBench, it achieves 78.3% success rate across 18 tasks, significantly outperforming PerAct (62.1%) and RVT (68.5%) [3].

References: [1][2][3]

---
【Few-shot Example 2】

【References】
[1] section=Abstract | page=1
We propose a lightweight attention mechanism that reduces the quadratic complexity of standard self-attention to linear while maintaining comparable performance on NLP benchmarks.

【Question】
How does this method perform on image classification tasks?

【Answer】
The provided references do not contain enough information to answer this question. The references only discuss NLP benchmarks [1] and do not mention any image classification experiments.

---

【References】
{context}

【Question】
{query}

【Answer】"""


# ---------- 论文对比（Agent 用） ----------

COMPARE_PROMPT_ZH = """你是学术论文比较助手。请基于下面两篇论文的片段，用中文写一份结构化对比分析。

要求：
1. 用四段式：研究问题对比 / 方法对比 / 实验结果对比 / 结论与意义对比
2. 明确指出两篇论文的相同点和不同点
3. 不要编造片段中没有的信息
4. 保留关键术语的英文原词

【论文 A】
{text1}

【论文 B】
{text2}

【对比分析】"""

COMPARE_PROMPT_EN = """You are an academic paper comparison assistant.
Write a structured comparison of the two papers below in English.
Use four sections: Problem Comparison / Method Comparison / Results Comparison / Significance Comparison.
Clearly identify similarities and differences.
Do not fabricate information not present in the excerpts.

【Paper A】
{text1}

【Paper B】
{text2}

【Comparison】"""

# ---------- tool 格式转换（Agent 用） ----------

def format_context_compact(hits, max_chars_per_hit: int = 400) -> str:
    """format_context 的精简版：用于 Agent tool 返回格式。"""
    if not hits:
        return "（无结果）"
    blocks = []
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata") or {}
        section = meta.get("section_title") or meta.get("title") or ""
        arxiv = meta.get("arxiv_id") or meta.get("source") or ""
        doc = (hit.get("document") or "").strip()[:max_chars_per_hit]
        blocks.append(f"[{i}] {arxiv} | {section}\n{doc}")
    return "\n\n".join(blocks)

# ---------- 工具函数：把检索命中拼成 context ----------

def format_context(hits, max_chars_per_hit: int = 600) -> str:
    """把 retriever 命中的 hits 拼成 prompt 里能直接塞进去的 context 字符串。

    hits 形如 [{"document": ..., "metadata": {...}, "distance": ...}, ...]
    返回形如：
        [1] section=Method | page=3
        <前 max_chars_per_hit 字>
        ...
    """
    if not hits:
        return "（无参考资料）"
    blocks = []
    for i, hit in enumerate(hits, 1):
        meta = hit.get("metadata") or {}
        section = meta.get("section_title") or meta.get("title") or ""
        page = meta.get("page", "")
        src = meta.get("source") or meta.get("arxiv_id") or ""
        header = f"[{i}]"
        if section:
            header += f" section={section}"
        if page not in (None, "", 0):
            header += f" | page={page}"
        if src:
            header += f" | source={src}"

        doc = (hit.get("document") or "").strip().replace("\n", " ")
        if len(doc) > max_chars_per_hit:
            doc = doc[:max_chars_per_hit] + "…"
        blocks.append(f"{header}\n{doc}")
    return "\n\n".join(blocks)
