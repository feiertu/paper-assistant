"""arXiv API 元数据抓取。

通过 arXiv API 获取论文元数据（标题、作者、摘要、PDF 链接），
并支持自动保存到 SQLite 数据库。
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

import requests

import config
from src.logging_config import get_logger

logger = get_logger(__name__)


def fetch_arxiv_metadata(query: Optional[str] = None, max_results: Optional[int] = None) -> List[Dict]:
    q = query or config.ARXIV_QUERY
    n = max_results if max_results is not None else config.ARXIV_MAX_RESULTS
    base_url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": q,
        "start": 0,
        "max_results": n,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    logger.info("arXiv fetch: query=%s max=%d", q, n)
    response = requests.get(base_url, params=params, timeout=config.ARXIV_REQUEST_TIMEOUT)

    if response.status_code != 200:
        logger.error("arXiv API 返回 %d", response.status_code)
        return []

    return parse_xml(response.content)


def parse_xml(xml_content):
    root = ET.fromstring(xml_content)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    papers = []

    for entry in root.findall('atom:entry', ns):
        id_url = entry.find('atom:id', ns).text
        arxiv_id = id_url.split('/')[-1]

        title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')
        summary = entry.find('atom:summary', ns).text.strip()
        authors = [a.find('atom:name', ns).text for a in entry.findall('atom:author', ns)]
        published = entry.find('atom:published', ns).text

        pdf_url = None
        for link in entry.findall('atom:link', ns):
            href = link.attrib.get('href', '')
            if (link.attrib.get('type') == 'application/pdf' or
                href.endswith('.pdf') or
                link.attrib.get('title') == 'pdf'):
                pdf_url = href
                break
        # arXiv 标准 PDF URL 作为兜底
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        papers.append({
            'id': arxiv_id,
            'title': title,
            'authors': ", ".join(authors),
            'summary': summary,
            'published': published,
            'pdf_url': pdf_url
        })

    logger.info("arXiv fetch: 获取 %d 篇论文", len(papers))
    return papers


def save_metadata_to_db(papers: List[Dict]) -> int:
    """将 arXiv 元数据保存到 SQLite 数据库。"""
    from src.db import Paper, get_dao

    paper_dao = get_dao("paper")
    saved = 0
    for p in papers:
        try:
            paper_dao.insert(Paper(
                arxiv_id=p["id"],
                title=p.get("title") or "",
                authors=p.get("authors") or "",
                abstract=p.get("summary") or "",
                published=p.get("published") or "",
                pdf_url=p.get("pdf_url") or "",
                source="arxiv",
                ingest_status="pending",
                chunk_count=0,
            ))
            saved += 1
        except Exception as e:
            logger.warning("保存元数据失败 %s: %s", p.get("id"), e)
    return saved


def fetch_and_persist(query: Optional[str] = None, max_results: Optional[int] = None) -> List[Dict]:
    """抓取 arXiv 元数据并保存到数据库。"""
    papers = fetch_arxiv_metadata(query=query, max_results=max_results)
    if papers:
        saved = save_metadata_to_db(papers)
        logger.info("已保存 %d/%d 条元数据到数据库", saved, len(papers))
    return papers


if __name__ == "__main__":
    papers = fetch_and_persist()
    for p in papers:
        print(f"标题: {p['title']}")
        print(f"作者: {p['authors']}")
        print(f"摘要: {p['summary'][:200]}...\n")
